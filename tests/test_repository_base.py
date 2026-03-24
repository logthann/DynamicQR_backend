"""Tests for generic repository soft-delete defaults."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.repositories.base import RepositoryBase


class SoftDeleteModel(Base):
    __tablename__ = "soft_delete_model"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RegularModel(Base):
    __tablename__ = "regular_model"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


def test_soft_delete_filter_applies_by_default() -> None:
    repo = RepositoryBase(AsyncMock(), SoftDeleteModel)

    statement = repo._base_select(include_deleted=False)
    sql = str(statement)

    assert "deleted_at IS NULL" in sql


def test_soft_delete_filter_can_be_disabled() -> None:
    repo = RepositoryBase(AsyncMock(), SoftDeleteModel)

    statement = repo._base_select(include_deleted=True)
    sql = str(statement)

    assert "deleted_at IS NULL" not in sql


def test_regular_model_does_not_get_soft_delete_filter() -> None:
    repo = RepositoryBase(AsyncMock(), RegularModel)

    statement = repo._base_select(include_deleted=False)
    sql = str(statement)

    assert "deleted_at IS NULL" not in sql


async def test_soft_delete_raises_for_models_without_deleted_at() -> None:
    repo = RepositoryBase(AsyncMock(), RegularModel)
    instance = RegularModel(id=1)

    with pytest.raises(ValueError, match="does not support soft delete"):
        await repo.soft_delete(instance)

