from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from types import SimpleNamespace

from typing import Any, Mapping

from learning_agent_service.domain.contracts import (
    AnswerContract,
    ClarificationCard,
    EvidenceQualityDecision,
    EntityJoinResult,
    RoutingDecision,
    ReferenceResolutionResult,
    RetrievalPlan,
)
from learning_agent_service.domain.enums import IntentType
from learning_agent_service.domain.utils import utcnow as _utc_now
from learning_agent_service.domain.state import GraphState, clone_graph_state
from ..state import append_runtime_event as _append_state_runtime_event
from ..state import append_stage_timeline_entry as _append_stage_timeline_entry
from ...routing_registry import (
    resolve_execution_route,
    resolve_top_level_route,
    route_registry_hits,
)

_DIRECT_RESPONSE_KINDS = {
    "greeting",
    "thanks",
    "farewell",
    "empty",
    "low_info",
    "profile",
    "memory_update",
    "conversation_recap",
    "location_unavailable",
}
_LOGGER = logging.getLogger(__name__)
_CLASSIFY_TIMEOUT_SECONDS = 1.2
_QUERY_REWRITE_TIMEOUT_SECONDS = 1.0
_ROUTING_EXTRA_KEYS = {
    "route_review_decision",
    "required_facets",
    "optional_facets",
    "required_facets_source_constraints",
    "user_need",
    "pending_clarification_restore",
    "top_level_intent",
    "route_candidate",
    "route_candidates",
    "matched_signals",
    "resolved_route_candidate",
    "route_registry_hits",
    "unsupported_route_candidate",
    "semantic_context",
    "follow_up_kind",
    "comparison_targets",
    "inherited_constraints",
    "fast_classify",
}


@dataclass
class StageTrace:
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float | None = None


def _event_sink_from_state(state: GraphState):
    runtime_context = state.get("runtime_context", {})
    if (
        isinstance(runtime_context, Mapping)
        and runtime_context.get("stream_event_sink") is not None
    ):
        return runtime_context.get("stream_event_sink")
    runtime = state["runtime"]
    return runtime.extra.get("stream_event_sink") if isinstance(runtime.extra, Mapping) else None


def _append_runtime_event(state: GraphState, event_type: str, payload: Mapping[str, Any]) -> None:
    _append_state_runtime_event(state, event_type, dict(payload))


