"""Tests for QR service business flow and RBAC ownership checks."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.rbac import Principal, RBACError
from app.schemas.qr_code import QRCodeCreate, QRCodeRead, QRCodeUpdate, QRType
from app.services.qr_service import QRService


def _qr_read(*, qr_id: int = 1, user_id: int = 10, qr_type: str = "url") -> QRCodeRead:
    now = datetime.now(UTC)
    return QRCodeRead(
        id=qr_id,
        user_id=user_id,
        campaign_id=22,
        name="QR",
        short_code="abc12345",
        destination_url="https://example.com/landing",
        qr_type=qr_type,
        design_config={"color": "#000000"},
        ga_measurement_id=None,
        utm_source=None,
        utm_medium=None,
        utm_campaign=None,
        status="active",
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_create_url_qr_persists_design_config_and_generated_code() -> None:
    repository = AsyncMock()
    repository.create.return_value = _qr_read(qr_id=11, user_id=7)
    repository.get_campaign_owner_user_id.return_value = 7

    async def generate_code(_: object) -> str:
        return "newCODE1"

    service = QRService(repository, short_code_generator=generate_code)

    payload = QRCodeCreate(
        name="Landing",
        campaign_id=22,
        destination_url="https://example.com/landing",
        qr_type=QRType.url,
        design_config={"color": "#ffffff", "logo": "brand"},
        status="active",
    )

    created = await service.create_qr(Principal(user_id=7, role="user"), payload)

    assert created.id == 11
    repository.create.assert_awaited_once_with(7, "newCODE1", payload)


@pytest.mark.asyncio
async def test_create_event_qr_invokes_event_handler_when_provided() -> None:
    repository = AsyncMock()
    repository.create.return_value = _qr_read(qr_id=33, user_id=3, qr_type="event")
    repository.get_campaign_owner_user_id.return_value = 3
    event_handler = AsyncMock()

    async def generate_code(_: object) -> str:
        return "event001"

    service = QRService(
        repository,
        short_code_generator=generate_code,
        event_qr_handler=event_handler,
    )

    payload = QRCodeCreate(
        name="Event",
        campaign_id=9,
        destination_url="https://example.com/event",
        qr_type=QRType.event,
        design_config={"theme": "blue"},
        status="active",
    )

    created = await service.create_qr(Principal(user_id=3, role="user"), payload)

    assert created.id == 33
    event_handler.assert_awaited_once_with(33, payload)


@pytest.mark.asyncio
async def test_user_cannot_create_qr_for_other_owner() -> None:
    repository = AsyncMock()
    repository.get_campaign_owner_user_id.return_value = 1

    async def generate_code(_: object) -> str:
        return "blocked01"

    service = QRService(repository, short_code_generator=generate_code)

    payload = QRCodeCreate(
        name="Forbidden",
        campaign_id=1,
        destination_url="https://example.com",
        qr_type=QRType.url,
    )

    with pytest.raises(RBACError):
        await service.create_qr(
            Principal(user_id=5, role="user"),
            payload,
            owner_user_id=99,
        )


@pytest.mark.asyncio
async def test_update_qr_checks_scope_before_repository_update() -> None:
    repository = AsyncMock()
    repository.get_by_id.return_value = _qr_read(user_id=12)
    repository.update.return_value = _qr_read(user_id=12)

    service = QRService(repository)

    result = await service.update_qr(
        Principal(user_id=12, role="user"),
        qr_id=1,
        payload=QRCodeUpdate(name="Updated QR"),
    )

    assert result is not None
    repository.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_qr_rejects_campaign_outside_owner_scope() -> None:
    repository = AsyncMock()
    repository.get_campaign_owner_user_id.return_value = 99

    service = QRService(repository)

    with pytest.raises(RBACError, match="Campaign is outside principal scope"):
        await service.list_qrs_by_owner(
            Principal(user_id=4, role="user"),
            owner_user_id=4,
            campaign_id=5,
        )


