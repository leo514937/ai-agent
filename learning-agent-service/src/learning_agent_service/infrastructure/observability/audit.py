"""Structured observability payloads shared by logging and async outbox writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AuditEnvelope:
    """A normalized audit event that can be logged or pushed to the outbox."""

    event_name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    level: str = "INFO"
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    emitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_log_extra(self) -> Dict[str, Any]:
        return {
            "audit_event": self.event_name,
            "audit_level": self.level,
            "audit_payload": dict(self.payload),
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "emitted_at": self.emitted_at.isoformat(),
        }


@dataclass(frozen=True)
class RetrievalObservation:
    """Retrieval metrics that should remain consistent across logs and outbox writes."""

    retrieval_strategy: str
    retrieval_hit_count: int = 0
    retrieval_top_score: float = 0.0
    evidence_used_count: int = 0
    degraded_to: Optional[str] = None


@dataclass(frozen=True)
class ToolObservation:
    """Tool execution metrics used by async tool invocation logging."""

    tool_name: str
    tool_call_id: str
    status: str
    duration_ms: Optional[int] = None
    degraded_to: Optional[str] = None
    error_code: Optional[str] = None