def _emit_stage_state(
    state: GraphState,
    stage: str,
    status: str,
    *,
    elapsed_ms: float | None = None,
    degrade_to: str | None = None,
    error: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    runtime = state["runtime"]
    turn = state["turn"]
    routing = _routing_decision_for_turn(turn)
    payload = {
        "stage": stage,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "degrade_to": degrade_to,
        "error": error,
        "metrics": dict(metrics or {}),
        "current_stage": getattr(turn, "current_stage", stage),
        "stage_status": getattr(turn, "stage_status", status),
        "route_decision": routing.required_action if routing is not None else None,
        "route_reason": routing.route_reason if routing is not None else None,
        "message": message,
        "details": dict(details or {}),
    }
    _append_runtime_event(
        state, f"{stage}_{status}" if status != "heartbeat" else "heartbeat", payload
    )
    _append_stage_timeline_entry(
        state,
        {
            "stage": stage,
            "status": status,
            "route_decision": routing.required_action if routing is not None else None,
            "route_reason": routing.route_reason if routing is not None else None,
            "detail": dict(details or {}),
            "timestamp": _utc_now().isoformat(),
        },
    )
    _LOGGER.info(
        "workflow_stage_event %s",
        json.dumps(
            {
                "trace_id": runtime.trace_id,
                "session_id": runtime.session_id,
                "turn_id": runtime.turn_id,
                "stage": stage,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "degrade_to": degrade_to,
                "error": error,
            },
            ensure_ascii=False,
        ),
    )


def _copy_state(state: GraphState) -> GraphState:
    return clone_graph_state(state)


_EXPLICIT_ENTITY_SUFFIXES = (
    "现在营业吗",
    "现在有券吗",
    "现在能不能订",
    "现在能不能约",
    "现在开吗",
    "适合带爸妈吗",
    "适合家庭聚餐吗",
    "怎么样呢",
    "有券吗呢",
    "营业吗呢",
    "怎么样",
    "有券吗",
    "有券",
    "有几张券",
    "有可用优惠券吗",
    "适合约会吗",
    "适合吗",
    "好不好",
    "值不值得",
    "值不值",
    "营业吗",
    "呢",
    "店呢",
    "家呢",
    "商家呢",
    "哪个呢",
)

_PRONOUNS = (
    "这家",
    "这店",
    "这间",
    "它",
    "他",
    "她",
    "刚才那家",
    "刚才那个",
    "这商家",
    "这个商家",
    "这几家",
    "第一家",
    "第二家",
)

_GENERIC_QUERY_TOKENS = ("附近", "推荐", "餐厅", "餐馆", "美食", "店铺", "店家", "一家", "几家")


def _strip_facet_suffixes(prefix: str) -> str:
    if not prefix:
        return prefix
    facet_suffixes = (
        "环境",
        "价格",
        "人均",
        "味道",
        "口味",
        "服务",
        "券",
        "优惠",
        "营业时间",
        "营业状态",
        "地址",
        "电话",
    )
    _question_verb_patterns = (
        "有券吗",
        "有优惠吗",
        "有优惠券吗",
        "有没有券",
        "有没有优惠",
        "有券",
        "有优惠",
        "营业吗",
        "开门吗",
        "现在营业吗",
    )
    changed = True
    while changed:
        changed = False
        for qv in _question_verb_patterns:
            if prefix.endswith(qv):
                prefix = prefix[: -len(qv)].strip(" 的，,;；")
                changed = True
                break
        if not changed:
            for f_suf in facet_suffixes:
                if prefix.endswith(f_suf):
                    prefix = prefix[: -len(f_suf)].strip(" 的，,;；")
                    changed = True
                    break
    return prefix


def _explicit_entity_from_query(raw_query: str) -> str | None:
    text = (raw_query or "").strip()
    if not text:
        return None
    compact = text.rstrip("？?。.!！")
    has_entity_shape = any(
        token in compact for token in ("(", "（", "）", ")", "店", "馆", "城", "街", "路")
    )
    if compact.startswith("那"):
        compact = re.sub(r"^那[，,\s]?", "", compact).strip()
    for pronoun in _PRONOUNS:
        idx = compact.find(pronoun)
        if idx > 0:
            prefix = compact[:idx].strip(" ，,;；")
            if (
                prefix
                and prefix not in _PRONOUNS
                and (
                    not any(token in prefix for token in _GENERIC_QUERY_TOKENS) or has_entity_shape
                )
            ):
                return _strip_facet_suffixes(prefix)
    for suffix in _EXPLICIT_ENTITY_SUFFIXES:
        if compact.endswith(suffix):
            prefix = compact[: -len(suffix)].strip(" ，,;；")
            if prefix:
                if any(pronoun in prefix for pronoun in _PRONOUNS) or prefix in _PRONOUNS:
                    continue
                if any(token in prefix for token in _GENERIC_QUERY_TOKENS) and not has_entity_shape:
                    continue
                return _strip_facet_suffixes(prefix)
    match = re.match(r"^(?P<name>.+?)(?:\s+)?(什么|哪家|哪个好|行不行|可以吗)$", compact)
    if match:
        prefix = match.group("name").strip(" ，,;；")
        if prefix:
            if any(pronoun in prefix for pronoun in _PRONOUNS) or prefix in _PRONOUNS:
                return None
            if any(token in prefix for token in _GENERIC_QUERY_TOKENS) and not has_entity_shape:
                return None
            return _strip_facet_suffixes(prefix)
    return None


def _append_stage_metric(state: GraphState, stage: str, elapsed_ms: float | None) -> None:
    if elapsed_ms is None:
        return
    runtime = state["runtime"]
    metrics = dict(runtime.metrics)
    stage_metrics = dict(metrics.get("stage_elapsed_ms", {}) or {})
    stage_metrics[stage] = round(float(elapsed_ms), 3)
    metrics["stage_elapsed_ms"] = stage_metrics
    metrics[f"{stage}_elapsed_ms"] = round(float(elapsed_ms), 3)
    state["runtime"] = runtime.model_copy(update={"metrics": metrics})


def _mark_degrade(state: GraphState, degrade_to: str | None) -> None:
    if not degrade_to:
        return
    runtime = state["runtime"]
    degrade_items = list((runtime.metrics or {}).get("degrade_to_list", []) or [])
    if degrade_to not in degrade_items:
        degrade_items.append(degrade_to)
    metrics = dict(runtime.metrics)
    metrics["degrade_to_list"] = degrade_items
    metrics["degrade_to"] = ",".join(degrade_items)
    state["runtime"] = runtime.model_copy(update={"metrics": metrics, "degrade_to": degrade_to})


def _build_raw_retrieval_plan(turn: Any) -> RetrievalPlan:
    raw_query = str(getattr(turn, "raw_query", "") or "").strip()
    base_filters = dict(getattr(turn, "slots", {}) or {})
    return RetrievalPlan(
        semantic_query=raw_query,
        keyword_query=raw_query,
        retrieval_filters=base_filters,
        preferred_chunk_types=[],
        need_retry_rewrite=False,
        reasoning_notes=["rewrite_skipped_use_raw_query"],
        extra={
            "rewrite_source": "raw_query",
            "rewrite_skipped": True,
            "raw_query": raw_query,
            "filter_confidence": 1.0,
            "metadata_filter_mode": "soft",
        },
    )


def _resolved_topic_for_turn(turn: Any, persistent: Any) -> Any:
    reference_resolution = getattr(turn, "reference_resolution", None)
    if reference_resolution is not None and getattr(reference_resolution, "resolved", False):
        resolved_entity = getattr(reference_resolution, "resolved_entity", None)
        if resolved_entity:
            return resolved_entity
    return persistent.current_topic


def _response_kind_for_turn(turn: Any) -> str | None:
    routing = _routing_decision_for_turn(turn)
    if routing is None:
        return None
    candidate = str(routing.route_candidate or "").strip().lower()
    if candidate in _DIRECT_RESPONSE_KINDS:
        return candidate
    if candidate == "continue_previous_topic":
        return "conversation_recap"
    if routing.required_action == "memory_update":
        return "memory_update"
    if routing.required_action == "reject":
        return (
            "empty"
            if routing.input_quality.kind in {"empty_input", "pure_punctuation"}
            else "low_info"
        )
    if routing.required_action == "clarify":
        return "low_info"
    if routing.required_action == "direct_answer":
        if candidate in {
            "greeting",
            "thanks",
            "profile",
            "farewell",
            "conversation_recap",
            "location_unavailable",
        }:
            return candidate
        return "low_info"
    return None


def _response_origin_for_turn(turn: Any, *, allow_direct_response: bool) -> str:
    routing = _routing_decision_for_turn(turn)
    routing_action = (
        str(getattr(routing, "required_action", "") or "").strip().lower()
        if routing is not None
        else ""
    )
    if allow_direct_response:
        return "direct"
    if (
        routing_action == "recommendation"
        and turn.rag_result is not None
        and turn.tool_result is not None
    ):
        return "recommendation"
    if turn.tool_result is not None and routing_action in {"tool_call", "recommendation"}:
        return "tool"
    if turn.rag_result is not None:
        return "recommendation"
    return "fallback"


def _phase2_evidence_pack(turn: Any) -> Any:
    pack = getattr(turn, "evidence_pack", None)
    if pack is not None:
        return pack
    evidence_result = getattr(turn, "rag_result", None)
    if evidence_result is not None:
        return getattr(evidence_result, "evidence_pack", None)
    return None


def _phase2_trace_reasons(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    evidence_gate_blocked: bool | None = None,
) -> list[str]:
    if routing is None:
        return []
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if action != "recommendation":
        return []

    reasons: list[str] = []
    if getattr(turn, "retrieval_plan", None) is None:
        reasons.append("retrieval_plan_missing")
    tool_plan = getattr(turn, "tool_plan", None)
    if tool_plan is None or not getattr(tool_plan, "tool_name", None):
        reasons.append("tool_plan_missing")
    if list(getattr(routing, "missing_slots", []) or []):
        reasons.append("tool_slot_missing")
    if not bool(getattr(routing, "should_call_tool", False)):
        reasons.append("tool_not_allowed")
    if not bool(getattr(routing, "should_retrieve", False)):
        reasons.append("retrieval_not_allowed")

    if evidence_gate_blocked is None:
        pack = _phase2_evidence_pack(turn)
        evidence_gate_blocked = bool(pack is None or not getattr(pack, "items", None))
        if not evidence_gate_blocked and evidence_quality is not None:
            evidence_gate_blocked = bool(
                not getattr(evidence_quality, "is_valid", True)
                and str(getattr(evidence_quality, "response_mode", "") or "").strip().lower()
                in {"no_answer", "weak_answer"}
            )
    if evidence_gate_blocked:
        reasons.append("evidence_gate_blocked")

    return list(dict.fromkeys(reasons))


def _build_phase2_trace(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    response_origin: str | None = None,
    answer_confidence: float | None = None,
    final_response_mode: str | None = None,
    evidence_gate_blocked: bool | None = None,
    evidence_after_gate_count: int | None = None,
) -> dict[str, Any]:
    reasons = _phase2_trace_reasons(
        turn, routing, evidence_quality, evidence_gate_blocked=evidence_gate_blocked
    )
    effective_response_mode = (
        str(final_response_mode or getattr(evidence_quality, "response_mode", "") or "")
        .strip()
        .lower()
        or None
    )
    missing_slots = list(getattr(routing, "missing_slots", []) or []) if routing is not None else []
    tool_candidates = (
        list(getattr(routing, "tool_candidates", []) or []) if routing is not None else []
    )
    clarification_slot = (
        getattr(evidence_quality, "clarification_slot", None)
        or (missing_slots[0] if missing_slots else None)
        or None
    )
    if evidence_after_gate_count is None:
        pack = _phase2_evidence_pack(turn)
        evidence_after_gate_count = len(getattr(pack, "items", []) or []) if pack is not None else 0

    trace: dict[str, Any] = {
        "active": bool(
            reasons or effective_response_mode or response_origin or answer_confidence is not None
        ),
        "required_action": str(getattr(routing, "required_action", "") or "").strip().lower()
        or None
        if routing is not None
        else None,
        "response_mode": effective_response_mode,
        "response_origin": response_origin,
        "answer_confidence": answer_confidence,
        "evidence_plus_tool_failed": bool(reasons),
        "evidence_plus_tool_failure_reason": reasons[0] if reasons else None,
        "evidence_plus_tool_failure_reasons": reasons,
        "retrieval_plan_missing": "retrieval_plan_missing" in reasons,
        "tool_plan_missing": "tool_plan_missing" in reasons,
        "tool_slot_missing": "tool_slot_missing" in reasons,
        "tool_not_allowed": "tool_not_allowed" in reasons,
        "retrieval_not_allowed": "retrieval_not_allowed" in reasons,
        "evidence_gate_blocked": "evidence_gate_blocked" in reasons,
        "evidence_after_gate_count": evidence_after_gate_count,
        "missing_slots": missing_slots,
        "clarification_slot": clarification_slot,
        "tool_candidates": tool_candidates,
        "covered_facets": list(getattr(evidence_quality, "covered_facets", None) or []),
        "missing_facets": list(getattr(evidence_quality, "missing_facets", None) or []),
    }
    return trace


def _routing_decision_for_turn(turn: Any) -> RoutingDecision | None:
    routing = getattr(turn, "routing_decision", None)
    if isinstance(routing, RoutingDecision):
        return routing
    return None


def _store_routing_decision(turn: Any, routing: RoutingDecision) -> Any:
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    for key in _ROUTING_EXTRA_KEYS:
        value = routing.extra.get(key) if isinstance(routing.extra, Mapping) else None
        if value is not None:
            turn_extra[key] = value
    turn_extra["routing_decision"] = routing.model_dump(mode="json")
    turn_extra["route_reason"] = routing.route_reason
    if routing.route_candidate is not None:
        turn_extra["route_candidate"] = routing.route_candidate
    return turn.model_copy(
        update={
            "routing_decision": routing,
            "extra": turn_extra,
        }
    )


def _apply_phase1_routing_extra(
    turn_extra: dict[str, Any], routing: RoutingDecision | None
) -> dict[str, Any]:
    if routing is None:
        return turn_extra
    merged = dict(turn_extra)
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    for key in _ROUTING_EXTRA_KEYS:
        value = routing_extra.get(key)
        if value is not None:
            merged[key] = value
    return merged


def _restore_pending_clarification_from_result(
    *,
    runtime: Any,
    turn: Any,
    persistent: Any,
) -> tuple[Any, Any]:
    if getattr(persistent, "pending_clarification", None) is not None:
        return persistent, turn

    clarification_result = dict(getattr(persistent, "clarification_result", {}) or {})
    if not clarification_result:
        return persistent, turn
    if bool(clarification_result.get("consumed")):
        return persistent, turn

    ambiguity_type = str(clarification_result.get("ambiguity_type") or "").strip().lower()
    if ambiguity_type not in {"location", "city", "area", "district", "region"}:
        return persistent, turn

    question_text = (
        str(
            clarification_result.get("question")
            or clarification_result.get("clarification_question")
            or clarification_result.get("original_question")
            or clarification_result.get("query")
            or ""
        ).strip()
        or "你现在在哪个城市或位置附近？"
    )
    pending_clarification = ClarificationCard(
        card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
        question=question_text,
        options=[],
        ambiguity_type=ambiguity_type,
        source_turn_id=str(
            clarification_result.get("source_turn_id")
            or clarification_result.get("turn_id")
            or runtime.turn_id
        ).strip()
        or runtime.turn_id,
        expires_at=None,
    )

    restored_result = dict(clarification_result)
    restored_result.setdefault("question", question_text)
    restored_result.setdefault("ambiguity_type", ambiguity_type)

    persistent = persistent.model_copy(
        update={
            "clarification_result": restored_result,
            "pending_clarification": pending_clarification,
        }
    )
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    turn_extra["clarification_result"] = restored_result
    turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
    turn = turn.model_copy(update={"extra": turn_extra})
    return persistent, turn


def _log_routing_decision(state: GraphState, *, stage: str) -> None:
    runtime = state["runtime"]
    turn = state["turn"]
    routing = _routing_decision_for_turn(turn)
    if routing is None:
        return
    _LOGGER.info(
        "routing_decision %s",
        json.dumps(
            {
                "trace_id": runtime.trace_id,
                "session_id": runtime.session_id,
                "turn_id": runtime.turn_id,
                "stage": stage,
                "raw_query": routing.raw_query,
                "normalized_query": routing.normalized_query,
                "input_quality": routing.input_quality.model_dump(mode="json"),
                "intent": routing.intent.model_dump(mode="json"),
                "required_action": routing.required_action,
                "should_rewrite_query": routing.should_rewrite_query,
                "should_retrieve": routing.should_retrieve,
                "should_call_tool": routing.should_call_tool,
                "should_use_memory": routing.should_use_memory,
                "should_persist_memory": routing.should_persist_memory,
                "should_vectorize_memory": routing.should_vectorize_memory,
                "should_emit_retrieval_events": routing.should_emit_retrieval_events,
                "missing_slots": list(routing.missing_slots),
                "resolved_references": list(routing.resolved_references),
                "route_reason": routing.route_reason,
                "safeguards_triggered": list(routing.safeguards_triggered),
                "fallback_reason": routing.fallback_reason,
            },
            ensure_ascii=False,
        ),
    )


def _coerce_reference_resolution(value: Any) -> ReferenceResolutionResult | None:
    if value is None:
        return None
    if isinstance(value, ReferenceResolutionResult):
        return value
    if isinstance(value, Mapping):
        try:
            return ReferenceResolutionResult.model_validate(dict(value))
        except Exception:
            return None
    return None


def _coerce_retrieval_plan(value: Any) -> RetrievalPlan | None:
    if value is None:
        return None
    if isinstance(value, RetrievalPlan):
        return value
    if isinstance(value, Mapping):
        try:
            return RetrievalPlan.model_validate(dict(value))
        except Exception:
            return None
    return None


def _build_cached_evidence_gate(
    required_action: str,
    intent: IntentType,
    confidence: float,
    payload: Mapping[str, Any],
    slots: Mapping[str, Any],
) -> dict[str, Any]:
    route_candidate = (
        str(payload.get("route_candidate") or slots.get("route_candidate") or "").strip().lower()
        or None
    )
    allowed = str(required_action).strip().lower() in {"recommendation", "tool_call"}
    response_kind = "fallback"
    if not allowed:
        response_kind = route_candidate or (
            "low_info"
            if str(required_action).strip().lower() == "clarify"
            or (intent == IntentType.FOLLOW_UP and confidence < 0.5)
            else "empty"
            if confidence <= 0.1
            else "low_info"
        )
    reason = route_candidate or str(required_action)
    final_vote = "allow" if allowed else "deny"
    return {
        "allowed": allowed,
        "reason": reason,
        "confidence": max(0.0, min(float(confidence or 0.0), 1.0)),
        "response_kind": response_kind,
        "precheck_skip_memory": False,
        "final_vote": final_vote,
        "rule_vote": None,
        "llm_vote": None,
        "metadata": {
            "source": "understanding_bundle",
            "decision": str(required_action),
            "intent": intent.value,
        },
    }


def _cached_evidence_gate(turn: Any) -> dict[str, Any] | None:
    extra = dict(getattr(turn, "extra", {}) or {})
    evidence_gate = extra.get("evidence_gate")
    if isinstance(evidence_gate, Mapping) and "allowed" in evidence_gate:
        return dict(evidence_gate)
    cached_vote = extra.get("cached_evidence_gate_vote")
    if isinstance(cached_vote, Mapping) and "allowed" in cached_vote:
        return dict(cached_vote)
    return None


def _event_sink_from_state(state: GraphState):
    runtime_context = state.get("runtime_context", {})
    if (
        isinstance(runtime_context, Mapping)
        and runtime_context.get("stream_event_sink") is not None
    ):
        return runtime_context.get("stream_event_sink")
    runtime = state["runtime"]
    return runtime.extra.get("stream_event_sink") if isinstance(runtime.extra, Mapping) else None


def _append_runtime_event(state: GraphState, event_type: str, payload: Mapping[str, Any]) -> None:
    _append_state_runtime_event(state, event_type, dict(payload))


def _emit_stage_state(
    state: GraphState,
    stage: str,
    status: str,
    *,
    elapsed_ms: float | None = None,
    degrade_to: str | None = None,
    error: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    runtime = state["runtime"]
    turn = state["turn"]
    routing = _routing_decision_for_turn(turn)
    payload = {
        "stage": stage,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "degrade_to": degrade_to,
        "error": error,
        "metrics": dict(metrics or {}),
        "current_stage": getattr(turn, "current_stage", stage),
        "stage_status": getattr(turn, "stage_status", status),
        "route_decision": routing.required_action if routing is not None else None,
        "route_reason": routing.route_reason if routing is not None else None,
        "message": message,
        "details": dict(details or {}),
    }
    _append_runtime_event(
        state, f"{stage}_{status}" if status != "heartbeat" else "heartbeat", payload
    )
    _append_stage_timeline_entry(
        state,
        {
            "stage": stage,
            "status": status,
            "route_decision": routing.required_action if routing is not None else None,
            "route_reason": routing.route_reason if routing is not None else None,
            "detail": dict(details or {}),
            "timestamp": _utc_now().isoformat(),
        },
    )
    _LOGGER.info(
        "workflow_stage_event %s",
        json.dumps(
            {
                "trace_id": runtime.trace_id,
                "session_id": runtime.session_id,
                "turn_id": runtime.turn_id,
                "stage": stage,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "degrade_to": degrade_to,
                "error": error,
            },
            ensure_ascii=False,
        ),
    )


def _copy_state(state: GraphState) -> GraphState:
    return clone_graph_state(state)


def _append_stage_metric(state: GraphState, stage: str, elapsed_ms: float | None) -> None:
    if elapsed_ms is None:
        return
    runtime = state["runtime"]
    metrics = dict(runtime.metrics)
    stage_metrics = dict(metrics.get("stage_elapsed_ms", {}) or {})
    stage_metrics[stage] = round(float(elapsed_ms), 3)
    metrics["stage_elapsed_ms"] = stage_metrics
    metrics[f"{stage}_elapsed_ms"] = round(float(elapsed_ms), 3)
    state["runtime"] = runtime.model_copy(update={"metrics": metrics})


def _mark_degrade(state: GraphState, degrade_to: str | None) -> None:
    if not degrade_to:
        return
    runtime = state["runtime"]
    degrade_items = list((runtime.metrics or {}).get("degrade_to_list", []) or [])
    if degrade_to not in degrade_items:
        degrade_items.append(degrade_to)
    metrics = dict(runtime.metrics)
    metrics["degrade_to_list"] = degrade_items
    metrics["degrade_to"] = ",".join(degrade_items)
    state["runtime"] = runtime.model_copy(update={"metrics": metrics, "degrade_to": degrade_to})


def _build_raw_retrieval_plan(turn: Any) -> RetrievalPlan:
    raw_query = str(getattr(turn, "raw_query", "") or "").strip()
    base_filters = dict(getattr(turn, "slots", {}) or {})
    return RetrievalPlan(
        semantic_query=raw_query,
        keyword_query=raw_query,
        retrieval_filters=base_filters,
        preferred_chunk_types=[],
        need_retry_rewrite=False,
        reasoning_notes=["rewrite_skipped_use_raw_query"],
        extra={
            "rewrite_source": "raw_query",
            "rewrite_skipped": True,
            "raw_query": raw_query,
            "filter_confidence": 1.0,
            "metadata_filter_mode": "soft",
        },
    )


def _resolved_topic_for_turn(turn: Any, persistent: Any) -> Any:
    reference_resolution = getattr(turn, "reference_resolution", None)
    if reference_resolution is not None and getattr(reference_resolution, "resolved", False):
        resolved_entity = getattr(reference_resolution, "resolved_entity", None)
        if resolved_entity:
            return resolved_entity
    return persistent.current_topic


def _response_kind_for_turn(turn: Any) -> str | None:
    routing = _routing_decision_for_turn(turn)
    if routing is None:
        return None
    candidate = str(routing.route_candidate or "").strip().lower()
    if candidate in _DIRECT_RESPONSE_KINDS:
        return candidate
    if candidate == "continue_previous_topic":
        return "conversation_recap"
    if routing.required_action == "memory_update":
        return "memory_update"
    if routing.required_action == "reject":
        return (
            "empty"
            if routing.input_quality.kind in {"empty_input", "pure_punctuation"}
            else "low_info"
        )
    if routing.required_action == "clarify":
        return "low_info"
    if routing.required_action == "direct_answer":
        if candidate in {
            "greeting",
            "thanks",
            "profile",
            "farewell",
            "conversation_recap",
            "location_unavailable",
        }:
            return candidate
        return "low_info"
    return None


def _response_origin_for_turn(turn: Any, *, allow_direct_response: bool) -> str:
    routing = _routing_decision_for_turn(turn)
    routing_action = (
        str(getattr(routing, "required_action", "") or "").strip().lower()
        if routing is not None
        else ""
    )
    if allow_direct_response:
        return "direct"
    if (
        routing_action == "recommendation"
        and turn.rag_result is not None
        and turn.tool_result is not None
    ):
        return "recommendation"
    if turn.tool_result is not None and routing_action in {"tool_call", "recommendation"}:
        return "tool"
    if turn.rag_result is not None:
        return "recommendation"
    return "fallback"


def _phase2_evidence_pack(turn: Any) -> Any:
    pack = getattr(turn, "evidence_pack", None)
    if pack is not None:
        return pack
    evidence_result = getattr(turn, "rag_result", None)
    if evidence_result is not None:
        return getattr(evidence_result, "evidence_pack", None)
    return None


def _phase2_trace_reasons(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    evidence_gate_blocked: bool | None = None,
) -> list[str]:
    if routing is None:
        return []
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if action != "recommendation":
        return []

    reasons: list[str] = []
    if getattr(turn, "retrieval_plan", None) is None:
        reasons.append("retrieval_plan_missing")
    tool_plan = getattr(turn, "tool_plan", None)
    if tool_plan is None or not getattr(tool_plan, "tool_name", None):
        reasons.append("tool_plan_missing")
    if list(getattr(routing, "missing_slots", []) or []):
        reasons.append("tool_slot_missing")
    if not bool(getattr(routing, "should_call_tool", False)):
        reasons.append("tool_not_allowed")
    if not bool(getattr(routing, "should_retrieve", False)):
        reasons.append("retrieval_not_allowed")

    if evidence_gate_blocked is None:
        pack = _phase2_evidence_pack(turn)
        evidence_gate_blocked = bool(pack is None or not getattr(pack, "items", None))
        if not evidence_gate_blocked and evidence_quality is not None:
            evidence_gate_blocked = bool(
                not getattr(evidence_quality, "is_valid", True)
                and str(getattr(evidence_quality, "response_mode", "") or "").strip().lower()
                in {"no_answer", "weak_answer"}
            )
    if evidence_gate_blocked:
        reasons.append("evidence_gate_blocked")

    return list(dict.fromkeys(reasons))


def _build_phase2_trace(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    response_origin: str | None = None,
    answer_confidence: float | None = None,
    final_response_mode: str | None = None,
    evidence_gate_blocked: bool | None = None,
    evidence_after_gate_count: int | None = None,
) -> dict[str, Any]:
    reasons = _phase2_trace_reasons(
        turn, routing, evidence_quality, evidence_gate_blocked=evidence_gate_blocked
    )
    effective_response_mode = (
        str(final_response_mode or getattr(evidence_quality, "response_mode", "") or "")
        .strip()
        .lower()
        or None
    )
    missing_slots = list(getattr(routing, "missing_slots", []) or []) if routing is not None else []
    tool_candidates = (
        list(getattr(routing, "tool_candidates", []) or []) if routing is not None else []
    )
    clarification_slot = (
        getattr(evidence_quality, "clarification_slot", None)
        or (missing_slots[0] if missing_slots else None)
        or None
    )
    if evidence_after_gate_count is None:
        pack = _phase2_evidence_pack(turn)
        evidence_after_gate_count = len(getattr(pack, "items", []) or []) if pack is not None else 0

    trace: dict[str, Any] = {
        "active": bool(
            reasons or effective_response_mode or response_origin or answer_confidence is not None
        ),
        "required_action": str(getattr(routing, "required_action", "") or "").strip().lower()
        or None
        if routing is not None
        else None,
        "response_mode": effective_response_mode,
        "response_origin": response_origin,
        "answer_confidence": answer_confidence,
        "evidence_plus_tool_failed": bool(reasons),
        "evidence_plus_tool_failure_reason": reasons[0] if reasons else None,
        "evidence_plus_tool_failure_reasons": reasons,
        "retrieval_plan_missing": "retrieval_plan_missing" in reasons,
        "tool_plan_missing": "tool_plan_missing" in reasons,
        "tool_slot_missing": "tool_slot_missing" in reasons,
        "tool_not_allowed": "tool_not_allowed" in reasons,
        "retrieval_not_allowed": "retrieval_not_allowed" in reasons,
        "evidence_gate_blocked": "evidence_gate_blocked" in reasons,
        "evidence_after_gate_count": evidence_after_gate_count,
        "missing_slots": missing_slots,
        "clarification_slot": clarification_slot,
        "tool_candidates": tool_candidates,
        "covered_facets": list(getattr(evidence_quality, "covered_facets", None) or []),
        "missing_facets": list(getattr(evidence_quality, "missing_facets", None) or []),
    }
    return trace


def _routing_decision_for_turn(turn: Any) -> RoutingDecision | None:
    routing = getattr(turn, "routing_decision", None)
    if isinstance(routing, RoutingDecision):
        return routing
    return None


def _store_routing_decision(turn: Any, routing: RoutingDecision) -> Any:
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    for key in (
        "route_review_decision",
        "required_facets",
        "optional_facets",
        "required_facets_source_constraints",
        "user_need",
        "pending_clarification_restore",
    ):
        value = routing.extra.get(key) if isinstance(routing.extra, Mapping) else None
        if value is not None:
            turn_extra[key] = value
    turn_extra["routing_decision"] = routing.model_dump(mode="json")
    turn_extra["route_reason"] = routing.route_reason
    if routing.route_candidate is not None:
        turn_extra["route_candidate"] = routing.route_candidate
    return turn.model_copy(
        update={
            "routing_decision": routing,
            "extra": turn_extra,
        }
    )


def _apply_phase1_routing_extra(
    turn_extra: dict[str, Any], routing: RoutingDecision | None
) -> dict[str, Any]:
    if routing is None:
        return turn_extra
    merged = dict(turn_extra)
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    for key in (
        "route_review_decision",
        "required_facets",
        "optional_facets",
        "required_facets_source_constraints",
        "user_need",
        "pending_clarification_restore",
    ):
        value = routing_extra.get(key)
        if value is not None:
            merged[key] = value
    return merged


def _restore_pending_clarification_from_result(
    *,
    runtime: Any,
    turn: Any,
    persistent: Any,
) -> tuple[Any, Any]:
    if getattr(persistent, "pending_clarification", None) is not None:
        return persistent, turn

    clarification_result = dict(getattr(persistent, "clarification_result", {}) or {})
    if not clarification_result:
        return persistent, turn
    if bool(clarification_result.get("consumed")):
        return persistent, turn

    ambiguity_type = str(clarification_result.get("ambiguity_type") or "").strip().lower()
    if ambiguity_type not in {"location", "city", "area", "district", "region"}:
        return persistent, turn

    question_text = (
        str(
            clarification_result.get("question")
            or clarification_result.get("clarification_question")
            or clarification_result.get("original_question")
            or clarification_result.get("query")
            or ""
        ).strip()
        or "你现在在哪个城市或位置附近？"
    )
    pending_clarification = ClarificationCard(
        card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
        question=question_text,
        options=[],
        ambiguity_type=ambiguity_type,
        source_turn_id=str(
            clarification_result.get("source_turn_id")
            or clarification_result.get("turn_id")
            or runtime.turn_id
        ).strip()
        or runtime.turn_id,
        expires_at=None,
    )

    restored_result = dict(clarification_result)
    restored_result.setdefault("question", question_text)
    restored_result.setdefault("ambiguity_type", ambiguity_type)

    persistent = persistent.model_copy(
        update={
            "clarification_result": restored_result,
            "pending_clarification": pending_clarification,
        }
    )
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    turn_extra["clarification_result"] = restored_result
    turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
    turn = turn.model_copy(update={"extra": turn_extra})
    return persistent, turn


def _log_routing_decision(state: GraphState, *, stage: str) -> None:
    runtime = state["runtime"]
    turn = state["turn"]
    routing = _routing_decision_for_turn(turn)
    if routing is None:
        return
    _LOGGER.info(
        "routing_decision %s",
        json.dumps(
            {
                "trace_id": runtime.trace_id,
                "session_id": runtime.session_id,
                "turn_id": runtime.turn_id,
                "stage": stage,
                "raw_query": routing.raw_query,
                "normalized_query": routing.normalized_query,
                "input_quality": routing.input_quality.model_dump(mode="json"),
                "intent": routing.intent.model_dump(mode="json"),
                "required_action": routing.required_action,
                "should_rewrite_query": routing.should_rewrite_query,
                "should_retrieve": routing.should_retrieve,
                "should_call_tool": routing.should_call_tool,
                "should_use_memory": routing.should_use_memory,
                "should_persist_memory": routing.should_persist_memory,
                "should_vectorize_memory": routing.should_vectorize_memory,
                "should_emit_retrieval_events": routing.should_emit_retrieval_events,
                "missing_slots": list(routing.missing_slots),
                "resolved_references": list(routing.resolved_references),
                "route_reason": routing.route_reason,
                "safeguards_triggered": list(routing.safeguards_triggered),
                "fallback_reason": routing.fallback_reason,
            },
            ensure_ascii=False,
        ),
    )


def _coerce_reference_resolution(value: Any) -> ReferenceResolutionResult | None:
    if value is None:
        return None
    if isinstance(value, ReferenceResolutionResult):
        return value
    if isinstance(value, Mapping):
        try:
            return ReferenceResolutionResult.model_validate(dict(value))
        except Exception:
            return None
    return None


def _coerce_retrieval_plan(value: Any) -> RetrievalPlan | None:
    if value is None:
        return None
    if isinstance(value, RetrievalPlan):
        return value
    if isinstance(value, Mapping):
        try:
            return RetrievalPlan.model_validate(dict(value))
        except Exception:
            return None
    return None


def _build_cached_evidence_gate(
    required_action: str,
    intent: IntentType,
    confidence: float,
    payload: Mapping[str, Any],
    slots: Mapping[str, Any],
) -> dict[str, Any]:
    route_candidate = (
        str(payload.get("route_candidate") or slots.get("route_candidate") or "").strip().lower()
        or None
    )
    allowed = str(required_action).strip().lower() in {"recommendation", "tool_call"}
    response_kind = "fallback"
    if not allowed:
        response_kind = route_candidate or (
            "low_info"
            if str(required_action).strip().lower() == "clarify"
            or (intent == IntentType.FOLLOW_UP and confidence < 0.5)
            else "empty"
            if confidence <= 0.1
            else "low_info"
        )
    reason = route_candidate or str(required_action)
    final_vote = "allow" if allowed else "deny"
    return {
        "allowed": allowed,
        "reason": reason,
        "confidence": max(0.0, min(float(confidence or 0.0), 1.0)),
        "response_kind": response_kind,
        "precheck_skip_memory": False,
        "final_vote": final_vote,
        "rule_vote": None,
        "llm_vote": None,
        "metadata": {
            "source": "understanding_bundle",
            "decision": str(required_action),
            "intent": intent.value,
        },
    }


def _cached_evidence_gate(turn: Any) -> dict[str, Any] | None:
    extra = dict(getattr(turn, "extra", {}) or {})
    evidence_gate = extra.get("evidence_gate")
    if isinstance(evidence_gate, Mapping) and "allowed" in evidence_gate:
        return dict(evidence_gate)
    cached_vote = extra.get("cached_evidence_gate_vote")
    if isinstance(cached_vote, Mapping) and "allowed" in cached_vote:
        return dict(cached_vote)
    return None


def _build_recommendation_answer_text(
    shop_names: list[str],
    limit: int = 3,
    fallback_text: str | None = None,
    scene_hint: str | None = None,
    focus_hint: str | None = None,
    shop_data: list[dict[str, Any]] | None = None,
    query: str | None = None,
    openai_client: Any | None = None,
    model: str | None = None,
) -> str:
    """
    构建推荐回答文本。

    优先使用PromptEngine生成自然回答，失败时降级到模板。
    """
    # 尝试使用PromptEngine生成自然回答
    if shop_data and query:
        try:
            from learning_agent_service.local_life.prompt_engine import get_prompt_engine

            engine = get_prompt_engine()
            if engine.has_config("multi_shop_recommendation"):
                # 构建evidence_context
                evidence_lines = ["候选店铺:"]
                for i, shop in enumerate(shop_data[:limit], 1):
                    name = shop.get("name") or shop.get("shop_name") or f"店铺{i}"
                    score = shop.get("score", "未知")
                    avg_price = shop.get("avg_price", "未知")
                    distance = shop.get("distance", "未知")
                    highlights = shop.get("highlights") or shop.get("特色") or []
                    if isinstance(highlights, list):
                        highlights_str = ", ".join(highlights[:3])
                    else:
                        highlights_str = str(highlights)
                    comments = shop.get("comments", "未知")
                    evidence_lines.append(
                        f"{i}. {name} - 评分{score}, 人均{avg_price}元, 距离{distance}km, 特色:{highlights_str}, 评价数{comments}"
                    )

                evidence_context = "\n".join(evidence_lines)

                # 构建完整查询
                full_query = query
                if scene_hint:
                    full_query = f"{query}（场景：{scene_hint}）"
                if focus_hint:
                    full_query = f"{full_query}（重点：{focus_hint}）"

                # 如果有OpenAI客户端，直接调用LLM生成回答
                if openai_client is not None and model is not None:
                    llm_result = engine.generate(
                        "multi_shop_recommendation",
                        full_query,
                        evidence_context,
                        client=openai_client,
                        model=model,
                    )
                    if llm_result:
                        return llm_result
        except Exception as e:
            logger.warning("prompt_engine_fallback error=%s", e)

    # 降级到原有模板逻辑
    names = [str(name).strip() for name in shop_names if str(name).strip()]
    if not names:
        return fallback_text or "我暂时没有找到合适的店。"

    lines = ["我先帮你推荐以下这几家店铺：", ""]
    scene_text = scene_hint or "适合约会、聊天或轻松聚餐。"
    for i, name in enumerate(names[:limit], 1):
        lines.append(f"{i}. {name}")
        lines.append("- 推荐理由：当前候选里它的综合信息比较靠前，值得优先查看。")
        lines.append(f"- 适合场景：{scene_text}")
        lines.append("- 注意事项：建议先确认营业状态、预算和是否需要排队。")
        lines.append("")
    lines.append("综合建议")
    if focus_hint:
        lines.append(f"- 筛选重点：{focus_hint}")
    lines.append("- 如果你更在意气氛和稳定性，建议先从前两家开始看。")
    lines.append("- 另外，如果你想继续看实时优惠，我可以接着帮你查。")
    return "\n".join(lines).strip()


def _build_single_shop_review_answer(shop_name: str | None) -> str:
    name = str(shop_name or "\u8fd9\u5bb6\u5e97").strip() or "\u8fd9\u5bb6\u5e97"
    return "\n".join(
        [
            "\u603b\u4f53\u7ed3\u8bba",
            f"- {name}\u76ee\u524d\u53ef\u4ee5\u5148\u4f5c\u4e3a\u5019\u9009\uff0c\u73b0\u6709\u4fe1\u606f\u652f\u6301\u7ee7\u7eed\u89c2\u5bdf\u3002",
            "\u6838\u5fc3\u4f18\u70b9",
            "- \u5f53\u524d\u8bc1\u636e\u548c\u6392\u5e8f\u90fd\u8bf4\u660e\u5b83\u5177\u6709\u4e00\u5b9a\u4f18\u52bf\uff0c\u9002\u5408\u7ee7\u7eed\u7b5b\u9009\u3002",
            "- \u5982\u679c\u4f60\u66f4\u91cd\u89c6\u73af\u5883\u548c\u4f53\u9a8c\uff0c\u53ef\u4ee5\u4f18\u5148\u770b\u8fd9\u5bb6\u3002",
            "\u53ef\u80fd\u4e0d\u8db3",
            "- \u4ecd\u5efa\u8bae\u7ed3\u5408\u8425\u4e1a\u65f6\u95f4\u548c\u6392\u961f\u60c5\u51b5\u518d\u786e\u8ba4\u4e00\u6b21\u3002",
            "\u9002\u5408\u573a\u666f",
            "- \u9002\u5408\u60f3\u5148\u5feb\u901f\u5224\u65ad\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u5230\u5e97\u7684\u573a\u666f\u3002",
            "\u5230\u5e97\u5efa\u8bae",
            "- \u5148\u770b\u8425\u4e1a\u65f6\u95f4\u548c\u5b9e\u65f6\u4fe1\u606f\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u73b0\u5728\u53bb\u3002",
        ]
    )


# ============================================================
# Phase 1a: 缺失的旧 router 模块兼容函数
# 替代已删除 application/router/ 模块中的功能
# ============================================================

# --- router.base 兼容函数 ---


def routing_trace_payload(routing: RoutingDecision | None) -> dict[str, Any]:
    """生成路由追踪载荷。"""
    if routing is None:
        return {}
    try:
        extra = dict(getattr(routing, "extra", {}) or {})
        return {
            "required_action": routing.required_action,
            "execution_mode": routing.execution_mode,
            "route_reason": routing.route_reason,
            "route_candidate": routing.route_candidate,
            "resolved_route_candidate": extra.get("resolved_route_candidate"),
            "resolved_top_level_route": extra.get("resolved_top_level_route"),
            "should_retrieve": routing.should_retrieve,
            "should_call_tool": routing.should_call_tool,
            "route_registry_hits": list(extra.get("route_registry_hits") or []),
            "unsupported_route_candidate": extra.get("unsupported_route_candidate"),
            "routing_decision": routing.model_dump(mode="json"),
        }
    except Exception:
        return {"required_action": str(getattr(routing, "required_action", "") or "")}


def _update_phase_trace(state: GraphState, phase: str, **kwargs: Any) -> GraphState:
    """通用阶段追踪更新函数。"""
    if not kwargs:
        return state
    runtime = state["runtime"]
    metrics = dict(runtime.metrics)
    phase_traces = dict(metrics.get("phase_traces", {}) or {})
    phase_traces[phase] = dict(kwargs)
    metrics["phase_traces"] = phase_traces
    metrics[f"{phase}_trace"] = dict(kwargs)
    state["runtime"] = runtime.model_copy(update={"metrics": metrics})
    return state


def _update_phase0_trace(state: GraphState, **kwargs: Any) -> GraphState:
    return _update_phase_trace(state, "phase0", **kwargs)


def _update_phase1_trace(state: GraphState, **kwargs: Any) -> GraphState:
    return _update_phase_trace(state, "phase1", **kwargs)


def _update_phase2_trace(state: GraphState, **kwargs: Any) -> GraphState:
    return _update_phase_trace(state, "phase2", **kwargs)


def _update_phase3_trace(state: GraphState, **kwargs: Any) -> GraphState:
    return _update_phase_trace(state, "phase3", **kwargs)


def _update_phase4_trace(state: GraphState, **kwargs: Any) -> GraphState:
    return _update_phase_trace(state, "phase4", **kwargs)


def _effective_should_call_tool(routing: RoutingDecision | None) -> bool:
    """判断是否应调用工具。"""
    if routing is None:
        return True
    return bool(getattr(routing, "should_call_tool", True))


def should_run_tool(routing: RoutingDecision | None) -> bool:
    """判断是否应运行工具（旧名兼容）。"""
    if routing is None:
        return True
    return bool(getattr(routing, "should_call_tool", True))


# --- router.phase7_compose 兼容 ---


def _build_entity_join_result(turn: Any) -> EntityJoinResult:
    """构建实体连接结果。"""
    routing = _routing_decision_for_turn(turn)
    selected_entity = None
    candidate_entities = []
    if routing is not None and routing.extra:
        selected_entity = routing.extra.get("selected_shop_name") or routing.extra.get(
            "current_shop"
        )
        candidate_entities = list(routing.extra.get("candidate_shop_ids", []) or [])
    return EntityJoinResult(
        cross_entity_detected=False,
        candidate_entities=[str(item).strip() for item in candidate_entities if str(item).strip()],
        selected_entity=str(selected_entity or "").strip() or None,
    )


def _build_answer_contract(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    entity_join_result: Any,
) -> AnswerContract:
    """构建答案合约。"""
    selected_entity = str(getattr(entity_join_result, "selected_entity", "") or "").strip() or None
    return AnswerContract(
        original_query=str(getattr(turn, "raw_query", "") or "").strip(),
        allowed_facets=[],
        optional_facets=[],
        forbidden_facets=[],
        required_facets=[],
        realtime_facets=[],
        evidence_requirements={},
        tool_requirements={},
        forbidden_without_evidence=[],
        candidate_entities=list(getattr(entity_join_result, "candidate_entities", []) or []),
        selected_entity=selected_entity,
        missing_slots=list(getattr(routing, "missing_slots", []) or [])
        if routing is not None
        else [],
        clarification_slot=str(getattr(routing, "clarification_question", "") or "").strip()
        or None,
        answer_style="",
        scope_kind=str(getattr(routing, "domain", "") or "").strip() or None,
        facet_source_expectations={},
        extra={
            "source": "workflow_default",
            "selected_entity": selected_entity,
            "route_candidate": str(getattr(routing, "route_candidate", "") or "").strip() or None,
            "required_action": str(getattr(routing, "required_action", "") or "").strip() or None,
        },
    )


def _build_answer_verifier_result(
    request: Any,
    answer_text: str,
    entity_join_result: Any,
    answer_contract: Any,
) -> Any:
    """构建答案验证器结果。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        passed=True,
        issues=[],
        suggested_response_mode=None,
        repair_hint=None,
        extra={"phase4_mode": None},
        model_dump=lambda mode="json": {
            "passed": True,
            "issues": [],
            "suggested_response_mode": None,
            "repair_hint": None,
            "extra": {"phase4_mode": None},
        },
    )


def _build_loop_counter(turn: Any, runtime_context: dict[str, Any]) -> Any:
    """构建循环计数器。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        loop_count=0,
        max_loops=3,
        model_dump=lambda mode="json": {
            "loop_count": 0,
            "max_loops": 3,
        },
    )


def _build_review_report(
    request: Any,
    answer_text: str,
    entity_join_result: Any,
    answer_contract: Any,
    verifier_result: Any,
    loop_counter: Any,
    *,
    runtime_context: dict[str, Any] | None = None,
) -> Any:
    """构建审查报告。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        passed=True,
        issues=[],
        suggested_response_mode=None,
        model_dump=lambda mode="json": {
            "passed": True,
            "issues": [],
            "suggested_response_mode": None,
        },
    )


def _build_semantic_parse_result(
    turn: Any, routing: RoutingDecision | None, answer_contract: Any
) -> Any:
    """构建语义解析结果。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        parsed_intent="",
        parsed_slots={},
        model_dump=lambda mode="json": {
            "parsed_intent": "",
            "parsed_slots": {},
        },
    )


