"""OAuth integration service for connect, callback, refresh, and revoke flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.audit import AuditLogger, get_audit_logger
from app.core.config import get_settings
from app.core.rbac import Principal
from app.core.token_crypto import OAuthTokenCrypto, get_token_crypto
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.integrations import (
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthCallbackRequest,
    OAuthConnectRequest,
    OAuthConnectResponse,
    ProviderCredentialWrite,
)


class IntegrationServiceError(RuntimeError):
    """Raised when OAuth integration operations fail."""


@dataclass(frozen=True, slots=True)
class OAuthProviderConfig:
    """OAuth endpoint configuration for one provider."""

    auth_url: str
    token_url: str
    default_scopes: tuple[str, ...]


class IntegrationService:
    """Coordinate OAuth provider lifecycle with encrypted credential storage."""

    def __init__(
        self,
        repository: UserIntegrationRepository,
        *,
        token_crypto: OAuthTokenCrypto | None = None,
        audit_logger: AuditLogger | None = None,
        provider_configs: dict[IntegrationProvider, OAuthProviderConfig] | None = None,
        google_client_id: str | None = None,
        google_client_secret: str | None = None,
        default_redirect_uri: str | None = None,
    ) -> None:
        settings = get_settings()
        self.repository = repository
        self.token_crypto = token_crypto or get_token_crypto()
        self.audit_logger = audit_logger or get_audit_logger()
        self.google_client_id = google_client_id or settings.google_client_id
        self.google_client_secret = google_client_secret or settings.google_client_secret
        self.default_redirect_uri = default_redirect_uri or settings.google_redirect_uri
        self.provider_configs = provider_configs or {
            IntegrationProvider.google_calendar: OAuthProviderConfig(
                auth_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                default_scopes=("openid", "https://www.googleapis.com/auth/calendar.events"),
            ),
            IntegrationProvider.google_analytics: OAuthProviderConfig(
                auth_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                default_scopes=("openid", "https://www.googleapis.com/auth/analytics.readonly"),
            ),
        }

    async def build_connect_url(
        self,
        principal: Principal,
        payload: OAuthConnectRequest,
    ) -> OAuthConnectResponse:
        """Create OAuth authorization URL for provider connect flow."""

        self._ensure_google_oauth_credentials()
        provider_config = self._get_provider_config(payload.provider_name)
        redirect_uri = str(payload.redirect_uri) if payload.redirect_uri else self.default_redirect_uri
        if not redirect_uri:
            raise IntegrationServiceError("Missing redirect URI for OAuth connect flow")

        state = payload.state or self._generate_state(principal.user_id, payload.provider_name)
        scopes = payload.scopes or list(provider_config.default_scopes)

        query = urlencode(
            {
                "client_id": self.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )

        return OAuthConnectResponse(
            provider_name=payload.provider_name,
            authorization_url=f"{provider_config.auth_url}?{query}",
            state=state,
            redirect_uri=redirect_uri,
        )

    def parse_oauth_state(self, state: str) -> tuple[IntegrationProvider, int]:
        """Parse OAuth state in format `<provider>:<user_id>:<entropy>`."""

        parts = state.split(":", 2)
        if len(parts) != 3:
            raise IntegrationServiceError("Invalid OAuth state format")

        provider_raw, user_id_raw, _ = parts

        try:
            provider = IntegrationProvider(provider_raw)
        except ValueError as exc:
            raise IntegrationServiceError("Invalid OAuth state provider") from exc

        try:
            user_id = int(user_id_raw)
        except ValueError as exc:
            raise IntegrationServiceError("Invalid OAuth state user id") from exc

        if user_id <= 0:
            raise IntegrationServiceError("Invalid OAuth state user id")

        return provider, user_id

    async def handle_callback(
        self,
        principal: Principal,
        payload: OAuthCallbackRequest,
    ) -> IntegrationConnectionStatus:
        """Exchange authorization code and persist encrypted provider tokens."""

        self._ensure_google_oauth_credentials()
        redirect_uri = str(payload.redirect_uri) if payload.redirect_uri else self.default_redirect_uri
        if not redirect_uri:
            raise IntegrationServiceError("Missing redirect URI for OAuth callback flow")

        token_data = await self._exchange_code_for_token(
            provider=payload.provider_name,
            code=payload.code,
            redirect_uri=redirect_uri,
        )
        return await self._save_tokens(
            principal=principal,
            provider_name=payload.provider_name,
            token_data=token_data,
        )

    async def refresh_provider_token(
        self,
        principal: Principal,
        provider_name: IntegrationProvider,
    ) -> IntegrationConnectionStatus:
        """Refresh provider access token and persist rotated encrypted credentials."""

        record = await self.repository.get_by_user_and_provider(principal.user_id, provider_name)
        if record is None:
            raise IntegrationServiceError("Provider connection not found")
        if not record.refresh_token:
            raise IntegrationServiceError("Provider connection has no refresh token")

        try:
            await self.audit_logger.record_token_access(
                actor_user_id=principal.user_id,
                provider_name=provider_name.value,
                integration_id=str(record.id),
                success=True,
                metadata={"action": "refresh_precheck"},
            )
            refresh_token = self.token_crypto.decrypt_token(record.refresh_token)
            token_data = await self._exchange_refresh_token(
                provider=provider_name,
                refresh_token=refresh_token,
            )
            if "refresh_token" not in token_data:
                token_data["refresh_token"] = refresh_token
            status = await self._save_tokens(
                principal=principal,
                provider_name=provider_name,
                token_data=token_data,
            )
        except Exception:
            await self.audit_logger.record_token_access(
                actor_user_id=principal.user_id,
                provider_name=provider_name.value,
                integration_id=str(record.id),
                success=False,
                metadata={"action": "refresh_precheck"},
            )
            await self.audit_logger.record_token_refresh(
                actor_user_id=principal.user_id,
                provider_name=provider_name.value,
                integration_id=str(record.id),
                success=False,
            )
            raise

        await self.audit_logger.record_token_refresh(
            actor_user_id=principal.user_id,
            provider_name=provider_name.value,
            integration_id=str(record.id),
            success=True,
        )
        return status

    async def revoke_provider_connection(
        self,
        principal: Principal,
        provider_name: IntegrationProvider,
    ) -> bool:
        """Revoke local provider connection and record audit event."""

        record = await self.repository.get_by_user_and_provider(principal.user_id, provider_name)
        if record is None:
            return False

        deleted = await self.repository.delete_by_user_and_provider(principal.user_id, provider_name)
        await self.audit_logger.record_token_revoke(
            actor_user_id=principal.user_id,
            provider_name=provider_name.value,
            integration_id=str(record.id),
            success=deleted,
        )
        return deleted

    async def list_connection_statuses(self, principal: Principal) -> list[IntegrationConnectionStatus]:
        """List public-safe integration statuses for one principal."""

        records = await self.repository.list_by_user(principal.user_id)
        return [
            IntegrationConnectionStatus(
                provider_name=record.provider_name,
                connected=True,
                expires_at=record.expires_at,
                has_refresh_token=record.refresh_token is not None,
            )
            for record in records
        ]

    async def _save_tokens(
        self,
        *,
        principal: Principal,
        provider_name: IntegrationProvider,
        token_data: dict[str, Any],
    ) -> IntegrationConnectionStatus:
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise IntegrationServiceError("OAuth provider response missing access_token")

        refresh_token_raw = token_data.get("refresh_token")
        expires_at = self._resolve_expires_at(token_data)

        encrypted_access_token = self.token_crypto.encrypt_token(access_token)
        encrypted_refresh_token = (
            self.token_crypto.encrypt_token(refresh_token_raw)
            if isinstance(refresh_token_raw, str) and refresh_token_raw
            else None
        )

        record = await self.repository.upsert_credentials(
            principal.user_id,
            ProviderCredentialWrite(
                provider_name=provider_name,
                access_token=encrypted_access_token,
                refresh_token=encrypted_refresh_token,
                expires_at=expires_at,
            ),
        )

        return IntegrationConnectionStatus(
            provider_name=record.provider_name,
            connected=True,
            expires_at=record.expires_at,
            has_refresh_token=record.refresh_token is not None,
        )

    async def _exchange_code_for_token(
        self,
        *,
        provider: IntegrationProvider,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        provider_config = self._get_provider_config(provider)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                provider_config.token_url,
                data={
                    "code": code,
                    "client_id": self.google_client_id,
                    "client_secret": self.google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.is_error:
            raise IntegrationServiceError("OAuth token exchange failed")
        return response.json()

    async def _exchange_refresh_token(
        self,
        *,
        provider: IntegrationProvider,
        refresh_token: str,
    ) -> dict[str, Any]:
        provider_config = self._get_provider_config(provider)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                provider_config.token_url,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self.google_client_id,
                    "client_secret": self.google_client_secret,
                    "grant_type": "refresh_token",
                },
            )
        if response.is_error:
            raise IntegrationServiceError("OAuth token refresh failed")
        return response.json()

    def _get_provider_config(self, provider: IntegrationProvider) -> OAuthProviderConfig:
        try:
            return self.provider_configs[provider]
        except KeyError as exc:
            raise IntegrationServiceError(f"Unsupported provider '{provider.value}'") from exc

    def _generate_state(self, user_id: int, provider_name: IntegrationProvider) -> str:
        entropy = secrets.token_urlsafe(18)
        return f"{provider_name.value}:{user_id}:{entropy}"

    def _resolve_expires_at(self, token_data: dict[str, Any]) -> datetime | None:
        expires_in = token_data.get("expires_in")
        if not isinstance(expires_in, int):
            return None
        return datetime.now(UTC) + timedelta(seconds=expires_in)

    def _ensure_google_oauth_credentials(self) -> None:
        if not self.google_client_id or not self.google_client_secret:
            raise IntegrationServiceError(
                "Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET configuration",
            )

