"""Tests for integration OAuth endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.integrations import (
    get_campaign_calendar_sync_service,
    get_google_calendar_service,
    get_integration_service,
)
from app.core.rbac import Principal
from app.schemas.campaign import CampaignRead
from app.schemas.integrations import (
    CalendarImportCampaignsResponse,
    CalendarRangeType,
    GoogleCalendarEventListItem,
    GoogleCalendarEventListResponse,
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthConnectResponse,
)


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

    async def build_connect_url(self, principal: Principal, payload):
        return OAuthConnectResponse(
            provider_name=payload.provider_name,
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
            state=payload.state or "state-token",
        )

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


class _StubGoogleCalendarService:
    async def list_events_by_period(self, *, user_id: int, range_type: CalendarRangeType, year: int, month: int | None):
        return GoogleCalendarEventListResponse(
            range_type=range_type,
            year=year,
            month=month,
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
                    calendar_sync_status="synced",
                    calendar_last_synced_at=now,
                    calendar_sync_hash="hash",
                )
            ],
        )


@pytest.mark.asyncio
async def test_list_integrations_returns_items(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.get("/api/v1/integrations/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_connect_provider_returns_authorization_url(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.post(
            "/api/v1/integrations/connect",
            json={"provider_name": "google_calendar"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "authorization_url" in response.json()


@pytest.mark.asyncio
async def test_callback_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

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
async def test_refresh_provider_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.post("/api/v1/integrations/google_calendar/refresh")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider_name"] == "google_calendar"


@pytest.mark.asyncio
async def test_revoke_provider_returns_404_when_not_connected(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.delete("/api/v1/integrations/google_analytics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_google_calendar_events_returns_candidates(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_google_calendar_service] = lambda: _StubGoogleCalendarService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

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
async def test_import_google_calendar_events_creates_campaigns(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_calendar_sync_service] = lambda: _StubCampaignCalendarSyncService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

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


