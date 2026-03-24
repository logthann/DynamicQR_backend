"""Initial schema for Dynamic QR platform.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply initial schema with all required tables and constraints."""

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("subscription_plan", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('admin', 'agency', 'user')", name="ck_users_role"),
    )

    op.create_table(
        "user_integrations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_integrations_user_id"),
        sa.UniqueConstraint(
            "user_id",
            "provider_name",
            name="uq_user_integrations_user_provider",
        ),
        sa.CheckConstraint(
            "provider_name IN ('google_calendar', 'google_analytics')",
            name="ck_user_integrations_provider_name",
        ),
    )

    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_campaigns_user_id",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "qr_codes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_code", sa.String(length=32), nullable=False),
        sa.Column("destination_url", sa.Text(), nullable=False),
        sa.Column("qr_type", sa.String(length=20), nullable=False),
        sa.Column("design_config", sa.JSON(), nullable=True),
        sa.Column("ga_measurement_id", sa.String(length=100), nullable=True),
        sa.Column("utm_source", sa.String(length=255), nullable=True),
        sa.Column("utm_medium", sa.String(length=255), nullable=True),
        sa.Column("utm_campaign", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_qr_codes_user_id"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_qr_codes_campaign_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("short_code", name="uq_qr_codes_short_code"),
    )

    op.create_table(
        "qr_event_details",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qr_id", sa.BigInteger(), nullable=False),
        sa.Column("event_title", sa.String(length=255), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("google_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["qr_id"], ["qr_codes.id"], name="fk_qr_event_details_qr_id"),
        sa.UniqueConstraint("qr_id", name="uq_qr_event_details_qr_id"),
    )

    op.create_table(
        "scan_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qr_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "scanned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("device_type", sa.String(length=100), nullable=True),
        sa.Column("os", sa.String(length=100), nullable=True),
        sa.Column("browser", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("referer", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["qr_id"], ["qr_codes.id"], name="fk_scan_logs_qr_id"),
    )
    op.create_index(
        "ix_scan_logs_qr_id_scanned_at",
        "scan_logs",
        ["qr_id", "scanned_at"],
    )

    op.create_table(
        "daily_analytics_summary",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qr_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("total_scans", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_visitors", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["qr_id"],
            ["qr_codes.id"],
            name="fk_daily_analytics_summary_qr_id",
        ),
        sa.UniqueConstraint(
            "qr_id",
            "summary_date",
            name="uq_daily_analytics_summary_qr_id_summary_date",
        ),
    )


def downgrade() -> None:
    """Revert initial schema in reverse dependency order."""

    op.drop_table("daily_analytics_summary")
    op.drop_index("ix_scan_logs_qr_id_scanned_at", table_name="scan_logs")
    op.drop_table("scan_logs")
    op.drop_table("qr_event_details")
    op.drop_table("qr_codes")
    op.drop_table("campaigns")
    op.drop_table("user_integrations")
    op.drop_table("users")

