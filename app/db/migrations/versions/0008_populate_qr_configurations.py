"""Populate qr_configurations with existing data from qr_codes.

Revision ID: 0008_populate_qr_configurations
Revises: 0007_qr_configurations_table
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0008_populate_qr_configurations"
down_revision = "0007_qr_configurations_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migrate existing qr_codes data to qr_configurations table."""

    op.execute(
        """
        INSERT INTO qr_configurations (
            qr_id,
            version_number,
            name,
            destination_url,
            ga_measurement_id,
            utm_source,
            utm_medium,
            utm_campaign,
            is_current,
            created_at
        )
        SELECT
            id AS qr_id,
            1 AS version_number,
            name,
            destination_url,
            ga_measurement_id,
            utm_source,
            utm_medium,
            utm_campaign,
            1 AS is_current,
            created_at
        FROM qr_codes
        """
    )


def downgrade() -> None:
    """Remove all data from qr_configurations table."""

    op.execute("DELETE FROM qr_configurations")
