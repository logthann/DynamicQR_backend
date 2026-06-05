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
    GAPropertiesResponse,
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


@dataclass(frozen=True, slots=True)
class _GAPropertySummary:
    """Normalized GA property summary returned by account summaries API."""

    property_name: str
    property_id: str
    display_name: str


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
        self.required_scopes: dict[IntegrationProvider, tuple[str, ...]] = {
            IntegrationProvider.google_calendar: (
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/analytics.readonly",
            ),
            IntegrationProvider.google_analytics: (
                "https://www.googleapis.com/auth/analytics.readonly",
            ),
        }
        self.allowed_scopes: dict[IntegrationProvider, set[str]] = {
            IntegrationProvider.google_calendar: {
                "openid",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/analytics.readonly",
            },
            IntegrationProvider.google_analytics: {
                "openid",
                "https://www.googleapis.com/auth/analytics.readonly",
            },
        }

    async def build_connect_url(
        self,
        principal: Principal,
        payload: OAuthConnectRequest,
    ) -> OAuthConnectResponse:
        """Create OAuth authorization URL for provider connect flow."""

        self._ensure_google_oauth_credentials()
        provider_config = self._get_provider_config(payload.provider_name)
        
        # Security: Always use the server-configured redirect URI. Ignore any value from the client.
        redirect_uri = self.default_redirect_uri
        if not redirect_uri:
            raise IntegrationServiceError("Missing redirect URI for OAuth connect flow")

        state = payload.state or self._generate_state(principal.user_id, payload.provider_name)
        scopes = self._resolve_connect_scopes(payload.provider_name, payload.scopes)

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
        provider_name = payload.provider_name
        principal_for_save = principal

        if payload.state:
            state_provider, state_user_id = self.parse_oauth_state(payload.state)
            if state_provider != payload.provider_name:
                raise IntegrationServiceError("OAuth state provider does not match callback payload")
            if state_user_id != principal.user_id:
                raise IntegrationServiceError("OAuth state user does not match authenticated user")

            provider_name = state_provider
            principal_for_save = Principal(
                user_id=state_user_id,
                role=principal.role,
            )

        # Security: Always use the server-configured redirect URI. Ignore any value from the client.
        redirect_uri = self.default_redirect_uri
        if not redirect_uri:
            raise IntegrationServiceError("Missing redirect URI for OAuth callback flow")

        token_data = await self._exchange_code_for_token(
            provider=provider_name,
            code=payload.code,
            redirect_uri=redirect_uri,
        )
        granted_scopes = self._extract_granted_scopes(token_data)
        self._validate_granted_scopes(provider_name, granted_scopes)
        return await self._save_tokens(
            principal=principal_for_save,
            provider_name=provider_name,
            token_data=token_data,
            granted_scopes=granted_scopes,
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
            granted_scopes = self._extract_granted_scopes(
                token_data,
                fallback=record.granted_scopes,
            )
            self._validate_granted_scopes(provider_name, granted_scopes)
            status = await self._save_tokens(
                principal=principal,
                provider_name=provider_name,
                token_data=token_data,
                granted_scopes=granted_scopes,
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
        checked_at = datetime.now(UTC)
        return [
            IntegrationConnectionStatus(
                provider_name=record.provider_name,
                connected=True,
                expires_at=record.expires_at,
                has_refresh_token=record.refresh_token is not None,
                granted_scopes=record.granted_scopes,
                last_validated_at=checked_at,
            )
            for record in records
        ]

    async def sync_connection_statuses(
        self,
        principal: Principal,
        *,
        refresh_if_expiring: bool,
        refresh_window_seconds: int,
    ) -> list[IntegrationConnectionStatus]:
        """Return statuses and optionally run silent refresh for expiring integrations."""

        records = await self.repository.list_by_user(principal.user_id)
        checked_at = datetime.now(UTC)
        statuses: list[IntegrationConnectionStatus] = []

        for record in records:
            status = IntegrationConnectionStatus(
                provider_name=record.provider_name,
                connected=True,
                expires_at=record.expires_at,
                has_refresh_token=record.refresh_token is not None,
                granted_scopes=record.granted_scopes,
                last_validated_at=checked_at,
            )

            should_try_refresh = refresh_if_expiring and self._is_expired_or_near_expiry(
                record.expires_at,
                refresh_window_seconds,
            )
            if not should_try_refresh:
                statuses.append(status)
                continue

            status.auto_refresh_attempted = True
            if not record.refresh_token:
                status.requires_reauth = True
                status.status_reason = "Provider token expired and no refresh token is stored"
                status.auto_refresh_succeeded = False
                statuses.append(status)
                continue

            try:
                refreshed = await self.refresh_provider_token(principal, record.provider_name)
                refreshed.last_validated_at = checked_at
                refreshed.auto_refresh_attempted = True
                refreshed.auto_refresh_succeeded = True
                statuses.append(refreshed)
            except Exception:
                status.requires_reauth = True
                status.status_reason = "Silent refresh failed; user must reconnect provider"
                status.auto_refresh_succeeded = False
                statuses.append(status)

        return statuses

    async def ensure_analytics_scope(self, principal: Principal) -> None:
        """Ensure the user has the analytics.readonly scope from any connected provider."""

        records = await self.repository.list_by_user(principal.user_id)
        granted_scopes = {scope for record in records for scope in record.granted_scopes}
        required = "https://www.googleapis.com/auth/analytics.readonly"
        if required not in granted_scopes:
            raise IntegrationServiceError(f"Missing required OAuth scopes: ['{required}']")

    async def list_ga4_properties(self, principal: Principal) -> GAPropertiesResponse:
        """Return flattened GA4 property-stream rows with per-stream measurement IDs."""

        await self.ensure_analytics_scope(principal)
        access_token = await self._resolve_analytics_access_token(principal)
        property_summaries = await self._list_ga4_property_summaries(access_token)

        items = []
        for summary in property_summaries:
            stream_rows = await self._list_property_stream_measurements(
                access_token=access_token,
                property_name=summary.property_name,
            )

            for stream in stream_rows:
                stream_display_name = str(stream.get("stream_display_name") or "Unnamed Stream")
                items.append(
                    {
                        "property_id": summary.property_id,
                        "display_name": f"{summary.display_name} - {stream_display_name}",
                        "ga_measurement_id": stream.get("ga_measurement_id"),
                    }
                )

        return GAPropertiesResponse(items=items)

    async def _resolve_analytics_access_token(self, principal: Principal) -> str:
        """Resolve and decrypt one access token that includes analytics.readonly scope."""

        records = await self.repository.list_by_user(principal.user_id)
        required_scope = "https://www.googleapis.com/auth/analytics.readonly"

        preferred_order = (
            IntegrationProvider.google_analytics,
            IntegrationProvider.google_calendar,
        )
        for provider in preferred_order:
            for record in records:
                if record.provider_name != provider:
                    continue
                if required_scope not in record.granted_scopes:
                    continue
                if not record.access_token:
                    continue
                return self.token_crypto.decrypt_token(record.access_token)

        raise IntegrationServiceError("No active Google token with analytics.readonly scope")

    async def _list_ga4_property_summaries(self, access_token: str) -> list[_GAPropertySummary]:
        """List GA4 properties from Analytics Admin account summaries (step 1)."""

        endpoint = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
        page_token: str | None = None
        summaries: dict[str, _GAPropertySummary] = {}

        while True:
            params: dict[str, str] = {"pageSize": "200"}
            if page_token:
                params["pageToken"] = page_token

            payload = await self._google_api_get(endpoint, access_token=access_token, params=params)
            for account in payload.get("accountSummaries", []):
                if not isinstance(account, dict):
                    continue
                for property_summary in account.get("propertySummaries", []):
                    if not isinstance(property_summary, dict):
                        continue
                    property_name = str(property_summary.get("property") or "")
                    if not property_name.startswith("properties/"):
                        continue
                    property_id = property_name.split("/", 1)[1]
                    display_name = str(property_summary.get("displayName") or property_id)
                    summaries[property_name] = _GAPropertySummary(
                        property_name=property_name,
                        property_id=property_id,
                        display_name=display_name,
                    )

            next_page_token_raw = payload.get("nextPageToken")
            page_token = str(next_page_token_raw) if isinstance(next_page_token_raw, str) and next_page_token_raw else None
            if not page_token:
                break

        return sorted(summaries.values(), key=lambda item: item.property_id)

    async def _list_property_stream_measurements(
        self,
        *,
        access_token: str,
        property_name: str,
    ) -> list[dict[str, str | None]]:
        """Return all GA data streams for a property with stream name and measurement id."""

        endpoint = f"https://analyticsadmin.googleapis.com/v1beta/{property_name}/dataStreams"
        page_token: str | None = None

        stream_rows: list[dict[str, str | None]] = []
        while True:
            params: dict[str, str] = {"pageSize": "200"}
            if page_token:
                params["pageToken"] = page_token

            payload = await self._google_api_get(endpoint, access_token=access_token, params=params)
            for stream in payload.get("dataStreams", []):
                if not isinstance(stream, dict):
                    continue
                stream_name = str(stream.get("displayName") or "").strip()
                if not stream_name:
                    stream_path = str(stream.get("name") or "")
                    stream_name = stream_path.split("/", 1)[1] if "/" in stream_path else (stream_path or "Unnamed Stream")
                web_stream_data = stream.get("webStreamData")
                measurement_id: str | None = None
                if isinstance(web_stream_data, dict):
                    raw = web_stream_data.get("measurementId")
                    if isinstance(raw, str) and raw.strip():
                        measurement_id = raw.strip()

                stream_rows.append(
                    {
                        "stream_display_name": stream_name,
                        "ga_measurement_id": measurement_id,
                    }
                )

            next_page_token_raw = payload.get("nextPageToken")
            page_token = str(next_page_token_raw) if isinstance(next_page_token_raw, str) and next_page_token_raw else None
            if not page_token:
                break

        return stream_rows

    async def _google_api_get(
        self,
        url: str,
        *,
        access_token: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Call Google API endpoint and normalize error messages for upstream failures."""

        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)

        if response.is_error:
            details = self._extract_google_error_message(response)
            raise IntegrationServiceError(
                f"Google Analytics Admin API request failed with status {response.status_code}: {details}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationServiceError("Google Analytics Admin API returned invalid JSON payload") from exc

        if not isinstance(payload, dict):
            raise IntegrationServiceError("Google Analytics Admin API returned unexpected payload shape")

        return payload

    def _extract_google_error_message(self, response: httpx.Response) -> str:
        """Extract stable message from Google error response payload."""

        try:
            payload = response.json()
        except ValueError:
            return response.text or "Unknown error"

        if not isinstance(payload, dict):
            return response.text or "Unknown error"

        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message

        return response.text or "Unknown error"

    async def _save_tokens(
        self,
        *,
        principal: Principal,
        provider_name: IntegrationProvider,
        token_data: dict[str, Any],
        granted_scopes: list[str],
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
                granted_scopes=granted_scopes,
            ),
        )

        return IntegrationConnectionStatus(
            provider_name=record.provider_name,
            connected=True,
            expires_at=record.expires_at,
            has_refresh_token=record.refresh_token is not None,
            granted_scopes=record.granted_scopes,
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

    def _is_expired_or_near_expiry(self, expires_at: datetime | None, window_seconds: int) -> bool:
        if expires_at is None:
            return False

        # Normalize DB naive datetime to UTC for safe comparison.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        threshold = datetime.now(UTC) + timedelta(seconds=max(window_seconds, 0))
        return expires_at <= threshold

    def _ensure_google_oauth_credentials(self) -> None:
        if not self.google_client_id or not self.google_client_secret:
            raise IntegrationServiceError(
                "Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET configuration",
            )

    def _resolve_connect_scopes(
        self,
        provider_name: IntegrationProvider,
        requested_scopes: list[str],
    ) -> list[str]:
        required = set(self.required_scopes.get(provider_name, ()))
        allowed = self.allowed_scopes.get(provider_name, set())

        resolved = set(requested_scopes or [])
        if not resolved:
            resolved = set(self._get_provider_config(provider_name).default_scopes)

        resolved.update(required)
        unknown = resolved - allowed
        if unknown:
            raise IntegrationServiceError(f"Unsupported OAuth scopes requested: {sorted(unknown)}")

        return sorted(resolved)

    def _extract_granted_scopes(self, token_data: dict[str, Any], fallback: list[str] | None = None) -> list[str]:
        scopes_raw = token_data.get("scope")
        if isinstance(scopes_raw, str) and scopes_raw.strip():
            return sorted({scope for scope in scopes_raw.split(" ") if scope})
        return sorted(set(fallback or []))

    def _validate_granted_scopes(
        self,
        provider_name: IntegrationProvider,
        granted_scopes: list[str],
    ) -> None:
        required = set(self.required_scopes.get(provider_name, ()))
        missing = sorted(required - set(granted_scopes))
        if missing:
            raise IntegrationServiceError(f"Missing required OAuth scopes: {missing}")