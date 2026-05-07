"""Update scan_logs and qr_configurations tables.

- Add qr_config_id to scan_logs (FK to qr_configurations)
- Move design_config, ga_type, ga_property_id from qr_codes to qr_configurations
- Add ga4_metadata JSON column to scan_logs

Revision ID: 0010_scan_logs_and_qr_config_updates
Revises: 0009_drop_moved_qr_columns
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0010_scan_logs_and_qr_config_updates"
down_revision = "0009_drop_moved_qr_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply schema changes."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Add columns to qr_configurations (moved from qr_codes)
    qr_config_columns = {column["name"] for column in inspector.get_columns("qr_configurations")}

    if "design_config" not in qr_config_columns:
        op.add_column(
            "qr_configurations",
            sa.Column("design_config", sa.JSON(), nullable=True),
        )
    if "ga_type" not in qr_config_columns:
        op.add_column(
            "qr_configurations",
            sa.Column("ga_type", sa.String(length=16), nullable=True),
        )
    if "ga_property_id" not in qr_config_columns:
        op.add_column(
            "qr_configurations",
            sa.Column("ga_property_id", sa.String(length=100), nullable=True),
        )

    # Note: Data migration for design_config, ga_type, ga_property_id was skipped
    # because these columns were already dropped in migration 0009.
    # The columns are added to qr_configurations as new nullable columns.

    # 3. Drop columns from qr_codes
    qr_columns = {column["name"] for column in inspector.get_columns("qr_codes")}

    if "design_config" in qr_columns:
        op.drop_column("qr_codes", "design_config")
    if "ga_type" in qr_columns:
        op.drop_column("qr_codes", "ga_type")
    if "ga_property_id" in qr_columns:
        op.drop_column("qr_codes", "ga_property_id")

    # 4. Add columns to scan_logs
    scan_logs_columns = {column["name"] for column in inspector.get_columns("scan_logs")}

    if "qr_config_id" not in scan_logs_columns:
        op.add_column(
            "scan_logs",
            sa.Column("qr_config_id", sa.BigInteger(), nullable=True),
        )
        # Add foreign key constraint
        op.create_foreign_key(
            "fk_scan_logs_qr_config_id",
            "scan_logs",
            "qr_configurations",
            ["qr_config_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if "ga4_metadata" not in scan_logs_columns:
        op.add_column(
            "scan_logs",
            sa.Column("ga4_metadata", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Revert schema changes."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Remove scan_logs columns
    scan_logs_columns = {column["name"] for column in inspector.get_columns("scan_logs")}

    if "ga4_metadata" in scan_logs_columns:
        op.drop_column("scan_logs", "ga4_metadata")

    if "qr_config_id" in scan_logs_columns:
        # Drop foreign key first
        op.drop_constraint("fk_scan_logs_qr_config_id", "scan_logs", type_="foreignkey")
        op.drop_column("scan_logs", "qr_config_id")

    # 2. Add back columns to qr_codes
    qr_columns = {column["name"] for column in inspector.get_columns("qr_codes")}

    if "ga_property_id" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("ga_property_id", sa.String(length=100), nullable=True),
        )
    if "ga_type" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("ga_type", sa.String(length=16), nullable=True),
        )
    if "design_config" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("design_config", sa.JSON(), nullable=True),
        )

    # 3. Remove columns from qr_configurations
    qr_config_columns = {column["name"] for column in inspector.get_columns("qr_configurations")}

    if "ga_property_id" in qr_config_columns:
        op.drop_column("qr_configurations", "ga_property_id")
    if "ga_type" in qr_config_columns:
        op.drop_column("qr_configurations", "ga_type")
    if "design_config" in qr_config_columns:
        op.drop_column("qr_configurations", "design_config")
