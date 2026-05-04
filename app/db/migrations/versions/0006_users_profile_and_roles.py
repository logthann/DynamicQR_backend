"""Revise users table profile fields and role values.

Revision ID: 0006_users_profile_and_roles
Revises: 0005_user_integrations_granted_scopes
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "0006_users_profile_and_roles"
down_revision = "0005_user_integrations_granted_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply users-table role/profile changes requested by product updates."""

    bind = op.get_bind()

    if _constraint_exists("users", "ck_users_role"):
        op.drop_constraint("ck_users_role", "users", type_="check")

    if not _column_exists("users", "phone_number"):
        op.add_column("users", sa.Column("phone_number", sa.String(length=32), nullable=True))
    if not _column_exists("users", "username"):
        op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
    if not _column_exists("users", "full_name"):
        op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))
    if not _column_exists("users", "address"):
        op.add_column("users", sa.Column("address", sa.String(length=512), nullable=True))

    if not _constraint_exists("users", "uq_users_username"):
        op.create_unique_constraint("uq_users_username", "users", ["username"])

    # Backfill legacy roles before enforcing the new role check.
    bind.execute(text("UPDATE users SET role = 'employee' WHERE role IN ('agency', 'user')"))

    if not _constraint_exists("users", "ck_users_role"):
        op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'employee')")

    if _column_exists("users", "company_name"):
        op.drop_column("users", "company_name")
    if _column_exists("users", "subscription_plan"):
        op.drop_column("users", "subscription_plan")


def downgrade() -> None:
    """Revert users-table role/profile changes."""

    if _constraint_exists("users", "ck_users_role"):
        op.drop_constraint("ck_users_role", "users", type_="check")
    if not _constraint_exists("users", "ck_users_role"):
        op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'agency', 'user')")

    if not _column_exists("users", "subscription_plan"):
        op.add_column("users", sa.Column("subscription_plan", sa.String(length=50), nullable=True))
    if not _column_exists("users", "company_name"):
        op.add_column("users", sa.Column("company_name", sa.String(length=255), nullable=True))

    if _constraint_exists("users", "uq_users_username"):
        op.drop_constraint("uq_users_username", "users", type_="unique")
    if _column_exists("users", "address"):
        op.drop_column("users", "address")
    if _column_exists("users", "full_name"):
        op.drop_column("users", "full_name")
    if _column_exists("users", "username"):
        op.drop_column("users", "username")
    if _column_exists("users", "phone_number"):
        op.drop_column("users", "phone_number")


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        text(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar()
    return result is not None


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        text(
            """
            SELECT 1
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND CONSTRAINT_NAME = :constraint_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).scalar()
    return result is not None


