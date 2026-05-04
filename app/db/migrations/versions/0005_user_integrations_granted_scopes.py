"""Add granted scopes column to user integrations.

Revision ID: 0005_user_integrations_granted_scopes
Revises: 0004_ga_tracking_columns
Create Date: 2026-04-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0005_user_integrations_granted_scopes"
down_revision = "0004_ga_tracking_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist granted OAuth scopes per provider connection."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("user_integrations")}

    if "granted_scopes" not in existing_columns:
        op.add_column("user_integrations", sa.Column("granted_scopes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove granted OAuth scopes persistence column."""

    op.drop_column("user_integrations", "granted_scopes")

