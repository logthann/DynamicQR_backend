"""Tests for Google Calendar service event sync and persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.token_crypto import OAuthTokenCrypto
from app.schemas.integrations import IntegrationProvider, ProviderCredentialRecord
from app.services.google_calendar_service import GoogleCalendarService, GoogleCalendarServiceError

FERNET_TEST_KEY = "oTP_EcEzN_G9ksvcjmcBbN1q8A5xj9Pf3Y8V97tXWW0="


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

