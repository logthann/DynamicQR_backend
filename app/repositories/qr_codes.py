"""Repository helpers for QR code persistence and lookup."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, text
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

        qr_type = row.get("qr_type")
        if not qr_type:
            row["qr_type"] = "url"
        return row

    @staticmethod
    def _default_table_columns(table_name: str) -> set[str]:
        """Fallback column sets used when the session is a test mock."""

        defaults = {
            "qr_codes": {
                "id",
                "user_id",
                "campaign_id",
                "short_code",
                "status",
                "created_at",
                "updated_at",
                "deleted_at",
            },
            "qr_configurations": {
                "id",
                "qr_id",
                "version_number",
                "name",
                "description",
                "destination_url",
                "ga_measurement_id",
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "is_current",
                "created_at",
                "design_config",
                "ga_type",
                "ga_property_id",
                "qr_type",
            },
        }
        return set(defaults.get(table_name, set()))

    async def _get_table_columns(self, table_name: str) -> set[str]:
        """Return cached column names for a MySQL table."""

        cache_attr = f"_{table_name}_columns"
        cached = getattr(self, cache_attr, None)
        if cached is not None:
            return cached

        if self.session.__class__.__module__.startswith("unittest.mock"):
            columns = self._default_table_columns(table_name)
        else:
            try:
                columns = await self.session.run_sync(
                    lambda sync_session: {
                        column["name"]
                        for column in inspect(sync_session.get_bind()).get_columns(table_name)
                    }
                )
            except Exception:
                columns = self._default_table_columns(table_name)

        setattr(self, cache_attr, columns)
        return columns

    @staticmethod
    def _pick_column_expr(
        column_name: str,
        q_columns: set[str],
        qc_columns: set[str],
        *,
        prefer_qc: bool = True,
        default_expr: str = "NULL",
    ) -> str:
        """Pick a safe SQL column expression from the table that owns it."""

        sources = (("qc", qc_columns), ("q", q_columns)) if prefer_qc else (("q", q_columns), ("qc", qc_columns))
        for alias, columns in sources:
            if column_name in columns:
                return f"{alias}.{column_name} AS {column_name}"
        return f"{default_expr} AS {column_name}"

    async def _resolve_qr_select_columns(self) -> tuple[set[str], set[str]]:
        """Fetch qr_codes and qr_configurations columns once per repository instance."""

        qr_columns = await self._get_table_columns("qr_codes")
        qr_config_columns = await self._get_table_columns("qr_configurations")
        return qr_columns, qr_config_columns

    async def get_by_id(self, qr_id: int, *, include_deleted: bool = False) -> QRCodeRead | None:
        """Fetch one QR code by id with optional soft-deleted visibility."""

        q_columns, qc_columns = await self._resolve_qr_select_columns()
        deleted_filter = "" if include_deleted else "AND q.deleted_at IS NULL"
        select_columns = [
            "q.id",
            "q.user_id",
            self._pick_column_expr("campaign_id", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("name", q_columns, qc_columns),
            self._pick_column_expr("description", q_columns, qc_columns),
            "q.short_code" if "short_code" in q_columns else self._pick_column_expr("short_code", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("destination_url", q_columns, qc_columns, default_expr="''"),
            self._pick_column_expr("qr_type", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("design_config", q_columns, qc_columns),
            self._pick_column_expr("ga_type", q_columns, qc_columns),
            self._pick_column_expr("ga_measurement_id", q_columns, qc_columns),
            self._pick_column_expr("ga_property_id", q_columns, qc_columns),
            self._pick_column_expr("utm_source", q_columns, qc_columns),
            self._pick_column_expr("utm_medium", q_columns, qc_columns),
            self._pick_column_expr("utm_campaign", q_columns, qc_columns),
            self._pick_column_expr("status", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("created_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("updated_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("deleted_at", q_columns, qc_columns, prefer_qc=False),
        ]
        statement = text(
            f"""
            SELECT
                {", ".join(select_columns)}
            FROM qr_codes q
            LEFT JOIN qr_configurations qc ON q.id = qc.qr_id AND qc.is_current = 1
            WHERE q.id = :qr_id
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

        q_columns, qc_columns = await self._resolve_qr_select_columns()
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
        select_columns = [
            "q.id",
            "q.user_id",
            self._pick_column_expr("campaign_id", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("name", q_columns, qc_columns),
            self._pick_column_expr("description", q_columns, qc_columns),
            "q.short_code" if "short_code" in q_columns else self._pick_column_expr("short_code", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("destination_url", q_columns, qc_columns, default_expr="''"),
            self._pick_column_expr("qr_type", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("design_config", q_columns, qc_columns),
            self._pick_column_expr("ga_type", q_columns, qc_columns),
            self._pick_column_expr("ga_measurement_id", q_columns, qc_columns),
            self._pick_column_expr("ga_property_id", q_columns, qc_columns),
            self._pick_column_expr("utm_source", q_columns, qc_columns),
            self._pick_column_expr("utm_medium", q_columns, qc_columns),
            self._pick_column_expr("utm_campaign", q_columns, qc_columns),
            self._pick_column_expr("status", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("created_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("updated_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("deleted_at", q_columns, qc_columns, prefer_qc=False),
        ]
        statement = text(
            f"""
            SELECT
                {", ".join(select_columns)}
            FROM qr_codes q
            LEFT JOIN qr_configurations qc ON q.id = qc.qr_id AND qc.is_current = 1
            WHERE {where_clause}
            ORDER BY q.id DESC
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

        q_columns, qc_columns = await self._resolve_qr_select_columns()
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

        select_columns = [
            "q.id",
            "q.user_id",
            "q.short_code" if "short_code" in q_columns else self._pick_column_expr("short_code", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("name", q_columns, qc_columns),
            self._pick_column_expr("description", q_columns, qc_columns),
            self._pick_column_expr("destination_url", q_columns, qc_columns, default_expr="''"),
            self._pick_column_expr("qr_type", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("design_config", q_columns, qc_columns),
            self._pick_column_expr("ga_type", q_columns, qc_columns),
            self._pick_column_expr("ga_measurement_id", q_columns, qc_columns),
            self._pick_column_expr("ga_property_id", q_columns, qc_columns),
            self._pick_column_expr("utm_source", q_columns, qc_columns),
            self._pick_column_expr("utm_medium", q_columns, qc_columns),
            self._pick_column_expr("utm_campaign", q_columns, qc_columns),
            self._pick_column_expr("status", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("created_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("updated_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("deleted_at", q_columns, qc_columns, prefer_qc=False),
            "c.id AS campaign_real_id",
            "c.name AS campaign_name",
            "c.description AS campaign_description",
        ]
        if include_employee:
            select_columns.extend(["u.username AS employee_username", "u.email AS employee_email"])
        select_columns.append(self._pick_column_expr("campaign_id", q_columns, qc_columns, prefer_qc=False))

        statement = text(
            f"""
            SELECT
                {", ".join(select_columns)}
            FROM qr_codes q
            LEFT JOIN qr_configurations qc ON q.id = qc.qr_id AND qc.is_current = 1
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
            "short_code": short_code,
            "status": payload.status.value,
        }

        statement = text(
            """
            INSERT INTO qr_codes (
                user_id,
                campaign_id,
                short_code,
                status,
                created_at,
                updated_at
            ) VALUES (
                :user_id,
                :campaign_id,
                :short_code,
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

        qr_id = int(result.lastrowid)

        # Insert configuration into qr_configurations table
        config_statement = text(
            """
            INSERT INTO qr_configurations (
                qr_id,
                version_number,
                name,
                description,
                qr_type,
                destination_url,
                design_config,
                ga_type,
                ga_measurement_id,
                ga_property_id,
                utm_source,
                utm_medium,
                utm_campaign,
                is_current,
                created_at
            ) VALUES (
                :qr_id,
                1,
                :name,
                :description,
                :qr_type,
                :destination_url,
                :design_config,
                :ga_type,
                :ga_measurement_id,
                :ga_property_id,
                :utm_source,
                :utm_medium,
                :utm_campaign,
                1,
                UTC_TIMESTAMP()
            )
            """
        )

        config_data = {
            "qr_id": qr_id,
            "name": payload.name,
            "description": payload.description,
            "qr_type": payload.qr_type.value,
            "destination_url": str(payload.destination_url),
            "design_config": self._serialize_design_config(payload.design_config),
            "ga_type": payload.ga_type.value if payload.ga_type is not None else None,
            "ga_measurement_id": payload.ga_measurement_id,
            "ga_property_id": payload.ga_property_id,
            "utm_source": payload.utm_source,
            "utm_medium": payload.utm_medium,
            "utm_campaign": payload.utm_campaign,
        }

        config_data = self._normalize_tracking_for_write(config_data)

        await self.session.execute(config_statement, config_data)
        await self.session.flush()

        created = await self.get_by_id(qr_id, include_deleted=True)
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
        existing = await self.get_by_id(qr_id)
        if existing is None:
            return None

        if not data:
            return existing

        # Separate configuration fields (that go to qr_configurations) from core fields (that stay in qr_codes)
        config_fields = {"name", "qr_type", "description", "destination_url", "design_config", "ga_type", "ga_measurement_id", "ga_property_id", "utm_source", "utm_medium", "utm_campaign"}
        core_data = {k: v for k, v in data.items() if k not in config_fields}
        config_data = {k: v for k, v in data.items() if k in config_fields}

        # Handle type conversions for core fields
        if "design_config" in core_data:
            core_data["design_config"] = self._serialize_design_config(core_data["design_config"])
        if "status" in core_data:
            core_data["status"] = core_data["status"].value

        core_data = self._normalize_tracking_for_write(core_data)

        # Update core fields in qr_codes table
        if core_data:
            assignments = ", ".join(f"{field} = :{field}" for field in core_data)
            statement = text(
                f"""
                UPDATE qr_codes
                SET {assignments},
                    updated_at = UTC_TIMESTAMP()
                WHERE id = :qr_id
                  AND deleted_at IS NULL
                """
            )
            await self.session.execute(statement, {"qr_id": qr_id, **core_data})
            await self.session.flush()

        # Handle configuration fields - create new version
        if config_data:
            # Convert destination_url to string if present
            if "destination_url" in config_data:
                config_data["destination_url"] = str(config_data["destination_url"])
            if "design_config" in config_data:
                config_data["design_config"] = self._serialize_design_config(config_data["design_config"])
            if "qr_type" in config_data:
                config_data["qr_type"] = config_data["qr_type"].value
            else:
                config_data["qr_type"] = existing.qr_type.value
            if "ga_type" in config_data and config_data["ga_type"] is not None:
                config_data["ga_type"] = config_data["ga_type"].value
            else:
                config_data["ga_type"] = existing.ga_type.value if getattr(existing, "ga_type", None) is not None else None

            merged_config = {
                "name": config_data.get("name", existing.name),
                "description": config_data.get("description", existing.description),
                "qr_type": config_data.get("qr_type", existing.qr_type.value),
                "destination_url": config_data.get("destination_url", str(existing.destination_url)),
                "design_config": config_data.get("design_config", self._serialize_design_config(existing.design_config)),
                "ga_type": config_data.get("ga_type", existing.ga_type.value if getattr(existing, "ga_type", None) is not None else None),
                "ga_measurement_id": config_data.get("ga_measurement_id", existing.ga_measurement_id),
                "ga_property_id": config_data.get("ga_property_id", existing.ga_property_id),
                "utm_source": config_data.get("utm_source", existing.utm_source),
                "utm_medium": config_data.get("utm_medium", existing.utm_medium),
                "utm_campaign": config_data.get("utm_campaign", existing.utm_campaign),
            }
            merged_config = self._normalize_tracking_for_write(merged_config)

            # Get the current version number
            version_statement = text(
                """
                SELECT MAX(version_number) as max_version
                FROM qr_configurations
                WHERE qr_id = :qr_id
                """
            )
            version_result = await self.session.execute(version_statement, {"qr_id": qr_id})
            version_row = version_result.mappings().first()
            current_version = (version_row["max_version"] or 0) + 1 if version_row else 1

            # Mark current configuration as inactive
            mark_inactive = text(
                """
                UPDATE qr_configurations
                SET is_current = 0
                WHERE qr_id = :qr_id AND is_current = 1
                """
            )
            await self.session.execute(mark_inactive, {"qr_id": qr_id})
            await self.session.flush()

            # Insert new configuration as current
            config_statement = text(
                """
                INSERT INTO qr_configurations (
                    qr_id,
                    version_number,
                    name,
                    description,
                    qr_type,
                    destination_url,
                    design_config,
                    ga_type,
                    ga_measurement_id,
                    ga_property_id,
                    utm_source,
                    utm_medium,
                    utm_campaign,
                    is_current,
                    created_at
                ) VALUES (
                    :qr_id,
                    :version_number,
                    :name,
                    :description,
                    :qr_type,
                    :destination_url,
                    :design_config,
                    :ga_type,
                    :ga_measurement_id,
                    :ga_property_id,
                    :utm_source,
                    :utm_medium,
                    :utm_campaign,
                    1,
                    UTC_TIMESTAMP()
                )
                """
            )

            insert_data = {
                "qr_id": qr_id,
                "version_number": current_version,
                **merged_config,
            }

            await self.session.execute(config_statement, insert_data)
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

        q_columns, qc_columns = await self._resolve_qr_select_columns()
        select_columns = [
            "q.id",
            "q.short_code" if "short_code" in q_columns else self._pick_column_expr("short_code", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("destination_url", q_columns, qc_columns, default_expr="''"),
            self._pick_column_expr("status", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("qr_type", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("deleted_at", q_columns, qc_columns, prefer_qc=False),
            self._pick_column_expr("ga_measurement_id", q_columns, qc_columns),
            self._pick_column_expr("ga_property_id", q_columns, qc_columns),
            self._pick_column_expr("utm_source", q_columns, qc_columns),
            self._pick_column_expr("utm_medium", q_columns, qc_columns),
            self._pick_column_expr("utm_campaign", q_columns, qc_columns),
        ]
        statement = text(
            """
            SELECT
                {select_columns}
            FROM qr_codes q
            LEFT JOIN qr_configurations qc ON q.id = qc.qr_id AND qc.is_current = 1
            WHERE q.short_code = :short_code
            LIMIT 1
            """.replace("{select_columns}", ", ".join(select_columns))
        )

        result = await self.session.execute(statement, {"short_code": short_code})
        row = result.mappings().first()
        return dict(row) if row else None

