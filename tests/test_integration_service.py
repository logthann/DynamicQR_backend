"""Tests for OAuth integration service workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.audit import AuditLogger, InMemoryAuditSink
from app.core.rbac import Principal
from app.core.token_crypto import OAuthTokenCrypto
from app.schemas.integrations import (
    IntegrationProvider,
    OAuthCallbackRequest,
    OAuthConnectRequest,
    ProviderCredentialRecord,
)
from app.services.integration_service import IntegrationService, IntegrationServiceError

FERNET_TEST_KEY = "oTP_EcEzN_G9ksvcjmcBbN1q8A5xj9Pf3Y8V97tXWW0="


@pytest.fixture
def principal() -> Principal:
    return Principal(user_id=42, role="user")


@pytest.fixture
def token_crypto() -> OAuthTokenCrypto:
    return OAuthTokenCrypto(FERNET_TEST_KEY)


@pytest.fixture
def audit_sink() -> InMemoryAuditSink:
    return InMemoryAuditSink()


@pytest.fixture
def audit_logger(audit_sink: InMemoryAuditSink) -> AuditLogger:
    return AuditLogger(sinks=[audit_sink])


@pytest.fixture
def repository() -> AsyncMock:
    return AsyncMock()


def _build_service(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
) -> IntegrationService:
    return IntegrationService(
        repository=repository,
        token_crypto=token_crypto,
        audit_logger=audit_logger,
        google_client_id="client-id",
        google_client_secret="client-secret",
        default_redirect_uri="https://example.com/oauth/callback",
    )


@pytest.mark.asyncio
async def test_build_connect_url_returns_google_authorize_url(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    service = _build_service(repository, token_crypto, audit_logger)

    response = await service.build_connect_url(
        principal,
        OAuthConnectRequest(provider_name=IntegrationProvider.google_calendar),
    )

    assert response.provider_name == IntegrationProvider.google_calendar
    assert "accounts.google.com/o/oauth2/v2/auth" in str(response.authorization_url)
    assert "client_id=client-id" in str(response.authorization_url)


@pytest.mark.asyncio
async def test_handle_callback_encrypts_and_upserts_tokens(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    repository.upsert_credentials.return_value = ProviderCredentialRecord(
        id=10,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token="encrypted",
        refresh_token="encrypted-refresh",
        expires_at=datetime.now(UTC),
    )

    service = _build_service(repository, token_crypto, audit_logger)
    service._exchange_code_for_token = AsyncMock(
        return_value={
            "access_token": "raw-access",
            "refresh_token": "raw-refresh",
            "expires_in": 3600,
        }
    )

    status = await service.handle_callback(
        principal,
        OAuthCallbackRequest(
            provider_name=IntegrationProvider.google_calendar,
            code="auth-code",
        ),
    )

    assert status.connected is True
    upsert_payload = repository.upsert_credentials.await_args.args[1]
    assert upsert_payload.access_token != "raw-access"
    assert token_crypto.decrypt_token(upsert_payload.access_token) == "raw-access"


@pytest.mark.asyncio
async def test_refresh_provider_token_records_success_audit_event(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    audit_sink: InMemoryAuditSink,
    principal: Principal,
) -> None:
    encrypted_refresh = token_crypto.encrypt_token("refresh-raw")
    repository.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=11,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=token_crypto.encrypt_token("old-access"),
        refresh_token=encrypted_refresh,
        expires_at=None,
    )
    repository.upsert_credentials.return_value = ProviderCredentialRecord(
        id=11,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=token_crypto.encrypt_token("new-access"),
        refresh_token=encrypted_refresh,
        expires_at=None,
    )

    service = _build_service(repository, token_crypto, audit_logger)
    service._exchange_refresh_token = AsyncMock(return_value={"access_token": "new-access"})

    result = await service.refresh_provider_token(principal, IntegrationProvider.google_calendar)

    assert result.connected is True
    assert any(event.action == "oauth_token_refresh" and event.success for event in audit_sink.events)


@pytest.mark.asyncio
async def test_refresh_provider_token_records_token_access_audit_event(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    audit_sink: InMemoryAuditSink,
    principal: Principal,
) -> None:
    encrypted_refresh = token_crypto.encrypt_token("refresh-raw")
    repository.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=15,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=token_crypto.encrypt_token("old-access"),
        refresh_token=encrypted_refresh,
        expires_at=None,
    )
    repository.upsert_credentials.return_value = ProviderCredentialRecord(
        id=15,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=token_crypto.encrypt_token("new-access"),
        refresh_token=encrypted_refresh,
        expires_at=None,
    )

    service = _build_service(repository, token_crypto, audit_logger)
    service._exchange_refresh_token = AsyncMock(return_value={"access_token": "new-access"})

    await service.refresh_provider_token(principal, IntegrationProvider.google_calendar)

    assert any(event.action == "oauth_token_access" and event.success for event in audit_sink.events)


@pytest.mark.asyncio
async def test_revoke_provider_connection_deletes_and_audits(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    audit_sink: InMemoryAuditSink,
    principal: Principal,
) -> None:
    repository.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=12,
        user_id=42,
        provider_name=IntegrationProvider.google_analytics,
        access_token="encrypted-access",
        refresh_token=None,
        expires_at=None,
    )
    repository.delete_by_user_and_provider.return_value = True

    service = _build_service(repository, token_crypto, audit_logger)

    deleted = await service.revoke_provider_connection(principal, IntegrationProvider.google_analytics)

    assert deleted is True
    assert any(event.action == "oauth_token_revoke" and event.success for event in audit_sink.events)


@pytest.mark.asyncio
async def test_refresh_requires_existing_refresh_token(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    repository.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=13,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token="encrypted",
        refresh_token=None,
        expires_at=None,
    )
    service = _build_service(repository, token_crypto, audit_logger)

    with pytest.raises(IntegrationServiceError, match="no refresh token"):
        await service.refresh_provider_token(principal, IntegrationProvider.google_calendar)
