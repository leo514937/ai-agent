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

    @model_validator(mode="after")
    def _validate_event_payload(self) -> StreamEventEnvelope:
        if self.event_type == StreamEventType.TRACE_STARTED:
            self._require_payload_key("workflow_version")
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
        elif self.event_type == StreamEventType.ERROR:
            for key in ("code", "message", "stage"):
                self._require_payload_key(key)
        return self

    def _require_payload_key(self, key: str) -> None:
        value = self.payload.get(key)
        if value is None:
            raise ValueError(f"{self.event_type.value}.payload.{key} is required")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{self.event_type.value}.payload.{key} is required")


def _build_envelope(
    event_type: StreamEventType | str,
    trace_id: str,
    session_id: str,
    turn_id: str,
    payload: dict[str, Any],
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    data: dict[str, Any] = {
        "event_type": event_type,
        "trace_id": trace_id,
        "session_id": session_id,
        "turn_id": turn_id,
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
    timestamp: datetime | None = None,
) -> StreamEventEnvelope:
    payload: dict[str, Any] = {"answer_text": answer_text}
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
        timestamp=timestamp,
    )


__all__ = [
    "StreamEventEnvelope",
    "StreamEventType",
    "make_error",
    "make_final",
    "make_tool_call_finished",
    "make_tool_call_started",
    "make_trace_started",
]
