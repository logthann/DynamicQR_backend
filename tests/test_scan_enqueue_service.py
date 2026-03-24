"""Tests for durable scan enqueue service behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.redirect import RedirectScanMetadata
from app.services.scan_enqueue_service import enqueue_scan_log
from app.workers.queue_client import QueueClient


class _StubQueueClient(QueueClient):
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        if self.should_fail:
            raise RuntimeError("queue unavailable")
        self.calls.append((queue_name, payload))
        return "msg-123"

    async def dequeue(self, queue_name: str, timeout_seconds: int = 1):
        return None

    async def ack(self, message):
        return None

    async def dead_letter(self, message, reason: str):
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_enqueue_scan_log_sends_expected_payload() -> None:
    stub = _StubQueueClient()
    metadata = RedirectScanMetadata(
        scanned_at=datetime(2026, 3, 24, 9, 0, tzinfo=UTC),
        ip_address="203.0.113.1",
        user_agent="UA/1.0",
        device_type="desktop",
        os="Windows",
        browser="Chrome",
        country="VN",
        city="HCM",
        referer="https://example.com",
    )

    message_id = await enqueue_scan_log(
        qr_id=55,
        scan_metadata=metadata,
        queue_client=stub,
        queue_name="scan_logs",
    )

    assert message_id == "msg-123"
    assert len(stub.calls) == 1

    queue_name, payload = stub.calls[0]
    assert queue_name == "scan_logs"
    assert payload["qr_id"] == 55
    assert payload["scan"]["ip_address"] == "203.0.113.1"
    assert payload["scan"]["scanned_at"] == "2026-03-24T09:00:00Z"


@pytest.mark.asyncio
async def test_enqueue_scan_log_raises_runtime_error_on_queue_failure() -> None:
    failing_stub = _StubQueueClient(should_fail=True)
    metadata = RedirectScanMetadata(ip_address="203.0.113.2")

    with pytest.raises(RuntimeError, match="Failed to enqueue scan log message"):
        await enqueue_scan_log(
            qr_id=77,
            scan_metadata=metadata,
            queue_client=failing_stub,
            queue_name="scan_logs",
        )

