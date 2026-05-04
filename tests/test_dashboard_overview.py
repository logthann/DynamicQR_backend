"""Tests for the dashboard overview aggregation endpoint."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.dashboard import get_dashboard_service
from app.core.rbac import Principal
from app.schemas.dashboard import (
    DashboardCampaignRow,
    DashboardCampaignTable,
    DashboardChartsSection,
    DashboardKPI,
    DashboardKPISection,
    DashboardMetadata,
    DashboardOverviewResponse,
    DashboardRange,
    DashboardScansPerCampaignItem,
    DashboardTrafficDistributionItem,
    TrendDirection,
)
from app.services.dashboard_service import DashboardOverviewResult, DashboardService


def _build_payload() -> DashboardOverviewResponse:
    return DashboardOverviewResponse(
        range=DashboardRange(
            start_date=date(2026, 3, 23),
            end_date=date(2026, 4, 22),
            timezone="Asia/Ho_Chi_Minh",
            compare_previous=True,
        ),
        metadata=DashboardMetadata(top_campaigns_limit=2, include_inactive=True),
        kpis=DashboardKPISection(
            total_scans=DashboardKPI(
                value=300,
                previous_value=200,
                change_abs=100,
                change_pct=50.0,
                trend=TrendDirection.up,
            ),
            active_campaigns=DashboardKPI(
                value=8,
                previous_value=6,
                change_abs=2,
                change_pct=33.33,
                trend=TrendDirection.up,
            ),
            total_unique_users=DashboardKPI(
                value=120,
                previous_value=90,
                change_abs=30,
                change_pct=33.33,
                trend=TrendDirection.up,
            ),
            system_growth=DashboardKPI(
                value=50.0,
                previous_value=100.0,
                change_abs=-50.0,
                change_pct=-50.0,
                trend=TrendDirection.down,
            ),
        ),
        charts=DashboardChartsSection(
            scans_per_campaign=[
                DashboardScansPerCampaignItem(
                    campaign_id="1",
                    campaign_name="Summer Sale 2024",
                    scans=120,
                    traffic_share_pct=40.0,
                ),
                DashboardScansPerCampaignItem(
                    campaign_id="2",
                    campaign_name="Product Launch Q4",
                    scans=100,
                    traffic_share_pct=33.33,
                ),
            ],
            traffic_distribution=[
                DashboardTrafficDistributionItem(
                    campaign_id="1",
                    campaign_name="Summer Sale 2024",
                    traffic_share_pct=40.0,
                ),
                DashboardTrafficDistributionItem(
                    campaign_id="2",
                    campaign_name="Product Launch Q4",
                    traffic_share_pct=33.33,
                ),
            ],
        ),
        campaigns=DashboardCampaignTable(total=3, items=[]),
    )


@pytest.mark.asyncio
async def test_dashboard_service_builds_comparison_payload() -> None:
    session = AsyncMock()
    service = DashboardService(session)

    service._fetch_scan_stats = AsyncMock(
        side_effect=[
            type("Stats", (), {"total_scans": 300, "unique_users": 120})(),
            type("Stats", (), {"total_scans": 200, "unique_users": 90})(),
            type("Stats", (), {"total_scans": 100, "unique_users": 60})(),
        ]
    )
    service._fetch_active_campaign_count = AsyncMock(side_effect=[8, 6])
    service._fetch_campaign_rows = AsyncMock(
        return_value=[
            DashboardCampaignRow(
                campaign_id="1",
                campaign_name="Summer Sale 2024",
                status="active",
                scans=120,
                unique_users=70,
            ),
            DashboardCampaignRow(
                campaign_id="2",
                campaign_name="Product Launch Q4",
                status="active",
                scans=100,
                unique_users=60,
            ),
            DashboardCampaignRow(
                campaign_id="3",
                campaign_name="Archive Campaign",
                status="archived",
                scans=80,
                unique_users=40,
            ),
        ]
    )

    result = await service.get_overview(
        Principal(user_id=7, role="employee"),
        start_date=date(2026, 3, 23),
        end_date=date(2026, 4, 22),
        timezone="Asia/Ho_Chi_Minh",
        top_campaigns_limit=2,
        include_inactive=True,
    )

    assert result.payload.range.start_date == date(2026, 3, 23)
    assert result.payload.kpis.total_scans.value == 300
    assert result.payload.kpis.system_growth.value == 50.0
    assert len(result.payload.charts.scans_per_campaign) == 2
    assert result.payload.charts.scans_per_campaign[0].traffic_share_pct == 40.0
    assert result.payload.campaigns.total == 3
    assert result.payload.metadata.top_campaigns_limit == 2
    assert result.etag.startswith('"') and result.etag.endswith('"')


class _StubDashboardService:
    async def get_overview(self, principal: Principal, **kwargs) -> DashboardOverviewResult:
        payload = DashboardOverviewResponse(
            range=DashboardRange(
                start_date=date(2026, 3, 23),
                end_date=date(2026, 4, 22),
                timezone=kwargs["timezone"],
                compare_previous=kwargs["compare_previous"],
            ),
            metadata=DashboardMetadata(
                top_campaigns_limit=kwargs["top_campaigns_limit"],
                include_inactive=kwargs["include_inactive"],
            ),
            kpis=DashboardKPISection(
                total_scans=DashboardKPI(value=300, trend=TrendDirection.flat),
                active_campaigns=DashboardKPI(value=8, trend=TrendDirection.flat),
                total_unique_users=DashboardKPI(value=120, trend=TrendDirection.flat),
                system_growth=DashboardKPI(value=50.0, trend=TrendDirection.flat),
            ),
            charts=DashboardChartsSection(scans_per_campaign=[], traffic_distribution=[]),
            campaigns=DashboardCampaignTable(total=0, items=[]),
        )
        return DashboardOverviewResult(payload=payload, etag='"dashboard-etag"')


@pytest.mark.asyncio
async def test_dashboard_overview_endpoint_returns_headers(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_dashboard_service] = lambda: _StubDashboardService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=7,
        role="employee",
    )

    try:
        response = await async_client.get(
            "/api/v1/dashboard/overview?start_date=2026-03-23&end_date=2026-04-22"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["ETag"] == '"dashboard-etag"'
    assert response.headers["Cache-Control"] == "private, max-age=30"
    body = response.json()
    assert body["metadata"]["include_inactive"] is True
    assert body["range"]["timezone"] == "Asia/Ho_Chi_Minh"

