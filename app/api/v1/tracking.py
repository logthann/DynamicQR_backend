"""Internal tracking endpoints protected by service JWT authentication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.security import decode_service_token

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])
service_bearer = HTTPBearer(auto_error=False)


class TrackingEventRequest(BaseModel):
    """Incoming internal tracking payload for GA/analytics forwarding."""

    campaign_id: int = Field(gt=0)
    qr_id: int = Field(gt=0)
    ga_measurement_id: str = Field(min_length=4, max_length=100)
    event_name: str = Field(min_length=1, max_length=100)
    event_params: dict[str, Any] = Field(default_factory=dict)


class TrackingEventResponse(BaseModel):
    """Acknowledgement payload for accepted internal tracking events."""

    accepted: bool
    received_at: datetime
    event_name: str


def _require_service_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(service_bearer),
) -> dict[str, Any]:
    """Require a valid internal service JWT token."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Service authentication required")

    try:
        return decode_service_token(credentials.credentials)
    except Exception as exc:  # pragma: no cover - concrete JWT errors are library-specific
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid service token") from exc


@router.post(
    "/event",
    response_model=TrackingEventResponse,
    summary="Ingest internal tracking event",
    description="Internal-only endpoint for service calls that forward scan/redirect events.",
    response_description="Tracking event accepted acknowledgement.",
)
async def ingest_tracking_event(
    payload: TrackingEventRequest,
    _: dict[str, Any] = Security(_require_service_auth),
) -> TrackingEventResponse:
    """Accept internal tracking events after service JWT validation."""

    return TrackingEventResponse(
        accepted=True,
        received_at=datetime.now(UTC),
        event_name=payload.event_name,
    )

