"""Pydantic schemas for campaign API payloads and responses."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CampaignCalendarSyncStatus(str, Enum):
    """Dashboard-ready synchronization status for campaign calendar linkage."""

    not_linked = "not_linked"
    synced = "synced"
    out_of_sync = "out_of_sync"
    removed = "removed"


class GATrackingType(str, Enum):
    """Tracking strategy for campaign/QR GA configuration."""

    oauth = "OAUTH"
    manual = "MANUAL"
    no = "NO"


class CampaignCreatorInfo(BaseModel):
    """Creator information for campaign (admin view only)."""

    username: str | None = None
    email: str


class CampaignBase(BaseModel):
    """Common campaign fields shared by create and update flows."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = Field(min_length=1, max_length=50)
    ga_type: GATrackingType | None = None
    ga_measurement_id: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("ga_measurement_id", "ga4_measurement_id"),
    )
    ga_property_id: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("ga_property_id", "ga4_property_id"),
    )


class CampaignCreate(CampaignBase):
    """Payload for creating a campaign."""


class CampaignUpdate(BaseModel):
    """Payload for partial campaign updates."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=50)
    ga_type: GATrackingType | None = None
    ga_measurement_id: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("ga_measurement_id", "ga4_measurement_id"),
    )
    ga_property_id: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("ga_property_id", "ga4_property_id"),
    )
    google_event_id: str | None = Field(default=None, max_length=255)
    calendar_sync_status: CampaignCalendarSyncStatus | None = None
    calendar_last_synced_at: datetime | None = None
    calendar_sync_hash: str | None = Field(default=None, max_length=128)


class CampaignRead(CampaignBase):
    """Campaign response model."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    creator: CampaignCreatorInfo | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    ga_type: GATrackingType | None = None
    ga_measurement_id: str | None = None
    ga_property_id: str | None = None
    google_event_id: str | None = None
    calendar_sync_status: CampaignCalendarSyncStatus = CampaignCalendarSyncStatus.not_linked
    calendar_last_synced_at: datetime | None = None
    calendar_sync_hash: str | None = None

