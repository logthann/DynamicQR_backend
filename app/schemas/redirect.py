"""Schemas for redirect resolution and scan metadata capture."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class QRCodeStatus(str, Enum):
    """Allowed runtime states for redirectable QR codes."""

    active = "active"
    paused = "paused"
    archived = "archived"


class RedirectQRCode(BaseModel):
    """Minimal QR data required to resolve a redirect target."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Database ID of the QR code")
    short_code: str = Field(min_length=4, max_length=32, description="Base62 short code")
    destination_url: str = Field(description="Final URL before UTM enrichment")
    status: QRCodeStatus = Field(description="Current QR status")
    deleted_at: datetime | None = Field(
        default=None,
        description="Soft-delete marker; non-null means redirect should be blocked",
    )
    ga_measurement_id: str | None = Field(
        default=None,
        description="Optional GA4 measurement ID",
    )
    utm_source: str | None = Field(default=None)
    utm_medium: str | None = Field(default=None)
    utm_campaign: str | None = Field(default=None)


class RedirectScanMetadata(BaseModel):
    """Normalized scan attributes captured from the inbound request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scanned_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the scan reached the redirect endpoint",
    )
    ip_address: str | None = Field(default=None, max_length=45)
    user_agent: str | None = Field(default=None)
    device_type: str | None = Field(default=None, max_length=100)
    os: str | None = Field(default=None, max_length=100)
    browser: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    referer: str | None = Field(default=None)


class RedirectContext(BaseModel):
    """Combined redirect and scan payload used by endpoint/service code."""

    qr_code: RedirectQRCode
    scan: RedirectScanMetadata


class ScanLogEnqueueMessage(BaseModel):
    """Queue message payload for durable scan log persistence."""

    qr_id: int
    scan: RedirectScanMetadata

