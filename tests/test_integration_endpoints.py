"""Tests for integration OAuth endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.integrations import (
    DETECT_RATE_LIMIT,
    _detect_rate_limit_buckets,
    get_campaign_calendar_sync_service,
    get_google_calendar_service,
    get_integration_service,
)
from app.core.rbac import Principal
from app.schemas.campaign import CampaignCalendarSyncStatus, CampaignRead
from app.schemas.integrations import (
    CalendarImportCampaignsResponse,
    CalendarRangeType,
    GoogleCalendarEventListItem,
    GoogleCalendarEventListResponse,
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthConnectResponse,
)
from app.services.integration_service import IntegrationServiceError


class _StubIntegrationService:
    async def list_connection_statuses(self, principal: Principal):
        return [
            IntegrationConnectionStatus(
                provider_name=IntegrationProvider.google_calendar,
                connected=True,
                expires_at=datetime.now(UTC),
                has_refresh_token=True,
            )
        ]

    async def sync_connection_statuses(self, principal: Principal, *, refresh_if_expiring: bool, refresh_window_seconds: int):
        return [
            IntegrationConnectionStatus(
                provider_name=IntegrationProvider.google_calendar,
                connected=True,
                expires_at=datetime.now(UTC),
                has_refresh_token=True,
                requires_reauth=False,
                auto_refresh_attempted=refresh_if_expiring,
                auto_refresh_succeeded=True if refresh_if_expiring else None,
            )
        ]

    async def build_connect_url(self, principal: Principal, payload):
        return OAuthConnectResponse(
            provider_name=payload.provider_name,
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
            state=payload.state or "state-token",
            redirect_uri=str(payload.redirect_uri or "http://localhost:3000/integrations/google/callback"),
        )

    def parse_oauth_state(self, state: str):
        return IntegrationProvider.google_calendar, 42

    async def handle_callback(self, principal: Principal, payload):
        return IntegrationConnectionStatus(
            provider_name=payload.provider_name,
            connected=True,
            expires_at=None,
            has_refresh_token=True,
        )

    async def refresh_provider_token(self, principal: Principal, provider_name: IntegrationProvider):
        return IntegrationConnectionStatus(
            provider_name=provider_name,
            connected=True,
            expires_at=None,
            has_refresh_token=True,
        )

    async def revoke_provider_connection(self, principal: Principal, provider_name: IntegrationProvider):
        return provider_name == IntegrationProvider.google_calendar

    async def ensure_analytics_scope(self, principal: Principal):
        return None

    async def list_ga4_properties(self, principal: Principal):
        return {
            "items": [
                {
                    "property_id": "123456789",
                    "display_name": "Demo Property",
                    "ga_measurement_id": "G-ABC12345",
                }
            ]
        }


class _StubGoogleCalendarService:
    async def list_events_by_period(
        self,
        *,
        user_id: int,
        range_type: CalendarRangeType,
        year: int,
        month: int | None,
        from_month: int | None,
        to_month: int | None,
    ):
        return GoogleCalendarEventListResponse(
            range_type=range_type,
            year=year,
            month=month,
            from_month=from_month,
            to_month=to_month,
            total=1,
            events=[
                GoogleCalendarEventListItem(
                    google_event_id="evt-123",
                    title="Calendar Imported Event",
                    starts_at=datetime.now(UTC),
                    ends_at=datetime.now(UTC),
                    event_status="confirmed",
                    linked_campaign_id=10,
                    calendar_sync_status="synced",
                    last_synced_at=datetime.now(UTC),
                )
            ],
        )


class _StubCampaignCalendarSyncService:
    async def import_selected_events(self, principal: Principal, payload):
        now = datetime.now(UTC)
        return CalendarImportCampaignsResponse(
            created_count=1,
            updated_count=0,
            skipped_count=0,
            campaigns=[
                CampaignRead(
                    id=101,
                    user_id=principal.user_id,
                    name="Imported Campaign",
                    description="Imported from Google Calendar",
                    start_date=None,
                    end_date=None,
                    status="active",
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                    google_event_id="evt-123",
                    calendar_sync_status=CampaignCalendarSyncStatus.synced,
                    calendar_last_synced_at=now,
                    calendar_sync_hash="hash",
                )
            ],
        )


class _StrictStateStubIntegrationService(_StubIntegrationService):
    async def handle_callback(self, principal: Principal, payload):
        if payload.state and f":{principal.user_id}:" not in payload.state:
            raise IntegrationServiceError("OAuth state user does not match authenticated user")
        return await super().handle_callback(principal, payload)


class _MissingScopeIntegrationService(_StubIntegrationService):
    async def ensure_analytics_scope(self, principal: Principal):
        raise IntegrationServiceError("Missing required OAuth scopes: ['https://www.googleapis.com/auth/analytics.readonly']")

    async def list_ga4_properties(self, principal: Principal):
        raise IntegrationServiceError("Missing required OAuth scopes: ['https://www.googleapis.com/auth/analytics.readonly']")


@pytest.mark.asyncio
async def test_list_integrations_returns_items(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get("/api/v1/integrations/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_session_sync_returns_bootstrap_statuses(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get("/api/v1/integrations/session-sync?refresh_if_expiring=true&refresh_window_seconds=600")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["refresh_if_expiring"] is True
    assert payload["refresh_window_seconds"] == 600
    assert len(payload["items"]) == 1
    assert payload["items"][0]["auto_refresh_attempted"] is True


@pytest.mark.asyncio
async def test_connect_provider_returns_authorization_url(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.post(
            "/api/v1/integrations/connect",
            json={"provider_name": "google_calendar"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "authorization_url" in response.json()
    assert "redirect_uri" in response.json()


@pytest.mark.asyncio
async def test_callback_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.post(
            "/api/v1/integrations/callback",
            json={"provider_name": "google_calendar", "code": "auth-code"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["connected"] is True


@pytest.mark.asyncio
async def test_callback_rejects_mismatched_state_user(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StrictStateStubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.post(
            "/api/v1/integrations/callback",
            json={
                "provider_name": "google_calendar",
                "code": "auth-code",
                "state": "google_calendar:999:entropy",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "state user" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_callback_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()

    try:
        response = await async_client.get(
            "/api/v1/integrations/callback?state=google_calendar:42:test-state&code=test-auth-code"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider_name"] == "google_calendar"


@pytest.mark.asyncio
async def test_refresh_provider_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.post("/api/v1/integrations/google_calendar/refresh")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider_name"] == "google_calendar"


@pytest.mark.asyncio
async def test_revoke_provider_returns_404_when_not_connected(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.delete("/api/v1/integrations/google_analytics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_google_calendar_events_returns_candidates(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_google_calendar_service] = lambda: _StubGoogleCalendarService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get(
            "/api/v1/integrations/google-calendar/events?range_type=month&year=2026&month=11"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["events"][0]["google_event_id"] == "evt-123"


@pytest.mark.asyncio
async def test_list_google_calendar_events_supports_month_range(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_google_calendar_service] = lambda: _StubGoogleCalendarService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get(
            "/api/v1/integrations/google-calendar/events?range_type=month&year=2026&from_month=3&to_month=5"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["month"] is None
    assert payload["from_month"] == 3
    assert payload["to_month"] == 5


@pytest.mark.asyncio
async def test_import_google_calendar_events_creates_campaigns(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_calendar_sync_service] = lambda: _StubCampaignCalendarSyncService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.post(
            "/api/v1/integrations/google-calendar/import-campaigns",
            json={
                "range_type": "month",
                "year": 2026,
                "month": 11,
                "event_ids": ["evt-123"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 1
    assert payload["campaigns"][0]["google_event_id"] == "evt-123"


@pytest.mark.asyncio
async def test_ga4_properties_returns_items(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get("/api/v1/ga4/properties")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["property_id"] == "123456789"


@pytest.mark.asyncio
async def test_ga4_properties_returns_ga4_error_envelope_when_scope_missing(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _MissingScopeIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get("/api/v1/ga4/properties")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "GA4_PROPERTIES_ERROR"


@pytest.mark.asyncio
async def test_ga4_detect_invalid_url_returns_error_envelope(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get("/api/v1/ga4/detect?url=not-a-url")
    finally:
        app.dependency_overrides.clear()
        _detect_rate_limit_buckets.clear()

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_URL"
    assert isinstance(detail["message"], str)


@pytest.mark.asyncio
async def test_ga4_detect_rate_limit_returns_429(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    original_limit = DETECT_RATE_LIMIT
    try:
        # Fill the bucket with first request
        response1 = await async_client.get("/api/v1/ga4/detect?url=https://example.invalid")
        # Second request should be rate-limited when limit is 1
        import app.api.v1.integrations as integrations_module

        integrations_module.DETECT_RATE_LIMIT = 1
        response2 = await async_client.get("/api/v1/ga4/detect?url=https://example.invalid")
    finally:
        import app.api.v1.integrations as integrations_module

        integrations_module.DETECT_RATE_LIMIT = original_limit
        app.dependency_overrides.clear()
        _detect_rate_limit_buckets.clear()

    assert response1.status_code in {200, 422, 504}
    assert response2.status_code == 429
    detail = response2.json()["detail"]
    assert detail["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_ga4_detect_returns_403_when_scope_missing(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _MissingScopeIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="employee")

    try:
        response = await async_client.get("/api/v1/ga4/detect?url=https://example.com")
    finally:
        app.dependency_overrides.clear()
        _detect_rate_limit_buckets.clear()

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "MISSING_SCOPE"


