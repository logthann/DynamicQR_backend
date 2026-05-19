"""Schemas for analytics summary query inputs and API responses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsSummaryRow(BaseModel):
    """One aggregated day-level analytics row from summary storage."""

    model_config = ConfigDict(from_attributes=True)

    summary_date: date
    total_scans: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)


class AnalyticsSummaryRequest(BaseModel):
    """Range query payload for daily summary analytics retrieval."""

    qr_id: int = Field(gt=0)
    start_date: date
    end_date: date


class AnalyticsSummaryResponse(BaseModel):
    """Dashboard-ready analytics response built from summary rows."""

    qr_id: int
    start_date: date
    end_date: date
    total_scans: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)
    rows: list[AnalyticsSummaryRow]


# Campaign Analytics Schemas

class CampaignKPISummaryResponse(BaseModel):
    """KPI summary for a campaign including scan logs and GA4 data."""
    
    campaign_id: int
    total_scans: int = Field(ge=0)
    active_users_ga4: int = Field(ge=0)
    conversion_rate: float = Field(ge=0)
    avg_session_duration: float = Field(ge=0)


class HourlyScanDataPoint(BaseModel):
    """Single data point for hourly scan chart."""
    
    hour: datetime
    mobile: int = Field(ge=0)
    desktop: int = Field(ge=0)
    tablet: int = Field(ge=0)
    scans: int = Field(ge=0)


class HourlyScansResponse(BaseModel):
    """Hourly scan chart data for a campaign."""
    
    campaign_id: int
    data: list[HourlyScanDataPoint]


class GA4RealtimeDataPoint(BaseModel):
    """Single data point for GA4 real-time chart."""
    
    time_label: str
    active_users: int = Field(ge=0)


class GA4RealtimeAggregated(BaseModel):
    """Aggregated GA4 real-time data for a campaign."""

    total_active_users: int
    data: list[GA4RealtimeDataPoint]


class GA4RealtimeResponse(BaseModel):
    """GA4 real-time chart data for a campaign."""
    
    campaign_id: int
    aggregated: GA4RealtimeAggregated
    sources: dict[str, GA4RealtimeAggregated]


class ScanLogEntry(BaseModel):
    """Single scan log entry."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    scanned_at: datetime
    ip_address: str | None
    device_type: str | None
    city: str | None


class ScanLogsResponse(BaseModel):
    """Paginated scan logs for a campaign."""
    
    campaign_id: int
    page: int = Field(ge=1)
    limit: int = Field(ge=1, le=1000)
    total: int = Field(ge=0)
    logs: list[ScanLogEntry]


class GA4InsightEntry(BaseModel):
    """Single GA4 insight entry."""
    
    page_path: str
    session_source: str
    device_category: str
    engagement_time: float = Field(ge=0)


class GA4InsightsResponse(BaseModel):
    """GA4 insights data for a campaign."""
    
    campaign_id: int
    insights: list[GA4InsightEntry]


class QRVersionActivePeriod(BaseModel):
    """Active period for one QR configuration version."""

    start: datetime
    end: datetime | None


class QRVersionComparison(BaseModel):
    """Version-level scan metrics for campaign comparison."""

    version: str
    title: str
    active_period: QRVersionActivePeriod
    destination_url: str
    total_scans: int = Field(ge=0)
    scan_diff: int | None
    status: str


class CampaignComparisonQRCode(BaseModel):
    """Campaign comparison payload for one QR code."""

    id: str
    name: str
    campaign: str
    destination_url: str
    total_scans: int = Field(ge=0)
    unique_scans: int = Field(ge=0)
    growth: float | None
    sparkline: list[int]
    versions: list[QRVersionComparison]


class CampaignComparisonResponse(BaseModel):
    """Comparison response for all QR codes in a campaign."""

    campaign_id: int
    qr_codes: list[CampaignComparisonQRCode]
