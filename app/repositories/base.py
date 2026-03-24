"""Generic repository base with default soft-delete filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class RepositoryBase(Generic[ModelT]):
    """Provide common persistence operations with soft-delete-aware defaults."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    @property
    def supports_soft_delete(self) -> bool:
        """Return True if the model defines a deleted_at column."""

        return hasattr(self.model, "deleted_at")

    @property
    def _id_column(self) -> Any:
        """Return model id column for typed query composition."""

        return getattr(self.model, "id")

    def _apply_soft_delete_filter(
        self,
        statement: Select[tuple[ModelT]],
        *,
        include_deleted: bool,
    ) -> Select[tuple[ModelT]]:
        """Apply default `deleted_at IS NULL` filtering when supported."""

        if include_deleted or not self.supports_soft_delete:
            return statement

        return statement.where(getattr(self.model, "deleted_at").is_(None))

    def _base_select(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        """Build a model select statement with default soft-delete behavior."""

        statement = select(self.model)
        return self._apply_soft_delete_filter(
            statement,
            include_deleted=include_deleted,
        )

    async def get_by_id(
        self,
        row_id: int,
        *,
        include_deleted: bool = False,
    ) -> ModelT | None:
        """Return one model by id, optionally including soft-deleted rows."""

        statement = self._base_select(include_deleted=include_deleted).where(
            self._id_column == row_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelT]:
        """List models with paging and default soft-delete filtering."""

        statement = (
            self._base_select(include_deleted=include_deleted)
            .order_by(self._id_column.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> ModelT:
        """Create and persist a model instance."""

        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: ModelT, data: dict[str, Any]) -> ModelT:
        """Update mutable fields on a model instance."""

        for field, value in data.items():
            setattr(instance, field, value)
        await self.session.flush()
        return instance

    async def soft_delete(self, instance: ModelT) -> ModelT:
        """Apply logical deletion by setting `deleted_at` when available."""

        if not self.supports_soft_delete:
            raise ValueError(f"Model '{self.model.__name__}' does not support soft delete")

        setattr(instance, "deleted_at", datetime.now(UTC))
        await self.session.flush()
        return instance

    async def hard_delete(self, instance: ModelT) -> None:
        """Physically delete a model row."""

        await self.session.delete(instance)
        await self.session.flush()

