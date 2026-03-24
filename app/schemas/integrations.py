"""Schemas for OAuth integration workflows and provider credentials."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class IntegrationProvider(str, Enum):
    """Supported third-party integration providers."""

    google_calendar = "google_calendar"
    google_analytics = "google_analytics"


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

