"""Tests for campaign service RBAC ownership enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.rbac import Principal, RBACError
from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignUpdate
from app.services.campaign_service import CampaignService, CampaignValidationError


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
    repository.get_creator_info.return_value = {"username": "testuser", "email": "test@example.com"}
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
            Principal(user_id=5, role="employee"),
            CampaignCreate(name="A", description=None, start_date=None, end_date=None, status="active"),
            owner_user_id=8,
        )


@pytest.mark.asyncio
async def test_agency_cannot_read_campaign_outside_company_scope() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=20)
    repository.get_creator_info.return_value = {"username": "testuser", "email": "test@example.com"}

    async def resolve_company(_: int) -> str | None:
        return "OtherCo"

    service = CampaignService(repository, company_name_resolver=resolve_company)

    with pytest.raises(RBACError):
        await service.get_campaign(
            Principal(user_id=2, role="employee"),
            campaign_id=1,
        )


@pytest.mark.asyncio
async def test_admin_get_campaign_includes_creator_info() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=4)
    repository.get_creator_info.return_value = {"username": "john_doe", "email": "john@example.com"}

    service = CampaignService(repository)

    result = await service.get_campaign(
        Principal(user_id=5, role="admin"),
        campaign_id=1,
    )

    assert result is not None
    assert result.user_id == 4
    assert result.creator is not None
    assert result.creator.username == "john_doe"
    assert result.creator.email == "john@example.com"


@pytest.mark.asyncio
async def test_update_campaign_checks_scope_before_update() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=7)
    repository.update.return_value = _campaign_read(user_id=7)
    repository.get_creator_info.return_value = {"username": "testuser", "email": "test@example.com"}

    service = CampaignService(repository)

    result = await service.update_campaign(
        Principal(user_id=7, role="employee"),
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
    repository.get_creator_info.return_value = {"username": "testuser", "email": "test@example.com"}

    service = CampaignService(repository)
    payload = CampaignUpdate(
        calendar_sync_status="out_of_sync",
        calendar_sync_hash="hash-123",
    )

    result = await service.update_campaign(
        Principal(user_id=7, role="employee"),
        campaign_id=1,
        payload=payload,
    )

    assert result is not None
    repository.update.assert_awaited_once_with(1, payload)


@pytest.mark.asyncio
async def test_create_campaign_rejects_oauth_without_property_id() -> None:
    repository = AsyncMock()
    service = CampaignService(repository)

    with pytest.raises(CampaignValidationError, match="ga_property_id is required"):
        await service.create_campaign(
            Principal(user_id=1, role="admin"),
            CampaignCreate(
                name="GA Campaign",
                description=None,
                start_date=None,
                end_date=None,
                status="active",
                ga_type="OAUTH",
            ),
        )


@pytest.mark.asyncio
async def test_update_campaign_no_mode_clears_ga_fields() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(user_id=7)
    repository.update.return_value = _campaign_read(user_id=7)
    repository.get_creator_info.return_value = {"username": "testuser", "email": "test@example.com"}
    service = CampaignService(repository)

    payload = CampaignUpdate(ga_type="NO")
    await service.update_campaign(Principal(user_id=7, role="employee"), campaign_id=1, payload=payload)

    normalized_payload = repository.update.await_args.args[1]
    assert normalized_payload.ga_type.value == "NO"
    assert normalized_payload.ga_measurement_id is None
    assert normalized_payload.ga_property_id is None


