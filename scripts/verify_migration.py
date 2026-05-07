"""Verify database schema changes for scan_ga4_details migration."""

import sys
import os

# Add parent directory to path to import app module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect

from app.core.config import Settings

settings = Settings()
engine = create_engine(settings.database_url)

with engine.connect() as conn:
    inspector = inspect(conn)

    print('=== SCAN_LOGS TABLE COLUMNS ===')
    scan_logs_cols = inspector.get_columns('scan_logs')
    for col in scan_logs_cols:
        print(f'  - {col["name"]}: {col["type"]}')

    print('\n=== SCAN_GA4_DETAILS TABLE ===')
    if 'scan_ga4_details' in inspector.get_table_names():
        print('Table exists: YES ✓')

        print('\nColumns:')
        cols = inspector.get_columns('scan_ga4_details')
        for col in cols:
            print(f'  - {col["name"]}: {col["type"]}')

        print('\nForeign Keys:')
        fks = inspector.get_foreign_keys('scan_ga4_details')
        for fk in fks:
            print(f'  - {fk["name"]}: {fk["constrained_columns"]} -> {fk["referred_table"]}({fk["referred_columns"]})')
            print(f'    ON DELETE: {fk["ondelete"]}')

        print('\nUnique Constraints:')
        for uc in inspector.get_unique_constraints('scan_ga4_details'):
            print(f'  - {uc["name"]}: {uc["column_names"]}')
    else:
        print('Table exists: NO ✗')

    print('\n=== VERIFICATION CHECK ===')
    # Verify ga4_metadata is removed from scan_logs
    has_ga4_metadata = any(col['name'] == 'ga4_metadata' for col in scan_logs_cols)
    print(f'✓ ga4_metadata removed from scan_logs: {not has_ga4_metadata}')

    # Verify scan_ga4_details table exists
    table_exists = 'scan_ga4_details' in inspector.get_table_names()
    print(f'✓ scan_ga4_details table created: {table_exists}')

    # Verify foreign key with CASCADE
    if table_exists:
        fks = inspector.get_foreign_keys('scan_ga4_details')
        has_cascade = any(fk['ondelete'] == 'CASCADE' for fk in fks)
        print(f'✓ Foreign key with ON DELETE CASCADE: {has_cascade}')

        # Verify UNIQUE constraint on scan_id
        unique_constraints = inspector.get_unique_constraints('scan_ga4_details')
        has_unique = any('scan_id' in uc['column_names'] for uc in unique_constraints)
        print(f'✓ UNIQUE constraint on scan_id: {has_unique}')

    print('\n=== SUMMARY ===')
    all_checks = [
        not has_ga4_metadata,
        table_exists,
    ]

    if table_exists:
        fks = inspector.get_foreign_keys('scan_ga4_details')
        all_checks.append(any(fk['ondelete'] == 'CASCADE' for fk in fks))
        all_checks.append(any('scan_id' in uc['column_names'] for uc in unique_constraints))

    if all(all_checks):
        print('✅ All migration tasks completed successfully!')
        sys.exit(0)
    else:
        print('❌ Some migration tasks failed!')
        sys.exit(1)

