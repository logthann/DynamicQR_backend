"""Tests for QR redirect endpoint behavior."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.redirect import get_qr_code_repository
from app.schemas.redirect import QRCodeStatus, RedirectQRCode


class _StubQRCodeRepository:
    def __init__(self, qr_code: RedirectQRCode | None) -> None:
        self._qr_code = qr_code

    async def resolve_by_short_code(self, short_code: str) -> RedirectQRCode | None:
        if self._qr_code is None:
            return None
        return self._qr_code if short_code == self._qr_code.short_code else None


@pytest.mark.asyncio
async def test_redirect_endpoint_returns_302_for_known_short_code(
    app: FastAPI,
    async_client: AsyncClient,
) -> None:
    qr_code = RedirectQRCode(
        id=1,
        short_code="abc123",
        destination_url="https://example.com/landing",
        status=QRCodeStatus.active,
        deleted_at=None,
        ga_measurement_id=None,
        utm_source="newsletter",
        utm_medium="email",
        utm_campaign="spring-launch",
    )

    app.dependency_overrides[get_qr_code_repository] = lambda: _StubQRCodeRepository(qr_code)

    try:
        response = await async_client.get("/q/abc123", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "https://example.com/landing?utm_source=newsletter&utm_medium=email&utm_campaign=spring-launch"
    )


@pytest.mark.asyncio
async def test_redirect_endpoint_returns_404_for_unknown_short_code(
    app: FastAPI,
    async_client: AsyncClient,
) -> None:
    app.dependency_overrides[get_qr_code_repository] = lambda: _StubQRCodeRepository(None)

    try:
        response = await async_client.get("/q/missing", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "QR code not found"


@pytest.mark.asyncio
async def test_redirect_endpoint_returns_410_for_inactive_qr(
    app: FastAPI,
    async_client: AsyncClient,
) -> None:
    qr_code = RedirectQRCode(
        id=2,
        short_code="paused1",
        destination_url="https://example.com/paused",
        status=QRCodeStatus.paused,
        deleted_at=None,
        ga_measurement_id=None,
        utm_source=None,
        utm_medium=None,
        utm_campaign=None,
    )

    app.dependency_overrides[get_qr_code_repository] = lambda: _StubQRCodeRepository(qr_code)

    try:
        response = await async_client.get("/q/paused1", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 410
    assert response.json()["detail"] == "QR code is inactive"


@pytest.mark.asyncio
async def test_redirect_endpoint_returns_410_for_soft_deleted_qr(
    app: FastAPI,
    async_client: AsyncClient,
) -> None:
    qr_code = RedirectQRCode(
        id=3,
        short_code="gone1",
        destination_url="https://example.com/gone",
        status=QRCodeStatus.active,
        deleted_at="2026-03-24T00:00:00Z",
        ga_measurement_id=None,
        utm_source=None,
        utm_medium=None,
        utm_campaign=None,
    )

    app.dependency_overrides[get_qr_code_repository] = lambda: _StubQRCodeRepository(qr_code)

    try:
        response = await async_client.get("/q/gone1", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 410
    assert response.json()["detail"] == "QR code has been deleted"


