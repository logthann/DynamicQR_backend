"""OAuth integration endpoints for Google provider connections."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
import re
import time
from typing import Deque
from urllib.parse import urlparse

import httpx
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
    GADetectResponse,
    GAPropertiesResponse,
    IntegrationConnectionStatus,
    IntegrationSessionSyncResponse,
    IntegrationProvider,
    OAuthCallbackRequest,
    OAuthConnectRequest,
    OAuthConnectResponse,
)
from app.schemas.common import ApiErrorResponse
from app.repositories.campaigns import CampaignRepository
from app.services.campaign_calendar_sync_service import (
    CampaignCalendarSyncService,
    CampaignCalendarSyncServiceError,
)
from app.services.google_calendar_service import GoogleCalendarService, GoogleCalendarServiceError
from app.services.integration_service import IntegrationService, IntegrationServiceError

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])
ga4_router = APIRouter(prefix="/api/v1/ga4", tags=["ga4"])

GA_MEASUREMENT_ID_PATTERN = re.compile(r"\bG-[A-Z0-9]{4,20}\b")
DETECT_RATE_LIMIT = 5
DETECT_RATE_WINDOW_SECONDS = 60
_detect_rate_limit_buckets: dict[int, Deque[float]] = defaultdict(deque)


def _error_payload(code: str, message: str, details: dict[str, str] | None = None) -> dict[str, object]:
    return {"code": code, "message": message, "details": details}


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _enforce_detect_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    bucket = _detect_rate_limit_buckets[user_id]
    window_start = now - DETECT_RATE_WINDOW_SECONDS

    while bucket and bucket[0] < window_start:
        bucket.popleft()

    if len(bucket) >= DETECT_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_error_payload(
                code="RATE_LIMITED",
                message="Too many detect requests. Please retry later.",
            ),
        )

    bucket.append(now)


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
    "",
    include_in_schema=False,
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
    "/session-sync",
    response_model=IntegrationSessionSyncResponse,
    summary="Sync integration statuses for session startup",
    description=(
        "Frontend bootstrap helper: returns provider statuses and can silently refresh "
        "expiring tokens to avoid forcing users through OAuth reconnect on every login."
    ),
    response_description="Connection statuses enriched with refresh/re-auth hints.",
)
async def sync_integrations_for_session(
    refresh_if_expiring: bool = Query(default=True),
    refresh_window_seconds: int = Query(default=900, ge=0, le=86400),
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> IntegrationSessionSyncResponse:
    """Return integration statuses for login bootstrap with optional silent refresh."""

    checked_at = datetime.now(UTC)
    statuses = await service.sync_connection_statuses(
        principal,
        refresh_if_expiring=refresh_if_expiring,
        refresh_window_seconds=refresh_window_seconds,
    )
    return IntegrationSessionSyncResponse(
        checked_at=checked_at,
        refresh_if_expiring=refresh_if_expiring,
        refresh_window_seconds=refresh_window_seconds,
        items=statuses,
    )


@router.get(
    "/google-calendar/events",
    response_model=GoogleCalendarEventListResponse,
    summary="List Google Calendar events",
    description="List Google Calendar events for a selected month, month range, or year and include campaign sync status metadata.",
    response_description="Calendar event candidates enriched with local campaign linkage status.",
)
async def list_google_calendar_events(
    range_type: CalendarRangeType = Query(default=CalendarRangeType.month),
    year: int = Query(ge=1970, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    from_month: int | None = Query(default=None, ge=1, le=12),
    to_month: int | None = Query(default=None, ge=1, le=12),
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
            from_month=from_month,
            to_month=to_month,
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


@ga4_router.get(
    "/properties",
    response_model=GAPropertiesResponse,
    summary="List GA4 properties",
    description="Returns GA4 properties visible to current user when analytics scope is granted.",
    response_description="Accessible GA4 property list.",
    responses={
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
    },
)
async def list_ga4_properties(
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> GAPropertiesResponse:
    """Return GA4 properties for users with analytics scope permission."""

    try:
        return await service.list_ga4_properties(principal)
    except IntegrationServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_payload(code="GA4_PROPERTIES_ERROR", message=str(exc)),
        ) from exc


@ga4_router.get(
    "/detect",
    response_model=GADetectResponse,
    summary="Detect GA measurement id",
    description="Detect GA measurement id by scanning target URL HTML.",
    response_description="Detected GA measurement id with confidence metadata.",
    responses={
        400: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        429: {"model": ApiErrorResponse},
        504: {"model": ApiErrorResponse},
    },
)
async def detect_ga_measurement_id(
    url: str = Query(min_length=8, max_length=2048),
    principal: Principal = Depends(get_current_principal),
    service: IntegrationService = Depends(get_integration_service),
) -> GADetectResponse:
    """Detect GA measurement id with per-user rate limiting and structured errors."""

    try:
        await service.ensure_analytics_scope(principal)
    except IntegrationServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error_payload(code="MISSING_SCOPE", message=str(exc)),
        ) from exc

    _enforce_detect_rate_limit(principal.user_id)

    if not _is_valid_http_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_payload(code="INVALID_URL", message="URL must be a valid http/https address."),
        )

    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=_error_payload(code="DETECT_TIMEOUT", message="Timed out while scanning target URL."),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error_payload(code="DETECT_UNREACHABLE", message="Target URL is unreachable or invalid."),
        ) from exc

    match = GA_MEASUREMENT_ID_PATTERN.search(response.text.upper())
    return GADetectResponse(
        url=url,
        ga_measurement_id=match.group(0) if match else None,
        confidence="high" if match else "low",
        source="html_scan" if match else "not_found",
    )


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
    description=(
        "Canonical callback flow: frontend receives provider redirect, then POSTs code/state "
        "to this endpoint to exchange authorization code and store encrypted provider tokens."
    ),
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


@router.get(
    "/callback",
    response_model=IntegrationConnectionStatus,
    deprecated=True,
    summary="Handle OAuth callback (direct redirect)",
    description=(
        "Compatibility fallback for provider direct GET redirects. "
        "Primary flow should use frontend callback and POST /integrations/callback."
    ),
    response_description="Updated provider connection status.",
)
async def callback_provider_get(
    code: str | None = Query(default=None, min_length=1),
    state: str | None = Query(default=None, min_length=8, max_length=255),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    redirect_uri: str | None = Query(default=None),
    service: IntegrationService = Depends(get_integration_service),
) -> IntegrationConnectionStatus:
    """Support Google direct callback redirects to backend to avoid 405 on GET."""

    if error:
        detail = error_description or error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth provider error: {detail}")
    if code is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code")
    if state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth state")

    try:
        provider_name, user_id = service.parse_oauth_state(state)
        principal = Principal(user_id=user_id, role="employee")
        payload = OAuthCallbackRequest(
            provider_name=provider_name,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
        )
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

