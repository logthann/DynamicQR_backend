"""Repository helpers for reading aggregated daily analytics summary rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analytics import AnalyticsSummaryRow


class DailyAnalyticsSummaryRepository:
    """Read dashboard analytics data from materialized daily summary table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_qr(
        self,
        qr_id: int,
        *,
        start_date: date,
        end_date: date,
    ) -> list[AnalyticsSummaryRow]:
        """List daily summary rows for one QR id within an inclusive date range."""

        statement = text(
            """
            SELECT
                summary_date,
                total_scans,
                unique_visitors
            FROM daily_analytics_summary
            WHERE qr_id = :qr_id
              AND summary_date >= :start_date
              AND summary_date <= :end_date
            ORDER BY summary_date ASC
            """
        )

        result = await self.session.execute(
            statement,
            {
                "qr_id": qr_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [AnalyticsSummaryRow.model_validate(dict(row)) for row in result.mappings().all()]

