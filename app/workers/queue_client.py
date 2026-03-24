"""Durable queue client interfaces and backend implementations."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from redis import asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import RedisError

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
        return envelope.id

    async def dequeue(self, queue_name: str, timeout_seconds: int = 1) -> DequeuedMessage | None:
        queue = self._queue(queue_name)

        try:
            raw = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None

        envelope = _deserialize_envelope(raw)
        self._processing_map(queue_name)[envelope.id] = raw
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


class RedisQueueClient(QueueClient):
    """Redis list-backed queue with processing and dead-letter support."""

    def __init__(self, redis_url: str, dead_letter_queue_name: str) -> None:
        self._redis: Redis = redis.from_url(
            redis_url,
            decode_responses=True,
            encoding="utf-8",
        )
        self._dead_letter_queue_name = dead_letter_queue_name

    @staticmethod
    def _queue_key(queue_name: str) -> str:
        return f"queue:{queue_name}"

    @staticmethod
    def _processing_key(queue_name: str) -> str:
        return f"queue:{queue_name}:processing"

    def _dead_letter_key(self) -> str:
        return self._queue_key(self._dead_letter_queue_name)

    async def enqueue(self, queue_name: str, payload: dict[str, Any]) -> str:
        envelope = QueueEnvelope(
            id=str(uuid4()),
            payload=payload,
            attempts=0,
            enqueued_at=datetime.now(UTC).isoformat(),
        )
        raw = _serialize_envelope(envelope)

        try:
            await self._redis.lpush(self._queue_key(queue_name), raw)
        except RedisError as exc:
            raise RuntimeError(f"Failed to enqueue message into '{queue_name}'") from exc

        return envelope.id

    async def dequeue(self, queue_name: str, timeout_seconds: int = 1) -> DequeuedMessage | None:
        source_key = self._queue_key(queue_name)
        processing_key = self._processing_key(queue_name)

        try:
            raw = await self._redis.brpoplpush(source_key, processing_key, timeout_seconds)
        except RedisError as exc:
            raise RuntimeError(f"Failed to dequeue message from '{queue_name}'") from exc

        if not raw:
            return None

        envelope = _deserialize_envelope(raw)
        return DequeuedMessage(envelope=envelope, raw=raw, queue_name=queue_name)

    async def ack(self, message: DequeuedMessage) -> None:
        try:
            await self._redis.lrem(
                self._processing_key(message.queue_name),
                1,
                message.raw,
            )
        except RedisError as exc:
            raise RuntimeError(
                f"Failed to ack message '{message.envelope.id}'",
            ) from exc

    async def dead_letter(self, message: DequeuedMessage, reason: str) -> None:
        dead_letter_payload = {
            "id": message.envelope.id,
            "payload": message.envelope.payload,
            "attempts": message.envelope.attempts + 1,
            "reason": reason,
            "failed_at": datetime.now(UTC).isoformat(),
        }

        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.lrem(self._processing_key(message.queue_name), 1, message.raw)
            pipe.lpush(self._dead_letter_key(), json.dumps(dead_letter_payload))
            await pipe.execute()
        except RedisError as exc:
            raise RuntimeError(
                f"Failed to dead-letter message '{message.envelope.id}'",
            ) from exc

    async def close(self) -> None:
        await self._redis.aclose()


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
    """Return singleton queue client based on configured backend."""

    global _queue_client

    if _queue_client is not None:
        return _queue_client

    settings = get_settings()
    backend = settings.queue_backend.lower().strip()

    if backend == "memory":
        logger.info("Using in-memory queue backend")
        _queue_client = InMemoryQueueClient()
        return _queue_client

    if backend == "redis":
        redis_url = settings.queue_url or settings.redis_url
        logger.info("Using redis queue backend")
        _queue_client = RedisQueueClient(
            redis_url=redis_url,
            dead_letter_queue_name=settings.dlq_name,
        )
        return _queue_client

    raise ValueError(f"Unsupported queue backend '{settings.queue_backend}'")


async def close_queue_client() -> None:
    """Close and reset singleton queue client."""

    global _queue_client

    if _queue_client is not None:
        await _queue_client.close()
        _queue_client = None

