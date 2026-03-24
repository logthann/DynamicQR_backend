"""Analytics service that composes dashboard responses from summary rows."""

from __future__ import annotations

from datetime import date

from app.repositories.daily_analytics_summary import DailyAnalyticsSummaryRepository
from app.schemas.analytics import AnalyticsSummaryResponse


class AnalyticsService:
    """Expose summary-based analytics queries for dashboard endpoints."""

    def __init__(self, repository: DailyAnalyticsSummaryRepository) -> None:
        self.repository = repository

    async def get_qr_summary(
        self,
        *,
        qr_id: int,
        start_date: date,
        end_date: date,
    ) -> AnalyticsSummaryResponse:
        """Return rolled-up totals and daily rows for one QR in date range."""

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

