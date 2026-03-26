"""Tests for Google Calendar service event sync and persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.token_crypto import OAuthTokenCrypto
from app.schemas.integrations import (
    CalendarRangeType,
    IntegrationProvider,
    ProviderCredentialRecord,
)
from app.services.google_calendar_service import GoogleCalendarService, GoogleCalendarServiceError

FERNET_TEST_KEY = "oTP_EcEzN_G9ksvcjmcBbN1q8A5xj9Pf3Y8V97tXWW0="


class _MappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> _MappingResult:
        return _MappingResult(self._rows)


@pytest.mark.asyncio
async def test_sync_event_for_qr_upserts_google_event_id() -> None:
    session = AsyncMock()
    integration_repo = AsyncMock()
    crypto = OAuthTokenCrypto(FERNET_TEST_KEY)

    integration_repo.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=5,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=crypto.encrypt_token("raw-access"),
        refresh_token=None,
        expires_at=None,
    )

    service = GoogleCalendarService(session, integration_repo, token_crypto=crypto)
    service._create_google_event = AsyncMock(return_value="google-event-123")

    start_time = datetime.now(UTC)
    end_time = start_time + timedelta(hours=1)

    event_id = await service.sync_event_for_qr(
        user_id=42,
        qr_id=99,
        event_title="Launch Webinar",
        start_datetime=start_time,
        end_datetime=end_time,
        location="Online",
        description="Campaign kickoff",
    )

    assert event_id == "google-event-123"
    statement = session.execute.await_args.args[0]
    assert "ON DUPLICATE KEY UPDATE" in str(statement)
    params = session.execute.await_args.args[1]
    assert params["google_event_id"] == "google-event-123"


@pytest.mark.asyncio
async def test_sync_event_requires_calendar_integration() -> None:
    session = AsyncMock()
    integration_repo = AsyncMock()
    integration_repo.get_by_user_and_provider.return_value = None

    service = GoogleCalendarService(
        session,
        integration_repo,
        token_crypto=OAuthTokenCrypto(FERNET_TEST_KEY),
    )

    with pytest.raises(GoogleCalendarServiceError, match="not connected"):
        await service.sync_event_for_qr(
            user_id=42,
            qr_id=99,
            event_title="Launch Webinar",
            start_datetime=datetime.now(UTC),
            end_datetime=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_list_events_by_period_returns_campaign_link_metadata() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(
        rows=[
            {
                "id": 321,
                "google_event_id": "event-1",
                "calendar_sync_status": "synced",
                "calendar_last_synced_at": datetime.now(UTC),
            }
        ]
    )
    integration_repo = AsyncMock()
    crypto = OAuthTokenCrypto(FERNET_TEST_KEY)

    integration_repo.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=5,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=crypto.encrypt_token("raw-access"),
        refresh_token=None,
        expires_at=None,
    )

    service = GoogleCalendarService(session, integration_repo, token_crypto=crypto)
    service._fetch_google_events = AsyncMock(
        return_value=[
            {
                "google_event_id": "event-1",
                "title": "Imported Event",
                "starts_at": datetime.now(UTC),
                "ends_at": datetime.now(UTC),
                "event_status": "confirmed",
            },
            {
                "google_event_id": "event-2",
                "title": "Unlinked Event",
                "starts_at": None,
                "ends_at": None,
                "event_status": "tentative",
            },
        ]
    )

    response = await service.list_events_by_period(
        user_id=42,
        range_type=CalendarRangeType.month,
        year=2026,
        month=11,
    )

    assert response.total == 2
    assert response.events[0].linked_campaign_id == 321
    assert response.events[0].calendar_sync_status == "synced"
    assert response.events[1].linked_campaign_id is None
    assert response.events[1].calendar_sync_status == "not_linked"


@pytest.mark.asyncio
async def test_list_events_month_requires_valid_month() -> None:
    session = AsyncMock()
    integration_repo = AsyncMock()
    integration_repo.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=5,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=OAuthTokenCrypto(FERNET_TEST_KEY).encrypt_token("raw-access"),
        refresh_token=None,
        expires_at=None,
    )

    service = GoogleCalendarService(
        session,
        integration_repo,
        token_crypto=OAuthTokenCrypto(FERNET_TEST_KEY),
    )

    with pytest.raises(GoogleCalendarServiceError, match="Month must be provided"):
        await service.list_events_by_period(
            user_id=42,
            range_type=CalendarRangeType.month,
            year=2026,
            month=None,
        )


@pytest.mark.asyncio
async def test_sync_campaign_event_uses_update_path_when_google_event_id_exists() -> None:
    session = AsyncMock()
    integration_repo = AsyncMock()
    crypto = OAuthTokenCrypto(FERNET_TEST_KEY)

    integration_repo.get_by_user_and_provider.return_value = ProviderCredentialRecord(
        id=8,
        user_id=42,
        provider_name=IntegrationProvider.google_calendar,
        access_token=crypto.encrypt_token("raw-access"),
        refresh_token=None,
        expires_at=None,
    )

    service = GoogleCalendarService(session, integration_repo, token_crypto=crypto)
    service._update_google_event = AsyncMock(return_value="evt-updated")

    event_id = await service.sync_campaign_event(
        user_id=42,
        campaign_name="Black Friday 2026",
        campaign_description="Promo",
        start_date=None,
        end_date=None,
        google_event_id="evt-existing",
    )

    assert event_id == "evt-updated"
    service._update_google_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_campaign_event_requires_calendar_integration() -> None:
    session = AsyncMock()
    integration_repo = AsyncMock()
    integration_repo.get_by_user_and_provider.return_value = None

    service = GoogleCalendarService(
        session,
        integration_repo,
        token_crypto=OAuthTokenCrypto(FERNET_TEST_KEY),
    )

    with pytest.raises(GoogleCalendarServiceError, match="not connected"):
        await service.remove_campaign_event(user_id=42, google_event_id="evt-1")


