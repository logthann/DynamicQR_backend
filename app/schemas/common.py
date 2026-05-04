"""Shared API response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ApiErrorResponse(BaseModel):
    """Standardized API error envelope."""

    code: str
    message: str
    details: dict[str, str] | None = None

