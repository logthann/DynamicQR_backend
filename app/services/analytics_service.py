"""Analytics service that composes dashboard responses from summary rows."""

from __future__ import annotations

from datetime import date

from app.core.rbac import Principal, RBACError, ensure_scope_access
from app.repositories.qr_codes import QRCodeRepository
from app.repositories.daily_analytics_summary import DailyAnalyticsSummaryRepository
from app.schemas.analytics import AnalyticsSummaryResponse


class AnalyticsService:
    """Expose summary-based analytics queries for dashboard endpoints."""

    def __init__(
        self,
        repository: DailyAnalyticsSummaryRepository,
        qr_repository: QRCodeRepository | None = None,
    ) -> None:
        self.repository = repository
        self.qr_repository = qr_repository

    async def get_qr_summary(
        self,
        *,
        qr_id: int,
        start_date: date,
        end_date: date,
        principal: Principal | None = None,
    ) -> AnalyticsSummaryResponse:
        """Return rolled-up totals and daily rows for one QR in date range."""

        if principal is not None:
            if self.qr_repository is None:
                raise RBACError("QR ownership lookup is unavailable")

            qr_code = await self.qr_repository.get_by_id(qr_id)
            if qr_code is None:
                raise LookupError("QR code not found")

            ensure_scope_access(
                principal,
                owner_user_id=qr_code.user_id,
                owner_company_name=None,
            )

        rows = await self.repository.list_for_qr(
            qr_id,
            start_date=start_date,
            end_date=end_date,
        )

        return AnalyticsSummaryResponse(
            qr_id=qr_id,
            start_date=start_date,
            end_date=end_date,
            total_scans=sum(row.total_scans for row in rows),
            unique_visitors=sum(row.unique_visitors for row in rows),
            rows=rows,
        )

