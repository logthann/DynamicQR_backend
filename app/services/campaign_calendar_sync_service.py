"""Campaign import workflows from Google Calendar event selections."""

from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json

from app.core.rbac import Principal
from app.repositories.campaigns import CampaignRepository
from app.schemas.campaign import CampaignCalendarSyncStatus, CampaignCreate, CampaignRead, CampaignUpdate
from app.schemas.integrations import CalendarImportCampaignsRequest, CalendarImportCampaignsResponse
from app.services.google_calendar_service import GoogleCalendarService


class CampaignCalendarSyncServiceError(RuntimeError):
    """Raised when calendar-to-campaign import requests are invalid."""


class CampaignCalendarSyncService:
    """Import selected Google Calendar events into campaigns idempotently."""

    def __init__(
        self,
        campaign_repository: CampaignRepository,
        google_calendar_service: GoogleCalendarService,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.google_calendar_service = google_calendar_service

    async def import_selected_events(
        self,
        principal: Principal,
        payload: CalendarImportCampaignsRequest,
    ) -> CalendarImportCampaignsResponse:
        """Create or update campaigns from selected Google event ids."""

        selected_ids = list(dict.fromkeys(payload.event_ids))
        if not selected_ids:
            raise CampaignCalendarSyncServiceError("At least one event id must be selected")

        event_response = await self.google_calendar_service.list_events_by_period(
            user_id=principal.user_id,
            range_type=payload.range_type,
            year=payload.year,
            month=payload.month,
        )

        indexed_events = {event.google_event_id: event for event in event_response.events}
        now_utc = datetime.now(UTC)

        created_count = 0
        updated_count = 0
        skipped_count = 0
        campaigns: list[CampaignRead] = []

        for event_id in selected_ids:
            event = indexed_events.get(event_id)
            if event is None:
                skipped_count += 1
                continue

            sync_hash = self._build_sync_hash(
                title=event.title,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                event_status=event.event_status,
            )
            start_date = event.starts_at.date() if event.starts_at else None
            end_date = event.ends_at.date() if event.ends_at else None
            campaign_status = self._derive_campaign_status(start_date=start_date, end_date=end_date)

            existing = await self.campaign_repository.get_by_user_and_google_event_id(
                principal.user_id,
                event_id,
            )
            if existing is None:
                created = await self.campaign_repository.create(
                    principal.user_id,
                    CampaignCreate(
                        name=event.title,
                        description=f"Imported from Google Calendar event {event_id}",
                        start_date=start_date,
                        end_date=end_date,
                        status=campaign_status,
                    ),
                )
                updated = await self.campaign_repository.update(
                    created.id,
                    CampaignUpdate(
                        google_event_id=event_id,
                        calendar_sync_status=CampaignCalendarSyncStatus.synced,
                        calendar_last_synced_at=now_utc,
                        calendar_sync_hash=sync_hash,
                    ),
                )
                campaigns.append(updated or created)
                created_count += 1
                continue

            if self._is_already_synced(
                existing,
                title=event.title,
                start_date=start_date,
                end_date=end_date,
                status=campaign_status,
                sync_hash=sync_hash,
            ):
                skipped_count += 1
                campaigns.append(existing)
                continue

            updated = await self.campaign_repository.update(
                existing.id,
                CampaignUpdate(
                    name=event.title,
                    start_date=start_date,
                    end_date=end_date,
                    status=campaign_status,
                    calendar_sync_status=CampaignCalendarSyncStatus.synced,
                    calendar_last_synced_at=now_utc,
                    calendar_sync_hash=sync_hash,
                ),
            )
            campaigns.append(updated or existing)
            updated_count += 1

        return CalendarImportCampaignsResponse(
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            campaigns=campaigns,
        )

    async def sync_campaign_to_calendar(
        self,
        *,
        user_id: int,
        campaign: CampaignRead,
    ) -> CampaignRead:
        """Push one campaign to Google Calendar and persist sync metadata."""

        google_event_id = await self.google_calendar_service.sync_campaign_event(
            user_id=user_id,
            campaign_name=campaign.name,
            campaign_description=campaign.description,
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            google_event_id=campaign.google_event_id,
        )
        sync_hash = self._build_sync_hash(
            title=campaign.name,
            starts_at=self._to_datetime_utc(campaign.start_date),
            ends_at=self._to_datetime_utc(campaign.end_date),
            event_status="confirmed",
        )

        updated = await self.campaign_repository.update(
            campaign.id,
            CampaignUpdate(
                google_event_id=google_event_id,
                calendar_sync_status=CampaignCalendarSyncStatus.synced,
                calendar_last_synced_at=datetime.now(UTC),
                calendar_sync_hash=sync_hash,
            ),
        )
        if updated is None:
            raise CampaignCalendarSyncServiceError("Campaign not found or deleted")
        return updated

    async def remove_campaign_from_calendar(
        self,
        *,
        user_id: int,
        campaign: CampaignRead,
    ) -> CampaignRead:
        """Delete linked Google event and update local campaign link status."""

        if not campaign.google_event_id:
            raise CampaignCalendarSyncServiceError("Campaign is not linked to a Google Calendar event")

        await self.google_calendar_service.remove_campaign_event(
            user_id=user_id,
            google_event_id=campaign.google_event_id,
        )

        updated = await self.campaign_repository.update(
            campaign.id,
            CampaignUpdate(
                google_event_id=None,
                calendar_sync_status=CampaignCalendarSyncStatus.removed,
                calendar_last_synced_at=datetime.now(UTC),
                calendar_sync_hash=None,
            ),
        )
        if updated is None:
            raise CampaignCalendarSyncServiceError("Campaign not found or deleted")
        return updated

    def _derive_campaign_status(self, *, start_date: date | None, end_date: date | None) -> str:
        today = datetime.now(UTC).date()
        if end_date is not None and end_date < today:
            return "completed"
        if start_date is not None and start_date > today:
            return "planned"
        return "active"

    def _build_sync_hash(
        self,
        *,
        title: str,
        starts_at: datetime | None,
        ends_at: datetime | None,
        event_status: str,
    ) -> str:
        payload = {
            "title": title,
            "starts_at": starts_at.isoformat() if starts_at else None,
            "ends_at": ends_at.isoformat() if ends_at else None,
            "event_status": event_status,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _is_already_synced(
        self,
        campaign: CampaignRead,
        *,
        title: str,
        start_date: date | None,
        end_date: date | None,
        status: str,
        sync_hash: str,
    ) -> bool:
        """Return whether campaign already matches remote event snapshot and needs no update."""

        return (
            campaign.name == title
            and campaign.start_date == start_date
            and campaign.end_date == end_date
            and campaign.status == status
            and campaign.calendar_sync_hash == sync_hash
            and campaign.calendar_sync_status == CampaignCalendarSyncStatus.synced
        )

    def _to_datetime_utc(self, value: date | None) -> datetime | None:
        if value is None:
            return None
        return datetime(value.year, value.month, value.day, tzinfo=UTC)

