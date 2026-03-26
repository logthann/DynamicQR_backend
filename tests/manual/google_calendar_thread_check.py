"""Manual threaded smoke test for Google Calendar event sync.

Run this script directly (not via pytest) after OAuth integration is connected.
It executes the sync flow in a dedicated thread to mimic a worker-style call path.
"""

from __future__ import annotations

# Support direct execution: `python tests/manual/google_calendar_thread_check.py`
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
from queue import Queue
import threading

from sqlalchemy import bindparam, text

from app.db.session import get_session_factory
from app.repositories.user_integrations import UserIntegrationRepository
from app.services.google_calendar_service import GoogleCalendarService, GoogleCalendarServiceError


@dataclass(slots=True)
class SyncInput:
    user_id: int
    qr_id: int
    event_title: str
    start_datetime: datetime
    end_datetime: datetime
    location: str | None
    description: str | None


async def _run_sync(payload: SyncInput) -> str:
    session_factory = get_session_factory()

    async with session_factory() as session:
        required_tables = ("qr_codes", "user_integrations", "qr_event_details")
        table_check = await session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name IN :table_names
                """
            ).bindparams(bindparam("table_names", expanding=True)),
            {"table_names": required_tables},
        )
        existing_tables = {row[0] for row in table_check.fetchall()}
        missing_tables = [table for table in required_tables if table not in existing_tables]
        if missing_tables:
            missing = ", ".join(missing_tables)
            raise RuntimeError(
                f"Missing required table(s): {missing}. Run `alembic upgrade head` first."
            )

        # Fail early with a clear message if the QR id does not exist.
        qr_result = await session.execute(
            text("SELECT id, qr_type FROM qr_codes WHERE id = :qr_id LIMIT 1"),
            {"qr_id": payload.qr_id},
        )
        qr_row = qr_result.mappings().first()
        if qr_row is None:
            raise RuntimeError(f"QR id {payload.qr_id} was not found in qr_codes")

        service = GoogleCalendarService(
            session,
            UserIntegrationRepository(session),
        )

        google_event_id = await service.sync_event_for_qr(
            user_id=payload.user_id,
            qr_id=payload.qr_id,
            event_title=payload.event_title,
            start_datetime=payload.start_datetime,
            end_datetime=payload.end_datetime,
            location=payload.location,
            description=payload.description,
        )

        await session.commit()
        return google_event_id


def _thread_target(payload: SyncInput, output: Queue[tuple[bool, str]]) -> None:
    try:
        event_id = asyncio.run(_run_sync(payload))
        output.put((True, event_id))
    except Exception as exc:  # pragma: no cover - manual helper
        output.put((False, f"{type(exc).__name__}: {exc}"))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Google Calendar sync for one QR inside a dedicated thread.",
    )
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--qr-id", type=int, required=True)
    parser.add_argument("--event-title", type=str, required=True)
    parser.add_argument("--start", type=str, required=True, help="ISO 8601 datetime")
    parser.add_argument("--end", type=str, required=True, help="ISO 8601 datetime")
    parser.add_argument("--location", type=str, default=None)
    parser.add_argument("--description", type=str, default=None)
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()

    try:
        start_dt = datetime.fromisoformat(args.start)
        end_dt = datetime.fromisoformat(args.end)
    except ValueError as exc:
        print(f"[FAIL] Invalid datetime format: {exc}")
        return 2

    payload = SyncInput(
        user_id=args.user_id,
        qr_id=args.qr_id,
        event_title=args.event_title,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=args.location,
        description=args.description,
    )

    output: Queue[tuple[bool, str]] = Queue()
    worker = threading.Thread(target=_thread_target, args=(payload, output), daemon=False)
    worker.start()
    worker.join(timeout=60)

    if worker.is_alive():
        print("[FAIL] Worker thread timed out after 60 seconds")
        return 3

    success, message = output.get_nowait()
    if success:
        print(f"[PASS] Google Calendar event synced successfully. event_id={message}")
        return 0

    if "GoogleCalendarServiceError" in message:
        print(f"[FAIL] Service error: {message}")
        return 4

    print(f"[FAIL] Unexpected error: {message}")
    return 5


if __name__ == "__main__":
    raise SystemExit(main())

