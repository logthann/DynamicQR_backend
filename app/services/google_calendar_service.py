"""Google Calendar event sync service with QR event-detail persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.token_crypto import OAuthTokenCrypto, get_token_crypto
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.integrations import (
    CalendarRangeType,
    GoogleCalendarEventListItem,
    GoogleCalendarEventListResponse,
    IntegrationProvider,
)


class GoogleCalendarServiceError(RuntimeError):
    """Raised when Google Calendar synchronization fails."""


class GoogleCalendarService:
    """Create Google Calendar events and persist `google_event_id` for event QRs."""

    def __init__(
        self,
        session: AsyncSession,
        integration_repository: UserIntegrationRepository,
        *,
        token_crypto: OAuthTokenCrypto | None = None,
    ) -> None:
        self.session = session
        self.integration_repository = integration_repository
        self.token_crypto = token_crypto or get_token_crypto()

    async def sync_event_for_qr(
        self,
        *,
        user_id: int,
        qr_id: int,
        event_title: str,
        start_datetime: datetime,
        end_datetime: datetime,
        location: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a Google Calendar event and upsert matching QR event details."""

        integration = await self.integration_repository.get_by_user_and_provider(
            user_id,
            IntegrationProvider.google_calendar,
        )
        if integration is None:
            raise GoogleCalendarServiceError("Google Calendar integration is not connected")

        access_token = self.token_crypto.decrypt_token(integration.access_token)
        google_event_id = await self._create_google_event(
            access_token=access_token,
            event_title=event_title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            description=description,
        )

        await self._upsert_qr_event_detail(
            qr_id=qr_id,
            event_title=event_title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            description=description,
            google_event_id=google_event_id,
        )
        return google_event_id

    async def sync_campaign_event(
        self,
        *,
        user_id: int,
        campaign_name: str,
        campaign_description: str | None,
        start_date: date | None,
        end_date: date | None,
        google_event_id: str | None,
    ) -> str:
        """Create or update a Google Calendar event for a campaign and return event id."""

        integration = await self.integration_repository.get_by_user_and_provider(
            user_id,
            IntegrationProvider.google_calendar,
        )
        if integration is None:
            raise GoogleCalendarServiceError("Google Calendar integration is not connected")

        access_token = self.token_crypto.decrypt_token(integration.access_token)
        payload = self._build_campaign_event_payload(
            campaign_name=campaign_name,
            campaign_description=campaign_description,
            start_date=start_date,
            end_date=end_date,
        )

        if google_event_id:
            return await self._update_google_event(
                access_token=access_token,
                google_event_id=google_event_id,
                payload=payload,
            )

        return await self._create_google_event_from_payload(
            access_token=access_token,
            payload=payload,
        )

    async def remove_campaign_event(
        self,
        *,
        user_id: int,
        google_event_id: str,
    ) -> None:
        """Delete one linked Google Calendar event for a campaign."""

        integration = await self.integration_repository.get_by_user_and_provider(
            user_id,
            IntegrationProvider.google_calendar,
        )
        if integration is None:
            raise GoogleCalendarServiceError("Google Calendar integration is not connected")

        access_token = self.token_crypto.decrypt_token(integration.access_token)
        await self._delete_google_event(access_token=access_token, google_event_id=google_event_id)

    async def list_events_by_period(
        self,
        *,
        user_id: int,
        range_type: CalendarRangeType,
        year: int,
        month: int | None = None,
        from_month: int | None = None,
        to_month: int | None = None,
    ) -> GoogleCalendarEventListResponse:
        """List Google Calendar events for a month or year and attach local sync metadata."""

        integration = await self.integration_repository.get_by_user_and_provider(
            user_id,
            IntegrationProvider.google_calendar,
        )
        if integration is None:
            raise GoogleCalendarServiceError("Google Calendar integration is not connected")

        access_token = self.token_crypto.decrypt_token(integration.access_token)
        time_min, time_max = self._resolve_period_bounds(
            range_type=range_type,
            year=year,
            month=month,
            from_month=from_month,
            to_month=to_month,
        )

        events = await self._fetch_google_events(
            access_token=access_token,
            time_min=time_min,
            time_max=time_max,
        )
        google_event_ids = [event["google_event_id"] for event in events]
        campaign_links = await self._get_campaign_links_by_google_event_id(user_id, google_event_ids)

        items = [
            GoogleCalendarEventListItem(
                google_event_id=event["google_event_id"],
                title=event["title"],
                starts_at=event["starts_at"],
                ends_at=event["ends_at"],
                event_status=event["event_status"],
                linked_campaign_id=campaign_links.get(event["google_event_id"], {}).get("campaign_id"),
                calendar_sync_status=campaign_links.get(event["google_event_id"], {}).get(
                    "calendar_sync_status",
                    "not_linked",
                ),
                last_synced_at=campaign_links.get(event["google_event_id"], {}).get("calendar_last_synced_at"),
            )
            for event in events
        ]

        return GoogleCalendarEventListResponse(
            range_type=range_type,
            year=year,
            month=month,
            from_month=from_month,
            to_month=to_month,
            total=len(items),
            events=items,
        )

    async def _create_google_event(
        self,
        *,
        access_token: str,
        event_title: str,
        start_datetime: datetime,
        end_datetime: datetime,
        location: str | None,
        description: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "summary": event_title,
            "start": {"dateTime": start_datetime.isoformat()},
            "end": {"dateTime": end_datetime.isoformat()},
        }
        if location:
            payload["location"] = location
        if description:
            payload["description"] = description

        return await self._create_google_event_from_payload(access_token=access_token, payload=payload)

    async def _create_google_event_from_payload(
        self,
        *,
        access_token: str,
        payload: dict[str, Any],
    ) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.is_error:
            raise GoogleCalendarServiceError("Google Calendar event creation failed")

        body = response.json()
        event_id = body.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise GoogleCalendarServiceError("Google Calendar response missing event id")
        return event_id

    async def _update_google_event(
        self,
        *,
        access_token: str,
        google_event_id: str,
        payload: dict[str, Any],
    ) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{google_event_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.is_error:
            raise GoogleCalendarServiceError("Google Calendar event update failed")

        body = response.json()
        event_id = body.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise GoogleCalendarServiceError("Google Calendar response missing event id")
        return event_id

    async def _delete_google_event(
        self,
        *,
        access_token: str,
        google_event_id: str,
    ) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{google_event_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        # Already deleted remotely is treated as idempotent success for unlink flows.
        if response.status_code == 404:
            return
        if response.is_error:
            raise GoogleCalendarServiceError("Google Calendar event delete failed")

    def _build_campaign_event_payload(
        self,
        *,
        campaign_name: str,
        campaign_description: str | None,
        start_date: date | None,
        end_date: date | None,
    ) -> dict[str, Any]:
        effective_start = start_date or datetime.now(UTC).date()
        effective_end = end_date or effective_start
        exclusive_end = effective_end + timedelta(days=1)

        payload: dict[str, Any] = {
            "summary": campaign_name,
            "start": {"date": effective_start.isoformat()},
            "end": {"date": exclusive_end.isoformat()},
        }
        if campaign_description:
            payload["description"] = campaign_description
        return payload

    async def _upsert_qr_event_detail(
        self,
        *,
        qr_id: int,
        event_title: str,
        start_datetime: datetime,
        end_datetime: datetime,
        location: str | None,
        description: str | None,
        google_event_id: str,
    ) -> None:
        statement = text(
            """
            INSERT INTO qr_event_details (
                qr_id,
                event_title,
                start_datetime,
                end_datetime,
                location,
                description,
                google_event_id,
                updated_at
            ) VALUES (
                :qr_id,
                :event_title,
                :start_datetime,
                :end_datetime,
                :location,
                :description,
                :google_event_id,
                UTC_TIMESTAMP()
            )
            ON DUPLICATE KEY UPDATE
                event_title = VALUES(event_title),
                start_datetime = VALUES(start_datetime),
                end_datetime = VALUES(end_datetime),
                location = VALUES(location),
                description = VALUES(description),
                google_event_id = VALUES(google_event_id),
                updated_at = UTC_TIMESTAMP()
            """
        )

        await self.session.execute(
            statement,
            {
                "qr_id": qr_id,
                "event_title": event_title,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "location": location,
                "description": description,
                "google_event_id": google_event_id,
            },
        )
        await self.session.flush()

    def _resolve_period_bounds(
        self,
        *,
        range_type: CalendarRangeType,
        year: int,
        month: int | None,
        from_month: int | None,
        to_month: int | None,
    ) -> tuple[datetime, datetime]:
        if range_type == CalendarRangeType.year:
            start = datetime(year, 1, 1, tzinfo=UTC)
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
            return start, end

        if month is not None and (from_month is not None or to_month is not None):
            raise GoogleCalendarServiceError(
                "Provide either month or from_month/to_month for month range"
            )

        if month is not None:
            if not 1 <= month <= 12:
                raise GoogleCalendarServiceError("Month must be between 1 and 12")
            start = datetime(year, month, 1, tzinfo=UTC)
            if month == 12:
                end = datetime(year + 1, 1, 1, tzinfo=UTC)
            else:
                end = datetime(year, month + 1, 1, tzinfo=UTC)
            return start, end

        if from_month is None and to_month is None:
            raise GoogleCalendarServiceError(
                "Month must be provided, or provide both from_month and to_month"
            )

        if from_month is None or to_month is None:
            raise GoogleCalendarServiceError("Both from_month and to_month must be provided")

        if not 1 <= from_month <= 12 or not 1 <= to_month <= 12:
            raise GoogleCalendarServiceError("from_month and to_month must be between 1 and 12")

        if from_month > to_month:
            raise GoogleCalendarServiceError("from_month must be less than or equal to to_month")

        start = datetime(year, from_month, 1, tzinfo=UTC)
        if to_month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(year, to_month + 1, 1, tzinfo=UTC)
        return start, end

    async def _fetch_google_events(
        self,
        *,
        access_token: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "timeMin": time_min.isoformat().replace("+00:00", "Z"),
                    "timeMax": time_max.isoformat().replace("+00:00", "Z"),
                    "maxResults": 2500,
                },
            )

        if response.is_error:
            raise GoogleCalendarServiceError("Google Calendar event list failed")

        payload = response.json()
        items = payload.get("items")
        if not isinstance(items, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            event_id = item.get("id")
            if not isinstance(event_id, str) or not event_id:
                continue

            start_payload = item.get("start") or {}
            end_payload = item.get("end") or {}
            start_raw = start_payload.get("dateTime") or start_payload.get("date")
            end_raw = end_payload.get("dateTime") or end_payload.get("date")

            normalized.append(
                {
                    "google_event_id": event_id,
                    "title": item.get("summary") or "Untitled event",
                    "starts_at": self._parse_rfc3339_datetime(start_raw),
                    "ends_at": self._parse_rfc3339_datetime(end_raw),
                    "event_status": item.get("status") or "confirmed",
                }
            )

        return normalized

    async def _get_campaign_links_by_google_event_id(
        self,
        user_id: int,
        google_event_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not google_event_ids:
            return {}

        result = await self.session.execute(
            text(
                """
                SELECT
                    id,
                    google_event_id,
                    calendar_sync_status,
                    calendar_last_synced_at
                FROM campaigns
                WHERE user_id = :user_id
                  AND deleted_at IS NULL
                  AND google_event_id IN :google_event_ids
                """
            ).bindparams(bindparam("google_event_ids", expanding=True)),
            {"user_id": user_id, "google_event_ids": google_event_ids},
        )

        links: dict[str, dict[str, Any]] = {}
        for row in result.mappings().all():
            links[row["google_event_id"]] = {
                "campaign_id": row["id"],
                "calendar_sync_status": row["calendar_sync_status"],
                "calendar_last_synced_at": row["calendar_last_synced_at"],
            }
        return links

    def _parse_rfc3339_datetime(self, raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            return None

