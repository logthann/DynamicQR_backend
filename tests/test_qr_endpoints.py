"""Tests for QR code CRUD and status endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.qr_codes import get_qr_service
from app.core.rbac import Principal
from app.schemas.qr_code import QRCodeRead


class _StubQRService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self._qr = QRCodeRead(
            id=1,
            user_id=7,
            campaign_id=11,
            name="Landing QR",
            short_code="abc12345",
            destination_url="https://example.com/landing",
            qr_type="url",
            design_config={"color": "#000000"},
            ga_measurement_id=None,
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="launch",
            status="active",
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self.last_include_deleted_list: bool | None = None
        self.last_include_deleted_get: bool | None = None

    async def list_qrs_by_owner(self, principal: Principal, **kwargs):
        self.last_include_deleted_list = kwargs.get("include_deleted")
        return [self._qr]

    async def get_qr(self, principal: Principal, qr_id: int, **kwargs):
        self.last_include_deleted_get = kwargs.get("include_deleted")
        return self._qr if qr_id == 1 else None

    async def create_qr(self, principal: Principal, payload, **kwargs):
        return self._qr.model_copy(update={"name": payload.name})

    async def update_qr(self, principal: Principal, qr_id: int, payload):
        if qr_id != 1:
            return None
        name = payload.name if payload.name is not None else self._qr.name
        return self._qr.model_copy(update={"name": name})

    async def set_qr_status(self, principal: Principal, qr_id: int, status):
        if qr_id != 1:
            return None
        return self._qr.model_copy(update={"status": status})

    async def delete_qr(self, principal: Principal, qr_id: int):
        return qr_id == 1


@pytest.mark.asyncio
async def test_list_qr_codes_returns_items(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.get("/api/v1/qr/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_create_qr_code_returns_201(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.post(
            "/api/v1/qr/",
            json={
                "name": "Promo QR",
                "campaign_id": 11,
                "destination_url": "https://example.com/promo",
                "qr_type": "url",
                "design_config": {"color": "#ffffff"},
                "status": "active",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["name"] == "Promo QR"


@pytest.mark.asyncio
async def test_update_qr_status_returns_updated_model(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.patch(
            "/api/v1/qr/1/status",
            json={"status": "paused"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_get_qr_returns_404_when_missing(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.get("/api/v1/qr/999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_qr_returns_204(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.delete("/api/v1/qr/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_non_admin_cannot_request_deleted_qr_codes(app: FastAPI, async_client: AsyncClient) -> None:
    stub = _StubQRService()
    app.dependency_overrides[get_qr_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.get("/api/v1/qr/?include_deleted=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "Only admin can include deleted QR codes"


@pytest.mark.asyncio
async def test_admin_can_request_deleted_qr_codes(app: FastAPI, async_client: AsyncClient) -> None:
    stub = _StubQRService()
    app.dependency_overrides[get_qr_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")

    try:
        response = await async_client.get("/api/v1/qr/?include_deleted=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert stub.last_include_deleted_list is True


