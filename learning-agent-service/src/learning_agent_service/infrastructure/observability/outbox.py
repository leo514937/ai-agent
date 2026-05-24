"""Helpers for packaging async log writes into typed outbox events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from learning_agent_service.infrastructure.repositories.records import OutboxEventRecord

from .audit import AuditEnvelope, ToolObservation


@dataclass(frozen=True)
class AsyncLogWriteRequest:
    """Outbox-ready representation of an async log write."""

    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    available_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_record(self) -> OutboxEventRecord:
        return OutboxEventRecord(
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            event_type=self.event_type,
            dedupe_key=self.dedupe_key,
            payload=dict(self.payload),
            trace_id=self.trace_id,
            available_at=self.available_at,
        )


@dataclass(frozen=True)
class TypedAsyncLogEvent:
    """Typed async log envelope used by composition-root and runtime adapters."""

    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    available_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_request(self) -> AsyncLogWriteRequest:
        return AsyncLogWriteRequest(
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            event_type=self.event_type,
            dedupe_key=self.dedupe_key,
            payload=dict(self.payload),
            trace_id=self.trace_id,
            available_at=self.available_at,
        )


def normalize_async_log_request(
    entry: Mapping[str, Any] | AsyncLogWriteRequest | TypedAsyncLogEvent,
) -> AsyncLogWriteRequest:
    """Normalize legacy dict payloads and typed events into one outbox request type."""

    if isinstance(entry, AsyncLogWriteRequest):
        return entry
    if isinstance(entry, TypedAsyncLogEvent):
        return entry.to_request()

    session_id = str(entry.get("session_id") or "unknown-session")
    turn_id = str(entry.get("turn_id") or "unknown-turn")
    event_type = str(entry.get("event_type") or "log.appended")
    dedupe_key = str(entry.get("dedupe_key") or "%s:%s:%s" % (session_id, turn_id, event_type))
    aggregate_type = str(entry.get("aggregate_type") or "async_log")
    aggregate_id = str(entry.get("aggregate_id") or "%s:%s" % (session_id, turn_id))
    available_at = entry.get("available_at")
    if not isinstance(available_at, datetime):
        available_at = datetime.now(timezone.utc)
    return AsyncLogWriteRequest(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        dedupe_key=dedupe_key,
        payload=dict(entry),
        trace_id=entry.get("trace_id"),
        available_at=available_at,
    )


def build_audit_outbox_request(envelope: AuditEnvelope, aggregate_type: str, aggregate_id: str) -> AsyncLogWriteRequest:
    """Convert an audit envelope into an outbox request."""

    dedupe_key = "%s:%s:%s" % (aggregate_type, aggregate_id, envelope.event_name)
    return AsyncLogWriteRequest(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=envelope.event_name,
        dedupe_key=dedupe_key,
        payload=envelope.as_log_extra(),
        trace_id=envelope.trace_id,
    )


def build_tool_log_outbox_request(
    observation: ToolObservation,
    session_id: str,
    turn_id: str,
    payload: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> AsyncLogWriteRequest:
    """Build the canonical outbox event for asynchronous tool log persistence."""

    event_payload = dict(payload or {})
    event_payload.update(
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_name": observation.tool_name,
            "tool_call_id": observation.tool_call_id,
            "status": observation.status,
            "duration_ms": observation.duration_ms,
            "degraded_to": observation.degraded_to,
            "error_code": observation.error_code,
        }
    )
    return AsyncLogWriteRequest(
        aggregate_type="tool_invocation_log",
        aggregate_id=observation.tool_call_id,
        event_type="tool.invocation.logged",
        dedupe_key="tool:%s" % observation.tool_call_id,
        payload=event_payload,
        trace_id=trace_id,
    )
