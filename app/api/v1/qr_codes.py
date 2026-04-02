"""QR code CRUD and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.campaigns import get_current_principal
from app.core.rbac import Principal, RBACError
from app.db.session import get_db_session
from app.repositories.qr_codes import QRCodeRepository
from app.schemas.qr_code import QRCodeCreate, QRCodeRead, QRCodeStatus, QRCodeUpdate
from app.services.qr_service import QRService

router = APIRouter(prefix="/api/v1/qr", tags=["qr-codes"])


def _resolve_include_deleted(principal: Principal, include_deleted: bool) -> bool:
    """Allow deleted-row visibility only for admin principals."""

    if not include_deleted:
        return False

    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can include deleted QR codes",
        )

    return True


class QRStatusUpdateRequest(BaseModel):
    """Request payload for status-only updates."""

    status: QRCodeStatus


async def get_qr_service(
    session: AsyncSession = Depends(get_db_session),
) -> QRService:
    """Provide QR service dependency."""

    return QRService(QRCodeRepository(session))


@router.get(
    "",
    response_model=list[QRCodeRead],
    summary="List QR codes",
    description="List QR codes by owner/campaign/status with RBAC and soft-delete-aware filtering.",
    response_description="QR code list.",
)
@router.get(
    "/",
    include_in_schema=False,
)
async def list_qr_codes(
    owner_user_id: int | None = None,
    campaign_id: int | None = None,
    status_filter: QRCodeStatus | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
    principal: Principal = Depends(get_current_principal),
    service: QRService = Depends(get_qr_service),
) -> list[QRCodeRead]:
    """List QR codes visible within principal ownership scope."""

    target_owner = owner_user_id if owner_user_id is not None else principal.user_id
    include_deleted_allowed = _resolve_include_deleted(principal, include_deleted)

    try:
        return await service.list_qrs_by_owner(
            principal,
            owner_user_id=target_owner,
            campaign_id=campaign_id,
            status=status_filter,
            include_deleted=include_deleted_allowed,
            limit=limit,
            offset=offset,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get(
    "/{qr_id}",
    response_model=QRCodeRead,
    summary="Get QR code",
    description="Get one QR code by id if it is visible in the principal RBAC scope.",
    response_description="QR code details.",
)
async def get_qr_code(
    qr_id: int,
    include_deleted: bool = False,
    principal: Principal = Depends(get_current_principal),
    service: QRService = Depends(get_qr_service),
) -> QRCodeRead:
    """Get one QR code if principal can access it."""

    include_deleted_allowed = _resolve_include_deleted(principal, include_deleted)

    try:
        qr_code = await service.get_qr(principal, qr_id, include_deleted=include_deleted_allowed)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if qr_code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QR code not found")

    return qr_code


@router.post(
    "",
    response_model=QRCodeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create QR code",
    description="Create URL or event QR code with generated Base62 short code.",
    response_description="Created QR code payload.",
)
@router.post(
    "/",
    response_model=QRCodeRead,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_qr_code(
    payload: QRCodeCreate,
    owner_user_id: int | None = None,
    principal: Principal = Depends(get_current_principal),
    service: QRService = Depends(get_qr_service),
) -> QRCodeRead:
    """Create a QR code within principal ownership scope."""

    try:
        return await service.create_qr(
            principal,
            payload,
            owner_user_id=owner_user_id,
        )
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch(
    "/{qr_id}",
    response_model=QRCodeRead,
    summary="Update QR code",
    description="Partially update QR fields such as destination and campaign linkage.",
    response_description="Updated QR code payload.",
)
async def update_qr_code(
    qr_id: int,
    payload: QRCodeUpdate,
    principal: Principal = Depends(get_current_principal),
    service: QRService = Depends(get_qr_service),
) -> QRCodeRead:
    """Partially update a QR code in principal ownership scope."""

    try:
        qr_code = await service.update_qr(principal, qr_id, payload)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if qr_code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QR code not found")

    return qr_code


@router.patch(
    "/{qr_id}/status",
    response_model=QRCodeRead,
    summary="Update QR status",
    description="Change QR runtime status (active, paused, archived).",
    response_description="Updated QR code status payload.",
)
async def update_qr_status(
    qr_id: int,
    payload: QRStatusUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    service: QRService = Depends(get_qr_service),
) -> QRCodeRead:
    """Update only status field for one QR code."""

    try:
        qr_code = await service.set_qr_status(principal, qr_id, payload.status)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if qr_code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QR code not found")

    return qr_code


@router.delete(
    "/{qr_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete QR code",
    description="Soft-delete one QR code by setting deleted_at timestamp.",
    response_description="QR code soft-deleted successfully.",
)
async def delete_qr_code(
    qr_id: int,
    principal: Principal = Depends(get_current_principal),
    service: QRService = Depends(get_qr_service),
) -> Response:
    """Soft-delete a QR code in principal ownership scope."""

    try:
        deleted = await service.delete_qr(principal, qr_id)
    except RBACError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QR code not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)

