"""Pydantic schemas for campaign API payloads and responses."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CampaignCalendarSyncStatus(str, Enum):
    """Dashboard-ready synchronization status for campaign calendar linkage."""

    not_linked = "not_linked"
    synced = "synced"
    out_of_sync = "out_of_sync"
    removed = "removed"


class CampaignBase(BaseModel):
    """Common campaign fields shared by create and update flows."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = Field(min_length=1, max_length=50)


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
    google_event_id: str | None = Field(default=None, max_length=255)
    calendar_sync_status: CampaignCalendarSyncStatus | None = None
    calendar_last_synced_at: datetime | None = None
    calendar_sync_hash: str | None = Field(default=None, max_length=128)


class CampaignRead(CampaignBase):
    """Campaign response model."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    google_event_id: str | None = None
    calendar_sync_status: CampaignCalendarSyncStatus = CampaignCalendarSyncStatus.not_linked
    calendar_last_synced_at: datetime | None = None
    calendar_sync_hash: str | None = None

