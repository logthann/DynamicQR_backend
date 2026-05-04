"""Repository helpers for QR code persistence and lookup."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    get_cached_short_code,
    invalidate_short_code_cache,
    set_cached_short_code,
)
from app.schemas.qr_code import QRCodeCreate, QRCodeListItem, QRCodeRead, QRCodeStatus, QRCodeUpdate
from app.schemas.redirect import RedirectQRCode


class QRCodeRepository:
    """Access QR records with cache-first short-code lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _serialize_design_config(self, value: Any) -> str | None:
        """Serialize JSON payload for raw SQL text statements.

        asyncmy can fail to bind dict objects directly when using textual SQL,
        so we serialize explicitly to valid JSON text.
        """

        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=True)

    def _normalize_qr_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize DB row payload into schema-friendly Python values."""

        design_config = row.get("design_config")
        if isinstance(design_config, str):
            try:
                parsed = json.loads(design_config)
                row["design_config"] = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                row["design_config"] = {}
        return row

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
                ga_type,
                ga_measurement_id,
                ga_property_id,
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
        if not row:
            return None
        return QRCodeRead.model_validate(self._normalize_qr_row(dict(row)))

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
                ga_type,
                ga_measurement_id,
                ga_property_id,
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
        return [QRCodeRead.model_validate(self._normalize_qr_row(dict(row))) for row in result.mappings().all()]

    async def list_by_user_with_joins(
        self,
        user_id: int,
        *,
        campaign_id: int | None = None,
        status: QRCodeStatus | None = None,
        include_deleted: bool = False,
        include_employee: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[QRCodeListItem]:
        """List QR codes with campaign info and optional employee info via joins."""

        filters: list[str] = ["q.user_id = :user_id"]
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        }

        if campaign_id is not None:
            filters.append("q.campaign_id = :campaign_id")
            params["campaign_id"] = campaign_id

        if status is not None:
            filters.append("q.status = :status")
            params["status"] = status.value

        if not include_deleted:
            filters.append("q.deleted_at IS NULL")

        where_clause = " AND ".join(filters)

        # Select employee fields only if include_employee is True
        employee_fields = "u.username AS employee_username, u.email AS employee_email," if include_employee else ""
        employee_join = "LEFT JOIN users u ON q.user_id = u.id" if include_employee else ""

        # Log for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"[QR List] user_id={user_id}, include_employee={include_employee}, include_deleted={include_deleted}, limit={limit}, offset={offset}")

        statement = text(
            f"""
            SELECT
                q.id,
                q.user_id,
                q.short_code,
                q.name,
                q.destination_url,
                q.qr_type,
                q.design_config,
                q.ga_type,
                q.ga_measurement_id,
                q.ga_property_id,
                q.utm_source,
                q.utm_medium,
                q.utm_campaign,
                q.status,
                q.created_at,
                q.updated_at,
                q.deleted_at,
                c.id AS campaign_real_id,
                c.name AS campaign_name,
                c.description AS campaign_description,
                {employee_fields}
                q.campaign_id
            FROM qr_codes q
            LEFT JOIN campaigns c ON q.campaign_id = c.id
            {employee_join}
            WHERE {where_clause}
            ORDER BY q.id DESC
            LIMIT :limit OFFSET :offset
            """
        )

        sql_str = str(statement) % params
        logger.warning(f"[QR List] SQL: {sql_str}")

        result = await self.session.execute(statement, params)
        rows = result.mappings().all()
        logger.warning(f"[QR List] Rows returned: {len(rows)}")

        items: list[QRCodeListItem] = []
        for row in rows:
            row_dict = dict(row)
            row_dict = self._normalize_qr_row(row_dict)

            # Build campaign object
            campaign = None
            if row_dict.get("campaign_name"):
                campaign = {
                    "id": row_dict.pop("campaign_real_id"),
                    "name": row_dict.pop("campaign_name"),
                    "description": row_dict.pop("campaign_description"),
                }

            # Build employee object (for admin)
            employee = None
            if include_employee and row_dict.get("employee_email"):
                employee = {
                    "username": row_dict.pop("employee_username", None),
                    "email": row_dict.pop("employee_email"),
                }

            # Remove campaign_id from response (not needed anymore)
            row_dict.pop("campaign_id", None)

            # Add campaign and employee to the data
            row_dict["campaign"] = campaign
            if include_employee:
                row_dict["employee"] = employee

            items.append(QRCodeListItem.model_validate(row_dict))

        return items

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

    async def get_campaign_context(self, campaign_id: int) -> dict[str, Any] | None:
        """Return campaign owner and GA defaults for inheritance/ownership checks."""

        statement = text(
            """
            SELECT
                user_id,
                ga_type,
                ga_measurement_id,
                ga_property_id
            FROM campaigns
            WHERE id = :campaign_id
              AND deleted_at IS NULL
            LIMIT 1
            """
        )
        result = await self.session.execute(statement, {"campaign_id": campaign_id})
        row = result.mappings().first()
        return dict(row) if row else None

    async def create(self, user_id: int, short_code: str, payload: QRCodeCreate) -> QRCodeRead:
        """Insert one QR code linked to user/campaign and return created row."""

        write_data: dict[str, Any] = {
            "user_id": user_id,
            "campaign_id": payload.campaign_id,
            "name": payload.name,
            "short_code": short_code,
            "destination_url": str(payload.destination_url),
            "qr_type": payload.qr_type.value,
            "design_config": self._serialize_design_config(payload.design_config),
            "ga_type": payload.ga_type.value if payload.ga_type is not None else None,
            "ga_measurement_id": payload.ga_measurement_id,
            "ga_property_id": payload.ga_property_id,
            "utm_source": payload.utm_source,
            "utm_medium": payload.utm_medium,
            "utm_campaign": payload.utm_campaign,
            "status": payload.status.value,
        }
        write_data = self._normalize_tracking_for_write(write_data)

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
                ga_type,
                ga_measurement_id,
                ga_property_id,
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
                :ga_type,
                :ga_measurement_id,
                :ga_property_id,
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
            write_data,
        )
        await self.session.flush()

        created = await self.get_by_id(int(result.lastrowid), include_deleted=True)
        if created is None:
            raise RuntimeError("Failed to read QR code after create")

        return created

    def _normalize_tracking_for_write(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply GA integrity rules before INSERT/UPDATE statements."""

        ga_type = data.get("ga_type")
        if ga_type is None:
            return data

        ga_type_value = ga_type.value if hasattr(ga_type, "value") else str(ga_type)
        ga_property_id = data.get("ga_property_id")
        if isinstance(ga_property_id, str):
            ga_property_id = ga_property_id.strip()
            data["ga_property_id"] = ga_property_id or None

        if ga_type_value == "MANUAL":
            data["ga_property_id"] = None
        elif ga_type_value == "OAUTH" and not data.get("ga_property_id"):
            raise ValueError("ga_property_id is required when ga_type is OAUTH")

        return data

    async def update(self, qr_id: int, payload: QRCodeUpdate) -> QRCodeRead | None:
        """Update mutable QR fields and return updated row."""

        data = payload.model_dump(exclude_none=True)
        data.pop("use_campaign_defaults", None)
        if not data:
            return await self.get_by_id(qr_id)

        if "destination_url" in data:
            data["destination_url"] = str(data["destination_url"])
        if "design_config" in data:
            data["design_config"] = self._serialize_design_config(data["design_config"])
        if "qr_type" in data:
            data["qr_type"] = data["qr_type"].value
        if "ga_type" in data and data["ga_type"] is not None:
            data["ga_type"] = data["ga_type"].value
        if "status" in data:
            data["status"] = data["status"].value

        data = self._normalize_tracking_for_write(data)

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
                ga_type,
                deleted_at,
                ga_measurement_id,
                ga_property_id,
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

