"""Tests for OAuth integration service workflows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.audit import AuditLogger, InMemoryAuditSink
from app.core.rbac import Principal
from app.core.token_crypto import OAuthTokenCrypto
from app.schemas.integrations import (
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthCallbackRequest,
    OAuthConnectRequest,
    ProviderCredentialRecord,
)
from app.services.integration_service import (
    IntegrationService,
    IntegrationServiceError,
    _GAPropertySummary,
)

FERNET_TEST_KEY = "oTP_EcEzN_G9ksvcjmcBbN1q8A5xj9Pf3Y8V97tXWW0="


@pytest.fixture
def principal() -> Principal:
    return Principal(user_id=42, role="employee")


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
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.events" in str(response.authorization_url)
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fanalytics.readonly" in str(response.authorization_url)


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
            "scope": "openid https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/analytics.readonly",
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
    assert "https://www.googleapis.com/auth/calendar.events" in upsert_payload.granted_scopes
    assert "https://www.googleapis.com/auth/analytics.readonly" in upsert_payload.granted_scopes


@pytest.mark.asyncio
async def test_handle_callback_rejects_state_user_mismatch(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    service = _build_service(repository, token_crypto, audit_logger)

    with pytest.raises(IntegrationServiceError, match="state user"):
        await service.handle_callback(
            principal,
            OAuthCallbackRequest(
                provider_name=IntegrationProvider.google_calendar,
                code="auth-code",
                state="google_calendar:999:entropy",
            ),
        )


@pytest.mark.asyncio
async def test_handle_callback_rejects_state_provider_mismatch(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    service = _build_service(repository, token_crypto, audit_logger)

    with pytest.raises(IntegrationServiceError, match="state provider"):
        await service.handle_callback(
            principal,
            OAuthCallbackRequest(
                provider_name=IntegrationProvider.google_calendar,
                code="auth-code",
                state="google_analytics:42:entropy",
            ),
        )


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
        granted_scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
    )
    repository.upsert_credentials.return_value = ProviderCredentialRecord(
        id=11,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=token_crypto.encrypt_token("new-access"),
        refresh_token=encrypted_refresh,
        expires_at=None,
        granted_scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
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
        granted_scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
    )
    repository.upsert_credentials.return_value = ProviderCredentialRecord(
        id=15,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=token_crypto.encrypt_token("new-access"),
        refresh_token=encrypted_refresh,
        expires_at=None,
        granted_scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
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
        granted_scopes=[],
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
        granted_scopes=[],
    )
    service = _build_service(repository, token_crypto, audit_logger)

    with pytest.raises(IntegrationServiceError, match="no refresh token"):
        await service.refresh_provider_token(principal, IntegrationProvider.google_calendar)


@pytest.mark.asyncio
async def test_list_ga4_properties_flattens_all_streams_across_properties(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    repository.list_by_user.return_value = [
        ProviderCredentialRecord(
            id=20,
            user_id=principal.user_id,
            provider_name=IntegrationProvider.google_analytics,
            access_token=token_crypto.encrypt_token("ga-access-token"),
            refresh_token=None,
            expires_at=None,
            granted_scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
    ]
    service = _build_service(repository, token_crypto, audit_logger)
    service._list_ga4_property_summaries = AsyncMock(
        return_value=[
            _GAPropertySummary("properties/1001", "1001", "Property One"),
            _GAPropertySummary("properties/1002", "1002", "Property Two"),
        ]
    )
    service._list_property_stream_measurements = AsyncMock(
        side_effect=[
            [
                {"stream_display_name": "Main Website", "ga_measurement_id": "G-AAAA1111"},
                {"stream_display_name": "Landing Page", "ga_measurement_id": "G-AAAA2222"},
            ],
            [
                {"stream_display_name": "App Stream", "ga_measurement_id": None},
            ],
        ]
    )

    result = await service.list_ga4_properties(principal)

    assert len(result.items) == 3
    assert result.items[0].property_id == "1001"
    assert result.items[0].display_name == "Property One - Main Website"
    assert result.items[0].ga_measurement_id == "G-AAAA1111"
    assert result.items[1].property_id == "1001"
    assert result.items[1].display_name == "Property One - Landing Page"
    assert result.items[1].ga_measurement_id == "G-AAAA2222"
    assert result.items[2].property_id == "1002"
    assert result.items[2].display_name == "Property Two - App Stream"
    assert result.items[2].ga_measurement_id is None


@pytest.mark.asyncio
async def test_google_api_get_surfaces_google_403_without_missing_scope_marker(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
) -> None:
    class _StubResponse:
        status_code = 403
        is_error = True
        text = '{"error":{"message":"Permission denied"}}'

        @staticmethod
        def json():
            return {"error": {"message": "Permission denied"}}

    class _StubClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, headers=None):
            return _StubResponse()

    service = _build_service(repository, token_crypto, audit_logger)

    from unittest.mock import patch

    with patch("app.services.integration_service.httpx.AsyncClient", return_value=_StubClient()):
        with pytest.raises(IntegrationServiceError, match="status 403") as exc_info:
            await service._google_api_get(
                "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
                access_token="token",
            )

    assert "Missing required OAuth scopes" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_sync_connection_statuses_refreshes_expired_token_when_enabled(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    repository.list_by_user.return_value = [
        ProviderCredentialRecord(
            id=90,
            user_id=principal.user_id,
            provider_name=IntegrationProvider.google_calendar,
            access_token=token_crypto.encrypt_token("access"),
            refresh_token=token_crypto.encrypt_token("refresh"),
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            granted_scopes=[
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/analytics.readonly",
            ],
        )
    ]
    service = _build_service(repository, token_crypto, audit_logger)
    service.refresh_provider_token = AsyncMock(
        return_value=IntegrationConnectionStatus(
            provider_name=IntegrationProvider.google_calendar,
            connected=True,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            has_refresh_token=True,
            granted_scopes=[
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/analytics.readonly",
            ],
        )
    )

    statuses = await service.sync_connection_statuses(
        principal,
        refresh_if_expiring=True,
        refresh_window_seconds=900,
    )

    assert len(statuses) == 1
    assert statuses[0].auto_refresh_attempted is True
    assert statuses[0].auto_refresh_succeeded is True
    assert statuses[0].requires_reauth is False


@pytest.mark.asyncio
async def test_sync_connection_statuses_marks_reauth_when_refresh_fails(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    repository.list_by_user.return_value = [
        ProviderCredentialRecord(
            id=91,
            user_id=principal.user_id,
            provider_name=IntegrationProvider.google_analytics,
            access_token=token_crypto.encrypt_token("access"),
            refresh_token=token_crypto.encrypt_token("refresh"),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            granted_scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
    ]
    service = _build_service(repository, token_crypto, audit_logger)
    service.refresh_provider_token = AsyncMock(side_effect=IntegrationServiceError("OAuth token refresh failed"))

    statuses = await service.sync_connection_statuses(
        principal,
        refresh_if_expiring=True,
        refresh_window_seconds=900,
    )

    assert len(statuses) == 1
    assert statuses[0].connected is True
    assert statuses[0].requires_reauth is True
    assert statuses[0].auto_refresh_attempted is True
    assert statuses[0].auto_refresh_succeeded is False


@pytest.mark.asyncio
async def test_sync_connection_statuses_marks_reauth_when_no_refresh_token(
    repository: AsyncMock,
    token_crypto: OAuthTokenCrypto,
    audit_logger: AuditLogger,
    principal: Principal,
) -> None:
    repository.list_by_user.return_value = [
        ProviderCredentialRecord(
            id=92,
            user_id=principal.user_id,
            provider_name=IntegrationProvider.google_analytics,
            access_token=token_crypto.encrypt_token("access"),
            refresh_token=None,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            granted_scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
    ]
    service = _build_service(repository, token_crypto, audit_logger)

    statuses = await service.sync_connection_statuses(
        principal,
        refresh_if_expiring=True,
        refresh_window_seconds=900,
    )

    assert len(statuses) == 1
    assert statuses[0].requires_reauth is True
    assert statuses[0].auto_refresh_attempted is True
    assert statuses[0].auto_refresh_succeeded is False


