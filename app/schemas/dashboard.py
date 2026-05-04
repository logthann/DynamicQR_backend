"""Schemas for the aggregated dashboard overview endpoint."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TrendDirection(str, Enum):
    """Direction of metric movement versus previous period."""

    up = "up"
    down = "down"
    flat = "flat"


class DashboardRange(BaseModel):
    """Resolved date boundaries and options used for aggregation."""

    start_date: date
    end_date: date
    timezone: str
    compare_previous: bool


class DashboardMetadata(BaseModel):
    """Request options echoed back for dashboard consumers."""

    top_campaigns_limit: int = Field(ge=1, le=50)
    include_inactive: bool


class DashboardKPI(BaseModel):
    """One KPI card value with optional period-over-period comparison fields."""

    value: float | int
    previous_value: float | int | None = None
    change_abs: float | int | None = None
    change_pct: float | None = None
    trend: TrendDirection = TrendDirection.flat


class DashboardKPISection(BaseModel):
    """Top-level KPI cards returned for dashboard overview."""

    total_scans: DashboardKPI
    active_campaigns: DashboardKPI
    total_unique_users: DashboardKPI
    system_growth: DashboardKPI


class DashboardScansPerCampaignItem(BaseModel):
    """Chart item for absolute scan volume by campaign."""

    campaign_id: str
    campaign_name: str
    scans: int = Field(ge=0)
    traffic_share_pct: float = Field(ge=0)


class DashboardTrafficDistributionItem(BaseModel):
    """Chart item for traffic share split by campaign."""

    campaign_id: str
    campaign_name: str
    traffic_share_pct: float = Field(ge=0)


class DashboardChartsSection(BaseModel):
    """Chart datasets used by the overview page."""

    scans_per_campaign: list[DashboardScansPerCampaignItem]
    traffic_distribution: list[DashboardTrafficDistributionItem]


class DashboardCampaignRow(BaseModel):
    """One campaign row for the overview table."""

    campaign_id: str
    campaign_name: str
    status: str
    scans: int = Field(ge=0)
    unique_users: int = Field(ge=0)


class DashboardCampaignTable(BaseModel):
    """Campaign table payload for overview page."""

    total: int = Field(ge=0)
    items: list[DashboardCampaignRow]


class DashboardOverviewResponse(BaseModel):
    """Aggregated response for dashboard overview in one request."""

    range: DashboardRange
    metadata: DashboardMetadata
    kpis: DashboardKPISection
    charts: DashboardChartsSection
    campaigns: DashboardCampaignTable

