"""Alembic runtime configuration for online and offline migrations."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db.base import Base

# Alembic Config object provides access to values within alembic.ini.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import model metadata for autogenerate support.
target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Resolve database URL from app settings or Alembic config fallback."""

    try:
        return get_settings().database_url
    except Exception:
        configured_url = config.get_main_option("sqlalchemy.url")
        if not configured_url:
            raise
        return configured_url


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    config_section = config.get_section(config.config_ini_section) or {}
    config_section["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

