"""Tests for QR code CRUD and status endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.qr_codes import get_qr_service
from app.core.rbac import Principal
from app.schemas.qr_code import QRCodeListItem, QRCodeRead


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
        self._qr_list_item_employee = QRCodeListItem(
            id=1,
            user_id=7,
            name="Landing QR",
            short_code="abc12345",
            destination_url="https://example.com/landing",
            qr_type="url",
            design_config={"color": "#000000"},
            ga_type=None,
            ga_measurement_id=None,
            ga_property_id=None,
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="launch",
            status="active",
            campaign={"id": 11, "name": "Summer Sale", "description": "Summer promotion campaign"},
            employee=None,  # Employee role does not see employee info
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self._qr_list_item_admin = QRCodeListItem(
            id=1,
            user_id=7,
            name="Landing QR",
            short_code="abc12345",
            destination_url="https://example.com/landing",
            qr_type="url",
            design_config={"color": "#000000"},
            ga_type=None,
            ga_measurement_id=None,
            ga_property_id=None,
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="launch",
            status="active",
            campaign={"id": 11, "name": "Summer Sale", "description": "Summer promotion campaign"},
            employee={"username": "john_doe", "email": "john@example.com"},  # Admin sees employee info
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self.last_include_deleted_list: bool | None = None
        self.last_include_deleted_get: bool | None = None
        self.last_principal_role: str | None = None

    async def list_qrs_by_owner(self, principal: Principal, **kwargs):
        self.last_include_deleted_list = kwargs.get("include_deleted")
        self.last_principal_role = principal.role
        # Return different response based on role
        if principal.role == "admin":
            return [self._qr_list_item_admin]
        return [self._qr_list_item_employee]

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
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.get("/api/v1/qr/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_list_qr_codes_employee_has_campaign_no_employee(app: FastAPI, async_client: AsyncClient) -> None:
    """Employee role should see campaign info but NOT employee info."""
    stub = _StubQRService()
    app.dependency_overrides[get_qr_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.get("/api/v1/qr/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    qr = data[0]
    # Employee should see campaign info
    assert "campaign" in qr
    assert qr["campaign"] is not None
    assert qr["campaign"]["id"] == 11
    assert qr["campaign"]["name"] == "Summer Sale"
    assert qr["campaign"]["description"] == "Summer promotion campaign"
    # campaign_id should NOT be present at root (replaced by campaign object)
    assert "campaign_id" not in qr
    # Employee should NOT see employee info
    assert "employee" not in qr or qr.get("employee") is None


@pytest.mark.asyncio
async def test_list_qr_codes_admin_has_campaign_and_employee(app: FastAPI, async_client: AsyncClient) -> None:
    """Admin role should see both campaign info AND employee info."""
    stub = _StubQRService()
    app.dependency_overrides[get_qr_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")

    try:
        response = await async_client.get("/api/v1/qr/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    qr = data[0]
    # Admin should see campaign info
    assert "campaign" in qr
    assert qr["campaign"] is not None
    assert qr["campaign"]["id"] == 11
    assert qr["campaign"]["name"] == "Summer Sale"
    assert qr["campaign"]["description"] == "Summer promotion campaign"
    # Admin should also see employee info
    assert "employee" in qr
    assert qr["employee"] is not None
    assert qr["employee"]["username"] == "john_doe"
    assert qr["employee"]["email"] == "john@example.com"


@pytest.mark.asyncio
async def test_create_qr_code_returns_201(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

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
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

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
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.get("/api/v1/qr/999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_qr_returns_204(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_qr_service] = lambda: _StubQRService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

    try:
        response = await async_client.delete("/api/v1/qr/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_non_admin_cannot_request_deleted_qr_codes(app: FastAPI, async_client: AsyncClient) -> None:
    stub = _StubQRService()
    app.dependency_overrides[get_qr_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="employee")

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


