"""Tests for importing selected Google Calendar events into campaigns."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.rbac import Principal
from app.schemas.campaign import CampaignRead
from app.schemas.integrations import (
    CalendarImportCampaignsRequest,
    CalendarRangeType,
    GoogleCalendarEventListItem,
    GoogleCalendarEventListResponse,
)
from app.services.campaign_calendar_sync_service import CampaignCalendarSyncService


def _campaign(
    *,
    campaign_id: int,
    user_id: int = 42,
    google_event_id: str | None = None,
    name: str = "Campaign",
    status: str = "active",
    calendar_sync_hash: str | None = None,
    calendar_sync_status: str = "not_linked",
) -> CampaignRead:
    now = datetime.now(UTC)
    return CampaignRead(
        id=campaign_id,
        user_id=user_id,
        name=name,
        description=None,
        start_date=None,
        end_date=None,
        status=status,
        created_at=now,
        updated_at=now,
        deleted_at=None,
        google_event_id=google_event_id,
        calendar_sync_hash=calendar_sync_hash,
        calendar_sync_status=calendar_sync_status,
    )


@pytest.mark.asyncio
async def test_import_selected_events_creates_and_updates_idempotently() -> None:
    campaign_repo = AsyncMock()
    google_service = AsyncMock()

    google_service.list_events_by_period.return_value = GoogleCalendarEventListResponse(
        range_type=CalendarRangeType.month,
        year=2026,
        month=11,
        total=2,
        events=[
            GoogleCalendarEventListItem(google_event_id="evt-a", title="Event A"),
            GoogleCalendarEventListItem(google_event_id="evt-b", title="Event B"),
        ],
    )

    campaign_repo.get_by_user_and_google_event_id.side_effect = [None, _campaign(campaign_id=2, google_event_id="evt-b")]
    campaign_repo.create.return_value = _campaign(campaign_id=1)
    campaign_repo.update.side_effect = [
        _campaign(campaign_id=1, google_event_id="evt-a"),
        _campaign(campaign_id=2, google_event_id="evt-b"),
    ]

    service = CampaignCalendarSyncService(campaign_repo, google_service)
    result = await service.import_selected_events(
        Principal(user_id=42, role="user"),
        CalendarImportCampaignsRequest(
            range_type=CalendarRangeType.month,
            year=2026,
            month=11,
            event_ids=["evt-a", "evt-b"],
        ),
    )

    assert result.created_count == 1
    assert result.updated_count == 1
    assert result.skipped_count == 0
    assert len(result.campaigns) == 2


@pytest.mark.asyncio
async def test_import_selected_events_skips_missing_event_ids() -> None:
    campaign_repo = AsyncMock()
    google_service = AsyncMock()

    google_service.list_events_by_period.return_value = GoogleCalendarEventListResponse(
        range_type=CalendarRangeType.month,
        year=2026,
        month=11,
        total=1,
        events=[GoogleCalendarEventListItem(google_event_id="evt-a", title="Event A")],
    )
    campaign_repo.get_by_user_and_google_event_id.return_value = None
    campaign_repo.create.return_value = _campaign(campaign_id=1)
    campaign_repo.update.return_value = _campaign(campaign_id=1, google_event_id="evt-a")

    service = CampaignCalendarSyncService(campaign_repo, google_service)
    result = await service.import_selected_events(
        Principal(user_id=42, role="user"),
        CalendarImportCampaignsRequest(
            range_type=CalendarRangeType.month,
            year=2026,
            month=11,
            event_ids=["evt-a", "evt-missing"],
        ),
    )

    assert result.created_count == 1
    assert result.updated_count == 0
    assert result.skipped_count == 1


@pytest.mark.asyncio
async def test_import_selected_events_skips_when_campaign_already_synced() -> None:
    campaign_repo = AsyncMock()
    google_service = AsyncMock()

    google_service.list_events_by_period.return_value = GoogleCalendarEventListResponse(
        range_type=CalendarRangeType.month,
        year=2026,
        month=11,
        total=1,
        events=[GoogleCalendarEventListItem(google_event_id="evt-a", title="Event A")],
    )

    service = CampaignCalendarSyncService(campaign_repo, google_service)
    expected_hash = service._build_sync_hash(
        title="Event A",
        starts_at=None,
        ends_at=None,
        event_status="confirmed",
    )
    campaign_repo.get_by_user_and_google_event_id.return_value = _campaign(
        campaign_id=7,
        google_event_id="evt-a",
        name="Event A",
        status="active",
        calendar_sync_hash=expected_hash,
        calendar_sync_status="synced",
    )

    result = await service.import_selected_events(
        Principal(user_id=42, role="user"),
        CalendarImportCampaignsRequest(
            range_type=CalendarRangeType.month,
            year=2026,
            month=11,
            event_ids=["evt-a"],
        ),
    )

    assert result.created_count == 0
    assert result.updated_count == 0
    assert result.skipped_count == 1
    campaign_repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_sync_campaign_to_calendar_updates_sync_metadata() -> None:
    campaign_repo = AsyncMock()
    google_service = AsyncMock()
    now = datetime.now(UTC)
    campaign = _campaign(campaign_id=9, google_event_id=None, name="Sync Me")

    google_service.sync_campaign_event.return_value = "evt-google-999"
    campaign_repo.update.return_value = campaign.model_copy(
        update={
            "google_event_id": "evt-google-999",
            "calendar_sync_status": "synced",
            "calendar_last_synced_at": now,
            "calendar_sync_hash": "hash-abc",
        }
    )

    service = CampaignCalendarSyncService(campaign_repo, google_service)
    updated = await service.sync_campaign_to_calendar(user_id=42, campaign=campaign)

    assert updated.google_event_id == "evt-google-999"
    assert str(updated.calendar_sync_status) == "synced"
    campaign_repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_campaign_from_calendar_clears_link() -> None:
    campaign_repo = AsyncMock()
    google_service = AsyncMock()
    now = datetime.now(UTC)
    campaign = _campaign(campaign_id=9, google_event_id="evt-google-999", name="Sync Me")

    campaign_repo.update.return_value = campaign.model_copy(
        update={
            "google_event_id": None,
            "calendar_sync_status": "removed",
            "calendar_last_synced_at": now,
            "calendar_sync_hash": None,
        }
    )

    service = CampaignCalendarSyncService(campaign_repo, google_service)
    updated = await service.remove_campaign_from_calendar(user_id=42, campaign=campaign)

    assert updated.google_event_id is None
    assert str(updated.calendar_sync_status) == "removed"
    google_service.remove_campaign_event.assert_awaited_once_with(
        user_id=42,
        google_event_id="evt-google-999",
    )


