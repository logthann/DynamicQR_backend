"""Tests for queue client interfaces and in-memory durability semantics."""

from __future__ import annotations

from app.workers.queue_client import InMemoryQueueClient


async def test_inmemory_queue_roundtrip_ack() -> None:
    client = InMemoryQueueClient()

    message_id = await client.enqueue("scan_logs", {"qr_id": 1, "ip": "127.0.0.1"})
    dequeued = await client.dequeue("scan_logs", timeout_seconds=1)

    assert dequeued is not None
    assert dequeued.envelope.id == message_id
    assert dequeued.envelope.payload["qr_id"] == 1

    await client.ack(dequeued)
    nothing_left = await client.dequeue("scan_logs", timeout_seconds=0)
    assert nothing_left is None

    await client.close()


async def test_inmemory_queue_dead_letter() -> None:
    client = InMemoryQueueClient()

    await client.enqueue("scan_logs", {"qr_id": 99, "reason": "broken"})
    dequeued = await client.dequeue("scan_logs", timeout_seconds=1)

    assert dequeued is not None

    await client.dead_letter(dequeued, reason="db_unavailable")
    nothing_left = await client.dequeue("scan_logs", timeout_seconds=0)
    assert nothing_left is None

    await client.close()

