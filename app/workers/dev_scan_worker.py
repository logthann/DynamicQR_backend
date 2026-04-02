"""Local development runner for continuous scan-log queue consumption."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.workers.scan_log_worker import process_next_scan_log_message

logger = logging.getLogger(__name__)


async def run_scan_log_worker(
    *,
    poll_interval_seconds: float = 0.25,
    process_once: Callable[[], Awaitable[bool]] = process_next_scan_log_message,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuously consume queued scan-log messages until stopped."""

    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must be >= 0")

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Scan worker stop signal received")
            return

        handled = await process_once()
        if not handled:
            await asyncio.sleep(poll_interval_seconds)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local scan-log queue worker")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.25,
        help="Seconds to sleep when queue is empty (default: 0.25)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


async def _run_cli() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logger.info("Starting scan-log worker loop")
    await run_scan_log_worker(poll_interval_seconds=float(args.poll_interval))


def main() -> None:
    """CLI entry point for local worker execution."""

    try:
        asyncio.run(_run_cli())
    except KeyboardInterrupt:
        logger.info("Scan-log worker interrupted by user")


if __name__ == "__main__":
    main()

