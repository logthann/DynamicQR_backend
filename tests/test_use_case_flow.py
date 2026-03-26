"""End-to-end style use-case tests across auth, campaigns, QR, GA4, and Calendar flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.analytics import get_analytics_service
from app.api.v1.campaigns import get_campaign_service, get_current_principal
from app.api.v1.integrations import get_integration_service
from app.api.v1.qr_codes import get_qr_service
from app.core.rbac import Principal
from app.schemas.analytics import AnalyticsSummaryResponse, AnalyticsSummaryRow
from app.schemas.campaign import CampaignRead
from app.schemas.integrations import (
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthConnectResponse,
)
from app.schemas.qr_code import QRCodeRead
from app.services.google_analytics_service import GoogleAnalyticsService


@dataclass
class _FlowState:
    campaign_seq: int = 1
    qr_seq: int = 1
    campaigns: dict[int, CampaignRead] = field(default_factory=dict)
    qrs: dict[int, QRCodeRead] = field(default_factory=dict)
    connected_providers: set[IntegrationProvider] = field(default_factory=set)


class _FlowCampaignService:
    def __init__(self, state: _FlowState) -> None:
        self.state = state

    async def list_campaigns_by_owner(self, principal: Principal, **kwargs) -> list[CampaignRead]:
        return list(self.state.campaigns.values())

    async def get_campaign(self, principal: Principal, campaign_id: int, **kwargs) -> CampaignRead | None:
        return self.state.campaigns.get(campaign_id)

    async def create_campaign(self, principal: Principal, payload, **kwargs) -> CampaignRead:
        now = datetime.now(UTC)
        campaign_id = self.state.campaign_seq
        self.state.campaign_seq += 1
        campaign = CampaignRead(
            id=campaign_id,
            user_id=principal.user_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            status=payload.status,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self.state.campaigns[campaign_id] = campaign
        return campaign

    async def update_campaign(self, principal: Principal, campaign_id: int, payload) -> CampaignRead | None:
        campaign = self.state.campaigns.get(campaign_id)
        if campaign is None:
            return None
        updates = payload.model_dump(exclude_unset=True)
        updated = campaign.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
        self.state.campaigns[campaign_id] = updated
        return updated

    async def delete_campaign(self, principal: Principal, campaign_id: int) -> bool:
        return self.state.campaigns.pop(campaign_id, None) is not None


class _FlowQRService:
    def __init__(self, state: _FlowState) -> None:
        self.state = state

    async def list_qrs_by_owner(self, principal: Principal, **kwargs) -> list[QRCodeRead]:
        return list(self.state.qrs.values())

    async def get_qr(self, principal: Principal, qr_id: int, **kwargs) -> QRCodeRead | None:
        return self.state.qrs.get(qr_id)

    async def create_qr(self, principal: Principal, payload, **kwargs) -> QRCodeRead:
        now = datetime.now(UTC)
        qr_id = self.state.qr_seq
        self.state.qr_seq += 1
        qr = QRCodeRead(
            id=qr_id,
            user_id=principal.user_id,
            campaign_id=payload.campaign_id,
            name=payload.name,
            short_code=f"qr{qr_id:06d}",
            destination_url=str(payload.destination_url),
            qr_type=payload.qr_type,
            design_config=payload.design_config,
            ga_measurement_id=payload.ga_measurement_id,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            status=payload.status,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        self.state.qrs[qr_id] = qr
        return qr

    async def update_qr(self, principal: Principal, qr_id: int, payload) -> QRCodeRead | None:
        qr = self.state.qrs.get(qr_id)
        if qr is None:
            return None
        updates = payload.model_dump(exclude_unset=True)
        if "destination_url" in updates and updates["destination_url"] is not None:
            updates["destination_url"] = str(updates["destination_url"])
        updated = qr.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
        self.state.qrs[qr_id] = updated
        return updated

    async def set_qr_status(self, principal: Principal, qr_id: int, status):
        qr = self.state.qrs.get(qr_id)
        if qr is None:
            return None
        updated = qr.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})
        self.state.qrs[qr_id] = updated
        return updated

    async def delete_qr(self, principal: Principal, qr_id: int) -> bool:
        return self.state.qrs.pop(qr_id, None) is not None


class _FlowIntegrationService:
    def __init__(self, state: _FlowState) -> None:
        self.state = state

    async def list_connection_statuses(self, principal: Principal) -> list[IntegrationConnectionStatus]:
        statuses: list[IntegrationConnectionStatus] = []
        for provider_name in sorted(self.state.connected_providers, key=lambda value: value.value):
            statuses.append(
                IntegrationConnectionStatus(
                    provider_name=provider_name,
                    connected=True,
                    expires_at=None,
                    has_refresh_token=True,
                )
            )
        return statuses

    async def build_connect_url(self, principal: Principal, payload) -> OAuthConnectResponse:
        return OAuthConnectResponse(
            provider_name=payload.provider_name,
            authorization_url=(
                "https://accounts.google.com/o/oauth2/v2/auth?provider="
                f"{payload.provider_name.value}"
            ),
            state=payload.state or "state-token",
        )

    async def handle_callback(self, principal: Principal, payload) -> IntegrationConnectionStatus:
        self.state.connected_providers.add(payload.provider_name)
        return IntegrationConnectionStatus(
            provider_name=payload.provider_name,
            connected=True,
            expires_at=None,
            has_refresh_token=True,
        )

    async def refresh_provider_token(self, principal: Principal, provider_name: IntegrationProvider):
        return IntegrationConnectionStatus(
            provider_name=provider_name,
            connected=provider_name in self.state.connected_providers,
            expires_at=None,
            has_refresh_token=True,
        )

    async def revoke_provider_connection(self, principal: Principal, provider_name: IntegrationProvider) -> bool:
        if provider_name in self.state.connected_providers:
            self.state.connected_providers.remove(provider_name)
            return True
        return False


class _FlowAnalyticsService:
    async def get_qr_summary(self, *, qr_id: int, start_date: date, end_date: date) -> AnalyticsSummaryResponse:
        return AnalyticsSummaryResponse(
            qr_id=qr_id,
            start_date=start_date,
            end_date=end_date,
            total_scans=200,
            unique_visitors=140,
            rows=[
                AnalyticsSummaryRow(summary_date=start_date, total_scans=80, unique_visitors=60),
                AnalyticsSummaryRow(summary_date=end_date, total_scans=120, unique_visitors=80),
            ],
        )


@pytest.mark.asyncio
async def test_admin_flow_auth_campaign_qr_ga4_calendar(app: FastAPI, async_client: AsyncClient) -> None:
    state = _FlowState()
    principal = Principal(user_id=1, role="admin", company_name="DynamicQR")

    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_campaign_service] = lambda: _FlowCampaignService(state)
    app.dependency_overrides[get_qr_service] = lambda: _FlowQRService(state)
    app.dependency_overrides[get_integration_service] = lambda: _FlowIntegrationService(state)
    app.dependency_overrides[get_analytics_service] = lambda: _FlowAnalyticsService()

    try:
        register_response = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@dynamicqr.local",
                "password": "admin-pass-123",
                "role": "admin",
                "company_name": "DynamicQR",
            },
        )
        assert register_response.status_code == 201
        assert register_response.json()["role"] == "admin"

        login_response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@dynamicqr.local", "password": "admin-pass-123"},
        )
        assert login_response.status_code == 200
        assert len(login_response.json()["access_token"]) > 10

        campaign_response = await async_client.post(
            "/api/v1/campaigns/",
            json={
                "name": "Black Friday 2026",
                "description": "Main agency campaign",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
                "status": "active",
            },
        )
        assert campaign_response.status_code == 201
        campaign_id = campaign_response.json()["id"]

        qr_response = await async_client.post(
            "/api/v1/qr/",
            json={
                "name": "Landing Page QR",
                "campaign_id": campaign_id,
                "destination_url": "https://example.com/black-friday",
                "qr_type": "url",
                "design_config": {"fg": "#000000", "bg": "#ffffff"},
                "ga_measurement_id": "G-TEST123",
                "utm_source": "flyer",
                "utm_medium": "offline",
                "utm_campaign": "black-friday-2026",
                "status": "active",
            },
        )
        assert qr_response.status_code == 201
        qr_payload = qr_response.json()
        assert qr_payload["short_code"].startswith("qr")

        event_qr_response = await async_client.post(
            "/api/v1/qr/",
            json={
                "name": "Event QR",
                "campaign_id": campaign_id,
                "destination_url": "https://calendar.google.com/event",
                "qr_type": "event",
                "design_config": {"fg": "#111111"},
                "status": "active",
            },
        )
        assert event_qr_response.status_code == 201
        assert event_qr_response.json()["qr_type"] == "event"

        status_response = await async_client.patch(
            f"/api/v1/qr/{qr_payload['id']}/status",
            json={"status": "paused"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "paused"

        calendar_connect = await async_client.post(
            "/api/v1/integrations/connect",
            json={"provider_name": "google_calendar"},
        )
        assert calendar_connect.status_code == 200

        calendar_callback = await async_client.post(
            "/api/v1/integrations/callback",
            json={"provider_name": "google_calendar", "code": "calendar-auth-code"},
        )
        assert calendar_callback.status_code == 200
        assert calendar_callback.json()["connected"] is True

        ga_callback = await async_client.post(
            "/api/v1/integrations/callback",
            json={"provider_name": "google_analytics", "code": "ga-auth-code"},
        )
        assert ga_callback.status_code == 200

        list_integrations = await async_client.get("/api/v1/integrations/")
        assert list_integrations.status_code == 200
        providers = {item["provider_name"] for item in list_integrations.json()}
        assert providers == {"google_calendar", "google_analytics"}

        enriched_url = GoogleAnalyticsService().enrich_redirect_url(
            destination_url=qr_payload["destination_url"],
            ga_measurement_id=qr_payload["ga_measurement_id"],
            utm_source=qr_payload["utm_source"],
            utm_medium=qr_payload["utm_medium"],
            utm_campaign=qr_payload["utm_campaign"],
        )
        parsed_params = parse_qs(urlparse(enriched_url).query)
        assert parsed_params["ga_measurement_id"] == ["G-TEST123"]
        assert parsed_params["utm_campaign"] == ["black-friday-2026"]

        analytics_response = await async_client.get(
            f"/api/v1/analytics/{qr_payload['id']}?start_date=2026-11-01&end_date=2026-11-02"
        )
        assert analytics_response.status_code == 200
        assert analytics_response.json()["total_scans"] == 200
    finally:
        app.dependency_overrides.clear()

