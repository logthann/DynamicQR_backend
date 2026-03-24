"""In-memory metrics helpers for redirect latency and queue lag signals."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class MetricsSnapshot:
    """Small metrics snapshot used for debugging and tests."""

    redirect_latency_count: int
    redirect_latency_avg_ms: float
    queue_lag_count: int
    queue_lag_avg_seconds: float


class MetricsCollector:
    """Store bounded samples for lightweight runtime instrumentation."""

    def __init__(self, *, max_samples: int = 1000) -> None:
        self._redirect_latency_ms: deque[float] = deque(maxlen=max_samples)
        self._queue_lag_seconds: deque[float] = deque(maxlen=max_samples)

    def observe_redirect_latency_ms(self, value_ms: float) -> None:
        """Record redirect path latency in milliseconds."""

        self._redirect_latency_ms.append(max(value_ms, 0.0))

    def observe_queue_lag_seconds(self, value_seconds: float) -> None:
        """Record queue lag in seconds between enqueue and processing."""

        self._queue_lag_seconds.append(max(value_seconds, 0.0))

    def snapshot(self) -> MetricsSnapshot:
        """Return aggregate averages for collected metrics."""

        redirect_count = len(self._redirect_latency_ms)
        queue_count = len(self._queue_lag_seconds)

        redirect_avg = (
            sum(self._redirect_latency_ms) / redirect_count if redirect_count else 0.0
        )
        queue_avg = sum(self._queue_lag_seconds) / queue_count if queue_count else 0.0

        return MetricsSnapshot(
            redirect_latency_count=redirect_count,
            redirect_latency_avg_ms=redirect_avg,
            queue_lag_count=queue_count,
            queue_lag_avg_seconds=queue_avg,
        )


_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Return singleton metrics collector instance."""

    global _metrics_collector

    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()

    return _metrics_collector


def reset_metrics_collector() -> None:
    """Reset singleton metrics collector; intended for tests."""

    global _metrics_collector
    _metrics_collector = None


def compute_queue_lag_seconds(enqueued_at: datetime, *, now: datetime | None = None) -> float:
    """Compute queue lag seconds from enqueue time to now in UTC."""

    current = now or datetime.now(UTC)

    if enqueued_at.tzinfo is None:
        enqueued_at = enqueued_at.replace(tzinfo=UTC)

    return max((current - enqueued_at).total_seconds(), 0.0)

