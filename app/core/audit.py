"""Audit event logging for security-sensitive and maintenance operations."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger("app.audit")


class AuditEventType(StrEnum):
    """Supported audit event categories."""

    TOKEN_ACCESS = "token_access"
    TOKEN_REFRESH = "token_refresh"
    TOKEN_REVOKE = "token_revoke"
    MAINTENANCE_HARD_DELETE = "maintenance_hard_delete"


@dataclass(slots=True)
class AuditEvent:
    """Structured audit event payload."""

    event_type: AuditEventType
    actor_user_id: int | None
    action: str
    target_resource: str
    target_id: str | None = None
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditSink(Protocol):
    """Protocol for audit destinations."""

    async def write_event(self, event: AuditEvent) -> None:
        """Persist one audit event."""


class LoggerAuditSink:
    """Standard sink that emits structured JSON to the application logger."""

    async def write_event(self, event: AuditEvent) -> None:
        data = asdict(event)
        data["event_type"] = event.event_type.value
        data["occurred_at"] = event.occurred_at.isoformat()
        logger.info("audit_event=%s", json.dumps(data, separators=(",", ":"), sort_keys=True))


class InMemoryAuditSink:
    """Test-friendly sink that stores events in process memory."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def write_event(self, event: AuditEvent) -> None:
        self.events.append(event)


class AuditLogger:
    """Orchestrates writing audit events to one or many sinks."""

    def __init__(self, sinks: list[AuditSink] | None = None) -> None:
        self._sinks = sinks or [LoggerAuditSink()]

    async def record_event(self, event: AuditEvent) -> None:
        """Write one event to all configured sinks."""

        for sink in self._sinks:
            await sink.write_event(event)

    async def record_token_access(
        self,
        *,
        actor_user_id: int,
        provider_name: str,
        integration_id: str,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record token read access from integration workflows."""

        event = AuditEvent(
            event_type=AuditEventType.TOKEN_ACCESS,
            actor_user_id=actor_user_id,
            action="oauth_token_access",
            target_resource="user_integrations",
            target_id=integration_id,
            success=success,
            metadata={"provider_name": provider_name, **(metadata or {})},
        )
        await self.record_event(event)

    async def record_token_refresh(
        self,
        *,
        actor_user_id: int,
        provider_name: str,
        integration_id: str,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record token refresh operations."""

        event = AuditEvent(
            event_type=AuditEventType.TOKEN_REFRESH,
            actor_user_id=actor_user_id,
            action="oauth_token_refresh",
            target_resource="user_integrations",
            target_id=integration_id,
            success=success,
            metadata={"provider_name": provider_name, **(metadata or {})},
        )
        await self.record_event(event)

    async def record_token_revoke(
        self,
        *,
        actor_user_id: int,
        provider_name: str,
        integration_id: str,
        success: bool,
    ) -> None:
        """Record token revoke/disconnect operations."""

        event = AuditEvent(
            event_type=AuditEventType.TOKEN_REVOKE,
            actor_user_id=actor_user_id,
            action="oauth_token_revoke",
            target_resource="user_integrations",
            target_id=integration_id,
            success=success,
            metadata={"provider_name": provider_name},
        )
        await self.record_event(event)

    async def record_maintenance_hard_delete(
        self,
        *,
        actor_user_id: int,
        resource_type: str,
        resource_id: str,
        reason: str,
    ) -> None:
        """Record audited maintenance-only hard-delete actions."""

        event = AuditEvent(
            event_type=AuditEventType.MAINTENANCE_HARD_DELETE,
            actor_user_id=actor_user_id,
            action="maintenance_hard_delete",
            target_resource=resource_type,
            target_id=resource_id,
            success=True,
            metadata={"reason": reason},
        )
        await self.record_event(event)


_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Return singleton audit logger instance."""

    global _audit_logger

    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def set_audit_logger(audit_logger: AuditLogger | None) -> None:
    """Override singleton audit logger, mostly for tests."""

    global _audit_logger
    _audit_logger = audit_logger

