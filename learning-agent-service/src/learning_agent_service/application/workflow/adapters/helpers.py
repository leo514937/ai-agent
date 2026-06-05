from __future__ import annotations

import json
import logging
import time

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, wait
from typing import Any, Mapping

from learning_agent_service.domain.contracts import (
    AnswerComposeRequest,
    ChatTurnCommand,
    ClarificationCard,
    CitationBuildRequest,
    EvidenceEvaluationRequest,
    FastDecision,
    EvidenceQualityDecision,
    MasteryUpdateCommand,
    HybridRetrieveRequest,
    RoutingDecision,
    PersistSessionCommand,
    QueryRewriteRequest,
    ReferenceResolutionRequest,
    ReferenceResolutionResult,
    RetrievalPlan,
    SseEnvelope,
    ToolExecutionCommand,
    ToolNormalizationRequest,
    ToolPlanningRequest,
    MemoryUpdateSummary,
    TurnUnderstandingRequest,
)
from learning_agent_service.domain.enums import IntentType
from learning_agent_service.domain.utils import as_mapping as _as_mapping, utcnow as _utc_now
from learning_agent_service.domain.errors import TerminalEvent, WorkflowErrorCode, build_error
from learning_agent_service.domain.state import GraphState, clone_graph_state
from learning_agent_service.memory.models import MemoryCapabilityError
from learning_agent_service.local_life.query_rewriter import normalize_query as normalize_local_life_query
from learning_agent_service.application.routing_primitives import _mark_routing_blocked, _pending_clarification_matches_query
from learning_agent_service.application.router import (
    apply_fast_decision_to_routing,
    _build_answer_contract,
    _build_answer_verifier_result,
    _build_entity_join_result,
    build_evidence_quality,
    build_initial_routing_decision,
    build_rewrite_decision,
    can_enter_retrieval,
    ensure_retrieval_plan,
    ensure_tool_plan,
    ensure_task_plan,
    _apply_route_review,
    _update_phase1_trace,
    _update_phase0_trace,
    _update_phase2_trace,
    _update_phase3_trace,
    _update_phase4_trace,
    routing_trace_payload,
)
from learning_agent_service.application.rag_gate import RagGateRequest
from learning_agent_service.application.workflow.legacy_routing_migration import legacy_to_routing_decision
from learning_agent_service.application.workflow.plan_execute import ReactStepExecutor

_DIRECT_RESPONSE_KINDS = {"greeting", "thanks", "farewell", "empty", "low_info", "profile", "memory_update", "conversation_recap", "location_unavailable"}
_LOGGER = logging.getLogger(__name__)
_CLASSIFY_TIMEOUT_SECONDS = 1.2
_QUERY_REWRITE_TIMEOUT_SECONDS = 1.0
def _event_sink_from_state(state: GraphState):
    runtime = state["runtime"]
    return runtime.extra.get("stream_event_sink") if isinstance(runtime.extra, Mapping) else None


def _append_runtime_event(state: GraphState, event_type: str, payload: Mapping[str, Any]) -> None:
    runtime = state["runtime"]
    events = list(runtime.emitted_events)
    events.append(
        SseEnvelope(
            event_type=event_type,
            trace_id=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            timestamp=_utc_now(),
            workflow_version=runtime.workflow_version,
            payload=dict(payload),
        )
    )
    state["runtime"] = runtime.model_copy(update={"emitted_events": events})


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
    _append_runtime_event(state, f"{stage}_{status}" if status != "heartbeat" else "heartbeat", payload)
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
        return "empty" if routing.input_quality.kind in {"empty_input", "pure_punctuation"} else "low_info"
    if routing.required_action == "clarify":
        return "low_info"
    if routing.required_action == "direct_answer":
        if candidate in {"greeting", "thanks", "profile", "farewell", "conversation_recap", "location_unavailable"}:
            return candidate
        return "low_info"
    return None


def _response_origin_for_turn(turn: Any, *, allow_direct_response: bool) -> str:
    routing = _routing_decision_for_turn(turn)
    routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
    if allow_direct_response:
        return "direct"
    if routing_action == "rag_plus_tool" and turn.rag_result is not None and turn.tool_result is not None:
        return "rag_plus_tool"
    if turn.tool_result is not None and routing_action in {"tool_call", "rag_plus_tool"}:
        return "tool"
    if turn.rag_result is not None:
        return "rag"
    return "fallback"


def _phase2_evidence_pack(turn: Any) -> Any:
    pack = getattr(turn, "evidence_pack", None)
    if pack is not None:
        return pack
    rag_result = getattr(turn, "rag_result", None)
    if rag_result is not None:
        return getattr(rag_result, "evidence_pack", None)
    return None


