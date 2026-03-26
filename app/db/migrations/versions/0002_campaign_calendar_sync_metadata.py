"""Add calendar synchronization metadata columns to campaigns.

Revision ID: 0002_campaign_sync_meta
Revises: 0001_initial_schema
Create Date: 2026-03-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_campaign_sync_meta"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend campaigns with calendar linkage and reconciliation metadata."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("campaigns")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("campaigns")}

    if "google_event_id" not in existing_columns:
        op.add_column("campaigns", sa.Column("google_event_id", sa.String(length=255), nullable=True))
    if "calendar_sync_status" not in existing_columns:
        op.add_column(
            "campaigns",
            sa.Column(
                "calendar_sync_status",
                sa.String(length=32),
                nullable=False,
                server_default="not_linked",
            ),
        )
    if "calendar_last_synced_at" not in existing_columns:
        op.add_column(
            "campaigns",
            sa.Column("calendar_last_synced_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "calendar_sync_hash" not in existing_columns:
        op.add_column("campaigns", sa.Column("calendar_sync_hash", sa.String(length=128), nullable=True))

    if "ix_campaigns_user_id_google_event_id" not in existing_indexes:
        op.create_index(
            "ix_campaigns_user_id_google_event_id",
            "campaigns",
            ["user_id", "google_event_id"],
        )


def downgrade() -> None:
    """Remove calendar synchronization metadata from campaigns."""

    op.drop_index("ix_campaigns_user_id_google_event_id", table_name="campaigns")
    op.drop_column("campaigns", "calendar_sync_hash")
    op.drop_column("campaigns", "calendar_last_synced_at")
    op.drop_column("campaigns", "calendar_sync_status")
    op.drop_column("campaigns", "google_event_id")

