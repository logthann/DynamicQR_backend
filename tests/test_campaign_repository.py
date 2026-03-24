"""Tests for campaign repository SQL composition and soft-delete lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.repositories.campaigns import CampaignRepository
from app.schemas.campaign import CampaignCreate


class _MappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeExecuteResult:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        *,
        rowcount: int = 0,
        lastrowid: int = 1,
    ) -> None:
        self._rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self) -> _MappingResult:
        return _MappingResult(self._rows)


def _campaign_row(campaign_id: int = 1) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": campaign_id,
        "user_id": 100,
        "name": "Spring Campaign",
        "description": "Desc",
        "start_date": None,
        "end_date": None,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }


@pytest.mark.asyncio
async def test_get_by_id_applies_soft_delete_filter_by_default() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rows=[_campaign_row()])
    repo = CampaignRepository(session)

    result = await repo.get_by_id(1)

    assert result is not None
    statement = session.execute.await_args.args[0]
    assert "deleted_at IS NULL" in str(statement)


@pytest.mark.asyncio
async def test_get_by_id_can_include_deleted_rows() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rows=[_campaign_row()])
    repo = CampaignRepository(session)

    await repo.get_by_id(1, include_deleted=True)

    statement = session.execute.await_args.args[0]
    assert "deleted_at IS NULL" not in str(statement)


@pytest.mark.asyncio
async def test_soft_delete_updates_deleted_at_and_returns_true_on_change() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rowcount=1)
    repo = CampaignRepository(session)

    deleted = await repo.soft_delete(9)

    assert deleted is True
    statement = session.execute.await_args.args[0]
    assert "SET deleted_at = UTC_TIMESTAMP()" in str(statement)


@pytest.mark.asyncio
async def test_create_inserts_and_returns_created_campaign() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        _FakeExecuteResult(lastrowid=22),
        _FakeExecuteResult(rows=[_campaign_row(campaign_id=22)]),
    ]
    repo = CampaignRepository(session)

    created = await repo.create(
        100,
        CampaignCreate(name="Launch", description=None, start_date=None, end_date=None, status="active"),
    )

    assert created.id == 22
    assert session.execute.await_count == 2

