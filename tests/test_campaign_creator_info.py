"""Test campaign creator info inclusion for admin users."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.rbac import Principal
from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignCreatorInfo
from app.services.campaign_service import CampaignService


def _campaign_read(*, campaign_id: int = 1, user_id: int = 10) -> CampaignRead:
    now = datetime.now(UTC)
    return CampaignRead(
        id=campaign_id,
        user_id=user_id,
        name="Q1 Campaign",
        description="Test campaign",
        start_date=None,
        end_date=None,
        status="active",
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_admin_gets_creator_info_on_list() -> None:
    """Verify admin users get creator info when listing campaigns."""
    repository = AsyncMock()
    repository.list_by_user.return_value = [_campaign_read(user_id=5)]
    repository.get_creator_info.return_value = {
        "username": "john_doe",
        "email": "john@example.com",
    }

    service = CampaignService(repository)

    result = await service.list_campaigns_by_owner(
        Principal(user_id=1, role="admin"),
        owner_user_id=5,
    )

    assert len(result) == 1
    campaign = result[0]
    assert campaign.id == 1
    assert campaign.user_id == 5
    # Verify creator info is populated
    assert campaign.creator is not None
    assert isinstance(campaign.creator, CampaignCreatorInfo)
    assert campaign.creator.username == "john_doe"
    assert campaign.creator.email == "john@example.com"


@pytest.mark.asyncio
async def test_employee_does_not_get_creator_info() -> None:
    """Verify employee users do not get creator info when listing campaigns."""
    repository = AsyncMock()
    repository.list_by_user.return_value = [_campaign_read(user_id=5)]
    repository.get_creator_info.return_value = {
        "username": "john_doe",
        "email": "john@example.com",
    }

    service = CampaignService(repository)

    result = await service.list_campaigns_by_owner(
        Principal(user_id=5, role="employee"),
        owner_user_id=5,
    )

    assert len(result) == 1
    campaign = result[0]
    # Verify creator info is NOT populated for employees
    assert campaign.creator is None


@pytest.mark.asyncio
async def test_admin_gets_creator_info_on_get_single() -> None:
    """Verify admin users get creator info when getting single campaign."""
    repository = AsyncMock()
    repository.get_by_id.return_value = _campaign_read(campaign_id=1, user_id=5)
    repository.get_creator_info.return_value = {
        "username": "john_doe",
        "email": "john@example.com",
    }

    service = CampaignService(repository)

    campaign = await service.get_campaign(
        Principal(user_id=1, role="admin"),
        campaign_id=1,
    )

    assert campaign is not None
    assert campaign.id == 1
    assert campaign.creator is not None
    assert campaign.creator.username == "john_doe"
    assert campaign.creator.email == "john@example.com"


@pytest.mark.asyncio
async def test_response_format_matches_specification() -> None:
    """Verify response format matches the specified schema."""
    repository = AsyncMock()
    campaign_data = _campaign_read(campaign_id=1, user_id=5)
    repository.list_by_user.return_value = [campaign_data]
    repository.get_creator_info.return_value = {
        "username": "john_doe",
        "email": "john@example.com",
    }

    service = CampaignService(repository)

    result = await service.list_campaigns_by_owner(
        Principal(user_id=1, role="admin"),
        owner_user_id=5,
    )

    campaign = result[0]

    # Verify the exact format requested:
    # {
    #   "id": 1,
    #   "user_id": 5,
    #   "creator": {
    #     "username": "john_doe",
    #     "email": "john@example.com"
    #   }
    # }

    response_dict = campaign.model_dump(exclude_none=True)

    # Verify required fields exist
    assert response_dict["id"] == 1
    assert response_dict["user_id"] == 5
    assert "creator" in response_dict

    # Verify creator structure
    creator = response_dict["creator"]
    assert creator["username"] == "john_doe"
    assert creator["email"] == "john@example.com"

    # Verify creator only has these two fields
    assert set(creator.keys()) == {"username", "email"}

