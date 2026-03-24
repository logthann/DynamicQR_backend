"""Tests for scan-log worker consume/persist/ack behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.workers.queue_client import DequeuedMessage, QueueClient, QueueEnvelope
from app.workers.scan_log_worker import process_next_scan_log_message


class _StubQueueClient(QueueClient):
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._payload = payload
        self.acked = False
        self.dead_letter_reason: str | None = None
        self.enqueued_messages: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        self.enqueued_messages.append((queue_name, payload))
        return "noop"

    async def dequeue(self, queue_name: str, timeout_seconds: int = 1) -> DequeuedMessage | None:
        if self._payload is None:
            return None

        envelope = QueueEnvelope(
            id="msg-1",
            payload=self._payload,
            attempts=0,
            enqueued_at=datetime.now(UTC).isoformat(),
        )
        return DequeuedMessage(envelope=envelope, raw="{}", queue_name=queue_name)

    async def ack(self, message: DequeuedMessage) -> None:
        self.acked = True

    async def dead_letter(self, message: DequeuedMessage, reason: str) -> None:
        self.dead_letter_reason = reason

    async def close(self) -> None:
        return None


class _FakeSession:
    def __init__(self, *, fail_on_execute: bool = False) -> None:
        self.fail_on_execute = fail_on_execute
        self.executed = False
        self.committed = False

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        if self.fail_on_execute:
            raise RuntimeError("db unavailable")
        self.executed = True

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
        self.session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self.session)


@pytest.mark.asyncio
async def test_process_next_scan_log_message_ack_on_success() -> None:
    queue = _StubQueueClient(
        payload={
            "qr_id": 11,
            "scan": {
                "scanned_at": "2026-03-24T09:00:00Z",
                "ip_address": "203.0.113.10",
            },
        }
    )
    session = _FakeSession()

    handled = await process_next_scan_log_message(
        queue_client=queue,
        session_factory=_SessionFactory(session),
        queue_name="scan_logs",
        timeout_seconds=0,
    )

    assert handled is True
    assert session.executed is True
    assert session.committed is True
    assert queue.acked is True
    assert queue.dead_letter_reason is None


@pytest.mark.asyncio
async def test_process_next_scan_log_message_dead_letters_invalid_payload() -> None:
    queue = _StubQueueClient(payload={"scan": {"ip_address": "203.0.113.10"}})

    handled = await process_next_scan_log_message(
        queue_client=queue,
        session_factory=_SessionFactory(_FakeSession()),
        queue_name="scan_logs",
        timeout_seconds=0,
    )

    assert handled is True
    assert queue.acked is False
    assert queue.dead_letter_reason is not None
    assert queue.dead_letter_reason.startswith("invalid_payload")


@pytest.mark.asyncio
async def test_process_next_scan_log_message_dead_letters_db_failures() -> None:
    queue = _StubQueueClient(
        payload={
            "qr_id": 22,
            "scan": {
                "scanned_at": "2026-03-24T10:00:00Z",
                "ip_address": "198.51.100.20",
            },
        }
    )

    handled = await process_next_scan_log_message(
        queue_client=queue,
        session_factory=_SessionFactory(_FakeSession(fail_on_execute=True)),
        queue_name="scan_logs",
        timeout_seconds=0,
        max_retry_attempts=0,
    )

    assert handled is True
    assert queue.acked is False
    assert queue.dead_letter_reason is not None
    assert queue.dead_letter_reason.startswith("db_write_failed")
    assert "retry_exhausted" in queue.dead_letter_reason


@pytest.mark.asyncio
async def test_process_next_scan_log_message_retries_before_dead_letter() -> None:
    queue = _StubQueueClient(
        payload={
            "qr_id": 33,
            "scan": {
                "scanned_at": "2026-03-24T11:00:00Z",
                "ip_address": "192.0.2.10",
            },
        }
    )

    handled = await process_next_scan_log_message(
        queue_client=queue,
        session_factory=_SessionFactory(_FakeSession(fail_on_execute=True)),
        queue_name="scan_logs",
        timeout_seconds=0,
        max_retry_attempts=2,
    )

    assert handled is True
    assert queue.acked is True
    assert queue.dead_letter_reason is None
    assert len(queue.enqueued_messages) == 1
    retry_queue, retry_payload = queue.enqueued_messages[0]
    assert retry_queue == "scan_logs"
    assert retry_payload["__retry_attempt"] == 1

