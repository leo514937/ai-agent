"""Streaming event DTOs and factories.

This module only defines the contract objects used by observability and
frontend consumers. It does not perform any HTTP/SSE writing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..domain.enums import ToolResultStatus


class StreamEventType(str, Enum):
    TRACE_STARTED = "trace_started"
    INPUT_NORMALIZED = "input_normalized"
    STATUS = "status"
    PREVIEW = "preview"
    EVIDENCE_UPDATE = "evidence_update"
    FALLBACK = "fallback"
    PENDING_CLARIFICATION_CHECKED = "pending_clarification_checked"
    HARD_GUARD_HIT = "hard_guard_hit"
    INTENT_DETECTED = "intent_detected"
    SEMANTIC_FRAME_READY = "semantic_frame_ready"
    TARGET_RESOLVED = "target_resolved"
    CLARIFY_REQUESTED = "clarify_requested"
    TASK_PLANNED = "task_planned"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    EVIDENCE_BUILT = "evidence_built"
    ANSWER_PLAN_BUILT = "answer_plan_built"
    ANSWER_DELTA = "answer_delta"
    FINAL = "final"
    ERROR = "error"


_ALLOWED_TOOL_STATUSES = {status.value for status in ToolResultStatus}


class StreamEventEnvelope(BaseModel):
    """Unified event envelope shared by the streaming layer."""

    model_config = ConfigDict(extra="forbid")

    event_type: StreamEventType
    trace_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    span_id: str | None = None
    workflow_name: str | None = None
    stage: str | None = None
    message: str | None = None
    facets: list[str] = Field(default_factory=list)
    partial: bool = False
    verified: bool = False
    evidence_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("event_type", mode="before")
    @classmethod
    def _coerce_legacy_ack(cls, value: Any) -> Any:
        if value == "ack":
            return StreamEventType.TRACE_STARTED
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def _ensure_payload_dict(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("payload must be a dict")
        return value

    @field_validator("facets", mode="before")
    @classmethod
    def _ensure_facets_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(item).strip() for item in value if str(item).strip()]

    @model_validator(mode="after")
    def _validate_event_payload(self) -> StreamEventEnvelope:
        if self.event_type == StreamEventType.TRACE_STARTED:
            self._require_payload_key("workflow_version")
        elif self.event_type == StreamEventType.STATUS:
            self._require_payload_key("status")
            self.partial = True
            self.verified = False
        elif self.event_type == StreamEventType.PREVIEW:
            self._require_payload_key("text")
            verified = self.payload.get("verified")
            if not isinstance(verified, bool):
                raise ValueError("preview.payload.verified is required")
            self.partial = True
            self.verified = bool(verified)
        elif self.event_type == StreamEventType.EVIDENCE_UPDATE:
            has_items = bool(self.payload.get("evidence_items"))
            has_summary = bool(str(self.payload.get("summary", "") or "").strip())
            if not (has_items or has_summary):
                raise ValueError("evidence_update.payload.evidence_items or summary is required")
            self.partial = True
            self.verified = False
        elif self.event_type == StreamEventType.FALLBACK:
            self._require_payload_key("reason")
            self.partial = False
            self.verified = False
        elif self.event_type == StreamEventType.TOOL_CALL_FINISHED:
            status = self.payload.get("status")
            if isinstance(status, ToolResultStatus):
                status = status.value
            if status not in _ALLOWED_TOOL_STATUSES:
                raise ValueError(
                    "tool_call_finished.payload.status must be one of "
                    f"{sorted(_ALLOWED_TOOL_STATUSES)}"
                )
        elif self.event_type == StreamEventType.FINAL:
            answer_text = self.payload.get("answer_text")
            if not isinstance(answer_text, str) or not answer_text.strip():
                raise ValueError("final.payload.answer_text is required")
            verified = self.payload.get("verified")
            if verified is not True:
                raise ValueError("final.payload.verified must be true")
            self.partial = False
            self.verified = True
        elif self.event_type == StreamEventType.ERROR:
            for key in ("code", "message", "stage"):
                self._require_payload_key(key)
            self.partial = False
            self.verified = False
        return self

    def _require_payload_key(self, key: str) -> None:
        value = self.payload.get(key)
        if value is None:
            raise ValueError(f"{self.event_type.value}.payload.{key} is required")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{self.event_type.value}.payload.{key} is required")

    @property
    def type(self) -> StreamEventType:
        return self.event_type


def _build_envelope(
    event_type: StreamEventType | str,
    trace_id: str,
    session_id: str,
    turn_id: str,
    payload: dict[str, Any],
    *,
    span_id: str | None = None,
    workflow_name: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    facets: list[str] | None = None,
    partial: bool = False,
    verified: bool = False,
    evidence_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    data: dict[str, Any] = {
        "event_type": event_type,
        "trace_id": trace_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "span_id": span_id,
        "workflow_name": workflow_name,
        "stage": stage,
        "message": message,
        "facets": facets or [],
        "partial": partial,
        "verified": verified,
        "evidence_ref": evidence_ref,
        "metadata": metadata or {},
        "payload": payload,
    }
    if timestamp is not None:
        data["timestamp"] = timestamp
    return StreamEventEnvelope.model_validate(data)


def make_trace_started(
    trace_id: str,
    session_id: str,
    turn_id: str,
    workflow_version: str,
    *,
    page: str | None = None,
    user_id: str | None = None,
    workflow_name: str | None = None,
    span_id: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {"workflow_version": workflow_version}
    if page is not None:
        payload["page"] = page
    if user_id is not None:
        payload["user_id"] = user_id
    return _build_envelope(
        StreamEventType.TRACE_STARTED,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage="trace_started",
        message="trace_started",
        partial=False,
        verified=False,
        metadata={"workflow_version": workflow_version, "page": page, "user_id": user_id},
        timestamp=timestamp,
    )


def make_status(
    trace_id: str,
    session_id: str,
    turn_id: str,
    status: str,
    *,
    stage: str | None = None,
    detail: dict[str, Any] | None = None,
    workflow_name: str | None = None,
    span_id: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {"status": status}
    if stage is not None:
        payload["stage"] = stage
    if detail is not None:
        payload["detail"] = detail
    return _build_envelope(
        StreamEventType.STATUS,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage=stage or "status",
        message=status,
        partial=True,
        verified=False,
        metadata=detail or {},
        timestamp=timestamp,
    )


def make_preview(
    trace_id: str,
    session_id: str,
    turn_id: str,
    text: str,
    *,
    verified: bool = False,
    preview_kind: str = "fast_preview",
    source: str | None = None,
    workflow_name: str | None = None,
    span_id: str | None = None,
    facets: list[str] | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {
        "text": text,
        "verified": verified,
        "preview_kind": preview_kind,
    }
    if source is not None:
        payload["source"] = source
    return _build_envelope(
        StreamEventType.PREVIEW,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage="preview",
        message=text,
        facets=facets or [],
        partial=True,
        verified=verified,
        metadata={"preview_kind": preview_kind, "source": source},
        timestamp=timestamp,
    )


def make_evidence_update(
    trace_id: str,
    session_id: str,
    turn_id: str,
    *,
    evidence_items: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    cache_key: str | None = None,
    cache_hit: bool | None = None,
    workflow_name: str | None = None,
    span_id: str | None = None,
    evidence_ref: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {}
    if evidence_items is not None:
        payload["evidence_items"] = evidence_items
    if summary is not None:
        payload["summary"] = summary
    if cache_key is not None:
        payload["cache_key"] = cache_key
    if cache_hit is not None:
        payload["cache_hit"] = cache_hit
    return _build_envelope(
        StreamEventType.EVIDENCE_UPDATE,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage="evidence_update",
        message=summary,
        partial=True,
        verified=False,
        evidence_ref=evidence_ref or cache_key,
        metadata={"cache_key": cache_key, "cache_hit": cache_hit},
        timestamp=timestamp,
    )


def make_fallback(
    trace_id: str,
    session_id: str,
    turn_id: str,
    reason: str,
    *,
    message: str | None = None,
    workflow_name: str | None = None,
    span_id: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {"reason": reason}
    if message is not None:
        payload["message"] = message
    return _build_envelope(
        StreamEventType.FALLBACK,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage="fallback",
        message=message or reason,
        partial=False,
        verified=False,
        metadata={"reason": reason},
        timestamp=timestamp,
    )


def make_tool_call_started(
    trace_id: str,
    session_id: str,
    turn_id: str,
    call_id: str,
    tool_name: str,
    *,
    target_shop_id: str | None = None,
    required: bool | None = None,
    facet: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {
        "call_id": call_id,
        "tool_name": tool_name,
    }
    if target_shop_id is not None:
        payload["target_shop_id"] = target_shop_id
    if required is not None:
        payload["required"] = required
    if facet is not None:
        payload["facet"] = facet
    return _build_envelope(
        StreamEventType.TOOL_CALL_STARTED,
        trace_id,
        session_id,
        turn_id,
        payload,
        timestamp=timestamp,
    )


def make_tool_call_finished(
    trace_id: str,
    session_id: str,
    turn_id: str,
    call_id: str,
    tool_name: str,
    status: ToolResultStatus | str,
    *,
    result_status: ToolResultStatus | str | None = None,
    error_code: str | None = None,
    degraded: bool | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {
        "call_id": call_id,
        "tool_name": tool_name,
        "status": status.value if isinstance(status, ToolResultStatus) else status,
    }
    if result_status is not None:
        payload["result_status"] = (
            result_status.value if isinstance(result_status, ToolResultStatus) else result_status
        )
    if error_code is not None:
        payload["error_code"] = error_code
    if degraded is not None:
        payload["degraded"] = degraded
    return _build_envelope(
        StreamEventType.TOOL_CALL_FINISHED,
        trace_id,
        session_id,
        turn_id,
        payload,
        timestamp=timestamp,
    )


def make_final(
    trace_id: str,
    session_id: str,
    turn_id: str,
    answer_text: str,
    *,
    cards: list[dict[str, Any]] | None = None,
    next_steps: list[str] | None = None,
    verified: bool = True,
    workflow_name: str | None = None,
    span_id: str | None = None,
    facets: list[str] | None = None,
    evidence_ref: str | None = None,
    fallback_reason: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {"answer_text": answer_text, "verified": verified}
    if cards is not None:
        payload["cards"] = cards
    if next_steps is not None:
        payload["next_steps"] = next_steps
    return _build_envelope(
        StreamEventType.FINAL,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage="final",
        message=answer_text,
        facets=facets or [],
        partial=False,
        verified=verified,
        evidence_ref=evidence_ref,
        metadata={"fallback_reason": fallback_reason},
        timestamp=timestamp,
    )


def make_error(
    trace_id: str,
    session_id: str,
    turn_id: str,
    code: str,
    message: str,
    stage: str,
    *,
    retryable: bool | None = None,
    detail: dict[str, Any] | None = None,
    workflow_name: str | None = None,
    span_id: str | None = None,
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "stage": stage,
    }
    if retryable is not None:
        payload["retryable"] = retryable
    if detail is not None:
        payload["detail"] = detail
    return _build_envelope(
        StreamEventType.ERROR,
        trace_id,
        session_id,
        turn_id,
        payload,
        span_id=span_id,
        workflow_name=workflow_name,
        stage=stage,
        message=message,
        partial=False,
        verified=False,
        metadata=detail or {},
        timestamp=timestamp,
    )


__all__ = [
    "StreamEventEnvelope",
    "StreamEventType",
    "make_evidence_update",
    "make_error",
    "make_final",
    "make_fallback",
    "make_preview",
    "make_status",
    "make_tool_call_finished",
    "make_tool_call_started",
    "make_trace_started",
]
