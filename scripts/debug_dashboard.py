"""Debug dashboard query issues."""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import get_db_session
from sqlalchemy import text


async def debug_query() -> None:
    """Test the dashboard query to see why scans are missing."""

    async for session in get_db_session():
        # Simulate dashboard query parameters
        start_date = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date() - timedelta(days=30)
        end_date = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date() + timedelta(days=1)

        start_utc = datetime.combine(
            start_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")
        ).astimezone(UTC)
        end_utc = datetime.combine(
            end_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")
        ).astimezone(UTC)

        print(f"Query range (UTC): {start_utc} to {end_utc}")

        # Check scan timestamps
        result = await session.execute(
            text(
                """
            SELECT COUNT(*) FROM scan_logs 
            WHERE qr_configurations_id IN (19, 43)
        """
            )
        )
        total_scans = result.scalar()
        print(f"\nTotal scans in scan_logs for configs 19, 43: {total_scans}")

        # Check if qr_configurations are valid
        result = await session.execute(
            text(
                """
            SELECT id, qr_id, is_current FROM qr_configurations 
            WHERE id IN (19, 43)
        """
            )
        )
        print("\nQR Configurations:")
        for row in result.fetchall():
            print(f"  Config {row[0]}: qr_id={row[1]}, is_current={row[2]}")

        # Check qr_codes validity
        result = await session.execute(
            text(
                """
            SELECT id, campaign_id, user_id, deleted_at FROM qr_codes 
            WHERE id IN (23, 30)
        """
            )
        )
        print("\nQR Codes:")
        for row in result.fetchall():
            print(f"  QR {row[0]}: campaign_id={row[1]}, user_id={row[2]}, deleted_at={row[3]}")

        # Check users
        result = await session.execute(
            text(
                """
            SELECT id, email, deleted_at FROM users 
            WHERE id IN (1, 5, 24)
        """
            )
        )
        print("\nUsers:")
        for row in result.fetchall():
            print(f"  User {row[0]}: email={row[1]}, deleted_at={row[2]}")

        # Run simplified join test
        result = await session.execute(
            text(
                """
            SELECT COUNT(sl.id)
            FROM scan_logs sl
            JOIN qr_configurations qc
              ON qc.id = sl.qr_configurations_id
            WHERE qc.id IN (19, 43)
        """
            )
        )
        print(f"\nScans after JOIN with qr_configurations: {result.scalar()}")

        # Add qr_codes join
        result = await session.execute(
            text(
                """
            SELECT COUNT(sl.id)
            FROM scan_logs sl
            JOIN qr_configurations qc
              ON qc.id = sl.qr_configurations_id
            JOIN qr_codes q
              ON q.id = qc.qr_id AND q.deleted_at IS NULL
            WHERE qc.id IN (19, 43)
        """
            )
        )
        print(f"Scans after JOIN with qr_codes (with deleted_at check): {result.scalar()}")

        # Add users join
        result = await session.execute(
            text(
                """
            SELECT COUNT(sl.id)
            FROM scan_logs sl
            JOIN qr_configurations qc
              ON qc.id = sl.qr_configurations_id
            JOIN qr_codes q
              ON q.id = qc.qr_id AND q.deleted_at IS NULL
            JOIN users owner
              ON owner.id = q.user_id AND owner.deleted_at IS NULL
            WHERE qc.id IN (19, 43)
        """
            )
        )
        print(f"Scans after JOIN with users: {result.scalar()}")

        # Full query with timing
        result = await session.execute(
            text(
                """
            SELECT COUNT(sl.id)
            FROM scan_logs sl
            JOIN qr_configurations qc
              ON qc.id = sl.qr_configurations_id
            JOIN qr_codes q
              ON q.id = qc.qr_id AND q.deleted_at IS NULL
            JOIN users owner
              ON owner.id = q.user_id AND owner.deleted_at IS NULL
            LEFT JOIN campaigns c
              ON c.id = q.campaign_id AND c.deleted_at IS NULL
            WHERE sl.scanned_at >= :start_utc
              AND sl.scanned_at < :end_utc
              AND qc.id IN (19, 43)
        """
            ),
            {"start_utc": start_utc, "end_utc": end_utc},
        )
        print(f"Scans after adding time range filter: {result.scalar()}")


if __name__ == "__main__":
    asyncio.run(debug_query())

