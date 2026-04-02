"""Schemas for OAuth integration workflows and provider credentials."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.campaign import CampaignRead


class IntegrationProvider(str, Enum):
    """Supported third-party integration providers."""

    google_calendar = "google_calendar"
    google_analytics = "google_analytics"


class CalendarRangeType(str, Enum):
    """Supported Google Calendar list window presets."""

    month = "month"
    year = "year"


class OAuthConnectRequest(BaseModel):
    """Client payload requesting an OAuth authorization URL."""

    provider_name: IntegrationProvider
    redirect_uri: HttpUrl | None = None
    state: str | None = Field(default=None, min_length=8, max_length=255)
    scopes: list[str] = Field(default_factory=list)


class OAuthConnectResponse(BaseModel):
    """Authorization URL payload returned to the client."""

    provider_name: IntegrationProvider
    authorization_url: str
    state: str
    redirect_uri: str


class OAuthCallbackRequest(BaseModel):
    """Server-side callback payload for exchanging OAuth authorization codes."""

    provider_name: IntegrationProvider
    code: str = Field(min_length=1)
    state: str | None = Field(default=None, min_length=8, max_length=255)
    redirect_uri: HttpUrl | None = None


class ProviderCredentialWrite(BaseModel):
    """Normalized credential payload persisted for a provider connection."""

    provider_name: IntegrationProvider
    access_token: str = Field(min_length=1)
    refresh_token: str | None = None
    expires_at: datetime | None = None


class ProviderCredentialRecord(BaseModel):
    """Credential row model used between repository and service layers."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider_name: IntegrationProvider
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None


class IntegrationConnectionStatus(BaseModel):
    """Public-safe integration connection state for API responses."""

    provider_name: IntegrationProvider
    connected: bool
    expires_at: datetime | None = None
    has_refresh_token: bool = False


class GoogleCalendarEventListItem(BaseModel):
    """Google Calendar event candidate enriched with campaign sync metadata."""

    google_event_id: str
    title: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    event_status: str = "confirmed"
    linked_campaign_id: int | None = None
    calendar_sync_status: str = "not_linked"
    last_synced_at: datetime | None = None


class GoogleCalendarEventListResponse(BaseModel):
    """List response for month/year Google Calendar event retrieval."""

    range_type: CalendarRangeType
    year: int
    month: int | None = None
    from_month: int | None = None
    to_month: int | None = None
    total: int
    events: list[GoogleCalendarEventListItem]


class CalendarImportCampaignsRequest(BaseModel):
    """Payload for importing selected Google Calendar events as campaigns."""

    range_type: CalendarRangeType
    year: int = Field(ge=1970, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    event_ids: list[str] = Field(min_length=1)


class CalendarImportCampaignsResponse(BaseModel):
    """Result summary for Google event-to-campaign import operation."""

    created_count: int
    updated_count: int
    skipped_count: int
    campaigns: list[CampaignRead]


