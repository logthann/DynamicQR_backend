"""Tests for scheduler bootstrap behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time

from app.workers.scheduler import SchedulerBootstrap, seconds_until_next_daily_run


async def test_interval_job_executes() -> None:
    scheduler = SchedulerBootstrap()
    counter = {"runs": 0}
    completed = asyncio.Event()

    async def sample_job() -> None:
        counter["runs"] += 1
        if counter["runs"] >= 2:
            completed.set()

    scheduler.add_interval_job("sample", interval_seconds=0.01, callback=sample_job)

    await scheduler.start()
    await asyncio.wait_for(completed.wait(), timeout=1)
    await scheduler.stop()

    assert counter["runs"] >= 2


def test_seconds_until_next_daily_run_for_future_time() -> None:
    now = datetime(2026, 3, 24, 10, 0, 0, tzinfo=UTC)
    next_run = time(hour=10, minute=30, tzinfo=UTC)

    result = seconds_until_next_daily_run(next_run, now=now)

    assert int(result) == 1800


def test_seconds_until_next_daily_run_rolls_to_next_day() -> None:
    now = datetime(2026, 3, 24, 23, 59, 0, tzinfo=UTC)
    next_run = time(hour=0, minute=5, tzinfo=UTC)

    result = seconds_until_next_daily_run(next_run, now=now)

    assert int(result) == 360