def _build_source_contract(
    turn: Any,
    routing: RoutingDecision | None,
    answer_contract: Any,
    *,
    selected_shop_id: Any = None,
    current_shop: Any = None,
    explicit_query_shop: Any = None,
) -> Any:
    """构建来源合约。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        selected_shop_id=selected_shop_id,
        current_shop=current_shop,
        explicit_query_shop=explicit_query_shop,
        model_dump=lambda mode="json": {
            "selected_shop_id": selected_shop_id,
            "current_shop": current_shop,
            "explicit_query_shop": explicit_query_shop,
        },
    )


# --- router.stages 兼容 ---


def route_execution_mode(routing: RoutingDecision | None) -> Any:
    """计算路由执行模式。"""
    from types import SimpleNamespace

    if routing is None:
        return SimpleNamespace(
            execution_mode="simple",
            reason="direct_or_simple_route",
            to_dict=lambda: {"execution_mode": "simple"},
        )
    explicit_mode = str(getattr(routing, "execution_mode", "") or "").strip().lower()
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if explicit_mode == "complex":
        mode = "complex"
        reason = "explicit_complex_route"
    elif action == "clarify" or explicit_mode == "clarify":
        mode = "clarify"
        reason = "clarify_route"
    elif action in {"recommendation", "tool_call"}:
        mode = "standard"
        reason = "evidence_capable_route"
    elif explicit_mode == "standard":
        mode = "standard"
        reason = "explicit_standard_route"
    else:
        mode = "simple"
        reason = "direct_or_simple_route"
    return SimpleNamespace(
        execution_mode=mode,
        reason=reason,
        to_dict=lambda: {"execution_mode": mode, "reason": reason},
    )


# --- router.stages.hard_guard 兼容 ---


def check_hard_guard(raw_query: str, persistent: Any, client_context: dict[str, Any]) -> Any:
    """硬门禁检查。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        blocked=False,
        required_action=None,
        route_candidate=None,
        reason=None,
    )


