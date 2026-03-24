"""Google Calendar event sync service with QR event-detail persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.token_crypto import OAuthTokenCrypto, get_token_crypto
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.integrations import IntegrationProvider


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

