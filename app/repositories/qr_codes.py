"""Repository helpers for QR code persistence and lookup."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cached_short_code, set_cached_short_code
from app.schemas.redirect import RedirectQRCode


class QRCodeRepository:
    """Access QR records with cache-first short-code lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_by_short_code(self, short_code: str) -> RedirectQRCode | None:
        """Return redirect-safe QR payload by short code using cache-first lookup."""

        cached_payload = await get_cached_short_code(short_code)
        if cached_payload:
            return RedirectQRCode.model_validate(cached_payload)

        payload = await self._fetch_redirect_payload(short_code)
        if payload is None:
            return None

        await set_cached_short_code(short_code, payload)
        return RedirectQRCode.model_validate(payload)

    async def _fetch_redirect_payload(self, short_code: str) -> dict[str, Any] | None:
        """Fetch redirect payload from MySQL when cache is cold or unavailable."""

        statement = text(
            """
            SELECT
                id,
                short_code,
                destination_url,
                status,
                deleted_at,
                ga_measurement_id,
                utm_source,
                utm_medium,
                utm_campaign
            FROM qr_codes
            WHERE short_code = :short_code
            LIMIT 1
            """
        )

        result = await self.session.execute(statement, {"short_code": short_code})
        row = result.mappings().first()
        return dict(row) if row else None

