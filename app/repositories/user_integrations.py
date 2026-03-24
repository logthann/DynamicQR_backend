"""Repository helpers for user provider credentials with unique key upsert behavior."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.integrations import (
    IntegrationProvider,
    ProviderCredentialRecord,
    ProviderCredentialWrite,
)


class UserIntegrationRepository:
    """Persist and query OAuth provider credentials for one user."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_and_provider(
        self,
        user_id: int,
        provider_name: IntegrationProvider,
    ) -> ProviderCredentialRecord | None:
        """Fetch one provider credential row by unique user/provider key."""

        statement = text(
            """
            SELECT
                id,
                user_id,
                provider_name,
                access_token,
                refresh_token,
                expires_at
            FROM user_integrations
            WHERE user_id = :user_id
              AND provider_name = :provider_name
            LIMIT 1
            """
        )

        result = await self.session.execute(
            statement,
            {
                "user_id": user_id,
                "provider_name": provider_name.value,
            },
        )
        row = result.mappings().first()
        return ProviderCredentialRecord.model_validate(dict(row)) if row else None

    async def list_by_user(self, user_id: int) -> list[ProviderCredentialRecord]:
        """List all provider connections for one user."""

        statement = text(
            """
            SELECT
                id,
                user_id,
                provider_name,
                access_token,
                refresh_token,
                expires_at
            FROM user_integrations
            WHERE user_id = :user_id
            ORDER BY id DESC
            """
        )

        result = await self.session.execute(statement, {"user_id": user_id})
        return [ProviderCredentialRecord.model_validate(dict(row)) for row in result.mappings().all()]

    async def upsert_credentials(
        self,
        user_id: int,
        payload: ProviderCredentialWrite,
    ) -> ProviderCredentialRecord:
        """Insert or update provider credentials via unique key upsert."""

        statement = text(
            """
            INSERT INTO user_integrations (
                user_id,
                provider_name,
                access_token,
                refresh_token,
                expires_at
            ) VALUES (
                :user_id,
                :provider_name,
                :access_token,
                :refresh_token,
                :expires_at
            )
            ON DUPLICATE KEY UPDATE
                access_token = VALUES(access_token),
                refresh_token = VALUES(refresh_token),
                expires_at = VALUES(expires_at)
            """
        )

        await self.session.execute(
            statement,
            {
                "user_id": user_id,
                "provider_name": payload.provider_name.value,
                "access_token": payload.access_token,
                "refresh_token": payload.refresh_token,
                "expires_at": payload.expires_at,
            },
        )
        await self.session.flush()

        record = await self.get_by_user_and_provider(user_id, payload.provider_name)
        if record is None:
            raise RuntimeError("Failed to read provider credentials after upsert")

        return record

    async def delete_by_user_and_provider(
        self,
        user_id: int,
        provider_name: IntegrationProvider,
    ) -> bool:
        """Delete one provider credential row by unique user/provider key."""

        statement = text(
            """
            DELETE FROM user_integrations
            WHERE user_id = :user_id
              AND provider_name = :provider_name
            """
        )

        result = await self.session.execute(
            statement,
            {
                "user_id": user_id,
                "provider_name": provider_name.value,
            },
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0

