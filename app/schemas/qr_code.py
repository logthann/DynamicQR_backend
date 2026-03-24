"""Pydantic schemas for QR code API payloads and responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class QRType(str, Enum):
    """Supported QR categories."""

    url = "url"
    event = "event"


class QRCodeStatus(str, Enum):
    """Runtime status for QR serving behavior."""

    active = "active"
    paused = "paused"
    archived = "archived"


class QRCodeBase(BaseModel):
    """Common QR fields shared across create and update payloads."""

    name: str = Field(min_length=1, max_length=255)
    campaign_id: int | None = None
    destination_url: HttpUrl
    qr_type: QRType
    design_config: dict[str, Any] | None = None
    ga_measurement_id: str | None = Field(default=None, max_length=100)
    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    status: QRCodeStatus = QRCodeStatus.active


class QRCodeCreate(QRCodeBase):
    """Payload for creating a dynamic QR code."""


class QRCodeUpdate(BaseModel):
    """Payload for partial QR updates."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    campaign_id: int | None = None
    destination_url: HttpUrl | None = None
    qr_type: QRType | None = None
    design_config: dict[str, Any] | None = None
    ga_measurement_id: str | None = Field(default=None, max_length=100)
    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    status: QRCodeStatus | None = None


class QRCodeRead(QRCodeBase):
    """QR code response model."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    short_code: str = Field(min_length=4, max_length=32)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

