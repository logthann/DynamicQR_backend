"""Analytics endpoints serving summary-based dashboard data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.campaigns import get_current_principal
from app.core.rbac import Principal, RBACError
from app.db.session import get_db_session
from app.repositories.campaigns import CampaignRepository
from app.repositories.daily_analytics_summary import DailyAnalyticsSummaryRepository
from app.repositories.qr_codes import QRCodeRepository
from app.repositories.scan_logs import ScanLogRepository
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    CampaignComparisonResponse,
    CampaignKPISummaryResponse,
    GA4InsightsResponse,
    GA4RealtimeResponse,
    HourlyScansResponse,
    ScanLogsResponse,
)
from app.schemas.common import ApiErrorResponse
from app.services.analytics_service import AnalyticsService
from app.services.campaign_analytics_service import CampaignAnalyticsService, CampaignAnalyticsServiceError
from app.services.cache_service import CacheService
from app.services.ga4_service import GA4Service

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


async def get_analytics_service(
    session: AsyncSession = Depends(get_db_session),
) -> AnalyticsService:
    """Provide analytics service dependency."""

    return AnalyticsService(DailyAnalyticsSummaryRepository(session), QRCodeRepository(session))


async def get_campaign_analytics_service(
    session: AsyncSession = Depends(get_db_session),
) -> CampaignAnalyticsService:
    """Provide campaign analytics service dependency."""

    campaign_repo = CampaignRepository(session)
    scan_log_repo = ScanLogRepository(session)
    user_integration_repo = UserIntegrationRepository(session)
    cache_service = CacheService()
    ga4_service = GA4Service(user_integration_repo, cache_service)
    qr_code_repo = QRCodeRepository(session)

    return CampaignAnalyticsService(
        campaign_repo, scan_log_repo, user_integration_repo, ga4_service, cache_service, qr_code_repo
    )


@router.get(
    "/{qr_id}",
    response_model=AnalyticsSummaryResponse,
    summary="Get QR analytics summary",
    description="Return dashboard metrics from daily aggregated summary data for one QR code.",
    response_description="Aggregated analytics totals and daily rows.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_qr_analytics(
    qr_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    principal: Principal = Depends(get_current_principal),
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsSummaryResponse:
    """Return dashboard metrics from `daily_analytics_summary` for one QR code."""

    default_end = datetime.now(UTC).date()
    resolved_end = end_date or default_end
    resolved_start = start_date or (resolved_end - timedelta(days=6))

    try:
        return await service.get_qr_summary(
            qr_id=qr_id,
            start_date=resolved_start,
            end_date=resolved_end,
            principal=principal,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# Campaign Analytics Endpoints

@router.get(
    "/campaign/{campaign_id}/comparison",
    response_model=CampaignComparisonResponse,
    summary="Get campaign QR comparison",
    description="Compare campaign QR performance by totals, growth, sparkline, and version history.",
    response_description="QR comparison analytics for a campaign.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_campaign_comparison(
    campaign_id: int,
    start_date: date = Query(..., description="Start date in YYYY-MM-DD"),
    end_date: date = Query(..., description="End date in YYYY-MM-DD"),
    principal: Principal = Depends(get_current_principal),
    service: CampaignAnalyticsService = Depends(get_campaign_analytics_service),
) -> CampaignComparisonResponse:
    """Get campaign-level comparison for all QR codes in date range."""

    try:
        return await service.get_campaign_comparison(campaign_id, start_date, end_date, principal)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CampaignAnalyticsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/campaign/{campaign_id}/summary",
    response_model=CampaignKPISummaryResponse,
    summary="Get campaign KPI summary",
    description="Provide data for the top 3 KPI tags including total scans, active users, conversion rate, and avg session duration.",
    response_description="KPI summary data for a campaign.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_campaign_kpi_summary(
    campaign_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CampaignAnalyticsService = Depends(get_campaign_analytics_service),
) -> CampaignKPISummaryResponse:
    """Get KPI summary for a campaign."""

    try:
        return await service.get_kpi_summary(campaign_id, principal)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CampaignAnalyticsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/campaign/{campaign_id}/internal-scans",
    response_model=HourlyScansResponse,
    summary="Get hourly scan chart",
    description="Query the scan_logs table and group data by hour and device type.",
    response_description="Hourly scan data for a campaign.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_campaign_hourly_scans(
    campaign_id: int,
    start_date: datetime = Query(..., description="Start date for hourly scan data"),
    end_date: datetime = Query(..., description="End date for hourly scan data"),
    principal: Principal = Depends(get_current_principal),
    service: CampaignAnalyticsService = Depends(get_campaign_analytics_service),
) -> HourlyScansResponse:
    """Get hourly scan chart data for a campaign."""

    try:
        return await service.get_hourly_scans(campaign_id, start_date, end_date, principal)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CampaignAnalyticsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/campaign/{campaign_id}/ga4-realtime",
    response_model=GA4RealtimeResponse,
    summary="Get GA4 real-time chart",
    description="Call the GA4 Real-time API with minutesAgo dimension and activeUsers metric.",
    response_description="Real-time GA4 data for a campaign.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_campaign_ga4_realtime(
    campaign_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CampaignAnalyticsService = Depends(get_campaign_analytics_service),
) -> GA4RealtimeResponse:
    """Get GA4 real-time chart data for a campaign."""

    try:
        return await service.get_ga4_realtime(campaign_id, principal)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CampaignAnalyticsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/campaign/{campaign_id}/logs",
    response_model=ScanLogsResponse,
    summary="Get detailed scan logs",
    description="Query the scan_logs table with pagination and sorting options.",
    response_description="Paginated scan logs for a campaign.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_campaign_scan_logs(
    campaign_id: int,
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(50, ge=1, le=1000, description="Number of items per page"),
    sort_by: str = Query("scanned_at", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc/desc)"),
    principal: Principal = Depends(get_current_principal),
    service: CampaignAnalyticsService = Depends(get_campaign_analytics_service),
) -> ScanLogsResponse:
    """Get detailed scan logs for a campaign."""

    try:
        return await service.get_scan_logs(campaign_id, principal, page, limit, sort_by, order)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CampaignAnalyticsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/campaign/{campaign_id}/ga4-insights",
    response_model=GA4InsightsResponse,
    summary="Get GA4 insights",
    description="Call the GA4 API to retrieve detailed behavioral information about active pages.",
    response_description="GA4 insights data for a campaign.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
    },
)
async def get_campaign_ga4_insights(
    campaign_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CampaignAnalyticsService = Depends(get_campaign_analytics_service),
) -> GA4InsightsResponse:
    """Get GA4 insights for a campaign."""

    try:
        return await service.get_ga4_insights(campaign_id, principal)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except CampaignAnalyticsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

