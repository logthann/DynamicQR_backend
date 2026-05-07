"""Tests for analytics dashboard endpoint responses."""

from __future__ import annotations

from datetime import date
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.analytics import get_analytics_service, get_campaign_analytics_service
from app.core.rbac import Principal
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    AnalyticsSummaryRow,
    CampaignComparisonQRCode,
    CampaignComparisonResponse,
)
from app.schemas.qr_code import QRCodeRead, QRCodeStatus, QRType
from app.services.analytics_service import AnalyticsService


class _StubAnalyticsService:
    async def get_qr_summary(
        self,
        *,
        qr_id: int,
        start_date: date,
        end_date: date,
        principal: Principal | None = None,
    ) -> AnalyticsSummaryResponse:
        return AnalyticsSummaryResponse(
            qr_id=qr_id,
            start_date=start_date,
            end_date=end_date,
            total_scans=25,
            unique_visitors=20,
            rows=[
                AnalyticsSummaryRow(summary_date=start_date, total_scans=10, unique_visitors=8),
                AnalyticsSummaryRow(summary_date=end_date, total_scans=15, unique_visitors=12),
            ],
        )


class _StubCampaignAnalyticsService:
    async def get_campaign_comparison(
        self,
        campaign_id: int,
        start_date: date,
        end_date: date,
        principal: Principal,
    ) -> CampaignComparisonResponse:
        return CampaignComparisonResponse(
            campaign_id=campaign_id,
            qr_codes=[
                CampaignComparisonQRCode(
                    id="10",
                    name="Landing QR",
                    campaign="Summer 2026",
                    destination_url="https://example.com/current",
                    total_scans=120,
                    unique_scans=80,
                    growth=20.0,
                    sparkline=[10, 12, 15, 20, 30, 18, 15],
                    versions=[],
                )
            ],
        )


@pytest.mark.asyncio
async def test_get_qr_analytics_returns_summary_payload(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_analytics_service] = lambda: _StubAnalyticsService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.get(
            "/api/v1/analytics/11?start_date=2026-03-20&end_date=2026-03-24"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["qr_id"] == 11
    assert body["total_scans"] == 25
    assert len(body["rows"]) == 2


class _FakeSummaryRepo:
    async def list_for_qr(self, qr_id: int, *, start_date: date, end_date: date):
        return [
            AnalyticsSummaryRow(summary_date=start_date, total_scans=10, unique_visitors=8),
            AnalyticsSummaryRow(summary_date=end_date, total_scans=15, unique_visitors=12),
        ]


class _FakeQRRepo:
    def __init__(self, user_id: int) -> None:
        self._qr = QRCodeRead(
            id=11,
            user_id=user_id,
            campaign_id=1,
            name="Landing QR",
            short_code="abc12345",
            destination_url=cast(Any, "https://example.com/landing"),
            qr_type=QRType.url,
            design_config=cast(Any, {"color": "#000000"}),
            ga_measurement_id=None,
            utm_source=None,
            utm_medium=None,
            utm_campaign=None,
            status=QRCodeStatus.active,
            created_at=datetime(2026, 3, 20, tzinfo=UTC),
            updated_at=datetime(2026, 3, 20, tzinfo=UTC),
            deleted_at=None,
        )

    async def get_by_id(self, qr_id: int, *, include_deleted: bool = False):
        return self._qr if qr_id == self._qr.id else None


@pytest.mark.asyncio
async def test_get_qr_analytics_denies_other_users(app: FastAPI, async_client: AsyncClient) -> None:
    service = AnalyticsService(cast(Any, _FakeSummaryRepo()), cast(Any, _FakeQRRepo(user_id=9)))
    app.dependency_overrides[get_analytics_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.get("/api/v1/analytics/11")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_qr_analytics_allows_admin_for_any_qr(app: FastAPI, async_client: AsyncClient) -> None:
    service = AnalyticsService(cast(Any, _FakeSummaryRepo()), cast(Any, _FakeQRRepo(user_id=9)))
    app.dependency_overrides[get_analytics_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")

    try:
        response = await async_client.get("/api/v1/analytics/11")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["qr_id"] == 11


@pytest.mark.asyncio
async def test_get_campaign_comparison_returns_payload(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_analytics_service] = lambda: _StubCampaignAnalyticsService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.get(
            "/api/v1/analytics/campaign/3/comparison?start_date=2026-05-01&end_date=2026-05-07"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["campaign_id"] == 3
    assert len(body["qr_codes"]) == 1
    assert body["qr_codes"][0]["id"] == "10"


