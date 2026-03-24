"""Tests for integration OAuth endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_current_principal
from app.api.v1.integrations import get_integration_service
from app.core.rbac import Principal
from app.schemas.integrations import (
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthConnectResponse,
)


class _StubIntegrationService:
    async def list_connection_statuses(self, principal: Principal):
        return [
            IntegrationConnectionStatus(
                provider_name=IntegrationProvider.google_calendar,
                connected=True,
                expires_at=datetime.now(UTC),
                has_refresh_token=True,
            )
        ]

    async def build_connect_url(self, principal: Principal, payload):
        return OAuthConnectResponse(
            provider_name=payload.provider_name,
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
            state=payload.state or "state-token",
        )

    async def handle_callback(self, principal: Principal, payload):
        return IntegrationConnectionStatus(
            provider_name=payload.provider_name,
            connected=True,
            expires_at=None,
            has_refresh_token=True,
        )

    async def refresh_provider_token(self, principal: Principal, provider_name: IntegrationProvider):
        return IntegrationConnectionStatus(
            provider_name=provider_name,
            connected=True,
            expires_at=None,
            has_refresh_token=True,
        )

    async def revoke_provider_connection(self, principal: Principal, provider_name: IntegrationProvider):
        return provider_name == IntegrationProvider.google_calendar


@pytest.mark.asyncio
async def test_list_integrations_returns_items(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.get("/api/v1/integrations/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_connect_provider_returns_authorization_url(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.post(
            "/api/v1/integrations/connect",
            json={"provider_name": "google_calendar"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "authorization_url" in response.json()


@pytest.mark.asyncio
async def test_callback_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.post(
            "/api/v1/integrations/callback",
            json={"provider_name": "google_calendar", "code": "auth-code"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["connected"] is True


@pytest.mark.asyncio
async def test_refresh_provider_returns_connected_status(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.post("/api/v1/integrations/google_calendar/refresh")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider_name"] == "google_calendar"


@pytest.mark.asyncio
async def test_revoke_provider_returns_404_when_not_connected(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_integration_service] = lambda: _StubIntegrationService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=42, role="user")

    try:
        response = await async_client.delete("/api/v1/integrations/google_analytics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404

