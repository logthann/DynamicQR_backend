"""Analytics endpoints serving summary-based dashboard data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.campaigns import get_current_principal
from app.core.rbac import Principal, RBACError
from app.db.session import get_db_session
from app.repositories.daily_analytics_summary import DailyAnalyticsSummaryRepository
from app.repositories.qr_codes import QRCodeRepository
from app.schemas.analytics import AnalyticsSummaryResponse
from app.schemas.common import ApiErrorResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


async def get_analytics_service(
    session: AsyncSession = Depends(get_db_session),
) -> AnalyticsService:
    """Provide analytics service dependency."""

    return AnalyticsService(DailyAnalyticsSummaryRepository(session), QRCodeRepository(session))


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

