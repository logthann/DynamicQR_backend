"""Maintenance-only hard-delete workflow with strict guardrails and auditing."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLogger, get_audit_logger
from app.core.rbac import Principal, RBACError, require_any_role


@dataclass(frozen=True, slots=True)
class HardDeleteResult:
    """Result metadata for maintenance hard-delete operations."""

    resource_type: str
    resource_id: int
    deleted: bool


class MaintenanceService:
    """Provide audited hard-delete operations for maintenance administrators only."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.session = session
        self.audit_logger = audit_logger or get_audit_logger()

    async def hard_delete_user(
        self,
        principal: Principal,
        user_id: int,
        *,
        reason: str,
        confirm: bool,
        allow_active_delete: bool = False,
    ) -> HardDeleteResult:
        """Hard-delete a user row under maintenance-only controls."""

        return await self._hard_delete(
            principal,
            table_name="users",
            resource_id=user_id,
            reason=reason,
            confirm=confirm,
            allow_active_delete=allow_active_delete,
        )

    async def hard_delete_campaign(
        self,
        principal: Principal,
        campaign_id: int,
        *,
        reason: str,
        confirm: bool,
        allow_active_delete: bool = False,
    ) -> HardDeleteResult:
        """Hard-delete a campaign row under maintenance-only controls."""

        return await self._hard_delete(
            principal,
            table_name="campaigns",
            resource_id=campaign_id,
            reason=reason,
            confirm=confirm,
            allow_active_delete=allow_active_delete,
        )

    async def hard_delete_qr_code(
        self,
        principal: Principal,
        qr_id: int,
        *,
        reason: str,
        confirm: bool,
        allow_active_delete: bool = False,
    ) -> HardDeleteResult:
        """Hard-delete a QR row under maintenance-only controls."""

        return await self._hard_delete(
            principal,
            table_name="qr_codes",
            resource_id=qr_id,
            reason=reason,
            confirm=confirm,
            allow_active_delete=allow_active_delete,
        )

    async def _hard_delete(
        self,
        principal: Principal,
        *,
        table_name: str,
        resource_id: int,
        reason: str,
        confirm: bool,
        allow_active_delete: bool,
    ) -> HardDeleteResult:
        """Run one guarded hard-delete and write an audit entry."""

        require_any_role(principal, ["admin"])

        if not confirm:
            raise RBACError("Hard delete requires explicit confirmation")

        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValueError("Hard delete reason is required")

        deletion_guard = "" if allow_active_delete else "AND deleted_at IS NOT NULL"

        statement = text(
            f"""
            DELETE FROM {table_name}
            WHERE id = :resource_id
              {deletion_guard}
            """
        )

        result = await self.session.execute(statement, {"resource_id": resource_id})
        await self.session.flush()

        deleted = (result.rowcount or 0) > 0
        if deleted:
            await self.audit_logger.record_maintenance_hard_delete(
                actor_user_id=principal.user_id,
                resource_type=table_name,
                resource_id=str(resource_id),
                reason=cleaned_reason,
            )

        return HardDeleteResult(
            resource_type=table_name,
            resource_id=resource_id,
            deleted=deleted,
        )

