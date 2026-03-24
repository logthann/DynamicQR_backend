"""Tests for campaign CRUD endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.campaigns import get_campaign_service, get_current_principal
from app.core.rbac import Principal
from app.schemas.campaign import CampaignRead


class _StubCampaignService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self._campaign = CampaignRead(
            id=1,
            user_id=7,
            name="Launch",
            description=None,
            start_date=None,
            end_date=None,
            status="active",
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self.last_include_deleted_list: bool | None = None
        self.last_include_deleted_get: bool | None = None

    async def list_campaigns_by_owner(self, principal: Principal, **kwargs):
        self.last_include_deleted_list = kwargs.get("include_deleted")
        return [self._campaign]

    async def get_campaign(self, principal: Principal, campaign_id: int, **kwargs):
        self.last_include_deleted_get = kwargs.get("include_deleted")
        return self._campaign if campaign_id == 1 else None

    async def create_campaign(self, principal: Principal, payload, **kwargs):
        return self._campaign.model_copy(update={"name": payload.name})

    async def update_campaign(self, principal: Principal, campaign_id: int, payload):
        if campaign_id != 1:
            return None
        return self._campaign.model_copy(update={"name": payload.name or self._campaign.name})

    async def delete_campaign(self, principal: Principal, campaign_id: int):
        return campaign_id == 1


@pytest.mark.asyncio
async def test_list_campaigns_returns_items(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_service] = lambda: _StubCampaignService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.get("/api/v1/campaigns/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_create_campaign_returns_201(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_service] = lambda: _StubCampaignService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.post(
            "/api/v1/campaigns/",
            json={
                "name": "New Campaign",
                "description": "desc",
                "start_date": None,
                "end_date": None,
                "status": "active",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["name"] == "New Campaign"


@pytest.mark.asyncio
async def test_get_campaign_returns_404_when_missing(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_service] = lambda: _StubCampaignService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.get("/api/v1/campaigns/999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_campaign_returns_204(app: FastAPI, async_client: AsyncClient) -> None:
    app.dependency_overrides[get_campaign_service] = lambda: _StubCampaignService()
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.delete("/api/v1/campaigns/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_non_admin_cannot_request_deleted_campaigns(app: FastAPI, async_client: AsyncClient) -> None:
    stub = _StubCampaignService()
    app.dependency_overrides[get_campaign_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=7, role="user")

    try:
        response = await async_client.get("/api/v1/campaigns/?include_deleted=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "Only admin can include deleted campaigns"


@pytest.mark.asyncio
async def test_admin_can_request_deleted_campaigns(app: FastAPI, async_client: AsyncClient) -> None:
    stub = _StubCampaignService()
    app.dependency_overrides[get_campaign_service] = lambda: stub
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id=1, role="admin")

    try:
        response = await async_client.get("/api/v1/campaigns/?include_deleted=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert stub.last_include_deleted_list is True


