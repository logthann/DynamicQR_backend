"""Tests for local scan-log worker runner loop."""

from __future__ import annotations

import asyncio

import pytest

from app.workers.dev_scan_worker import run_scan_log_worker


@pytest.mark.asyncio
async def test_run_scan_log_worker_stops_on_stop_event() -> None:
    stop_event = asyncio.Event()
    calls = {"count": 0}

    async def _process_once() -> bool:
        calls["count"] += 1
        stop_event.set()
        return True

    await run_scan_log_worker(process_once=_process_once, stop_event=stop_event)

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_run_scan_log_worker_sleeps_when_queue_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_event = asyncio.Event()
    sleeps: list[float] = []

    async def _process_once() -> bool:
        return False

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        stop_event.set()

    monkeypatch.setattr("app.workers.dev_scan_worker.asyncio.sleep", _fake_sleep)

    await run_scan_log_worker(
        process_once=_process_once,
        stop_event=stop_event,
        poll_interval_seconds=0.5,
    )

    assert sleeps == [0.5]

