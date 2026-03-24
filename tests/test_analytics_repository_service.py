"""Tests for daily analytics summary repository and service behavior."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.repositories.daily_analytics_summary import DailyAnalyticsSummaryRepository
from app.schemas.analytics import AnalyticsSummaryRow
from app.services.analytics_service import AnalyticsService


class _MappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingResult:
        return _MappingResult(self._rows)


@pytest.mark.asyncio
async def test_repository_lists_rows_in_date_range() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(
        [
            {"summary_date": date(2026, 3, 23), "total_scans": 10, "unique_visitors": 8},
            {"summary_date": date(2026, 3, 24), "total_scans": 12, "unique_visitors": 9},
        ]
    )
    repo = DailyAnalyticsSummaryRepository(session)

    rows = await repo.list_for_qr(11, start_date=date(2026, 3, 23), end_date=date(2026, 3, 24))

    assert len(rows) == 2
    statement = session.execute.await_args.args[0]
    assert "FROM daily_analytics_summary" in str(statement)


@pytest.mark.asyncio
async def test_service_rolls_up_totals_from_rows() -> None:
    repo = AsyncMock()
    repo.list_for_qr.return_value = [
        AnalyticsSummaryRow(summary_date=date(2026, 3, 23), total_scans=10, unique_visitors=8),
        AnalyticsSummaryRow(summary_date=date(2026, 3, 24), total_scans=12, unique_visitors=9),
    ]
    service = AnalyticsService(repo)

    summary = await service.get_qr_summary(
        qr_id=11,
        start_date=date(2026, 3, 23),
        end_date=date(2026, 3, 24),
    )

    assert summary.total_scans == 22
    assert summary.unique_visitors == 17
    assert len(summary.rows) == 2

