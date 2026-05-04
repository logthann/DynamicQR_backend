"""Dashboard overview endpoint."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.campaigns import get_current_principal
from app.core.rbac import Principal, RBACError
from app.db.session import get_db_session
from app.schemas.common import ApiErrorResponse
from app.schemas.dashboard import DashboardOverviewResponse
from app.services.dashboard_service import DashboardOverviewResult, DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


async def get_dashboard_service(
    session: AsyncSession = Depends(get_db_session),
) -> DashboardService:
    """Provide dashboard overview service dependency."""

    return DashboardService(session)


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Get dashboard overview aggregates",
    description=(
        "Returns KPI cards, chart series, campaign rows, and resolved metadata in a single request."
    ),
    response_description="Aggregated dashboard overview payload.",
    responses={
        400: {"model": ApiErrorResponse},
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
    },
)
async def get_dashboard_overview(
    response: Response,
    start_date: date | None = None,
    end_date: date | None = None,
    compare_previous: bool = Query(default=True),
    timezone: str = Query(default="Asia/Ho_Chi_Minh"),
    top_campaigns_limit: int = Query(default=5, ge=1, le=50),
    include_inactive: bool = Query(default=True),
    principal: Principal = Depends(get_current_principal),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardOverviewResponse:
    """Return all dashboard overview aggregates for the authenticated principal."""

    try:
        result: DashboardOverviewResult = await service.get_overview(
            principal,
            start_date=start_date,
            end_date=end_date,
            compare_previous=compare_previous,
            timezone=timezone,
            top_campaigns_limit=top_campaigns_limit,
            include_inactive=include_inactive,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    response.headers["ETag"] = result.etag
    response.headers["Cache-Control"] = "private, max-age=30"
    return result.payload

