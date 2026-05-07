"""Drop columns from qr_codes that were moved to qr_configurations.

Revision ID: 0009_drop_moved_qr_columns
Revises: 0008_populate_qr_configurations
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0009_drop_moved_qr_columns"
down_revision = "0008_populate_qr_configurations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop columns moved to qr_configurations table."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    qr_columns = {column["name"] for column in inspector.get_columns("qr_codes")}

    # Drop columns that were moved to qr_configurations
    if "utm_campaign" in qr_columns:
        op.drop_column("qr_codes", "utm_campaign")
    if "utm_medium" in qr_columns:
        op.drop_column("qr_codes", "utm_medium")
    if "utm_source" in qr_columns:
        op.drop_column("qr_codes", "utm_source")
    if "ga_measurement_id" in qr_columns:
        op.drop_column("qr_codes", "ga_measurement_id")
    if "destination_url" in qr_columns:
        op.drop_column("qr_codes", "destination_url")
    if "name" in qr_columns:
        op.drop_column("qr_codes", "name")


def downgrade() -> None:
    """Add back the dropped columns to qr_codes table."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    qr_columns = {column["name"] for column in inspector.get_columns("qr_codes")}

    if "name" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        )
    if "destination_url" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("destination_url", sa.Text(), nullable=False, server_default=""),
        )
    if "ga_measurement_id" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("ga_measurement_id", sa.String(length=100), nullable=True),
        )
    if "utm_source" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("utm_source", sa.String(length=255), nullable=True),
        )
    if "utm_medium" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("utm_medium", sa.String(length=255), nullable=True),
        )
    if "utm_campaign" not in qr_columns:
        op.add_column(
            "qr_codes",
            sa.Column("utm_campaign", sa.String(length=255), nullable=True),
        )
