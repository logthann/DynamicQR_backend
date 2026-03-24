"""Tests for analytics aggregation job SQL composition and time windows."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.workers.analytics_aggregator import (
    aggregate_scan_logs_into_daily_summary,
    run_daily_reconciliation,
    run_incremental_aggregation,
)


class _FakeExecuteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.execute_calls: list[tuple[Any, dict[str, Any]]] = []
        self.committed = False

    async def execute(self, statement: Any, params: dict[str, Any]) -> _FakeExecuteResult:
        self.execute_calls.append((statement, params))
        return _FakeExecuteResult(self.rowcount)

    async def commit(self) -> None:
        self.committed = True


class _SessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self._session)


@pytest.mark.asyncio
async def test_aggregate_scan_logs_into_daily_summary_uses_upsert_sql() -> None:
    session = _FakeSession(rowcount=3)

    upserted = await aggregate_scan_logs_into_daily_summary(
        session,
        start_time=datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 3, 24, 10, 5, tzinfo=UTC),
    )

    assert upserted == 3
    sql = str(session.execute_calls[0][0])
    assert "INSERT INTO daily_analytics_summary" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql


@pytest.mark.asyncio
async def test_run_incremental_aggregation_commits_with_5m_window() -> None:
    session = _FakeSession(rowcount=2)
    now = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)

    upserted = await run_incremental_aggregation(
        session_factory=_SessionFactory(session),
        now=now,
        window_minutes=5,
    )

    assert upserted == 2
    assert session.committed is True
    params = session.execute_calls[0][1]
    assert params["end_time"] == now
    assert params["start_time"].minute == 55


@pytest.mark.asyncio
async def test_run_daily_reconciliation_uses_full_day_window() -> None:
    session = _FakeSession(rowcount=7)

    upserted = await run_daily_reconciliation(
        session_factory=_SessionFactory(session),
        target_date=date(2026, 3, 24),
    )

    assert upserted == 7
    params = session.execute_calls[0][1]
    assert params["start_time"].hour == 0
    assert params["end_time"].day == 25

