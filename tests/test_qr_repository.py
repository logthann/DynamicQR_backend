"""Tests for QR repository SQL composition and campaign/status linkage behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.repositories.qr_codes import QRCodeRepository
from app.schemas.qr_code import QRCodeCreate, QRCodeStatus, QRType


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


def _qr_row(qr_id: int = 1) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": qr_id,
        "user_id": 100,
        "campaign_id": 99,
        "name": "Landing QR",
        "short_code": "abc12345",
        "destination_url": "https://example.com/landing",
        "qr_type": "url",
        "design_config": {"color": "#000000"},
        "ga_measurement_id": None,
        "utm_source": "newsletter",
        "utm_medium": "email",
        "utm_campaign": "launch",
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }


@pytest.mark.asyncio
async def test_list_by_user_applies_campaign_and_status_filters() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rows=[_qr_row()])
    repo = QRCodeRepository(session)

    result = await repo.list_by_user(
        100,
        campaign_id=99,
        status=QRCodeStatus.active,
    )

    assert len(result) == 1
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "campaign_id = :campaign_id" in sql
    assert "status = :status" in sql
    assert "deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_create_includes_campaign_linkage_and_status() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        _FakeExecuteResult(lastrowid=21),
        _FakeExecuteResult(rows=[_qr_row(qr_id=21)]),
    ]
    repo = QRCodeRepository(session)

    created = await repo.create(
        user_id=100,
        short_code="abc12345",
        payload=QRCodeCreate(
            name="Landing QR",
            campaign_id=99,
            destination_url="https://example.com/landing",
            qr_type=QRType.url,
            design_config={"color": "#000000"},
            status=QRCodeStatus.active,
        ),
    )

    assert created.id == 21
    assert created.campaign_id == 99
    first_call_params = session.execute.await_args_list[0].args[1]
    assert first_call_params["campaign_id"] == 99
    assert first_call_params["status"] == "active"


@pytest.mark.asyncio
async def test_set_status_updates_status_field() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rowcount=1)
    repo = QRCodeRepository(session)
    repo.get_by_id = AsyncMock(return_value=None)

    _ = await repo.set_status(5, QRCodeStatus.paused)

    statement = session.execute.await_args.args[0]
    assert "SET status = :status" in str(statement)
    params = session.execute.await_args.args[1]
    assert params["status"] == "paused"


@pytest.mark.asyncio
async def test_soft_delete_marks_deleted_at() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rowcount=1)
    repo = QRCodeRepository(session)
    repo.get_by_id = AsyncMock(return_value=None)

    deleted = await repo.soft_delete(7)

    assert deleted is True
    statement = session.execute.await_args.args[0]
    assert "SET deleted_at = UTC_TIMESTAMP()" in str(statement)

