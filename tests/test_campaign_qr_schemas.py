"""Tests for campaign and QR schema validation behavior."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.campaign import CampaignCreate
from app.schemas.qr_code import QRCodeCreate, QRCodeUpdate, QRType


def test_campaign_create_accepts_expected_fields() -> None:
    campaign = CampaignCreate(
        name="Black Friday 2026",
        description="Main sales campaign",
        status="active",
    )

    assert campaign.name == "Black Friday 2026"
    assert campaign.status == "active"


def test_qr_code_create_accepts_design_config_json() -> None:
    qr = QRCodeCreate(
        name="Landing QR",
        campaign_id=1,
        destination_url="https://example.com/offer",
        qr_type=QRType.url,
        design_config={"color": "#000000", "logo_url": "https://example.com/logo.png"},
        status="active",
    )

    assert qr.design_config is not None
    assert qr.design_config["color"] == "#000000"


def test_qr_code_create_rejects_invalid_design_config_shape() -> None:
    with pytest.raises(ValidationError):
        QRCodeCreate(
            name="Invalid QR",
            destination_url="https://example.com/offer",
            qr_type=QRType.url,
            design_config=["not", "an", "object"],
        )


def test_qr_code_update_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        QRCodeUpdate(status="paused", unknown_field="x")

