"""Tests for user management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.users import get_current_principal
from app.core.rbac import Principal
from app.core.security import hash_password


class _FakeMappingsResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list[dict[str, object]] | None = None, scalar_value: object | None = None) -> None:
        self._rows = rows or []
        self._scalar_value = scalar_value

    def mappings(self) -> _FakeMappingsResult:
        return _FakeMappingsResult(self._rows)

    def scalar(self) -> object | None:
        return self._scalar_value


class _FakeSession:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.execute = AsyncMock(
            side_effect=[
                _FakeExecuteResult(
                    rows=[
                        {
                            "id": 5,
                            "username": "john.doe",
                            "email": "john.doe@example.com",
                            "full_name": "John Doe",
                            "phone_number": "+1 (555) 123-4567",
                            "role": "admin",
                            "created_at": now,
                            "campaigns_created": 24,
                            "qr_codes_created": 156,
                        }
                    ]
                ),
                _FakeExecuteResult(
                    rows=[
                        {
                            "id": "c1",
                            "name": "Summer Sale 2024",
                            "status": "active",
                            "created_at": now,
                        }
                    ]
                ),
                _FakeExecuteResult(
                    rows=[
                        {
                            "id": "q1",
                            "name": "Store Entrance QR",
                            "scans": 1245,
                            "created_at": now,
                        }
                    ]
                ),
            ]
        )
        self.flush = AsyncMock()


class _PasswordChangeSession:
    def __init__(self, stored_password: str) -> None:
        self.execute = AsyncMock(
            side_effect=[
                _FakeExecuteResult(rows=[{"password_hash": stored_password}]),
                _FakeExecuteResult(),
            ]
        )
        self.flush = AsyncMock()


class _ListUsersSession:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.execute = AsyncMock(
            side_effect=[
                _FakeExecuteResult(scalar_value=1),
                _FakeExecuteResult(
                    rows=[
                        {
                            "id": 5,
                            "username": "john.doe",
                            "email": "john.doe@example.com",
                            "full_name": "John Doe",
                            "phone_number": "+1 (555) 123-4567",
                            "role": "employee",
                            "created_at": now,
                            "campaigns_created": 2,
                            "qr_codes_created": 3,
                        }
                    ]
                ),
            ]
        )
        self.flush = AsyncMock()


class _UpdateUserSession:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.execute = AsyncMock(
            side_effect=[
                _FakeExecuteResult(scalar_value=1),
                _FakeExecuteResult(),
                _FakeExecuteResult(
                    rows=[
                        {
                            "id": 5,
                            "username": "yuroyu",
                            "email": "longthan243@gmail.com",
                            "full_name": "yute",
                            "phone_number": "0335351365",
                            "role": "employee",
                            "created_at": now,
                            "campaigns_created": 0,
                            "qr_codes_created": 0,
                        }
                    ]
                ),
            ]
        )
        self.flush = AsyncMock()


@pytest.mark.asyncio
async def test_get_user_detail_accepts_numeric_user_id(app: FastAPI, async_client: AsyncClient) -> None:
    session = _FakeSession()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.get("/api/v1/users/5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == "u_5"
    assert body["user"]["username"] == "john.doe"
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_get_user_detail_still_accepts_prefixed_user_id(app: FastAPI, async_client: AsyncClient) -> None:
    session = _FakeSession()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.get("/api/v1/users/u_5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["user"]["id"] == "u_5"


@pytest.mark.asyncio
async def test_get_user_detail_accepts_legacy_role_and_campaign_status(app: FastAPI, async_client: AsyncClient) -> None:
    now = datetime.now(UTC)

    class _LegacySession:
        def __init__(self) -> None:
            self.execute = AsyncMock(
                side_effect=[
                    _FakeExecuteResult(
                        rows=[
                            {
                                "id": 5,
                                "username": "john.doe",
                                "email": "john.doe@example.com",
                                "full_name": "John Doe",
                                "phone_number": "+1 (555) 123-4567",
                                "role": "agency",
                                "created_at": now,
                                "campaigns_created": 1,
                                "qr_codes_created": 1,
                            }
                        ]
                    ),
                    _FakeExecuteResult(
                        rows=[
                            {
                                "id": "c1",
                                "name": "Summer Sale 2024",
                                "status": "paused",
                                "created_at": now,
                            }
                        ]
                    ),
                    _FakeExecuteResult(
                        rows=[
                            {
                                "id": "q1",
                                "name": "Store Entrance QR",
                                "scans": 1245,
                                "created_at": now,
                            }
                        ]
                    ),
                ]
            )

    session = _LegacySession()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.get("/api/v1/users/5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "agency"
    assert response.json()["campaigns"][0]["status"] == "paused"


@pytest.mark.asyncio
async def test_list_users_requires_admin(app: FastAPI, async_client: AsyncClient) -> None:
    session = _ListUsersSession()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=5, role="employee")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_allows_admin(app: FastAPI, async_client: AsyncClient) -> None:
    session = _ListUsersSession()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_update_user_accepts_phone_number_alias(app: FastAPI, async_client: AsyncClient) -> None:
    session = _UpdateUserSession()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=5, role="employee")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.patch(
            "/api/v1/users/5",
            json={
                "username": "yuroyu",
                "full_name": "yute",
                "phone_number": "0335351365",
                "email": "longthan243@gmail.com",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["user"]["phone_number"] == "0335351365"


@pytest.mark.asyncio
async def test_change_password_rejects_other_employee(app: FastAPI, async_client: AsyncClient) -> None:
    session = _PasswordChangeSession(hash_password("old-pass-123"))
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=99, role="employee")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.patch(
            "/api/v1/users/5/password",
            json={"new_password": "new-pass-123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_change_password_requires_current_password_for_self(app: FastAPI, async_client: AsyncClient) -> None:
    session = _PasswordChangeSession(hash_password("old-pass-123"))
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=5, role="employee")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.patch(
            "/api/v1/users/5/password",
            json={"new_password": "new-pass-123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_change_password_allows_employee_self_update(app: FastAPI, async_client: AsyncClient) -> None:
    session = _PasswordChangeSession(hash_password("old-pass-123"))
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=5, role="employee")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.patch(
            "/api/v1/users/5/password",
            json={"current_password": "old-pass-123", "new_password": "new-pass-123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully"
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_change_password_post_alias_works_for_self(app: FastAPI, async_client: AsyncClient) -> None:
    session = _PasswordChangeSession(hash_password("old-pass-123"))
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=5, role="employee")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.post(
            "/api/v1/users/5/password",
            json={"current_password": "old-pass-123", "new_password": "new-pass-123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully"


@pytest.mark.asyncio
async def test_change_password_allows_admin_reset_without_current_password(app: FastAPI, async_client: AsyncClient) -> None:
    session = _PasswordChangeSession(hash_password("old-pass-123"))
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")
    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: session

    try:
        response = await async_client.patch(
            "/api/v1/users/5/password",
            json={"new_password": "new-pass-123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully"


