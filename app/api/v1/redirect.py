"""Public redirect endpoint for dynamic QR short codes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.qr_codes import QRCodeRepository
from app.schemas.redirect import QRCodeStatus
from app.services.redirect_service import build_redirect_url
from app.services.scan_enqueue_service import enqueue_scan_log
from app.services.scan_metadata_service import extract_scan_metadata

router = APIRouter(tags=["redirect"])
logger = logging.getLogger(__name__)


async def get_qr_code_repository(
    session: AsyncSession = Depends(get_db_session),
) -> QRCodeRepository:
    """Provide QR repository dependency for redirect flows."""

    return QRCodeRepository(session)


@router.get(
    "/q/{short_code}",
    summary="Resolve QR short code and redirect",
    description=(
        "Resolve an active short code to its destination, enrich with UTM parameters, "
        "and return an HTTP 302 redirect."
    ),
    status_code=status.HTTP_302_FOUND,
    responses={
        302: {"description": "Redirect to resolved destination URL."},
        404: {"description": "Short code is not found."},
        410: {"description": "Short code is inactive or soft-deleted."},
    },
)
async def redirect_by_short_code(
    request: Request,
    short_code: str,
    repository: QRCodeRepository = Depends(get_qr_code_repository),
) -> RedirectResponse:
    """Return an HTTP 302 redirect for a known short code."""

    qr_code = await repository.resolve_by_short_code(short_code)
    if qr_code is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="QR code not found",
        )

    if qr_code.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="QR code has been deleted",
        )

    if qr_code.status is not QRCodeStatus.active:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="QR code is inactive",
        )

    scan_metadata = extract_scan_metadata(request)
    try:
        await enqueue_scan_log(qr_id=qr_code.id, scan_metadata=scan_metadata)
    except RuntimeError:
        # Keep redirect UX resilient, but log enqueue failures for ops visibility.
        logger.exception("Failed to enqueue scan log for qr_id=%s", qr_code.id)

    redirect_url = build_redirect_url(qr_code)
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

