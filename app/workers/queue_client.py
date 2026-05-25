"""Queue client interfaces and in-memory backend for demo/test usage."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueueEnvelope:
    """Serialized message envelope pushed to queue backends."""

    id: str
    payload: dict[str, Any]
    attempts: int
    enqueued_at: str


@dataclass(slots=True)
class DequeuedMessage:
    """Message returned by dequeue with backend metadata for ack/DLQ."""

    envelope: QueueEnvelope
    raw: str
    queue_name: str


class QueueClient(ABC):
    """Abstract queue client interface for enqueue/consume flows."""

    @abstractmethod
    async def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        """Persist a message to the queue and return its message id."""

    @abstractmethod
    async def dequeue(self, queue_name: str, timeout_seconds: int = 1) -> DequeuedMessage | None:
        """Consume one message from queue into a processing slot."""

    @abstractmethod
    async def ack(self, message: DequeuedMessage) -> None:
        """Acknowledge successful processing for a dequeued message."""

    @abstractmethod
    async def dead_letter(self, message: DequeuedMessage, reason: str) -> None:
        """Move a processing message to dead-letter storage with context."""

    @abstractmethod
    async def close(self) -> None:
        """Release backend resources."""


class InMemoryQueueClient(QueueClient):
    """Queue implementation for local development and tests."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[str]] = {}
        self._processing: dict[str, dict[str, str]] = {}
        self._dead_letters: dict[str, list[str]] = {}

    def _queue(self, queue_name: str) -> asyncio.Queue[str]:
        return self._queues.setdefault(queue_name, asyncio.Queue())

    def _processing_map(self, queue_name: str) -> dict[str, str]:
        return self._processing.setdefault(queue_name, {})

    async def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        envelope = QueueEnvelope(
            id=str(uuid4()),
            payload=payload,
            attempts=0,
            enqueued_at=datetime.now(UTC).isoformat(),
        )
        raw = _serialize_envelope(envelope)
        await self._queue(queue_name).put(raw)
        logger.debug("InMemoryQueue: enqueued message id=%s queue=%s", envelope.id, queue_name)
        # Also print so stdout log stream captures enqueue events on platforms like Render
        print(f"[QUEUE DEBUG] InMemoryQueue: enqueued message id={envelope.id} queue={queue_name}", flush=True)
        return envelope.id

    async def dequeue(self, queue_name: str, timeout_seconds: int = 1) -> DequeuedMessage | None:
        queue = self._queue(queue_name)

        try:
            raw = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None

        envelope = _deserialize_envelope(raw)
        self._processing_map(queue_name)[envelope.id] = raw
        print(f"[QUEUE DEBUG] InMemoryQueue: dequeued message id={envelope.id} queue={queue_name}", flush=True)
        return DequeuedMessage(envelope=envelope, raw=raw, queue_name=queue_name)

    async def ack(self, message: DequeuedMessage) -> None:
        self._processing_map(message.queue_name).pop(message.envelope.id, None)

    async def dead_letter(self, message: DequeuedMessage, reason: str) -> None:
        self._processing_map(message.queue_name).pop(message.envelope.id, None)
        failed_payload = {
            "id": message.envelope.id,
            "payload": message.envelope.payload,
            "attempts": message.envelope.attempts + 1,
            "reason": reason,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        self._dead_letters.setdefault(message.queue_name, []).append(
            json.dumps(failed_payload),
        )

    async def close(self) -> None:
        self._queues.clear()
        self._processing.clear()
        self._dead_letters.clear()


def _serialize_envelope(envelope: QueueEnvelope) -> str:
    return json.dumps(
        {
            "id": envelope.id,
            "payload": envelope.payload,
            "attempts": envelope.attempts,
            "enqueued_at": envelope.enqueued_at,
        },
        separators=(",", ":"),
    )


def _deserialize_envelope(raw: str) -> QueueEnvelope:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid queue payload JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("Queue payload must be a JSON object")

    return QueueEnvelope(
        id=str(data.get("id") or ""),
        payload=dict(data.get("payload") or {}),
        attempts=int(data.get("attempts") or 0),
        enqueued_at=str(data.get("enqueued_at") or ""),
    )


_queue_client: QueueClient | None = None


def get_queue_client() -> QueueClient:
    """Return singleton in-memory queue client."""

    global _queue_client

    if _queue_client is not None:
        return _queue_client

    settings = get_settings()
    if settings.queue_backend.lower().strip() != "memory":
        logger.warning(
            "QUEUE_BACKEND=%s is unsupported in this demo build; falling back to in-memory queue",
            settings.queue_backend,
        )
    else:
        logger.info("Using in-memory queue backend")
    # Mirror to stdout for Render visibility
    print(f"[QUEUE DEBUG] Selected queue backend: {settings.queue_backend}", flush=True)

    _queue_client = InMemoryQueueClient()
    return _queue_client



async def close_queue_client() -> None:
    """Close and reset singleton queue client."""

    global _queue_client

    if _queue_client is not None:
        await _queue_client.close()
        _queue_client = None

