"""Repository helpers for QR code persistence and lookup."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    get_cached_short_code,
    invalidate_short_code_cache,
    set_cached_short_code,
)
from app.schemas.qr_code import QRCodeCreate, QRCodeRead, QRCodeStatus, QRCodeUpdate
from app.schemas.redirect import RedirectQRCode


class QRCodeRepository:
    """Access QR records with cache-first short-code lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, qr_id: int, *, include_deleted: bool = False) -> QRCodeRead | None:
        """Fetch one QR code by id with optional soft-deleted visibility."""

        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        statement = text(
            f"""
            SELECT
                id,
                user_id,
                campaign_id,
                name,
                short_code,
                destination_url,
                qr_type,
                design_config,
                ga_measurement_id,
                utm_source,
                utm_medium,
                utm_campaign,
                status,
                created_at,
                updated_at,
                deleted_at
            FROM qr_codes
            WHERE id = :qr_id
            {deleted_filter}
            LIMIT 1
            """
        )

        result = await self.session.execute(statement, {"qr_id": qr_id})
        row = result.mappings().first()
        return QRCodeRead.model_validate(dict(row)) if row else None

    async def list_by_user(
        self,
        user_id: int,
        *,
        campaign_id: int | None = None,
        status: QRCodeStatus | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[QRCodeRead]:
        """List QR codes for one user with campaign/status filters."""

        filters: list[str] = ["user_id = :user_id"]
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        }

        if campaign_id is not None:
            filters.append("campaign_id = :campaign_id")
            params["campaign_id"] = campaign_id

        if status is not None:
            filters.append("status = :status")
            params["status"] = status.value

        if not include_deleted:
            filters.append("deleted_at IS NULL")

        where_clause = " AND ".join(filters)
        statement = text(
            f"""
            SELECT
                id,
                user_id,
                campaign_id,
                name,
                short_code,
                destination_url,
                qr_type,
                design_config,
                ga_measurement_id,
                utm_source,
                utm_medium,
                utm_campaign,
                status,
                created_at,
                updated_at,
                deleted_at
            FROM qr_codes
            WHERE {where_clause}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """
        )

        result = await self.session.execute(statement, params)
        return [QRCodeRead.model_validate(dict(row)) for row in result.mappings().all()]

    async def get_campaign_owner_user_id(self, campaign_id: int) -> int | None:
        """Return campaign owner id for access checks, or None if campaign is unavailable."""

        statement = text(
            """
            SELECT user_id
            FROM campaigns
            WHERE id = :campaign_id
              AND deleted_at IS NULL
            LIMIT 1
            """
        )
        result = await self.session.execute(statement, {"campaign_id": campaign_id})
        row = result.mappings().first()
        if row is None:
            return None
        return int(row["user_id"])

    async def create(self, user_id: int, short_code: str, payload: QRCodeCreate) -> QRCodeRead:
        """Insert one QR code linked to user/campaign and return created row."""

        statement = text(
            """
            INSERT INTO qr_codes (
                user_id,
                campaign_id,
                name,
                short_code,
                destination_url,
                qr_type,
                design_config,
                ga_measurement_id,
                utm_source,
                utm_medium,
                utm_campaign,
                status,
                created_at,
                updated_at
            ) VALUES (
                :user_id,
                :campaign_id,
                :name,
                :short_code,
                :destination_url,
                :qr_type,
                :design_config,
                :ga_measurement_id,
                :utm_source,
                :utm_medium,
                :utm_campaign,
                :status,
                UTC_TIMESTAMP(),
                UTC_TIMESTAMP()
            )
            """
        )

        result = await self.session.execute(
            statement,
            {
                "user_id": user_id,
                "campaign_id": payload.campaign_id,
                "name": payload.name,
                "short_code": short_code,
                "destination_url": str(payload.destination_url),
                "qr_type": payload.qr_type.value,
                "design_config": payload.design_config,
                "ga_measurement_id": payload.ga_measurement_id,
                "utm_source": payload.utm_source,
                "utm_medium": payload.utm_medium,
                "utm_campaign": payload.utm_campaign,
                "status": payload.status.value,
            },
        )
        await self.session.flush()

        created = await self.get_by_id(int(result.lastrowid), include_deleted=True)
        if created is None:
            raise RuntimeError("Failed to read QR code after create")

        return created

    async def update(self, qr_id: int, payload: QRCodeUpdate) -> QRCodeRead | None:
        """Update mutable QR fields and return updated row."""

        data = payload.model_dump(exclude_none=True)
        if not data:
            return await self.get_by_id(qr_id)

        if "destination_url" in data:
            data["destination_url"] = str(data["destination_url"])
        if "qr_type" in data:
            data["qr_type"] = data["qr_type"].value
        if "status" in data:
            data["status"] = data["status"].value

        assignments = ", ".join(f"{field} = :{field}" for field in data)
        statement = text(
            f"""
            UPDATE qr_codes
            SET {assignments},
                updated_at = UTC_TIMESTAMP()
            WHERE id = :qr_id
              AND deleted_at IS NULL
            """
        )

        await self.session.execute(statement, {"qr_id": qr_id, **data})
        await self.session.flush()

        updated = await self.get_by_id(qr_id)
        if updated is not None:
            await invalidate_short_code_cache(updated.short_code)
        return updated

    async def set_status(self, qr_id: int, status: QRCodeStatus) -> QRCodeRead | None:
        """Set QR status (active/paused/archived) and return updated row."""

        statement = text(
            """
            UPDATE qr_codes
            SET status = :status,
                updated_at = UTC_TIMESTAMP()
            WHERE id = :qr_id
              AND deleted_at IS NULL
            """
        )
        await self.session.execute(statement, {"qr_id": qr_id, "status": status.value})
        await self.session.flush()

        updated = await self.get_by_id(qr_id)
        if updated is not None:
            await invalidate_short_code_cache(updated.short_code)
        return updated

    async def soft_delete(self, qr_id: int) -> bool:
        """Soft-delete a QR code row by setting `deleted_at` timestamp."""

        current = await self.get_by_id(qr_id)

        statement = text(
            """
            UPDATE qr_codes
            SET deleted_at = UTC_TIMESTAMP(),
                updated_at = UTC_TIMESTAMP()
            WHERE id = :qr_id
              AND deleted_at IS NULL
            """
        )
        result = await self.session.execute(statement, {"qr_id": qr_id})
        await self.session.flush()

        changed = (result.rowcount or 0) > 0
        if changed and current is not None:
            await invalidate_short_code_cache(current.short_code)

        return changed

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