def _phase2_trace_reasons(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    rag_gate_blocked: bool | None = None,
) -> list[str]:
    if routing is None:
        return []
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if action != "rag_plus_tool":
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

    if rag_gate_blocked is None:
        pack = _phase2_evidence_pack(turn)
        rag_gate_blocked = bool(pack is None or not getattr(pack, "items", None))
        if not rag_gate_blocked and evidence_quality is not None:
            rag_gate_blocked = bool(
                not getattr(evidence_quality, "is_valid", True)
                and str(getattr(evidence_quality, "response_mode", "") or "").strip().lower() in {"no_answer", "weak_answer"}
            )
    if rag_gate_blocked:
        reasons.append("rag_gate_blocked")

    return list(dict.fromkeys(reasons))


def _build_phase2_trace(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    response_origin: str | None = None,
    answer_confidence: float | None = None,
    final_response_mode: str | None = None,
    rag_gate_blocked: bool | None = None,
    evidence_after_gate_count: int | None = None,
) -> dict[str, Any]:
    reasons = _phase2_trace_reasons(turn, routing, evidence_quality, rag_gate_blocked=rag_gate_blocked)
    effective_response_mode = (
        str(final_response_mode or getattr(evidence_quality, "response_mode", "") or "").strip().lower() or None
    )
    missing_slots = list(getattr(routing, "missing_slots", []) or []) if routing is not None else []
    tool_candidates = list(getattr(routing, "tool_candidates", []) or []) if routing is not None else []
    clarification_slot = (
        getattr(evidence_quality, "clarification_slot", None)
        or (missing_slots[0] if missing_slots else None)
        or None
    )
    if evidence_after_gate_count is None:
        pack = _phase2_evidence_pack(turn)
        evidence_after_gate_count = len(getattr(pack, "items", []) or []) if pack is not None else 0

    trace: dict[str, Any] = {
        "active": bool(reasons or effective_response_mode or response_origin or answer_confidence is not None),
        "required_action": str(getattr(routing, "required_action", "") or "").strip().lower() or None if routing is not None else None,
        "response_mode": effective_response_mode,
        "response_origin": response_origin,
        "answer_confidence": answer_confidence,
        "rag_plus_tool_failed": bool(reasons),
        "rag_plus_tool_failure_reason": reasons[0] if reasons else None,
        "rag_plus_tool_failure_reasons": reasons,
        "retrieval_plan_missing": "retrieval_plan_missing" in reasons,
        "tool_plan_missing": "tool_plan_missing" in reasons,
        "tool_slot_missing": "tool_slot_missing" in reasons,
        "tool_not_allowed": "tool_not_allowed" in reasons,
        "retrieval_not_allowed": "retrieval_not_allowed" in reasons,
        "rag_gate_blocked": "rag_gate_blocked" in reasons,
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
    for key in ("route_review_decision", "required_facets", "optional_facets", "required_facets_source_constraints", "user_need", "pending_clarification_restore"):
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


def _apply_phase1_routing_extra(turn_extra: dict[str, Any], routing: RoutingDecision | None) -> dict[str, Any]:
    if routing is None:
        return turn_extra
    merged = dict(turn_extra)
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    for key in ("route_review_decision", "required_facets", "optional_facets", "required_facets_source_constraints", "user_need", "pending_clarification_restore"):
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

    ambiguity_type = str(clarification_result.get("ambiguity_type") or "").strip().lower()
    if ambiguity_type not in {"location", "city", "area", "district", "region"}:
        return persistent, turn

    question_text = str(
        clarification_result.get("question")
        or clarification_result.get("clarification_question")
        or clarification_result.get("original_question")
        or clarification_result.get("query")
        or ""
    ).strip() or "你现在在哪个城市或位置附近？"
    pending_clarification = ClarificationCard(
        card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
        question=question_text,
        options=[],
        ambiguity_type=ambiguity_type,
        source_turn_id=str(
            clarification_result.get("source_turn_id")
            or clarification_result.get("turn_id")
            or runtime.turn_id
        ).strip() or runtime.turn_id,
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


def _build_cached_rag_gate(
    required_action: str,
    intent: IntentType,
    confidence: float,
    payload: Mapping[str, Any],
    slots: Mapping[str, Any],
) -> dict[str, Any]:
    route_candidate = str(payload.get("route_candidate") or slots.get("route_candidate") or "").strip().lower() or None
    allowed = str(required_action).strip().lower() in {"rag_retrieval", "rag_plus_tool"}
    response_kind = "fallback"
    if not allowed:
        response_kind = route_candidate or (
            "low_info"
            if str(required_action).strip().lower() == "clarify" or (intent == IntentType.FOLLOW_UP and confidence < 0.5)
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


def _cached_rag_gate(turn: Any) -> dict[str, Any] | None:
    extra = dict(getattr(turn, "extra", {}) or {})
    rag_gate = extra.get("rag_gate")
    if isinstance(rag_gate, Mapping) and "allowed" in rag_gate:
        return dict(rag_gate)
    cached_vote = extra.get("cached_rag_gate_vote")
    if isinstance(cached_vote, Mapping) and "allowed" in cached_vote:
        return dict(cached_vote)
    return None
def _event_sink_from_state(state: GraphState):
    runtime = state["runtime"]
    return runtime.extra.get("stream_event_sink") if isinstance(runtime.extra, Mapping) else None


def _append_runtime_event(state: GraphState, event_type: str, payload: Mapping[str, Any]) -> None:
    runtime = state["runtime"]
    events = list(runtime.emitted_events)
    events.append(
        SseEnvelope(
            event_type=event_type,
            trace_id=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            timestamp=_utc_now(),
            workflow_version=runtime.workflow_version,
            payload=dict(payload),
        )
    )
    state["runtime"] = runtime.model_copy(update={"emitted_events": events})


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
    _append_runtime_event(state, f"{stage}_{status}" if status != "heartbeat" else "heartbeat", payload)
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
        return "empty" if routing.input_quality.kind in {"empty_input", "pure_punctuation"} else "low_info"
    if routing.required_action == "clarify":
        return "low_info"
    if routing.required_action == "direct_answer":
        if candidate in {"greeting", "thanks", "profile", "farewell", "conversation_recap", "location_unavailable"}:
            return candidate
        return "low_info"
    return None


def _response_origin_for_turn(turn: Any, *, allow_direct_response: bool) -> str:
    routing = _routing_decision_for_turn(turn)
    routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
    if allow_direct_response:
        return "direct"
    if routing_action == "rag_plus_tool" and turn.rag_result is not None and turn.tool_result is not None:
        return "rag_plus_tool"
    if turn.tool_result is not None and routing_action in {"tool_call", "rag_plus_tool"}:
        return "tool"
    if turn.rag_result is not None:
        return "rag"
    return "fallback"


def _phase2_evidence_pack(turn: Any) -> Any:
    pack = getattr(turn, "evidence_pack", None)
    if pack is not None:
        return pack
    rag_result = getattr(turn, "rag_result", None)
    if rag_result is not None:
        return getattr(rag_result, "evidence_pack", None)
    return None


def _phase2_trace_reasons(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    rag_gate_blocked: bool | None = None,
) -> list[str]:
    if routing is None:
        return []
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if action != "rag_plus_tool":
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

    if rag_gate_blocked is None:
        pack = _phase2_evidence_pack(turn)
        rag_gate_blocked = bool(pack is None or not getattr(pack, "items", None))
        if not rag_gate_blocked and evidence_quality is not None:
            rag_gate_blocked = bool(
                not getattr(evidence_quality, "is_valid", True)
                and str(getattr(evidence_quality, "response_mode", "") or "").strip().lower() in {"no_answer", "weak_answer"}
            )
    if rag_gate_blocked:
        reasons.append("rag_gate_blocked")

    return list(dict.fromkeys(reasons))


def _build_phase2_trace(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    *,
    response_origin: str | None = None,
    answer_confidence: float | None = None,
    final_response_mode: str | None = None,
    rag_gate_blocked: bool | None = None,
    evidence_after_gate_count: int | None = None,
) -> dict[str, Any]:
    reasons = _phase2_trace_reasons(turn, routing, evidence_quality, rag_gate_blocked=rag_gate_blocked)
    effective_response_mode = (
        str(final_response_mode or getattr(evidence_quality, "response_mode", "") or "").strip().lower() or None
    )
    missing_slots = list(getattr(routing, "missing_slots", []) or []) if routing is not None else []
    tool_candidates = list(getattr(routing, "tool_candidates", []) or []) if routing is not None else []
    clarification_slot = (
        getattr(evidence_quality, "clarification_slot", None)
        or (missing_slots[0] if missing_slots else None)
        or None
    )
    if evidence_after_gate_count is None:
        pack = _phase2_evidence_pack(turn)
        evidence_after_gate_count = len(getattr(pack, "items", []) or []) if pack is not None else 0

    trace: dict[str, Any] = {
        "active": bool(reasons or effective_response_mode or response_origin or answer_confidence is not None),
        "required_action": str(getattr(routing, "required_action", "") or "").strip().lower() or None if routing is not None else None,
        "response_mode": effective_response_mode,
        "response_origin": response_origin,
        "answer_confidence": answer_confidence,
        "rag_plus_tool_failed": bool(reasons),
        "rag_plus_tool_failure_reason": reasons[0] if reasons else None,
        "rag_plus_tool_failure_reasons": reasons,
        "retrieval_plan_missing": "retrieval_plan_missing" in reasons,
        "tool_plan_missing": "tool_plan_missing" in reasons,
        "tool_slot_missing": "tool_slot_missing" in reasons,
        "tool_not_allowed": "tool_not_allowed" in reasons,
        "retrieval_not_allowed": "retrieval_not_allowed" in reasons,
        "rag_gate_blocked": "rag_gate_blocked" in reasons,
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
    for key in ("route_review_decision", "required_facets", "optional_facets", "required_facets_source_constraints", "user_need", "pending_clarification_restore"):
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


def _apply_phase1_routing_extra(turn_extra: dict[str, Any], routing: RoutingDecision | None) -> dict[str, Any]:
    if routing is None:
        return turn_extra
    merged = dict(turn_extra)
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    for key in ("route_review_decision", "required_facets", "optional_facets", "required_facets_source_constraints", "user_need", "pending_clarification_restore"):
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

    ambiguity_type = str(clarification_result.get("ambiguity_type") or "").strip().lower()
    if ambiguity_type not in {"location", "city", "area", "district", "region"}:
        return persistent, turn

    question_text = str(
        clarification_result.get("question")
        or clarification_result.get("clarification_question")
        or clarification_result.get("original_question")
        or clarification_result.get("query")
        or ""
    ).strip() or "你现在在哪个城市或位置附近？"
    pending_clarification = ClarificationCard(
        card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
        question=question_text,
        options=[],
        ambiguity_type=ambiguity_type,
        source_turn_id=str(
            clarification_result.get("source_turn_id")
            or clarification_result.get("turn_id")
            or runtime.turn_id
        ).strip() or runtime.turn_id,
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


def _build_cached_rag_gate(
    required_action: str,
    intent: IntentType,
    confidence: float,
    payload: Mapping[str, Any],
    slots: Mapping[str, Any],
) -> dict[str, Any]:
    route_candidate = str(payload.get("route_candidate") or slots.get("route_candidate") or "").strip().lower() or None
    allowed = str(required_action).strip().lower() in {"rag_retrieval", "rag_plus_tool"}
    response_kind = "fallback"
    if not allowed:
        response_kind = route_candidate or (
            "low_info"
            if str(required_action).strip().lower() == "clarify" or (intent == IntentType.FOLLOW_UP and confidence < 0.5)
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


def _cached_rag_gate(turn: Any) -> dict[str, Any] | None:
    extra = dict(getattr(turn, "extra", {}) or {})
    rag_gate = extra.get("rag_gate")
    if isinstance(rag_gate, Mapping) and "allowed" in rag_gate:
        return dict(rag_gate)
    cached_vote = extra.get("cached_rag_gate_vote")
    if isinstance(cached_vote, Mapping) and "allowed" in cached_vote:
        return dict(cached_vote)
    return None


def _build_recommendation_answer_text(
    shop_names: list[str],
    limit: int = 3,
    fallback_text: str | None = None,
) -> str:
    if not shop_names:
        return fallback_text or "我暂时没找到合适的店。"
    lines = ["我帮你推荐以下这几家店铺：", ""]
    for i, name in enumerate(shop_names[:limit], 1):
        lines.append(f"{i}. {name}")
        lines.append("- 推荐理由：当前候选里它的综合信息比较靠前，值得优先查看。")
        lines.append("- 适合场景：适合约会、聊天或轻松聚餐。")
        lines.append("- 注意事项：建议先确认营业状态、预算和是否需要排队。")
        lines.append("")
    lines.append("综合建议")
    lines.append("- 如果你更在意氛围和稳定性，建议先从前两家开始看。")
    return "\n".join(lines).strip()


def _build_single_shop_review_answer(shop_name: str | None) -> str:
    name = str(shop_name or "这家店").strip() or "这家店"
    return "\n".join(
        [
            "总体结论",
            f"- {name}整体上可以先作为候选，当前信息支持继续观察。",
            "核心优点",
            "- 当前证据和排序都说明它有一定优势，适合继续筛选。",
            "- 如果你更看重环境和体验，可以优先看这家。",
            "可能不足",
            "- 仍建议结合营业状态、预算和排队情况再确认一次。",
            "适合场景",
            "- 适合想先快速判断，再决定是否到店的场景。",
            "到店建议",
            "- 先看营业时间和实时信息，再决定是否现在去。",
        ]
    )


__all__ = [name for name in globals() if not name.startswith("__")]
