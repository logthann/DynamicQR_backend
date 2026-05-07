#!/usr/bin/env python
"""Verify the database schema after migration using direct SQL."""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.config import Settings


def verify_schema():
    """Verify all migration changes using synchronous SQLAlchemy."""
    settings = Settings()

    # Convert async URL to sync URL (asyncmy -> pymysql)
    db_url = settings.database_url
    if "+asyncmy://" in db_url:
        db_url = db_url.replace("+asyncmy://", "+pymysql://")

    # Use synchronous engine
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.begin() as conn:
        # Check scan_logs table structure
        print("=" * 60)
        print("VERIFICATION RESULTS")
        print("=" * 60)

        # 1. Check ga4_metadata is removed from scan_logs
        result = conn.execute(
            text("""
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'scan_logs' AND COLUMN_NAME = 'ga4_metadata'
            """)
        )
        ga4_in_scan_logs = result.fetchone() is not None
        print(f"\n✗ ga4_metadata in scan_logs: {ga4_in_scan_logs}")
        if not ga4_in_scan_logs:
            print("✓ Task 1.1 PASSED: ga4_metadata column removed from scan_logs")

        # 2. Check scan_ga4_details table exists
        result = conn.execute(
            text("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scan_ga4_details'
            """)
        )
        table_exists = result.fetchone() is not None
        print(f"\n✓ scan_ga4_details table exists: {table_exists}")
        if table_exists:
            print("✓ Task 1.2 PASSED: scan_ga4_details table created")

        # 3. Verify columns in scan_ga4_details
        if table_exists:
            result = conn.execute(
                text("""
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = 'scan_ga4_details'
                    ORDER BY ORDINAL_POSITION
                """)
            )
            print("\nscan_ga4_details columns:")
            for col in result.fetchall():
                print(f"  - {col[0]}: {col[1]} (nullable: {col[2]})")

        # 4. Check foreign key relationship
        result = conn.execute(
            text("""
                SELECT CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, 
                       REFERENCED_COLUMN_NAME, UPDATE_RULE, DELETE_RULE
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
                JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS r
                  ON k.CONSTRAINT_NAME = r.CONSTRAINT_NAME 
                 AND k.TABLE_SCHEMA = r.CONSTRAINT_SCHEMA
                WHERE k.TABLE_SCHEMA = DATABASE()
                  AND k.TABLE_NAME = 'scan_ga4_details'
                  AND k.REFERENCED_TABLE_NAME IS NOT NULL
            """)
        )
        fk_data = result.fetchall()
        if fk_data:
            print("\nForeign Key Constraints:")
            for fk in fk_data:
                constraint, column, ref_table, ref_column, update_rule, delete_rule = fk
                print(f"  - {constraint}: {column} -> {ref_table}({ref_column})")
                print(f"    ON DELETE: {delete_rule}")
                if delete_rule == "CASCADE":
                    print("    ✓ Task 1.3 PASSED: Foreign key has ON DELETE CASCADE")

        # 5. Check UNIQUE constraint on scan_id
        result = conn.execute(
            text("""
                SELECT CONSTRAINT_NAME, COLUMN_NAME, CONSTRAINT_TYPE
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'scan_ga4_details'
                  AND COLUMN_NAME = 'scan_id'
            """)
        )
        unique_data = result.fetchall()
        print("\nUnique Constraints on scan_id:")
        for constraint in unique_data:
            print(f"  - {constraint[0]}: {constraint[1]} ({constraint[2]})")
            if constraint[2] == 'UNIQUE':
                print("  ✓ UNIQUE constraint on scan_id confirmed (one-to-one relationship)")

        # Summary
        print("\n" + "=" * 60)
        print("CHECKLIST SUMMARY")
        print("=" * 60)
        print(f"[{'✓' if not ga4_in_scan_logs else '✗'}] 1.1. Remove redundant JSON columns")
        print(f"[{'✓' if table_exists else '✗'}] 1.2. Create a Detail table")
        print(f"[{'✓' if fk_data and any(fk[5] == 'CASCADE' for fk in fk_data) else '✗'}] 1.3. Check foreign keys")

        # Final result
        all_passed = (
            not ga4_in_scan_logs and
            table_exists and
            fk_data and
            any(fk[5] == 'CASCADE' for fk in fk_data)
        )

        print("\n" + "=" * 60)
        if all_passed:
            print("✅ ALL TASKS COMPLETED SUCCESSFULLY!")
            print("=" * 60)
            return 0
        else:
            print("❌ SOME TASKS FAILED - CHECK DETAILS ABOVE")
            print("=" * 60)
            return 1


if __name__ == "__main__":
    try:
        sys.exit(verify_schema())
    except Exception as e:
        print(f"Error verifying schema: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

