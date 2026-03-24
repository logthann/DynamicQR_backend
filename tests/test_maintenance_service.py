"""Tests for maintenance-only hard-delete workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.audit import AuditLogger, InMemoryAuditSink
from app.core.rbac import Principal, RBACError
from app.services.maintenance_service import MaintenanceService


class _FakeExecuteResult:
    def __init__(self, *, rowcount: int) -> None:
        self.rowcount = rowcount


@pytest.mark.asyncio
async def test_non_admin_cannot_hard_delete() -> None:
    session = AsyncMock()
    service = MaintenanceService(session)

    with pytest.raises(RBACError):
        await service.hard_delete_campaign(
            Principal(user_id=5, role="user"),
            campaign_id=10,
            reason="maintenance cleanup",
            confirm=True,
        )


@pytest.mark.asyncio
async def test_hard_delete_requires_confirmation() -> None:
    session = AsyncMock()
    service = MaintenanceService(session)

    with pytest.raises(RBACError, match="explicit confirmation"):
        await service.hard_delete_qr_code(
            Principal(user_id=1, role="admin"),
            qr_id=2,
            reason="maintenance cleanup",
            confirm=False,
        )


@pytest.mark.asyncio
async def test_hard_delete_records_audit_event_on_success() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rowcount=1)

    sink = InMemoryAuditSink()
    audit_logger = AuditLogger(sinks=[sink])

    service = MaintenanceService(session, audit_logger=audit_logger)

    result = await service.hard_delete_campaign(
        Principal(user_id=1, role="admin"),
        campaign_id=11,
        reason="gdpr cleanup",
        confirm=True,
    )

    assert result.deleted is True
    statement = session.execute.await_args.args[0]
    assert "AND deleted_at IS NOT NULL" in str(statement)
    assert len(sink.events) == 1
    assert sink.events[0].target_resource == "campaigns"
    assert sink.events[0].target_id == "11"


@pytest.mark.asyncio
async def test_hard_delete_can_allow_active_delete_in_maintenance_mode() -> None:
    session = AsyncMock()
    session.execute.return_value = _FakeExecuteResult(rowcount=1)

    service = MaintenanceService(session)

    result = await service.hard_delete_user(
        Principal(user_id=1, role="admin"),
        user_id=22,
        reason="manual remediation",
        confirm=True,
        allow_active_delete=True,
    )

    assert result.deleted is True
    statement = session.execute.await_args.args[0]
    assert "AND deleted_at IS NOT NULL" not in str(statement)

