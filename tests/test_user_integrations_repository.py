"""Tests for user integration repository SQL and unique-key upsert behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.integrations import IntegrationProvider, ProviderCredentialWrite


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
    ) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> _MappingResult:
        return _MappingResult(self._rows)


def _integration_row(integration_id: int = 1) -> dict[str, object]:
    return {
        "id": integration_id,
        "user_id": 42,
        "provider_name": "google_calendar",
        "access_token": "enc-access",
        "refresh_token": "enc-refresh",
        "expires_at": datetime.now(UTC),
    }


@pytest.mark.asyncio
async def test_get_by_user_and_provider_queries_unique_key() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rows=[_integration_row()])
    repo = UserIntegrationRepository(session)

    record = await repo.get_by_user_and_provider(42, IntegrationProvider.google_calendar)

    assert record is not None
    statement = session.execute.await_args.args[0]
    assert "WHERE user_id = :user_id" in str(statement)
    assert "provider_name = :provider_name" in str(statement)


@pytest.mark.asyncio
async def test_upsert_credentials_uses_on_duplicate_key_update() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        _FakeExecuteResult(),
        _FakeExecuteResult(rows=[_integration_row()]),
    ]
    repo = UserIntegrationRepository(session)

    record = await repo.upsert_credentials(
        user_id=42,
        payload=ProviderCredentialWrite(
            provider_name=IntegrationProvider.google_calendar,
            access_token="enc-access",
            refresh_token="enc-refresh",
        ),
    )

    assert record.user_id == 42
    statement = session.execute.await_args_list[0].args[0]
    sql = str(statement)
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "access_token = VALUES(access_token)" in sql


@pytest.mark.asyncio
async def test_delete_by_user_and_provider_returns_true_when_row_deleted() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rowcount=1)
    repo = UserIntegrationRepository(session)

    deleted = await repo.delete_by_user_and_provider(42, IntegrationProvider.google_analytics)

    assert deleted is True
    statement = session.execute.await_args.args[0]
    assert "DELETE FROM user_integrations" in str(statement)

