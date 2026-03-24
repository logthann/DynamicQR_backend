"""Tests for audit event logging helpers."""

from __future__ import annotations

from app.core.audit import AuditEvent, AuditEventType, AuditLogger, InMemoryAuditSink


async def test_record_event_writes_to_sink() -> None:
    sink = InMemoryAuditSink()
    audit_logger = AuditLogger(sinks=[sink])

    event = AuditEvent(
        event_type=AuditEventType.TOKEN_ACCESS,
        actor_user_id=1,
        action="oauth_token_access",
        target_resource="user_integrations",
        target_id="42",
        success=True,
        metadata={"provider_name": "google_calendar"},
    )

    await audit_logger.record_event(event)

    assert len(sink.events) == 1
    assert sink.events[0].event_type == AuditEventType.TOKEN_ACCESS
    assert sink.events[0].target_id == "42"


async def test_helper_methods_emit_expected_event_types() -> None:
    sink = InMemoryAuditSink()
    audit_logger = AuditLogger(sinks=[sink])

    await audit_logger.record_token_refresh(
        actor_user_id=5,
        provider_name="google_analytics",
        integration_id="abc",
        success=True,
    )
    await audit_logger.record_maintenance_hard_delete(
        actor_user_id=9,
        resource_type="qr_codes",
        resource_id="101",
        reason="gdpr cleanup",
    )

    assert [event.event_type for event in sink.events] == [
        AuditEventType.TOKEN_REFRESH,
        AuditEventType.MAINTENANCE_HARD_DELETE,
    ]
    assert sink.events[1].metadata["reason"] == "gdpr cleanup"

