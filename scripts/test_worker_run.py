import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path so `app` package can be imported when running this script
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.workers.dev_scan_worker import run_scan_log_worker


def _setup_env() -> None:
    # Ensure we use the memory queue for local testing
    os.environ.setdefault("QUEUE_BACKEND", "memory")
    # Use local env for validation to avoid production-only settings checks
    os.environ.setdefault("APP_ENV", "local")


async def _main() -> None:
    stop_event = asyncio.Event()

    async def _stop_after_delay() -> None:
        await asyncio.sleep(2)
        stop_event.set()

    asyncio.create_task(_stop_after_delay())
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger().info("Starting test worker run (2s)")
    await run_scan_log_worker(poll_interval_seconds=0.1, stop_event=stop_event)
    logging.getLogger().info("Test worker run complete")


if __name__ == "__main__":
    _setup_env()
    asyncio.run(_main())

