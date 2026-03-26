"""OAuth integration endpoints for Google provider connections."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.campaigns import get_current_principal
from app.core.rbac import Principal
from app.db.session import get_db_session
from app.repositories.user_integrations import UserIntegrationRepository
from app.schemas.integrations import (
    CalendarImportCampaignsRequest,
    CalendarImportCampaignsResponse,
    CalendarRangeType,
    GoogleCalendarEventListResponse,
    IntegrationConnectionStatus,
    IntegrationProvider,
    OAuthCallbackRequest,
    OAuthConnectRequest,
    OAuthConnectResponse,
)
from app.repositories.campaigns import CampaignRepository
from app.services.campaign_calendar_sync_service import (
    CampaignCalendarSyncService,
    CampaignCalendarSyncServiceError,
)
from app.services.google_calendar_service import GoogleCalendarService, GoogleCalendarServiceError
from app.services.integration_service import IntegrationService, IntegrationServiceError

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


async def get_integration_service(
    session: AsyncSession = Depends(get_db_session),
) -> IntegrationService:
    """Provide integration service dependency."""

    return IntegrationService(UserIntegrationRepository(session))


async def get_google_calendar_service(
    session: AsyncSession = Depends(get_db_session),
) -> GoogleCalendarService:
    """Provide Google Calendar service dependency."""

    return GoogleCalendarService(session, UserIntegrationRepository(session))


async def get_campaign_calendar_sync_service(
    session: AsyncSession = Depends(get_db_session),
) -> CampaignCalendarSyncService:
    """Provide campaign calendar sync service dependency."""

    return CampaignCalendarSyncService(
        CampaignRepository(session),
        GoogleCalendarService(session, UserIntegrationRepository(session)),
    )


@router.get(
    "/",
    response_model=list[IntegrationConnectionStatus],
    summary="List integrations",
    description="List connected OAuth providers and token-expiry status for the current user.",
    response_description="Connected provider statuses.",
)
async def list_integrations(
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> list[IntegrationConnectionStatus]:
    """List connected providers for the current principal."""

    return await service.list_connection_statuses(principal)


@router.get(
    "/google-calendar/events",
    response_model=GoogleCalendarEventListResponse,
    summary="List Google Calendar events",
    description="List Google Calendar events for a selected month or year and include campaign sync status metadata.",
    response_description="Calendar event candidates enriched with local campaign linkage status.",
)
async def list_google_calendar_events(
    range_type: CalendarRangeType = Query(default=CalendarRangeType.month),
    year: int = Query(ge=1970, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    principal: Principal = Depends(get_current_principal),
    service: GoogleCalendarService = Depends(get_google_calendar_service),
) -> GoogleCalendarEventListResponse:
    """Return Google Calendar event list for month/year windows for the current user."""

    try:
        return await service.list_events_by_period(
            user_id=principal.user_id,
            range_type=range_type,
            year=year,
            month=month,
        )
    except GoogleCalendarServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/google-calendar/import-campaigns",
    response_model=CalendarImportCampaignsResponse,
    summary="Import selected events as campaigns",
    description="Import selected Google Calendar events from a month/year window into campaigns with idempotent linkage by google_event_id.",
    response_description="Import summary including created/updated/skipped counts.",
)
async def import_google_calendar_events_as_campaigns(
    payload: CalendarImportCampaignsRequest,
    principal: Principal = Depends(get_current_principal),
    service: CampaignCalendarSyncService = Depends(get_campaign_calendar_sync_service),
) -> CalendarImportCampaignsResponse:
    """Create or update campaigns from selected Google Calendar event ids."""

    try:
        return await service.import_selected_events(principal, payload)
    except (CampaignCalendarSyncServiceError, GoogleCalendarServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/connect",
    response_model=OAuthConnectResponse,
    summary="Start OAuth connect",
    description="Build a provider authorization URL for OAuth consent flow.",
    response_description="Authorization URL and state token.",
)
async def connect_provider(
    payload: OAuthConnectRequest,
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> OAuthConnectResponse:
    """Build provider authorization URL for OAuth connect flow."""

    try:
        return await service.build_connect_url(principal, payload)
    except IntegrationServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/callback",
    response_model=IntegrationConnectionStatus,
    summary="Handle OAuth callback",
    description="Exchange authorization code and store encrypted provider tokens.",
    response_description="Updated provider connection status.",
)
async def callback_provider(
    payload: OAuthCallbackRequest,
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> IntegrationConnectionStatus:
    """Exchange OAuth code and persist encrypted provider credentials."""

    try:
        return await service.handle_callback(principal, payload)
    except IntegrationServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{provider_name}/refresh",
    response_model=IntegrationConnectionStatus,
    summary="Refresh provider token",
    description="Refresh stored OAuth token using provider refresh token and persist rotation.",
    response_description="Updated provider connection status.",
)
async def refresh_provider(
    provider_name: IntegrationProvider,
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> IntegrationConnectionStatus:
    """Refresh OAuth provider tokens and persist encrypted rotation results."""

    try:
        return await service.refresh_provider_token(principal, provider_name)
    except IntegrationServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/{provider_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect provider",
    description="Remove stored credentials for a provider integration.",
    response_description="Integration disconnected successfully.",
)
async def revoke_provider(
    provider_name: IntegrationProvider,
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> Response:
    """Disconnect provider integration for the principal."""

    deleted = await service.revoke_provider_connection(principal, provider_name)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)

