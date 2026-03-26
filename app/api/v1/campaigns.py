"""Campaign CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Principal, RBACError
from app.db.session import get_db_session
from app.repositories.campaigns import CampaignRepository
from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignUpdate
from app.services.campaign_calendar_sync_service import (
    CampaignCalendarSyncService,
    CampaignCalendarSyncServiceError,
)
from app.services.campaign_service import CampaignService
from app.services.google_calendar_service import GoogleCalendarService, GoogleCalendarServiceError
from app.repositories.user_integrations import UserIntegrationRepository

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


def _resolve_include_deleted(principal: Principal, include_deleted: bool) -> bool:
    """Allow deleted-row visibility only for admin principals."""

    if not include_deleted:
        return False

    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can include deleted campaigns",
        )

    return True


async def get_current_principal(
    x_user_id: int = Header(default=1),
    x_role: str = Header(default="admin"),
    x_company_name: str | None = Header(default=None),
) -> Principal:
    """Build a principal from request headers for temporary auth wiring."""

    role = x_role.strip().lower()
    if role not in {"admin", "agency", "user"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role header")

    return Principal(user_id=x_user_id, role=role, company_name=x_company_name)


async def get_campaign_service(
    session: AsyncSession = Depends(get_db_session),
) -> CampaignService:
    """Provide campaign service dependency."""

    return CampaignService(CampaignRepository(session))


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
    response_model=list[CampaignRead],
    summary="List campaigns",
    description="List campaigns visible to the current principal with RBAC and soft-delete controls.",
    response_description="Campaign list for requested owner scope.",
)
async def list_campaigns(
    owner_user_id: int | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
    principal: Principal = Depends(get_current_principal),
    service: CampaignService = Depends(get_campaign_service),
) -> list[CampaignRead]:
    """List campaigns visible within principal ownership scope."""

    target_owner = owner_user_id if owner_user_id is not None else principal.user_id
    include_deleted_allowed = _resolve_include_deleted(principal, include_deleted)

    try:
        return await service.list_campaigns_by_owner(
            principal,
            owner_user_id=target_owner,
            include_deleted=include_deleted_allowed,
            limit=limit,
            offset=offset,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get(
    "/{campaign_id}",
    response_model=CampaignRead,
    summary="Get campaign",
    description="Get one campaign by id when it is visible in the principal's RBAC scope.",
    response_description="Campaign details.",
)
async def get_campaign(
    campaign_id: int,
    include_deleted: bool = False,
    principal: Principal = Depends(get_current_principal),
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignRead:
    """Get one campaign by id if principal can access it."""

    include_deleted_allowed = _resolve_include_deleted(principal, include_deleted)

    try:
        campaign = await service.get_campaign(
            principal,
            campaign_id,
            include_deleted=include_deleted_allowed,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    return campaign


@router.post(
    "/",
    response_model=CampaignRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create campaign",
    description="Create a campaign for the principal or a delegated owner when permitted.",
    response_description="Created campaign payload.",
)
async def create_campaign(
    payload: CampaignCreate,
    owner_user_id: int | None = None,
    principal: Principal = Depends(get_current_principal),
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignRead:
    """Create a campaign within principal ownership scope."""

    try:
        return await service.create_campaign(
            principal,
            payload,
            owner_user_id=owner_user_id,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch(
    "/{campaign_id}",
    response_model=CampaignRead,
    summary="Update campaign",
    description="Partially update one campaign while preserving RBAC ownership boundaries.",
    response_description="Updated campaign payload.",
)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    principal: Principal = Depends(get_current_principal),
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignRead:
    """Partially update a campaign in principal ownership scope."""

    try:
        campaign = await service.update_campaign(principal, campaign_id, payload)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    return campaign


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete campaign",
    description="Soft-delete one campaign by setting deleted_at timestamp.",
    response_description="Campaign soft-deleted successfully.",
)
async def delete_campaign(
    campaign_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CampaignService = Depends(get_campaign_service),
) -> Response:
    """Soft-delete a campaign in principal ownership scope."""

    try:
        deleted = await service.delete_campaign(principal, campaign_id)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{campaign_id}/calendar/sync",
    response_model=CampaignRead,
    summary="Sync campaign to Google Calendar",
    description="Create or update linked Google Calendar event for one campaign and persist sync metadata.",
    response_description="Campaign with refreshed calendar sync fields.",
)
async def sync_campaign_to_calendar(
    campaign_id: int,
    principal: Principal = Depends(get_current_principal),
    campaign_service: CampaignService = Depends(get_campaign_service),
    sync_service: CampaignCalendarSyncService = Depends(get_campaign_calendar_sync_service),
) -> CampaignRead:
    """Push one campaign to Google Calendar and update sync metadata."""

    try:
        campaign = await campaign_service.get_campaign(principal, campaign_id)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    try:
        return await sync_service.sync_campaign_to_calendar(user_id=principal.user_id, campaign=campaign)
    except (CampaignCalendarSyncServiceError, GoogleCalendarServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/{campaign_id}/calendar/link",
    response_model=CampaignRead,
    summary="Remove campaign from Google Calendar",
    description="Delete linked Google Calendar event and mark local campaign calendar status as removed.",
    response_description="Campaign with cleared calendar link metadata.",
)
async def remove_campaign_calendar_link(
    campaign_id: int,
    principal: Principal = Depends(get_current_principal),
    campaign_service: CampaignService = Depends(get_campaign_service),
    sync_service: CampaignCalendarSyncService = Depends(get_campaign_calendar_sync_service),
) -> CampaignRead:
    """Unlink one campaign from Google Calendar by deleting the remote event."""

    try:
        campaign = await campaign_service.get_campaign(principal, campaign_id)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    try:
        return await sync_service.remove_campaign_from_calendar(
            user_id=principal.user_id,
            campaign=campaign,
        )
    except (CampaignCalendarSyncServiceError, GoogleCalendarServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


