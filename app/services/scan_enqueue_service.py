"""Service helpers for durable scan-log enqueue operations."""

from __future__ import annotations

from app.core.config import get_settings
from app.schemas.redirect import RedirectScanMetadata, ScanLogEnqueueMessage
from app.workers.queue_client import QueueClient, get_queue_client
import logging

logger = logging.getLogger(__name__)


async def enqueue_scan_log(
    qr_id: int,
    scan_metadata: RedirectScanMetadata,
    *,
    queue_client: QueueClient | None = None,
    queue_name: str | None = None,
) -> str:
    """Enqueue one scan log message to the durable queue backend."""

    client = queue_client or get_queue_client()
    destination_queue = queue_name or get_settings().scan_log_queue_name

    payload = ScanLogEnqueueMessage(
        qr_id=qr_id,
        scan=scan_metadata,
    ).model_dump(mode="json")

    try:
        message_id = await client.enqueue(destination_queue, payload)
        logger.info(
            "Enqueued scan-log message id=%s to queue=%s qr_id=%s",
            message_id,
            destination_queue,
            payload.get("qr_id"),
        )
        return message_id
    except Exception as exc:  # pragma: no cover - tested via stub raising RuntimeError
        logger.exception("Failed to enqueue scan log to %s", destination_queue)
        raise RuntimeError("Failed to enqueue scan log message") from exc

