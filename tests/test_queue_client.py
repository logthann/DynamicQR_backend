"""Tests for queue client interfaces and in-memory durability semantics."""

from __future__ import annotations

from types import SimpleNamespace

from app.workers.queue_client import InMemoryQueueClient, resolve_queue_backend


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


def test_resolve_queue_backend_prefers_explicit_value() -> None:
    settings = SimpleNamespace(
        queue_backend="redis",
        app_env="local",
        queue_url=None,
        redis_url="redis://localhost:6379/0",
    )

    assert resolve_queue_backend(settings) == "redis"


def test_resolve_queue_backend_auto_uses_redis_on_non_local_with_remote_redis() -> None:
    settings = SimpleNamespace(
        queue_backend="auto",
        app_env="production",
        queue_url="redis://red-customer-host:6379/0",
        redis_url="redis://localhost:6379/0",
    )

    assert resolve_queue_backend(settings) == "redis"


def test_resolve_queue_backend_auto_falls_back_to_memory_without_remote_redis() -> None:
    settings = SimpleNamespace(
        queue_backend="auto",
        app_env="production",
        queue_url=None,
        redis_url="redis://localhost:6379/0",
    )

    assert resolve_queue_backend(settings) == "memory"
