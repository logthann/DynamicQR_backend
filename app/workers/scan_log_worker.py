"""Worker utilities to consume queued scan logs and persist them to MySQL."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.schemas.redirect import ScanLogEnqueueMessage
from app.workers.queue_client import QueueClient, get_queue_client

logger = logging.getLogger(__name__)

RETRY_ATTEMPT_KEY = "__retry_attempt"
DEFAULT_MAX_RETRY_ATTEMPTS = 3


async def process_next_scan_log_message(
    *,
    queue_client: QueueClient | None = None,
    session_factory: async_sessionmaker[AsyncSession] | Callable[[], Any] | None = None,
    queue_name: str | None = None,
    timeout_seconds: int | None = None,
    max_retry_attempts: int | None = None,
) -> bool:
    """Consume one scan-log message, persist it, then ack or dead-letter."""

    client = queue_client or get_queue_client()
    factory = session_factory or get_session_factory()
    settings = get_settings()
    source_queue = queue_name or settings.scan_log_queue_name
    resolved_timeout = timeout_seconds if timeout_seconds is not None else settings.queue_visibility_timeout_seconds
    resolved_max_retries = (
        max_retry_attempts if max_retry_attempts is not None else settings.queue_max_retry_attempts
    )

    message = await client.dequeue(source_queue, timeout_seconds=resolved_timeout)
    if message is None:
        return False

    try:
        payload = ScanLogEnqueueMessage.model_validate(message.envelope.payload)
    except ValidationError as exc:
        await client.dead_letter(message, reason=f"invalid_payload:{exc.__class__.__name__}")
        return True

    try:
        async with factory() as session:
            await _insert_scan_log(session, payload)
            await session.commit()
    except Exception as exc:
        logger.exception("Failed to persist scan log message '%s'", message.envelope.id)
        current_attempt = _get_retry_attempt(message.envelope.payload)
        if current_attempt < resolved_max_retries:
            await client.enqueue(
                source_queue,
                _with_retry_attempt(message.envelope.payload, current_attempt + 1),
            )
            await client.ack(message)
            return True

        await client.dead_letter(
            message,
            reason=f"db_write_failed:{exc.__class__.__name__}:retry_exhausted",
        )
        return True

    await client.ack(message)
    return True


def _get_retry_attempt(payload: dict[str, Any]) -> int:
    """Return retry attempt counter embedded in queue payload metadata."""

    raw_value = payload.get(RETRY_ATTEMPT_KEY, 0)
    try:
        return max(int(raw_value), 0)
    except (TypeError, ValueError):
        return 0


def _with_retry_attempt(payload: dict[str, Any], attempt: int) -> dict[str, Any]:
    """Return payload copy with updated retry attempt marker."""

    updated = dict(payload)
    updated[RETRY_ATTEMPT_KEY] = attempt
    return updated


async def _insert_scan_log(session: AsyncSession, payload: ScanLogEnqueueMessage) -> None:
    """Insert one row into scan_logs from a validated queue payload."""

    statement = text(
        """
        INSERT INTO scan_logs (
            qr_id,
            scanned_at,
            ip_address,
            user_agent,
            device_type,
            os,
            browser,
            country,
            city,
            referer
        ) VALUES (
            :qr_id,
            :scanned_at,
            :ip_address,
            :user_agent,
            :device_type,
            :os,
            :browser,
            :country,
            :city,
            :referer
        )
        """
    )

    scan = payload.scan
    await session.execute(
        statement,
        {
            "qr_id": payload.qr_id,
            "scanned_at": scan.scanned_at,
            "ip_address": scan.ip_address,
            "user_agent": scan.user_agent,
            "device_type": scan.device_type,
            "os": scan.os,
            "browser": scan.browser,
            "country": scan.country,
            "city": scan.city,
            "referer": scan.referer,
        },
    )

