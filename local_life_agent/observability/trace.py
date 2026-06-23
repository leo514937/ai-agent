"""Trace helpers for turn-level observability."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from time import time
from typing import Any
from uuid import uuid4


_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "prompt",
    "system_prompt",
    "messages",
    "raw_llm_response",
}

_STRING_LIMIT = 240


@dataclass
class TraceSpanRecord:
    trace_id: str
    span_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp_ms: int = field(default_factory=lambda: int(time() * 1000))
    session_id: str | None = None
    turn_id: str = ""
    stage: str = ""
    status: str = "success"
    duration_ms: int | None = None
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnTrace:
    trace_id: str
    session_id: str | None = None
    turn_id: str = ""
    user_text: str = ""
    top_intent: str | None = None
    semantic_source: str | None = None
    llm_backend: str | None = None
    llm_called: bool = False
    task_type: str | None = None
    primary_task: str | None = None
    selected_flow: str | None = None
    target_status: str | None = None
    reference_resolution_source: str | None = None
    tool_plan_source: str | None = None
    tool_plan_validated: bool | None = None
    tool_plan_fallback_reason: str | None = None
    tool_plan_reason: str | None = None
    candidate_count: int = 0
    decision_type: str | None = None
    tool_call_count: int = 0
    answer_source: str | None = None
    answer_verify_passed: bool | None = None
    answer_verify_violations: list[str] = field(default_factory=list)
    rewrite_count: int = 0
    fallback_reason: str | None = None
    final_safety_status: str | None = None
    total_duration_ms: int | None = None
    llm_duration_ms: int = 0
    tool_duration_ms: int = 0
    verifier_duration_ms: int = 0
    events: list[TraceSpanRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["events"] = [event.to_dict() for event in self.events]
        return payload


_TRACE_SPANS: dict[str, list[TraceSpanRecord]] = {}
_TRACE_LOCK = Lock()


def _sanitize_string(value: str) -> str:
    if len(value) <= _STRING_LIMIT:
        return value
    return f"{value[:_STRING_LIMIT]}...(truncated)"


def sanitize_payload(value: Any, *, key_hint: str = "") -> Any:
    lowered = key_hint.lower()
    if lowered in _SENSITIVE_KEYS or any(token in lowered for token in ("api_key", "authorization")):
        return "<redacted>"
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:
            return "<unserializable>"
    if isinstance(value, dict):
        return {
            str(k): sanitize_payload(v, key_hint=str(k))
            for k, v in value.items()
            if not str(k).startswith("_")
        }
    if isinstance(value, list):
        return [sanitize_payload(item, key_hint=key_hint) for item in value[:20]]
    if isinstance(value, tuple):
        return [sanitize_payload(item, key_hint=key_hint) for item in value[:20]]
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return sanitize_payload(vars(value), key_hint=key_hint)
    return _sanitize_string(str(value))


def new_trace_id() -> str:
    """Generate a unique trace ID for a request."""
    return f"trace_{uuid4().hex}"


def record_span(trace_id: str, span_name: str, metadata: dict | None = None) -> None:
    """Record a span in the current trace."""
    if not trace_id or not span_name:
        return
    raw_metadata = dict(metadata or {})
    record = TraceSpanRecord(
        trace_id=trace_id,
        span_name=span_name,
        metadata=sanitize_payload(raw_metadata),
        session_id=raw_metadata.get("session_id"),
        turn_id=str(raw_metadata.get("turn_id", "") or ""),
        stage=str(raw_metadata.get("stage", span_name) or span_name),
        status=str(raw_metadata.get("status", "success") or "success"),
        duration_ms=_coerce_int(raw_metadata.get("duration_ms")),
        input_summary=_coerce_dict(raw_metadata.get("input_summary")),
        output_summary=_coerce_dict(raw_metadata.get("output_summary")),
        error_code=_coerce_optional_str(raw_metadata.get("error_code")),
        error_message=_coerce_optional_str(raw_metadata.get("error_message")),
    )
    with _TRACE_LOCK:
        _TRACE_SPANS.setdefault(trace_id, []).append(record)


def get_trace_spans(trace_id: str) -> list[TraceSpanRecord]:
    with _TRACE_LOCK:
        return list(_TRACE_SPANS.get(trace_id, []))


def reset_trace_store() -> None:
    with _TRACE_LOCK:
        _TRACE_SPANS.clear()


def build_turn_trace(final_state: dict[str, Any], *, user_text: str = "", total_duration_ms: int | None = None) -> TurnTrace:
    trace_id = str(final_state.get("trace_id", "") or "")
    events = get_trace_spans(trace_id)
    if not events:
        events = _events_from_event_log(final_state)
    semantic_frame = _coerce_dict(final_state.get("semantic_frame"))
    execution_plan = _coerce_dict(final_state.get("execution_plan"))
    evidence_pack = _coerce_dict(final_state.get("evidence_pack"))
    resolved_target = _coerce_dict(final_state.get("resolved_target") or final_state.get("resolve_shop_result"))
    comparison_result = _coerce_dict(final_state.get("comparison_result"))
    task_type = _coerce_optional_str(final_state.get("task_type")) or _coerce_optional_str(semantic_frame.get("task_type"))
    selected_flow = _infer_selected_flow(task_type, resolved_target, comparison_result)
    decision_type = (
        _coerce_optional_str(evidence_pack.get("decision_type"))
        or _coerce_optional_str(execution_plan.get("decision_type"))
        or _coerce_optional_str(final_state.get("decision_type"))
        or _infer_decision_type(task_type, evidence_pack)
    )
    candidate_count = _infer_candidate_count(evidence_pack, final_state)
    tool_call_count = _infer_tool_call_count(execution_plan, final_state)
    turn_trace = TurnTrace(
        trace_id=trace_id,
        session_id=_coerce_optional_str(final_state.get("session_id")),
        turn_id=str(final_state.get("turn_id", "") or ""),
        user_text=user_text or str(final_state.get("raw_text", "") or ""),
        top_intent=_coerce_optional_str(final_state.get("top_intent")) or _coerce_optional_str(semantic_frame.get("top_intent")),
        semantic_source=_coerce_optional_str(final_state.get("semantic_source")) or _coerce_optional_str(semantic_frame.get("semantic_source")),
        llm_backend=_coerce_optional_str(final_state.get("llm_backend")) or _coerce_optional_str(semantic_frame.get("llm_backend")),
        llm_called=bool(final_state.get("llm_called", False) or semantic_frame.get("llm_called", False)),
        task_type=task_type,
        primary_task=_coerce_optional_str(semantic_frame.get("primary_task")),
        selected_flow=selected_flow,
        target_status=_coerce_optional_str(resolved_target.get("status")),
        reference_resolution_source=_infer_reference_resolution_source(final_state, semantic_frame),
        tool_plan_source=_coerce_optional_str(final_state.get("tool_plan_source")),
        tool_plan_validated=_coerce_optional_bool(final_state.get("tool_plan_validated")),
        tool_plan_fallback_reason=_coerce_optional_str(final_state.get("tool_plan_fallback_reason")),
        tool_plan_reason=_coerce_optional_str(final_state.get("tool_plan_reason")),
        candidate_count=candidate_count,
        decision_type=decision_type,
        tool_call_count=tool_call_count,
        answer_source=_coerce_optional_str(final_state.get("answer_source")),
        answer_verify_passed=_coerce_optional_bool(final_state.get("answer_verify_passed")),
        answer_verify_violations=[str(item) for item in (final_state.get("answer_verify_violations") or []) if str(item).strip()],
        rewrite_count=int(final_state.get("rewrite_count", 0) or 0),
        fallback_reason=_coerce_optional_str(final_state.get("fallback_reason")),
        final_safety_status=_coerce_optional_str(final_state.get("final_safety_status")),
        total_duration_ms=total_duration_ms,
        llm_duration_ms=sum(event.duration_ms or 0 for event in events if event.stage in {"semantic_parse", "top_intent_router", "llm_verbalizer", "answer_generate"}),
        tool_duration_ms=sum(event.duration_ms or 0 for event in events if event.stage == "tool_call"),
        verifier_duration_ms=sum(event.duration_ms or 0 for event in events if event.stage == "answer_verify"),
        events=events,
    )
    return turn_trace


def _events_from_event_log(final_state: dict[str, Any]) -> list[TraceSpanRecord]:
    trace_id = str(final_state.get("trace_id", "") or "")
    session_id = _coerce_optional_str(final_state.get("session_id"))
    turn_id = str(final_state.get("turn_id", "") or "")
    events: list[TraceSpanRecord] = []
    for item in final_state.get("event_log", []) or []:
        if not isinstance(item, dict):
            continue
        event = TraceSpanRecord(
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn_id,
            span_name=str(item.get("node", "") or "unknown"),
            stage=str(item.get("stage", item.get("node", "unknown")) or "unknown"),
            status=str(item.get("status", "success") or "success"),
            timestamp_ms=_coerce_int(item.get("timestamp_ms")) or int(time() * 1000),
            duration_ms=_coerce_int(item.get("duration_ms")),
            input_summary=_coerce_dict(item.get("input_summary")),
            output_summary=_coerce_dict(item.get("output_summary")),
            error_code=_coerce_optional_str(item.get("error_code")),
            error_message=_coerce_optional_str(item.get("error_message")),
            metadata=_coerce_dict(item.get("metadata") or item),
        )
        events.append(event)
    return events


def _infer_selected_flow(task_type: str | None, resolved_target: dict[str, Any], comparison_result: dict[str, Any]) -> str | None:
    reason = _coerce_optional_str(resolved_target.get("reason"))
    if reason == "recommendation_flow":
        return "recommendation_flow"
    if reason == "recommendation_refine":
        return "recommendation_refine_flow"
    if reason == "comparison_targets_resolved" or comparison_result.get("mode") == "comparison":
        return "comparison_flow"
    if task_type == "comparison":
        return "comparison_flow"
    if task_type == "recommendation":
        return "recommendation_flow"
    if task_type:
        return f"{task_type}_flow"
    return None


def _infer_reference_resolution_source(final_state: dict[str, Any], semantic_frame: dict[str, Any]) -> str | None:
    explicit_source = _coerce_optional_str(final_state.get("reference_resolution_source"))
    if explicit_source:
        return explicit_source
    comparison_target_resolution = _coerce_dict(final_state.get("comparison_target_resolution"))
    if comparison_target_resolution:
        return "semantic_frame"
    if semantic_frame.get("ordinal_references") or semantic_frame.get("deictic_references"):
        return "semantic_frame"
    current_shop = _coerce_dict(final_state.get("current_shop"))
    if current_shop:
        return "session_state"
    return "raw_text_fallback"


def _infer_candidate_count(evidence_pack: dict[str, Any], final_state: dict[str, Any]) -> int:
    ranking_snapshot = _coerce_dict(evidence_pack.get("ranking_snapshot"))
    comparison_matrix = _coerce_dict(evidence_pack.get("comparison_matrix"))
    if ranking_snapshot.get("candidate_count") is not None:
        return int(ranking_snapshot.get("candidate_count") or 0)
    ranked = ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or []
    if ranked:
        return len(ranked)
    rows = comparison_matrix.get("rows") or []
    if rows:
        return len(rows)
    recommendation_candidates = final_state.get("recommendation_candidates") or []
    if recommendation_candidates:
        return len(recommendation_candidates)
    comparison_targets = final_state.get("comparison_targets") or []
    if comparison_targets:
        return len(comparison_targets)
    return int(final_state.get("candidate_count", 0) or 0)


def _infer_tool_call_count(execution_plan: dict[str, Any], final_state: dict[str, Any]) -> int:
    tool_calls = execution_plan.get("tool_calls") or []
    if tool_calls:
        return len(tool_calls)
    tool_results = _coerce_dict(final_state.get("tool_result_set") or final_state.get("tool_results"))
    return len(tool_results)


def _infer_decision_type(task_type: str | None, evidence_pack: dict[str, Any]) -> str | None:
    if _coerce_dict(evidence_pack.get("comparison_matrix")).get("rows"):
        return "comparison"
    if _coerce_dict(evidence_pack.get("ranking_snapshot")).get("ranked") or task_type == "recommendation":
        return "recommendation"
    if task_type:
        return task_type
    return None


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return sanitize_payload(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            return sanitize_payload(dumped) if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    return {}


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = getattr(value, "value")
    text = str(value).strip()
    return text or None


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except Exception:
        return None
