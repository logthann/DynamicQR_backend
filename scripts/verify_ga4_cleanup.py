"""Verify GA4 cleanup migration results."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings


def main() -> int:
    settings = get_settings()
    db_url = settings.database_url.replace("+asyncmy", "+mysqlconnector")
    engine = create_engine(db_url)

    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        scan_logs_columns = {col["name"] for col in inspector.get_columns("scan_logs")}

        print("Current tables include scan_ga4_details:", "scan_ga4_details" in tables)
        print("ga4_metadata in scan_logs:", "ga4_metadata" in scan_logs_columns)
        print("scan_logs columns:", sorted(scan_logs_columns))

        ok = True
        if "scan_ga4_details" in tables:
            ok = False
        if "ga4_metadata" in scan_logs_columns:
            ok = False

        return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())