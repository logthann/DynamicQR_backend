"""Clean up GA4-related schema elements.

- Drop scan_ga4_details auxiliary table
- Ensure ga4_metadata column is removed from scan_logs
- Keep only essential scan_logs columns: id, qr_config_id, scanned_at, device info

Revision ID: 0012_cleanup_ga4_schema
Revises: 0011_scan_ga4_details_table
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012_cleanup_ga4_schema"
down_revision = "0011_scan_ga4_details_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Clean up GA4-related schema elements.
    
    1. Drop scan_ga4_details table
    2. Verify and ensure ga4_metadata is removed from scan_logs
    """

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Drop scan_ga4_details table if it exists
    tables = set(inspector.get_table_names())
    if "scan_ga4_details" in tables:
        # Drop the table
        op.drop_table("scan_ga4_details")

    # 2. Ensure ga4_metadata column is removed from scan_logs
    scan_logs_columns = {column["name"] for column in inspector.get_columns("scan_logs")}
    
    if "ga4_metadata" in scan_logs_columns:
        op.drop_column("scan_logs", "ga4_metadata")


def downgrade() -> None:
    """Revert schema changes.
    
    1. Recreate scan_ga4_details table
    2. Add ga4_metadata column back to scan_logs (optional)
    """

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Recreate scan_ga4_details table
    tables = set(inspector.get_table_names())
    if "scan_ga4_details" not in tables:
        op.create_table(
            "scan_ga4_details",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("scan_id", sa.BigInteger(), nullable=False),
            sa.Column("ga4_metadata", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["scan_id"],
                ["scan_logs.id"],
                name="fk_scan_ga4_details_scan_id",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("scan_id", name="uq_scan_ga4_details_scan_id"),
        )

    # 2. Add ga4_metadata column back to scan_logs (optional for downgrade)
    scan_logs_columns = {column["name"] for column in inspector.get_columns("scan_logs")}
    
    if "ga4_metadata" not in scan_logs_columns:
        op.add_column(
            "scan_logs",
            sa.Column("ga4_metadata", sa.JSON(), nullable=True),
        )