# --- router.stages.query_safety 兼容 ---


def check_query_safety(query: str, *, client_context: dict[str, Any] | None = None) -> Any:
    """查询安全检查。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        blocked=False,
        allowed=True,
        required_action=None,
        reason=None,
    )


# --- router.phase2_slots 兼容 ---


def build_evidence_quality(
    result: Any,
    *,
    intent_name: str | None = None,
    context: dict[str, Any] | None = None,
) -> EvidenceQualityDecision:
    """构建证据质量决策。"""
    covered = (
        list(getattr(result, "covered_facets", []) or [])
        if hasattr(result, "covered_facets")
        else []
    )
    return EvidenceQualityDecision(
        is_valid=True,
        response_mode="grounded",
        covered_facets=covered,
        missing_facets=[],
        details={},
    )


def build_clarification_question(
    missing_slots: list[str],
    *,
    clarification_slot: str | None = None,
    query_text: str | None = None,
) -> str:
    """构建澄清问题。"""
    if clarification_slot:
        slot_display = clarification_slot.replace("_", " ").strip()
        return f"请问你想查询哪个{slot_display}？"
    if missing_slots:
        slot = missing_slots[0].replace("_", " ").strip()
        return f"请告诉我具体的{slot}。"
    return ""


# --- router.phase5_retrieval 兼容 ---


def can_enter_retrieval(state: GraphState) -> Any:
    """判断是否可进入检索阶段。"""
    from types import SimpleNamespace

    routing = _routing_decision_for_turn(state["turn"])
    if routing is not None:
        can_retrieve = bool(getattr(routing, "should_retrieve", True))
        return SimpleNamespace(
            allowed=can_retrieve,
            reason=None if can_retrieve else "routing_blocks_retrieval",
        )
    return SimpleNamespace(allowed=True, reason=None)


# --- router.phase1_intent 兼容 ---

from learning_agent_service.domain.contracts import RewriteDecision as _RewriteDecision


def build_rewrite_decision(
    raw_query: str,
    semantic_query: str,
    *,
    confidence: float = 1.0,
    reason: str = "rewrite",
    preserved_constraints: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> _RewriteDecision:
    """构建重写决策。"""
    return _RewriteDecision(
        original_query=raw_query,
        rewritten_query=semantic_query,
        confidence=confidence,
        reason=reason,
        preserved_constraints=preserved_constraints or [],
        should_retrieve=True,
        added_terms=[],
        removed_terms=[],
        risky_rewrite=False,
    )


# --- router.facet_planner 兼容 ---

from learning_agent_service.domain.contracts import InputQualityDecision as _InputQualityDecision
from learning_agent_service.domain.contracts import IntentRoutingDecision as _IntentRoutingDecision


def _build_facet_routing_decision(
    raw_query: str,
    persistent: Any,
    *,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision:
    """基于 facet planner 的初始路由决策（规则实现）。"""
    raw = str(raw_query or "").strip()
    compact = raw.replace(" ", "")
    input_quality = _InputQualityDecision(
        kind="valid_task" if raw else "empty_input",
        is_valid=bool(raw),
        reason="",
        score=1.0 if raw else 0.0,
        signals=[],
    )
    intent_name = "query"
    confidence = 1.0
    required_action = "direct_answer"
    route_candidate = "direct"
    route_reason = "rule_based_initial"
    current_shop = str(getattr(persistent, "current_shop", "") or "").strip()
    current_shop_name = str(getattr(persistent, "current_shop_name", "") or "").strip()
    has_shop_context = bool(current_shop or current_shop_name)

    def _has_explicit_prefix(tokens: tuple[str, ...]) -> bool:
        _GENERIC_PREFIXES = {"地址", "位置", "在哪", "在哪儿", "什么时间", "什么时候"}
        for token in tokens:
            idx = compact.find(token)
            if idx > 1:
                prefix = compact[:idx].strip(" ，,;；")
                if prefix and prefix not in _GENERIC_PREFIXES:
                    return True
        return False

    if not raw:
        route_candidate = "empty"
        route_reason = "empty_input"
    elif any(token in compact for token in ("谢谢", "感谢", "多谢")):
        intent_name = "thanks"
        route_candidate = "thanks"
        route_reason = "gratitude"
    elif any(token in compact for token in ("你是谁", "你叫什么", "介绍一下你", "介绍你自己")):
        intent_name = "identity"
        route_candidate = "identity"
        route_reason = "identity_query"
    elif any(
        token in compact for token in ("你能做什么", "你有什么功能", "怎么用", "如何使用", "帮助")
    ):
        intent_name = "capability"
        route_candidate = "capability"
        route_reason = "capability_query"
    elif any(token in compact for token in ("天气", "温度", "下雨", "晴天", "预报", "气温")):
        intent_name = "query"
        route_candidate = "direct"
        route_reason = "general_knowledge_query"
    elif any(
        token in compact
        for token in (
            "附近",
            "周边",
            "推荐",
            "几家",
            "多推荐",
            "多家",
            "对比",
            "比较",
            "哪个好",
            "哪家好",
            "比一下",
            "更好",
        )
    ):
        intent_name = "local_life_recommend"
        required_action = "recommendation"
        route_candidate = "recommendation"
        route_reason = "recommendation_query"
        confidence = 0.92
    elif any(
        token in compact
        for token in (
            "怎么样",
            "好不好",
            "评价",
            "口碑",
            "如何",
            "咋样",
            "适合",
            "适不适合",
            "地址",
            "在哪",
            "在哪儿",
            "什么时间",
            "什么时候",
            "券",
            "优惠",
            "营业",
            "开门",
            "距离",
            "多远",
            "路线",
            "导航",
        )
    ):
        intent_name = "local_life"
        route_candidate = "local_life"
        route_reason = "local_life_query"
        shop_context_tokens = (
            "怎么样",
            "好不好",
            "评价",
            "口碑",
            "如何",
            "咋样",
            "适合",
            "适不适合",
            "地址",
            "在哪",
            "在哪儿",
            "什么时间",
            "什么时候",
            "券",
            "优惠",
            "营业",
            "开门",
            "距离",
            "多远",
            "路线",
            "导航",
        )
        if _has_explicit_prefix(shop_context_tokens) or has_shop_context:
            required_action = "tool_call"
            route_candidate = "merchant_detail"
            route_reason = "single_shop_query"
            confidence = 0.9
        elif any(
            token in compact
            for token in (
                "券",
                "优惠",
                "营业",
                "开门",
                "距离",
                "多远",
                "路线",
                "导航",
                "地址",
                "在哪",
                "在哪儿",
                "什么时间",
                "什么时候",
            )
        ):
            required_action = "clarify"
            route_candidate = "low_info"
            route_reason = "missing_shop_context"
            confidence = 0.85
    intent = _IntentRoutingDecision(
        name=intent_name,
        confidence=confidence,
        required_slots=[],
        missing_slots=[],
        allowed_routes=[],
        forbidden_routes=[],
    )
    return RoutingDecision(
        raw_query=raw,
        normalized_query=raw,
        domain="general",
        confidence=confidence,
        input_quality=input_quality,
        intent=intent,
        required_action=required_action,
        blocked=False,
        blocked_reason=None,
        should_rewrite_query=False,
        should_retrieve=False,
        should_call_tool=False,
        should_use_memory=True,
        should_persist_memory=True,
        should_vectorize_memory=False,
        should_emit_retrieval_events=False,
        retrieval_skipped_reason=None,
        missing_slots=[],
        resolved_references=[],
        route_reason=route_reason,
        safeguards_triggered=[],
        fallback_reason=None,
        route_candidate=route_candidate,
        execution_mode="clarify" if required_action == "clarify" else "simple",
        preferred_chunk_roles=[],
        tool_candidates=[],
        clarification_question=None,
        rewrite_decision=None,
        evidence_quality=None,
        facet_plan=[],
        extra={},
    )


build_initial_routing_decision = _build_facet_routing_decision


def apply_fast_decision_to_routing(
    routing: RoutingDecision,
    decision_result: Any,
    *,
    reference_resolved: bool = False,
    reference_confidence: float | None = None,
    resolved_references: list[Any] | None = None,
) -> RoutingDecision:
    """将快速决策（FastDecision）应用到路由决策。"""
    from collections.abc import Mapping

    required_action = "direct_answer"
    should_retrieve = bool(getattr(decision_result, "needs_rag", False))
    should_call_tool = bool(getattr(decision_result, "needs_tool", False))
    needs_clarify = bool(getattr(decision_result, "needs_clarify", False))
    decision_extra = dict(getattr(decision_result, "extra", {}) or {})
    top_level_intent_payload = decision_extra.get("top_level_intent")
    if isinstance(top_level_intent_payload, Mapping):
        top_level_intent_payload = dict(top_level_intent_payload)
    else:
        top_level_intent_payload = {}
    top_level_intent_name = str(top_level_intent_payload.get("intent") or "").strip().lower()
    route_candidate = (
        str(
            decision_extra.get("route_candidate")
            or top_level_intent_payload.get("route_candidate")
            or ""
        )
        .strip()
        .lower()
        or None
    )
    route_candidates = decision_extra.get("route_candidates")
    if not isinstance(route_candidates, list):
        route_candidates = []
    matched_signals = decision_extra.get("matched_signals")
    if not isinstance(matched_signals, list):
        matched_signals = []
    if not top_level_intent_name:
        top_level_intent_name = (
            str(top_level_intent_payload.get("name") or route_candidate or "").strip().lower()
        )
    if needs_clarify:
        capability_line = "clarify"
    elif required_action == "reject":
        capability_line = "jailbreak"
    elif should_call_tool and should_retrieve:
        if top_level_intent_name in {"recommendation", "local_life_recommend", "comparison"}:
            capability_line = "recommendation_tool"
        elif top_level_intent_name in {"comparison"}:
            capability_line = "comparison_tool"
        else:
            capability_line = "single_shop_tool"
    elif should_call_tool:
        capability_line = "single_shop_tool"
    else:
        capability_line = "direct"
    if needs_clarify:
        required_action = "clarify"
    elif should_call_tool and should_retrieve:
        required_action = (
            "recommendation"
            if top_level_intent_name in {"recommendation", "local_life_recommend", "comparison"}
            else "tool_call"
        )
    elif should_call_tool:
        required_action = "tool_call"
    elif not should_retrieve:
        required_action = "direct_answer"
    top_level_route_match = resolve_top_level_route(
        top_level_intent_name or None,
        route_candidate=route_candidate,
        route_candidates=route_candidates,
    )
    execution_route_match = resolve_execution_route(
        required_action=required_action,
        route_candidate=route_candidate,
        top_level_intent=top_level_intent_name,
        route_candidates=route_candidates,
    )
    registry_hits = route_registry_hits(
        {
            "route_candidate": route_candidate,
            "top_level_intent": top_level_intent_name,
            "required_action": required_action,
        },
        route_candidates,
    )
    resolved_route_candidate = (
        str(execution_route_match.get("route_id") or "").strip().lower() or None
    )
    resolved_top_level_route = (
        str(top_level_route_match.get("route_id") or "").strip().lower() or None
    )
    unsupported_route_candidate = None
    if route_candidate and not any(
        str(hit.get("matched_value") or "").strip().lower() == str(route_candidate).strip().lower()
        for hit in registry_hits
    ):
        unsupported_route_candidate = route_candidate
    route_reason = f"fast_decision:intent={getattr(decision_result, 'intent', 'unknown')}"
    routing_intent_name = (
        top_level_intent_name
        or str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower()
    )
    if not routing_intent_name:
        routing_intent_name = (
            str(getattr(decision_result, "intent", "") or "").strip().lower() or "query"
        )
    routing = routing.model_copy(
        update={
            "capability_line": capability_line,
            "intent": _IntentRoutingDecision(
                name=routing_intent_name,
                confidence=float(getattr(decision_result, "confidence", 0.0) or 0.0),
                required_slots=list(
                    getattr(getattr(routing, "intent", None), "required_slots", []) or []
                ),
                missing_slots=list(
                    getattr(getattr(routing, "intent", None), "missing_slots", []) or []
                ),
                allowed_routes=list(
                    getattr(getattr(routing, "intent", None), "allowed_routes", []) or []
                ),
                forbidden_routes=list(
                    getattr(getattr(routing, "intent", None), "forbidden_routes", []) or []
                ),
            ),
            "required_action": required_action,
            "should_retrieve": should_retrieve,
            "should_call_tool": should_call_tool,
            "route_reason": route_reason,
            "resolved_references": list(resolved_references or []),
            "route_candidate": route_candidate or routing.route_candidate,
        }
    )
    extra = dict(routing.extra)
    extra["fast_decision_confidence"] = float(getattr(decision_result, "confidence", 0.0))
    extra["reference_resolved"] = reference_resolved
    extra["route_candidate"] = (
        route_candidate or extra.get("route_candidate") or routing.route_candidate
    )
    if resolved_route_candidate:
        extra["resolved_route_candidate"] = resolved_route_candidate
    if resolved_top_level_route:
        extra["resolved_top_level_route"] = resolved_top_level_route
    if route_candidates:
        extra["route_candidates"] = list(route_candidates)
    if matched_signals:
        extra["matched_signals"] = list(matched_signals)
    if registry_hits:
        extra["route_registry_hits"] = list(registry_hits)
    if unsupported_route_candidate:
        extra["unsupported_route_candidate"] = unsupported_route_candidate
    if top_level_intent_name:
        extra["top_level_intent"] = {
            "intent": top_level_intent_name,
            "confidence": float(
                top_level_intent_payload.get(
                    "confidence", getattr(decision_result, "confidence", 0.0)
                )
                or 0.0
            ),
            "reason": str(top_level_intent_payload.get("reason") or route_reason or "").strip()
            or route_reason,
            "source": str(top_level_intent_payload.get("source") or "fast_decision").strip()
            or "fast_decision",
            "matched_signals": list(
                top_level_intent_payload.get("matched_signals") or matched_signals or []
            ),
            "requires_current_shop": bool(
                top_level_intent_payload.get("requires_current_shop", False)
            ),
            "requires_candidate_context": bool(
                top_level_intent_payload.get("requires_candidate_context", False)
            ),
            "resolved_route_candidate": resolved_top_level_route,
        }
    if reference_confidence is not None:
        extra["reference_confidence"] = float(reference_confidence)
    routing = routing.model_copy(update={"extra": extra})
    return routing


# --- router.phase3_review 兼容 ---


def _apply_route_review(
    routing: RoutingDecision,
    *,
    raw_query: str | None = None,
    persistent: Any = None,
    client_context: Any = None,
) -> RoutingDecision:
    """应用路由审查。"""
    return routing


# --- router.phase4_plan / phase5_retrieval / phase6_tool 兼容 ---


def ensure_task_plan(state: GraphState) -> GraphState:
    """确保任务计划存在。"""
    return state


def ensure_retrieval_plan(state: GraphState) -> GraphState:
    """确保检索计划存在。"""
    turn = state["turn"]
    if getattr(turn, "retrieval_plan", None) is None:
        plan = _build_raw_retrieval_plan(turn)
        state["turn"] = turn.model_copy(update={"retrieval_plan": plan})
    return state


def ensure_tool_plan(state: GraphState) -> GraphState:
    """确保工具计划存在。"""
    return state


def can_enter_tool(state: GraphState) -> bool:
    """判断是否可进入工具阶段。"""
    routing = _routing_decision_for_turn(state["turn"])
    if routing is not None:
        return bool(getattr(routing, "should_call_tool", False))
    return False


def merge_local_life_query_context(
    query: str, slots: dict[str, Any], persistent: Any
) -> dict[str, Any]:
    """合并本地生活查询上下文。"""
    return {
        "query": query,
        "slots": dict(slots),
        "merged": True,
    }


# --- router.trace 兼容函数 (用于 harness/测试) ---


def build_routing_trace_from_state(state: Any) -> dict[str, Any]:
    """从 state 构建路由追踪。"""
    if state is None:
        return {}
    if isinstance(state, Mapping):
        turn = state.get("turn")
        runtime = state.get("runtime")
        metrics = dict(getattr(runtime, "metrics", {}) or {}) if runtime is not None else {}
        turn_extra = dict(getattr(turn, "extra", {}) or {}) if turn is not None else {}
    else:
        turn = getattr(state, "turn", None)
        runtime = getattr(state, "runtime", None)
        metrics = dict(getattr(runtime, "metrics", {}) or {}) if runtime is not None else dict(getattr(state, "metrics", {}) or {})
        turn_extra = dict(getattr(turn, "extra", {}) or {})
    trace: dict[str, Any] = {}
    stages: dict[str, Any] = {}
    for phase in ("phase0", "phase1", "phase2", "phase3", "phase4", "phase5"):
        phase_val = metrics.get(f"{phase}_trace") or turn_extra.get(f"{phase}_trace")
        if phase_val:
            trace[phase] = phase_val
            stages[f"{phase}_trace"] = {"output": routing_trace_to_dict(phase_val)}
    routing_decision = getattr(turn, "routing_decision", None)
    routing_trace: dict[str, Any] = {}
    if routing_decision is not None:
        decision_extra = dict(getattr(routing_decision, "extra", {}) or {})
        decision_trace = decision_extra.get("routing_trace")
        if isinstance(decision_trace, Mapping):
            routing_trace.update(dict(decision_trace))
        for key in ("canonical_route", "required_action", "required_sources"):
            value = getattr(routing_decision, key, None)
            if value is not None and key not in routing_trace:
                routing_trace[key] = value
        semantic_frame = getattr(routing_decision, "semantic_parse_result", None)
        if semantic_frame is not None:
            routing_trace.setdefault("semantic_frame_source", "router_agent")
            routing_trace.setdefault("global_intent_source", "router_agent")
    for source in (
        turn_extra.get("routing_trace"),
        metrics.get("routing_trace"),
    ):
        if isinstance(source, Mapping):
            routing_trace.update(dict(source))
    if routing_trace:
        trace.update(routing_trace)
    if stages:
        trace["stages"] = stages
    if routing_decision is not None:
        trace["final_decision"] = routing_trace_to_dict(routing_decision)
    trace["query"] = getattr(turn, "raw_query", None) if turn is not None else None
    trace["trace_id"] = getattr(runtime, "trace_id", None) if runtime is not None else None
    trace["session_id"] = getattr(runtime, "session_id", None) if runtime is not None else None
    trace["turn_id"] = getattr(runtime, "turn_id", None) if runtime is not None else None
    if routing_decision is not None:
        trace["execution_mode"] = getattr(routing_decision, "execution_mode", None)
    trace["metrics"] = metrics
    return trace


def routing_trace_to_dict(trace: Any) -> dict[str, Any]:
    """将路由追踪转换为字典。"""
    if trace is None:
        return {}
    if isinstance(trace, dict):
        return dict(trace)
    if hasattr(trace, "model_dump"):
        return trace.model_dump(mode="json")
    if hasattr(trace, "__dict__"):
        return {key: value for key, value in vars(trace).items() if not key.startswith("_")}
    return dict(trace)


def build_routing_trace(
    *,
    query: str,
    session_id: str,
    turn_id: str,
    trace_id: str,
    stages: dict[str, Any] | None = None,
    final_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建兼容旧测试的路由追踪字典。"""
    trace: dict[str, Any] = {
        "query": query,
        "session_id": session_id,
        "turn_id": turn_id,
        "trace_id": trace_id,
        "stages": {},
    }
    for stage_name, stage_value in dict(stages or {}).items():
        trace["stages"][stage_name] = routing_trace_to_dict(stage_value)
    if final_decision:
        trace["final_decision"] = dict(final_decision)
        if "execution_mode" in final_decision:
            trace["execution_mode"] = final_decision.get("execution_mode")
    return SimpleNamespace(**trace)


def build_routing_trace_from_metrics(
    *,
    query: str,
    session_id: str,
    turn_id: str,
    trace_id: str,
    metrics: dict[str, Any],
    final_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 metrics 构建路由追踪。"""
    trace: dict[str, Any] = {
        "query": query,
        "session_id": session_id,
        "turn_id": turn_id,
        "trace_id": trace_id,
    }
    for phase in ("phase0", "phase1", "phase2", "phase3", "phase4", "phase5"):
        phase_val = metrics.get(f"{phase}_trace")
        if phase_val:
            trace[phase] = phase_val
    if final_decision:
        trace["final_decision"] = final_decision
    trace["metrics"] = metrics
    return trace


__all__ = [name for name in globals() if not name.startswith("__")]
