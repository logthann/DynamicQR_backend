"""Analytics aggregation jobs for incremental and daily summary upserts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import get_session_factory


async def aggregate_scan_logs_into_daily_summary(
    session: AsyncSession,
    *,
    start_time: datetime,
    end_time: datetime,
) -> int:
    """Aggregate scan logs in a time window into daily summary rows via UPSERT."""

    statement = text(
        """
        INSERT INTO daily_analytics_summary (
            qr_id,
            summary_date,
            total_scans,
            unique_visitors
        )
        SELECT
            sl.qr_id,
            DATE(sl.scanned_at) AS summary_date,
            COUNT(*) AS total_scans,
            COUNT(DISTINCT COALESCE(sl.ip_address, CONCAT('unknown-', sl.id))) AS unique_visitors
        FROM scan_logs sl
        WHERE sl.scanned_at >= :start_time
          AND sl.scanned_at < :end_time
        GROUP BY sl.qr_id, DATE(sl.scanned_at)
        ON DUPLICATE KEY UPDATE
            total_scans = VALUES(total_scans),
            unique_visitors = VALUES(unique_visitors)
        """
    )

    result = await session.execute(
        statement,
        {
            "start_time": start_time,
            "end_time": end_time,
        },
    )
    return int(result.rowcount or 0)


async def run_incremental_aggregation(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    now: datetime | None = None,
    window_minutes: int = 5,
) -> int:
    """Run near-real-time aggregation for the latest rolling time window."""

    reference_time = now or datetime.now(UTC)
    end_time = reference_time
    start_time = reference_time - timedelta(minutes=window_minutes)
    factory = session_factory or get_session_factory()

    async with factory() as session:
        upserted = await aggregate_scan_logs_into_daily_summary(
            session,
            start_time=start_time,
            end_time=end_time,
        )
        await session.commit()
    return upserted


async def run_daily_reconciliation(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    target_date: date | None = None,
) -> int:
    """Recompute one UTC day to reconcile late-arriving scan logs."""

    day = target_date or datetime.now(UTC).date()
    start_time = datetime.combine(day, time.min).replace(tzinfo=UTC)
    end_time = start_time + timedelta(days=1)
    factory = session_factory or get_session_factory()

    async with factory() as session:
        upserted = await aggregate_scan_logs_into_daily_summary(
            session,
            start_time=start_time,
            end_time=end_time,
        )
        await session.commit()
    return upserted

