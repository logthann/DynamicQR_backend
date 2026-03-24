"""Analytics endpoints serving summary-based dashboard data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.daily_analytics_summary import DailyAnalyticsSummaryRepository
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


async def get_analytics_service(
    session: AsyncSession = Depends(get_db_session),
) -> AnalyticsService:
    """Provide analytics service dependency."""

    return AnalyticsService(DailyAnalyticsSummaryRepository(session))


@router.get(
    "/{qr_id}",
    response_model=AnalyticsSummaryResponse,
    summary="Get QR analytics summary",
    description="Return dashboard metrics from daily aggregated summary data for one QR code.",
    response_description="Aggregated analytics totals and daily rows.",
)
async def get_qr_analytics(
    qr_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsSummaryResponse:
    """Return dashboard metrics from `daily_analytics_summary` for one QR code."""

    default_end = datetime.now(UTC).date()
    resolved_end = end_date or default_end
    resolved_start = start_date or (resolved_end - timedelta(days=6))

    return await service.get_qr_summary(
        qr_id=qr_id,
        start_date=resolved_start,
        end_date=resolved_end,
    )

