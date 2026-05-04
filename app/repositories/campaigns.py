"""Repository helpers for campaign CRUD and soft-delete lifecycle."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.campaign import CampaignCreate, CampaignRead, CampaignUpdate


class CampaignRepository:
    """Access campaign records with soft-delete-aware defaults."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(
        self,
        campaign_id: int,
        *,
        include_deleted: bool = False,
    ) -> CampaignRead | None:
        """Fetch one campaign by id, optionally including soft-deleted rows."""

        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        statement = text(
            f"""
            SELECT
                id,
                user_id,
                name,
                description,
                start_date,
                end_date,
                status,
                ga_type,
                ga_measurement_id,
                ga_property_id,
                google_event_id,
                calendar_sync_status,
                calendar_last_synced_at,
                calendar_sync_hash,
                created_at,
                updated_at,
                deleted_at
            FROM campaigns
            WHERE id = :campaign_id
            {deleted_filter}
            LIMIT 1
            """
        )

        result = await self.session.execute(statement, {"campaign_id": campaign_id})
        row = result.mappings().first()
        return CampaignRead.model_validate(dict(row)) if row else None

    async def list_by_user(
        self,
        user_id: int,
        *,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CampaignRead]:
        """List campaigns for one owner with paging and soft-delete filtering."""

        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        statement = text(
            f"""
            SELECT
                id,
                user_id,
                name,
                description,
                start_date,
                end_date,
                status,
                ga_type,
                ga_measurement_id,
                ga_property_id,
                google_event_id,
                calendar_sync_status,
                calendar_last_synced_at,
                calendar_sync_hash,
                created_at,
                updated_at,
                deleted_at
            FROM campaigns
            WHERE user_id = :user_id
            {deleted_filter}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """
        )

        result = await self.session.execute(
            statement,
            {
                "user_id": user_id,
                "limit": limit,
                "offset": offset,
            },
        )
        return [CampaignRead.model_validate(dict(row)) for row in result.mappings().all()]

    async def list_all(
        self,
        *,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CampaignRead]:
        """List campaigns across all users with paging and soft-delete filtering."""

        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        statement = text(
            f"""
            SELECT
                id,
                user_id,
                name,
                description,
                start_date,
                end_date,
                status,
                ga_type,
                ga_measurement_id,
                ga_property_id,
                google_event_id,
                calendar_sync_status,
                calendar_last_synced_at,
                calendar_sync_hash,
                created_at,
                updated_at,
                deleted_at
            FROM campaigns
            WHERE 1=1
            {deleted_filter}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """
        )

        result = await self.session.execute(
            statement,
            {
                "limit": limit,
                "offset": offset,
            },
        )
        return [CampaignRead.model_validate(dict(row)) for row in result.mappings().all()]

    async def get_by_user_and_google_event_id(
        self,
        user_id: int,
        google_event_id: str,
        *,
        include_deleted: bool = False,
    ) -> CampaignRead | None:
        """Fetch one campaign by owner and linked Google event id."""

        deleted_filter = "" if include_deleted else "AND deleted_at IS NULL"
        statement = text(
            f"""
            SELECT
                id,
                user_id,
                name,
                description,
                start_date,
                end_date,
                status,
                ga_type,
                ga_measurement_id,
                ga_property_id,
                google_event_id,
                calendar_sync_status,
                calendar_last_synced_at,
                calendar_sync_hash,
                created_at,
                updated_at,
                deleted_at
            FROM campaigns
            WHERE user_id = :user_id
              AND google_event_id = :google_event_id
              {deleted_filter}
            LIMIT 1
            """
        )

        result = await self.session.execute(
            statement,
            {
                "user_id": user_id,
                "google_event_id": google_event_id,
            },
        )
        row = result.mappings().first()
        return CampaignRead.model_validate(dict(row)) if row else None

    async def create(self, user_id: int, payload: CampaignCreate) -> CampaignRead:
        """Insert a new campaign row and return the created campaign."""

        insert_stmt = text(
            """
            INSERT INTO campaigns (
                user_id,
                name,
                description,
                start_date,
                end_date,
                status,
                ga_type,
                ga_measurement_id,
                ga_property_id,
                created_at,
                updated_at
            ) VALUES (
                :user_id,
                :name,
                :description,
                :start_date,
                :end_date,
                :status,
                :ga_type,
                :ga_measurement_id,
                :ga_property_id,
                UTC_TIMESTAMP(),
                UTC_TIMESTAMP()
            )
            """
        )

        result = await self.session.execute(
            insert_stmt,
            {
                "user_id": user_id,
                "name": payload.name,
                "description": payload.description,
                "start_date": payload.start_date,
                "end_date": payload.end_date,
                "status": payload.status,
                "ga_type": payload.ga_type.value if payload.ga_type is not None else None,
                "ga_measurement_id": payload.ga_measurement_id,
                "ga_property_id": payload.ga_property_id,
            },
        )
        await self.session.flush()

        campaign_id = int(result.lastrowid)
        created = await self.get_by_id(campaign_id, include_deleted=True)
        if created is None:
            raise RuntimeError("Failed to read campaign after create")

        return created

    async def update(
        self,
        campaign_id: int,
        payload: CampaignUpdate,
    ) -> CampaignRead | None:
        """Apply partial updates to one active campaign and return updated row."""

        data = payload.model_dump(exclude_unset=True)
        if not data:
            return await self.get_by_id(campaign_id)

        if "ga_type" in data and data["ga_type"] is not None:
            data["ga_type"] = data["ga_type"].value

        assignments = ", ".join(f"{field} = :{field}" for field in data)
        statement = text(
            f"""
            UPDATE campaigns
            SET {assignments},
                updated_at = UTC_TIMESTAMP()
            WHERE id = :campaign_id
              AND deleted_at IS NULL
            """
        )

        params: dict[str, Any] = {"campaign_id": campaign_id, **data}
        await self.session.execute(statement, params)
        await self.session.flush()

        return await self.get_by_id(campaign_id)

    async def soft_delete(self, campaign_id: int) -> bool:
        """Soft-delete one campaign row by setting `deleted_at` in UTC."""

        statement = text(
            """
            UPDATE campaigns
            SET deleted_at = UTC_TIMESTAMP(),
                updated_at = UTC_TIMESTAMP()
            WHERE id = :campaign_id
              AND deleted_at IS NULL
            """
        )

        result = await self.session.execute(statement, {"campaign_id": campaign_id})
        await self.session.flush()
        return (result.rowcount or 0) > 0

    async def get_creator_info(self, user_id: int) -> dict[str, Any] | None:
        """Fetch creator information (username and email) by user_id."""

        statement = text(
            """
            SELECT username, email
            FROM users
            WHERE id = :user_id AND deleted_at IS NULL
            LIMIT 1
            """
        )

        result = await self.session.execute(statement, {"user_id": user_id})
        row = result.mappings().first()
        return dict(row) if row else None

