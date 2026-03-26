"""Tests for campaign service RBAC ownership enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.rbac import Principal, RBACError
from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignUpdate
from app.services.campaign_service import CampaignService


def _campaign_read(*, campaign_id: int = 1, user_id: int = 10) -> CampaignRead:
    now = datetime.now(UTC)
    return CampaignRead(
        id=campaign_id,
        user_id=user_id,
        name="Campaign",
        description=None,
        start_date=None,
        end_date=None,
        status="active",
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_admin_can_create_campaign_for_other_owner() -> None:
    repository = AsyncMock()
    repository.create.return_value = _campaign_read(user_id=99)
    service = CampaignService(repository)

    result = await service.create_campaign(
        Principal(user_id=1, role="admin"),
        CampaignCreate(name="A", description=None, start_date=None, end_date=None, status="active"),
        owner_user_id=99,
    )

    assert result.user_id == 99
    repository.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_cannot_create_campaign_for_another_owner() -> None:
    repository = AsyncMock()
    service = CampaignService(repository)

    with pytest.raises(RBACError):
        await service.create_campaign(
            Principal(user_id=5, role="user"),
            CampaignCreate(name="A", description=None, start_date=None, end_date=None, status="active"),
            owner_user_id=8,
        )


@pytest.mark.asyncio
async def test_agency_cannot_read_campaign_outside_company_scope() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=20)

    async def resolve_company(_: int) -> str | None:
        return "OtherCo"

    service = CampaignService(repository, company_name_resolver=resolve_company)

    with pytest.raises(RBACError):
        await service.get_campaign(
            Principal(user_id=2, role="agency", company_name="Acme"),
            campaign_id=1,
        )


@pytest.mark.asyncio
async def test_update_campaign_checks_scope_before_update() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=7)
    repository.update.return_value = _campaign_read(user_id=7)

    service = CampaignService(repository)

    result = await service.update_campaign(
        Principal(user_id=7, role="user"),
        campaign_id=1,
        payload=CampaignUpdate(name="Updated"),
    )

    assert result is not None
    repository.update.assert_awaited_once_with(1, CampaignUpdate(name="Updated"))


@pytest.mark.asyncio
async def test_update_campaign_allows_calendar_reconciliation_fields() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=7)
    repository.update.return_value = _campaign_read(user_id=7)

    service = CampaignService(repository)
    payload = CampaignUpdate(
        calendar_sync_status="out_of_sync",
        calendar_sync_hash="hash-123",
    )

    result = await service.update_campaign(
        Principal(user_id=7, role="user"),
        campaign_id=1,
        payload=payload,
    )

    assert result is not None
    repository.update.assert_awaited_once_with(1, payload)


