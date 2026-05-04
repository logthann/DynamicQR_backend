"""Add campaign-level GA measurement id column.

Revision ID: 0003_campaign_ga_measurement_id
Revises: 0002_campaign_sync_meta
Create Date: 2026-04-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_campaign_ga_measurement_id"
down_revision = "0002_campaign_sync_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add campaign-level default GA measurement id storage."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("campaigns")}

    if "ga_measurement_id" not in existing_columns:
        op.add_column(
            "campaigns",
            sa.Column("ga_measurement_id", sa.String(length=100), nullable=True),
        )


def downgrade() -> None:
    """Remove campaign-level GA measurement id column."""

    op.drop_column("campaigns", "ga_measurement_id")

