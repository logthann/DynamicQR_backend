"""Scheduler bootstrap for incremental and daily analytics aggregation jobs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from app.core.config import get_settings

logger = logging.getLogger(__name__)

JobCallback = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class ScheduledJob:
    """Runtime model describing one scheduler job."""

    name: str
    mode: str
    callback: JobCallback
    interval_seconds: float | None = None
    daily_time_utc: time | None = None


class SchedulerBootstrap:
    """Minimal async scheduler with interval and daily job support."""

    def __init__(self) -> None:
        self._jobs: list[ScheduledJob] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._stop_event = asyncio.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return True when scheduler loops are active."""

        return self._running

    def add_interval_job(
        self,
        name: str,
        interval_seconds: float,
        callback: JobCallback,
    ) -> None:
        """Register an interval-based async job."""

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")

        self._jobs.append(
            ScheduledJob(
                name=name,
                mode="interval",
                callback=callback,
                interval_seconds=interval_seconds,
            ),
        )

    def add_daily_job(
        self,
        name: str,
        at_utc: time,
        callback: JobCallback,
    ) -> None:
        """Register a daily async job running at a UTC wall-clock time."""

        self._jobs.append(
            ScheduledJob(
                name=name,
                mode="daily",
                callback=callback,
                daily_time_utc=at_utc,
            ),
        )

    async def start(self) -> None:
        """Start all registered jobs once."""

        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        for job in self._jobs:
            if job.mode == "interval":
                task = asyncio.create_task(self._run_interval_job(job), name=f"job:{job.name}")
            else:
                task = asyncio.create_task(self._run_daily_job(job), name=f"job:{job.name}")
            self._tasks.append(task)

        logger.info("Scheduler started with %d jobs", len(self._jobs))

    async def stop(self) -> None:
        """Stop all running jobs and clear internal task state."""

        if not self._running:
            return

        self._stop_event.set()

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        self._running = False
        logger.info("Scheduler stopped")

    async def _run_interval_job(self, job: ScheduledJob) -> None:
        assert job.interval_seconds is not None

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=job.interval_seconds)
                break
            except TimeoutError:
                await self._safe_execute(job)

    async def _run_daily_job(self, job: ScheduledJob) -> None:
        assert job.daily_time_utc is not None

        while not self._stop_event.is_set():
            wait_seconds = seconds_until_next_daily_run(job.daily_time_utc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                break
            except TimeoutError:
                await self._safe_execute(job)

    async def _safe_execute(self, job: ScheduledJob) -> None:
        try:
            await job.callback()
            logger.debug("Scheduled job '%s' completed", job.name)
        except Exception:
            logger.exception("Scheduled job '%s' failed", job.name)


async def _noop_aggregation_job() -> None:
    """Default placeholder callback for scheduler bootstrap before job wiring."""

    logger.debug("No-op aggregation callback executed")


def bootstrap_scheduler() -> SchedulerBootstrap:
    """Create scheduler with default 5-minute and daily aggregation jobs."""

    settings = get_settings()
    scheduler = SchedulerBootstrap()

    scheduler.add_interval_job(
        name="analytics_5min_aggregation",
        interval_seconds=float(settings.analytics_cron_interval_minutes * 60),
        callback=_noop_aggregation_job,
    )
    scheduler.add_daily_job(
        name="analytics_daily_reconciliation",
        at_utc=time(hour=0, minute=5, tzinfo=UTC),
        callback=_noop_aggregation_job,
    )

    return scheduler


def seconds_until_next_daily_run(at_utc: time, now: datetime | None = None) -> float:
    """Compute seconds until next scheduled UTC wall-clock run."""

    current = now or datetime.now(UTC)
    target_today = datetime.combine(current.date(), at_utc)

    if at_utc.tzinfo is None:
        target_today = target_today.replace(tzinfo=UTC)

    if target_today <= current:
        target_today = target_today + timedelta(days=1)

    return (target_today - current).total_seconds()


_scheduler: SchedulerBootstrap | None = None


def get_scheduler() -> SchedulerBootstrap:
    """Return singleton scheduler bootstrap instance."""

    global _scheduler

    if _scheduler is None:
        _scheduler = bootstrap_scheduler()

    return _scheduler


def set_scheduler(scheduler: SchedulerBootstrap | None) -> None:
    """Override singleton scheduler, mainly for tests."""

    global _scheduler
    _scheduler = scheduler

