"""Add GA tracking mode/property columns for campaigns and QR codes.

Revision ID: 0004_ga_tracking_columns
Revises: 0003_campaign_ga_measurement_id
Create Date: 2026-04-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_ga_tracking_columns"
down_revision = "0003_campaign_ga_measurement_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add GA mode/property columns to campaigns and qr_codes."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    campaign_columns = {column["name"] for column in inspector.get_columns("campaigns")}
    qr_columns = {column["name"] for column in inspector.get_columns("qr_codes")}

    if "ga_measurement_id" not in campaign_columns:
        op.add_column("campaigns", sa.Column("ga_measurement_id", sa.String(length=100), nullable=True))
    if "ga_type" not in campaign_columns:
        op.add_column("campaigns", sa.Column("ga_type", sa.String(length=16), nullable=True))
    if "ga_property_id" not in campaign_columns:
        op.add_column("campaigns", sa.Column("ga_property_id", sa.String(length=100), nullable=True))

    if "ga_type" not in qr_columns:
        op.add_column("qr_codes", sa.Column("ga_type", sa.String(length=16), nullable=True))
    if "ga_property_id" not in qr_columns:
        op.add_column("qr_codes", sa.Column("ga_property_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Remove GA mode/property columns from campaigns and qr_codes."""

    op.drop_column("qr_codes", "ga_property_id")
    op.drop_column("qr_codes", "ga_type")
    op.drop_column("campaigns", "ga_property_id")
    op.drop_column("campaigns", "ga_type")

