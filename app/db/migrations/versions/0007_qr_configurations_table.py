"""Create qr_configurations table for QR code version history.

Revision ID: 0007_qr_configurations_table
Revises: 0006_users_profile_and_roles
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0007_qr_configurations_table"
down_revision = "0006_users_profile_and_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create qr_configurations table for tracking QR code configuration versions."""

    op.create_table(
        "qr_configurations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qr_id", sa.BigInteger(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("destination_url", sa.Text(), nullable=False),
        sa.Column("ga_measurement_id", sa.String(length=100), nullable=True),
        sa.Column("utm_source", sa.String(length=255), nullable=True),
        sa.Column("utm_medium", sa.String(length=255), nullable=True),
        sa.Column("utm_campaign", sa.String(length=255), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["qr_id"],
            ["qr_codes.id"],
            name="fk_qr_configurations_qr_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "qr_id",
            "version_number",
            name="uq_qr_configurations_qr_id_version",
        ),
    )
    op.create_index(
        "ix_qr_configurations_qr_id_is_current",
        "qr_configurations",
        ["qr_id", "is_current"],
    )


def downgrade() -> None:
    """Drop qr_configurations table."""

    op.drop_index("ix_qr_configurations_qr_id_is_current", table_name="qr_configurations")
    op.drop_table("qr_configurations")
