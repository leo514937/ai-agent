"""Trace helpers for turn-level observability."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from time import time
from typing import Any
from uuid import uuid4

from .. import config


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
    top_intent_source: str | None = None
    top_intent_router_llm_available: bool | None = None
    top_intent_router_backend: str | None = None
    top_intent_router_error_type: str | None = None
    top_intent_router_error_message: str | None = None
    semantic_source: str | None = None
    llm_backend: str | None = None
    llm_backend_kind: str | None = None
    llm_backend_family: str | None = None
    tool_backend: str | None = None
    llm_called: bool = False
    task_type: str | None = None
    primary_task: str | None = None
    selected_flow: str | None = None
    target_status: str | None = None
    target_resolve_status: str | None = None
    reference_resolution_source: str | None = None
    candidate_count: int = 0
    candidate_status: str | None = None
    candidate_source: str | None = None
    candidate_query: str | None = None
    merchant_mentions: list[str] = field(default_factory=list)
    ambiguous_candidate_count: int = 0
    ambiguous_candidates: list[dict[str, Any]] = field(default_factory=list)
    decision_type: str | None = None
    tool_call_count: int = 0
    resolver_tool_called: bool = False
    resolver_tool_name: str | None = None
    resolver_tool_backend: str | None = None
    resolver_tool_result_count: int = 0
    resolver_error_type: str | None = None
    resolver_error_message: str | None = None
    answer_source: str | None = None
    answer_verify_passed: bool | None = None
    answer_verify_violations: list[str] = field(default_factory=list)
    verifier_result: str | None = None
    verifier_failure_code: str | None = None
    verifier_unknown_fields: list[str] = field(default_factory=list)
    verifier_unsupported_claims: list[str] = field(default_factory=list)
    verifier_false_fields: list[str] = field(default_factory=list)
    verifier_recoverable: bool | None = None
    rewrite_count: int = 0
    fallback_reason: str | None = None
    fallback_used: bool = False
    template_fallback_used: bool = False
    raw_text_fallback_source: str | None = None
    legacy_used: bool = False
    evidence_incomplete: bool = False
    final_safety_status: str | None = None
    total_duration_ms: int | None = None
    llm_duration_ms: int = 0
    tool_duration_ms: int = 0
    verifier_duration_ms: int = 0
    events: list[TraceSpanRecord] = field(default_factory=list)
    session_before_current_shop: Any | None = None
    session_before_last_recommendation_list_count: int = 0

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
    event_log_events = _events_from_event_log(final_state)
    if events:
        seen = {
            (
                event.span_name,
                event.stage,
                event.timestamp_ms,
                event.status,
                event.duration_ms,
            )
            for event in events
        }
        for event in event_log_events:
            key = (event.span_name, event.stage, event.timestamp_ms, event.status, event.duration_ms)
            if key not in seen:
                events.append(event)
                seen.add(key)
    else:
        events = event_log_events
    semantic_frame = _coerce_dict(final_state.get("semantic_frame"))
    execution_plan = _coerce_dict(final_state.get("execution_plan"))
    evidence_pack = _coerce_dict(final_state.get("evidence_pack"))
    resolved_target = _coerce_dict(final_state.get("resolved_target") or final_state.get("resolve_shop_result"))
    comparison_result = _coerce_dict(final_state.get("comparison_result"))
    target_resolve_event = _find_event(events, "target_resolve")
    target_resolve_metadata = _coerce_dict(target_resolve_event.metadata if target_resolve_event else {})
    session_before = _coerce_dict(final_state.get("session_state_before"))
    task_type = _coerce_optional_str(final_state.get("task_type")) or _coerce_optional_str(semantic_frame.get("task_type"))
    merchant_mentions = [str(item).strip() for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    selected_flow = _infer_selected_flow(task_type, resolved_target, comparison_result)
    decision_type = (
        _coerce_optional_str(evidence_pack.get("decision_type"))
        or _coerce_optional_str(execution_plan.get("decision_type"))
        or _coerce_optional_str(final_state.get("decision_type"))
        or _infer_decision_type(task_type, evidence_pack)
    )
    candidate_count = _infer_candidate_count(evidence_pack, final_state)
    candidate_source = _coerce_optional_str(target_resolve_metadata.get("candidate_source")) or _coerce_optional_str(semantic_frame.get("candidate_source")) or _coerce_optional_str(semantic_frame.get("candidate_source_origin"))
    if not candidate_source:
        hard_constraints = _coerce_dict(semantic_frame.get("hard_constraints"))
        if task_type == "recommendation" or _coerce_optional_str(semantic_frame.get("candidate_category")) or _coerce_optional_str(hard_constraints.get("category")):
            candidate_source = "discovery"
        elif merchant_mentions:
            candidate_source = "explicit"
        elif _coerce_dict(semantic_frame.get("follow_up")):
            candidate_source = "mixed"
    target_resolve_status = _coerce_optional_str(target_resolve_metadata.get("status")) or _coerce_optional_str(target_resolve_event.status if target_resolve_event else None) or _coerce_optional_str(final_state.get("target_status"))
    candidate_query = _infer_candidate_query(semantic_frame, final_state, candidate_source)
    ambiguous_candidate_count = _infer_ambiguous_candidate_count(target_resolve_metadata, candidate_count, target_resolve_status)
    ambiguous_candidates = _infer_ambiguous_candidates(final_state, target_resolve_metadata)
    resolver_tool_called = target_resolve_event is not None
    resolver_tool_name = _infer_resolver_tool_name(candidate_source, semantic_frame)
    resolver_tool_backend = _infer_resolver_tool_backend(resolver_tool_called, final_state)
    resolver_tool_result_count = candidate_count if resolver_tool_called else 0
    resolver_error_type, resolver_error_message = _infer_resolver_error(target_resolve_metadata, target_resolve_status)
    llm_backend = _coerce_optional_str(final_state.get("llm_backend")) or _coerce_optional_str(semantic_frame.get("llm_backend"))
    tool_call_count = _infer_tool_call_count(execution_plan, final_state)
    turn_trace = TurnTrace(
        trace_id=trace_id,
        session_id=_coerce_optional_str(final_state.get("session_id")),
        turn_id=str(final_state.get("turn_id", "") or ""),
        user_text=user_text or str(final_state.get("raw_text", "") or ""),
        top_intent=_coerce_optional_str(final_state.get("top_intent")) or _coerce_optional_str(semantic_frame.get("top_intent")),
        top_intent_source=_coerce_optional_str(final_state.get("top_intent_source")) or _coerce_optional_str(semantic_frame.get("top_intent_source")),
        top_intent_router_llm_available=_coerce_optional_bool(final_state.get("top_intent_router_llm_available")),
        top_intent_router_backend=_coerce_optional_str(final_state.get("top_intent_router_backend")),
        top_intent_router_error_type=_coerce_optional_str(final_state.get("top_intent_router_error_type")),
        top_intent_router_error_message=_coerce_optional_str(final_state.get("top_intent_router_error_message")),
        semantic_source=_coerce_optional_str(final_state.get("semantic_source")) or _coerce_optional_str(semantic_frame.get("semantic_source")),
        llm_backend=llm_backend,
        llm_backend_kind=_infer_llm_backend_kind(llm_backend),
        llm_backend_family=_infer_llm_backend_family(llm_backend),
        tool_backend=_infer_tool_backend(final_state, evidence_pack, events),
        llm_called=bool(final_state.get("llm_called", False) or semantic_frame.get("llm_called", False)),
        task_type=task_type,
        primary_task=_coerce_optional_str(semantic_frame.get("primary_task")),
        selected_flow=selected_flow,
        target_status=_coerce_optional_str(resolved_target.get("status")),
        target_resolve_status=target_resolve_status,
        reference_resolution_source=_infer_reference_resolution_source(final_state, semantic_frame),
        candidate_count=candidate_count,
        candidate_status=_coerce_optional_str(final_state.get("candidate_status")) or target_resolve_status,
        candidate_source=candidate_source,
        candidate_query=candidate_query,
        merchant_mentions=merchant_mentions,
        ambiguous_candidate_count=ambiguous_candidate_count,
        ambiguous_candidates=ambiguous_candidates,
        decision_type=decision_type,
        tool_call_count=tool_call_count,
        resolver_tool_called=resolver_tool_called,
        resolver_tool_name=resolver_tool_name,
        resolver_tool_backend=resolver_tool_backend,
        resolver_tool_result_count=resolver_tool_result_count,
        resolver_error_type=resolver_error_type,
        resolver_error_message=resolver_error_message,
        answer_source=_coerce_optional_str(final_state.get("answer_source")),
        answer_verify_passed=_coerce_optional_bool(final_state.get("answer_verify_passed")),
        answer_verify_violations=[str(item) for item in (final_state.get("answer_verify_violations") or []) if str(item).strip()],
        verifier_result=_coerce_optional_str(final_state.get("verifier_result")) or (
            "pass" if _coerce_optional_bool(final_state.get("answer_verify_passed")) else "fail" if final_state.get("answer_verify_passed") is not None else None
        ),
        verifier_failure_code=_coerce_optional_str(final_state.get("verifier_failure_code")),
        verifier_unknown_fields=[str(item) for item in (final_state.get("verifier_unknown_fields") or []) if str(item).strip()],
        verifier_unsupported_claims=[str(item) for item in (final_state.get("verifier_unsupported_claims") or []) if str(item).strip()],
        verifier_false_fields=[str(item) for item in (final_state.get("verifier_false_fields") or []) if str(item).strip()],
        verifier_recoverable=_coerce_optional_bool(final_state.get("verifier_recoverable")),
        rewrite_count=int(final_state.get("rewrite_count", 0) or 0),
        fallback_reason=_coerce_optional_str(final_state.get("fallback_reason")),
        fallback_used=_infer_fallback_used(final_state, semantic_frame),
        template_fallback_used=_coerce_optional_bool(final_state.get("template_fallback_used")),
        raw_text_fallback_source=_coerce_optional_str(final_state.get("raw_text_fallback_source")),
        legacy_used=_infer_legacy_used(final_state, events),
        evidence_incomplete=_infer_evidence_incomplete(final_state),
        final_safety_status=_coerce_optional_str(final_state.get("final_safety_status")),
        total_duration_ms=total_duration_ms,
        llm_duration_ms=sum(event.duration_ms or 0 for event in events if event.stage in {"semantic_parse", "top_intent_router", "llm_verbalizer", "answer_generate"}),
        tool_duration_ms=sum(event.duration_ms or 0 for event in events if event.stage == "tool_call"),
        verifier_duration_ms=sum(event.duration_ms or 0 for event in events if event.stage == "answer_verify"),
        events=events,
        session_before_current_shop=session_before.get("current_shop"),
        session_before_last_recommendation_list_count=len(session_before.get("last_recommendation_list") or []),
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
    for event in _coerce_event_list(final_state):
        if event.span_name == "target_resolve":
            meta = _coerce_dict(event.metadata)
            if meta.get("candidate_count") is not None:
                return int(meta.get("candidate_count") or 0)
    return int(final_state.get("candidate_count", 0) or 0)


def _infer_candidate_query(semantic_frame: dict[str, Any], final_state: dict[str, Any], candidate_source: str | None) -> str | None:
    merchant_mentions = [str(item).strip() for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    if candidate_source in {"explicit", "mixed", "context"} and merchant_mentions:
        return "、".join(merchant_mentions)
    if candidate_source == "discovery":
        candidate_category = _coerce_optional_str(semantic_frame.get("candidate_category"))
        if candidate_category:
            return candidate_category
        hard_constraints = _coerce_dict(semantic_frame.get("hard_constraints"))
        candidate_category = _coerce_optional_str(hard_constraints.get("category"))
        if candidate_category:
            return candidate_category
        raw_text = _coerce_optional_str(final_state.get("raw_text"))
        if raw_text:
            stripped = raw_text
            for prefix in ("附近推荐几家", "附近推荐", "附近有没有", "推荐几家", "推荐几个", "帮我推荐几家"):
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    break
            stripped = stripped.strip(" ，,。?？")
            if stripped:
                return stripped
    raw_text = _coerce_optional_str(final_state.get("raw_text"))
    if raw_text:
        return raw_text
    return _coerce_optional_str(semantic_frame.get("primary_task"))


def _infer_ambiguous_candidate_count(metadata: dict[str, Any], candidate_count: int, target_resolve_status: str | None) -> int:
    if target_resolve_status == "AMBIGUOUS":
        return int(metadata.get("candidate_count") or candidate_count or 0)
    if target_resolve_status in {"LOW_CONFIDENCE", "NEED_CLARIFICATION"} and "ambiguous" in str(metadata.get("reason", "")).lower():
        return int(metadata.get("candidate_count") or candidate_count or 0)
    return 0


def _infer_ambiguous_candidates(final_state: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("ambiguous_candidates", "candidate_set", "effective_candidate_set"):
        value = _coerce_dict(final_state.get(key))
        if value:
            candidates = value.get("candidates") or value.get("items") or []
            if isinstance(candidates, list):
                return [item for item in candidates if isinstance(item, dict)]
    candidates = metadata.get("candidates") or []
    if isinstance(candidates, list):
        return [item for item in candidates if isinstance(item, dict)]
    return []


def _infer_resolver_tool_name(candidate_source: str | None, semantic_frame: dict[str, Any]) -> str | None:
    if candidate_source in {"explicit", "context"}:
        return "resolve_shop"
    if candidate_source == "discovery":
        return "search_shops"
    if candidate_source == "mixed":
        return "resolve_shop+search_shops"
    if semantic_frame.get("candidate_category") or _coerce_dict(semantic_frame.get("hard_constraints")).get("category"):
        return "search_shops"
    if semantic_frame.get("merchant_mentions"):
        return "resolve_shop"
    return None


def _infer_resolver_tool_backend(resolver_tool_called: bool, final_state: dict[str, Any]) -> str | None:
    if not resolver_tool_called:
        return None
    backend = _coerce_optional_str(final_state.get("tool_backend"))
    if backend:
        return backend
    return config.TOOL_BACKEND


def _infer_resolver_error(metadata: dict[str, Any], target_resolve_status: str | None) -> tuple[str | None, str | None]:
    reason = _coerce_optional_str(metadata.get("reason"))
    if target_resolve_status == "AMBIGUOUS":
        return "AMBIGUOUS", reason
    if target_resolve_status == "NOT_FOUND":
        return "NOT_FOUND", reason
    if reason and "not found" in reason.lower():
        return "NOT_FOUND", reason
    return None, reason


def _infer_llm_backend_kind(llm_backend: str | None) -> str | None:
    if not llm_backend:
        return None
    lowered = llm_backend.lower()
    if lowered in {"real_llm", "fake_llm", "rule_based", "spy", "spy_llm", "spy_real_llm"}:
        return lowered
    if any(token in lowered for token in ("fake", "spy", "rule_based")):
        return lowered.split("/", 1)[0]
    if "/" in llm_backend:
        return "real_llm"
    return llm_backend


def _infer_llm_backend_family(llm_backend: str | None) -> str | None:
    if not llm_backend:
        return None
    if "/" in llm_backend:
        return llm_backend.split("/", 1)[0]
    return llm_backend


def _find_event(events: list[TraceSpanRecord], span_name: str) -> TraceSpanRecord | None:
    for event in reversed(events):
        if event.span_name == span_name:
            return event
    return None


def _coerce_event_list(final_state: dict[str, Any]) -> list[TraceSpanRecord]:
    events: list[TraceSpanRecord] = []
    trace_id = str(final_state.get("trace_id", "") or "")
    session_id = _coerce_optional_str(final_state.get("session_id"))
    turn_id = str(final_state.get("turn_id", "") or "")
    for item in final_state.get("event_log", []) or []:
        if not isinstance(item, dict):
            continue
        events.append(
            TraceSpanRecord(
                trace_id=trace_id,
                span_name=str(item.get("node", "") or "unknown"),
                metadata=_coerce_dict(item.get("metadata") or item),
                timestamp_ms=_coerce_int(item.get("timestamp_ms")) or int(time() * 1000),
                session_id=session_id,
                turn_id=turn_id,
                stage=str(item.get("stage", item.get("node", "unknown")) or "unknown"),
                status=str(item.get("status", "success") or "success"),
                duration_ms=_coerce_int(item.get("duration_ms")),
                input_summary=_coerce_dict(item.get("input_summary")),
                output_summary=_coerce_dict(item.get("output_summary")),
                error_code=_coerce_optional_str(item.get("error_code")),
                error_message=_coerce_optional_str(item.get("error_message")),
            )
        )
    return events


def _infer_tool_backend(final_state: dict[str, Any], evidence_pack: dict[str, Any], events: list[TraceSpanRecord]) -> str | None:
    for key in ("tool_backend", "backend_source", "source"):
        value = _coerce_optional_str(final_state.get(key))
        if value:
            return value
    tool_results = _coerce_dict(final_state.get("tool_result_set") or final_state.get("tool_results"))
    for result in tool_results.values():
        if isinstance(result, dict):
            value = _coerce_optional_str(result.get("tool_backend")) or _coerce_optional_str(result.get("backend_source"))
            if value:
                return value
    for event in events:
        value = _coerce_optional_str(event.metadata.get("tool_backend")) or _coerce_optional_str(event.metadata.get("backend_source"))
        if value:
            return value
    pack_tool_results = _coerce_dict(evidence_pack.get("tool_results"))
    for result in pack_tool_results.values():
        if isinstance(result, dict):
            value = _coerce_optional_str(result.get("tool_backend")) or _coerce_optional_str(result.get("backend_source"))
            if value:
                return value
    return None


def _infer_fallback_used(final_state: dict[str, Any], semantic_frame: dict[str, Any]) -> bool:
    answer_source = _coerce_optional_str(final_state.get("answer_source")) or _coerce_optional_str(semantic_frame.get("answer_source"))
    if answer_source in {"fallback", "template_fallback"}:
        return True
    fallback_reason = _coerce_optional_str(final_state.get("fallback_reason")) or _coerce_optional_str(semantic_frame.get("fallback_reason"))
    if fallback_reason:
        return True
    return False


def _infer_legacy_used(final_state: dict[str, Any], events: list[TraceSpanRecord]) -> bool:
    return bool(final_state.get("legacy_used", False))


def _infer_evidence_incomplete(final_state: dict[str, Any]) -> bool:
    rr = _coerce_dict(final_state.get("review_results"))
    review = rr.get("evidence_review")
    if review is None:
        return False
    return bool(_coerce_optional_bool(getattr(review, "evidence_incomplete", None)) or _coerce_optional_bool(_coerce_dict(review).get("evidence_incomplete")))


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
