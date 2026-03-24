"""Tests for integration and analytics schema validation behavior."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.analytics import AnalyticsSummaryRequest, AnalyticsSummaryResponse, AnalyticsSummaryRow
from app.schemas.integrations import (
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthConnectRequest,
    ProviderCredentialWrite,
)


def test_oauth_connect_request_accepts_provider_scopes() -> None:
    payload = OAuthConnectRequest(
        provider_name=IntegrationProvider.google_calendar,
        state="state-token-123",
        scopes=["calendar.events", "calendar.readonly"],
    )

    assert payload.provider_name == IntegrationProvider.google_calendar
    assert len(payload.scopes) == 2


def test_provider_credential_write_requires_access_token() -> None:
    with pytest.raises(ValidationError):
        ProviderCredentialWrite(provider_name=IntegrationProvider.google_analytics, access_token="")


def test_integration_connection_status_reports_refresh_availability() -> None:
    status = IntegrationConnectionStatus(
        provider_name=IntegrationProvider.google_analytics,
        connected=True,
        has_refresh_token=True,
    )

    assert status.connected is True
    assert status.has_refresh_token is True


def test_analytics_summary_request_rejects_non_positive_qr_id() -> None:
    with pytest.raises(ValidationError):
        AnalyticsSummaryRequest(qr_id=0, start_date=date(2026, 3, 1), end_date=date(2026, 3, 24))


def test_analytics_summary_response_accepts_rows() -> None:
    row = AnalyticsSummaryRow(summary_date=date(2026, 3, 24), total_scans=100, unique_visitors=80)
    response = AnalyticsSummaryResponse(
        qr_id=12,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 24),
        total_scans=100,
        unique_visitors=80,
        rows=[row],
    )

    assert response.qr_id == 12
    assert response.rows[0].summary_date == date(2026, 3, 24)

