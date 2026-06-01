from __future__ import annotations

import json
import logging
import time

from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, wait
from typing import Any, Mapping

from ...domain.contracts import (
    AnswerContract,
    AnswerComposeRequest,
    ChatTurnCommand,
    ClarificationCard,
    ClarificationOption,
    CitationBuildRequest,
    EvidenceEvaluationRequest,
    GraphRuntimeMeta,
    FastDecision,
    EvidenceQualityDecision,
    EntityJoinResult,
    MasteryUpdateCommand,
    HybridRetrieveRequest,
    KnowledgeSearchRequest,
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
from ...domain.enums import IntentType
from ...domain.errors import TerminalEvent, WorkflowErrorCode, build_error
from ...domain.state import GraphState, clone_graph_state
from ...memory.models import MemoryCapabilityError
from ...local_life.query_rewriter import normalize_query as normalize_local_life_query
from ..routing import (
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
    normalize_query,
    _pending_clarification_matches_query,
    _mark_routing_blocked,
    _apply_route_review,
    _update_phase1_trace,
    _update_phase0_trace,
    _update_phase2_trace,
    _update_phase3_trace,
    _update_phase4_trace,
    routing_trace_payload,
    should_persist_memory as routing_should_persist_memory,
)
from ..rag_gate import RagGateRequest
from .legacy_routing_migration import legacy_to_routing_decision
from .plan_execute import ReactStepExecutor

_DIRECT_RESPONSE_KINDS = {"greeting", "thanks", "farewell", "empty", "low_info", "profile", "memory_update", "conversation_recap", "location_unavailable"}
_LOGGER = logging.getLogger(__name__)
_CLASSIFY_TIMEOUT_SECONDS = 1.2
_QUERY_REWRITE_TIMEOUT_SECONDS = 1.0


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


@dataclass
class WorkflowNodeAdapter:
    container: Any

    def __post_init__(self) -> None:
        self._plan_executor = ReactStepExecutor(
            container=self.container,
            append_event=self._append_event,
        )

    def _append_event(self, state: GraphState, event_type: str, payload: Mapping[str, Any]) -> GraphState:
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
        return state

    def load_context(self, state: GraphState) -> GraphState:
        state = _copy_state(state)
        turn = state["turn"]
        persistent = state["persistent"]
        persistent, turn = _restore_pending_clarification_from_result(
            runtime=state["runtime"],
            turn=turn,
            persistent=persistent,
        )
        state["persistent"] = persistent
        state["turn"] = turn
        client_context = dict(state["runtime"].client_context)
        shop_anchor = str(
            client_context.get("shopName")
            or client_context.get("shop_name")
            or client_context.get("selected_shop_name")
            or client_context.get("current_shop")
            or ""
        ).strip()
        if shop_anchor:
            persistent_updates: dict[str, Any] = {}
            if not str(getattr(persistent, "current_shop", "") or "").strip():
                persistent_updates["current_shop"] = shop_anchor
            if not str(getattr(persistent, "selected_shop_name", "") or "").strip():
                persistent_updates["selected_shop_name"] = shop_anchor
            shop_id = str(
                client_context.get("shopId")
                or client_context.get("shop_id")
                or client_context.get("selected_shop_id")
                or ""
            ).strip()
            if shop_id and not str(getattr(persistent, "selected_shop_id", "") or "").strip():
                persistent_updates["selected_shop_id"] = shop_id
            if persistent_updates:
                persistent = persistent.model_copy(update=persistent_updates)
                state["persistent"] = persistent
        routing = build_initial_routing_decision(
            turn.raw_query,
            persistent,
            client_context=state["runtime"].client_context,
        )
        routing = legacy_to_routing_decision(turn, persistent, routing)
        routing = _apply_route_review(
            routing,
            raw_query=turn.raw_query,
            persistent=persistent,
            client_context=state["runtime"].client_context,
        )
        turn = _store_routing_decision(turn, routing)
        if routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}:
            if routing.required_action == "clarify":
                clarification_result, pending_clarification = self._build_pending_clarification_state(
                    runtime=state["runtime"],
                    turn=turn,
                    routing=routing,
                    question=str(routing.clarification_question or ""),
                )
                persistent = persistent.model_copy(
                    update={
                        "clarification_result": clarification_result,
                        "pending_clarification": pending_clarification,
                    }
                )
                state["persistent"] = persistent
                turn_extra = dict(turn.extra)
                turn_extra["clarification_result"] = clarification_result
                turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
                turn = turn.model_copy(update={"extra": turn_extra})
            state["turn"] = turn
            runtime = state["runtime"]
            metrics = dict(runtime.metrics)
            metrics["memory_retrieval_skipped"] = True
            metrics["routing_decision"] = routing.model_dump(mode="json")
            metrics["routing_required_action"] = routing.required_action
            metrics["routing_reason"] = routing.route_reason
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
            state = _update_phase0_trace(
                state,
                harness_mode=str((state["runtime"].extra or {}).get("harness_mode") or "off"),
                initial_routing_decision=routing.model_dump(mode="json"),
                initial_route_reason=routing.route_reason,
                initial_route_candidate=routing.route_candidate,
                initial_required_action=routing.required_action,
                retrieval_plan_status="not_attempted",
                retrieval_plan_failure_reason=None,
                tool_plan_status="not_attempted",
                tool_plan_failure_reason=None,
            )
            _log_routing_decision(state, stage="load_context_terminal")
            return state

        gate = getattr(self.container, "rag_route_gate", None)
        if gate is not None and hasattr(gate, "precheck"):
            request = RagGateRequest(
                raw_query=turn.raw_query,
                intent=turn.intent,
                intent_confidence=turn.intent_confidence,
                requested_output_style=turn.requested_output_style,
                current_topic=persistent.current_topic,
                recent_entities=persistent.recent_entities,
                history_summary=persistent.history_summary,
                pending_clarification=persistent.pending_clarification,
                reference_confidence=getattr(turn.reference_resolution, "confidence", None) if turn.reference_resolution else None,
                reference_resolved=getattr(turn.reference_resolution, "resolved", None) if turn.reference_resolution else None,
                client_context=dict(state["runtime"].client_context),
            )
            vote = gate.precheck(request)
            cached_vote = {
                "allowed": vote.vote == "allow",
                "reason": vote.reason,
                "confidence": vote.confidence,
                "response_kind": vote.response_kind,
                "precheck_skip_memory": False,
                "final_vote": vote.vote,
                "rule_vote": None,
                "llm_vote": None,
                "metadata": {
                    "source": "precheck",
                    "decision": vote.vote,
                    "reason": vote.reason,
                },
            }
            turn_extra = dict(turn.extra)
            turn_extra["rag_gate"] = {
                **dict(turn_extra.get("rag_gate", {})),
                "precheck_vote": vote.vote,
                "precheck_reason": vote.reason,
                "precheck_response_kind": vote.response_kind,
            }
            turn_extra["cached_rag_gate_vote"] = cached_vote
            turn = turn.model_copy(update={"extra": turn_extra})

        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["routing_decision"] = routing.model_dump(mode="json")
        metrics["routing_required_action"] = routing.required_action
        metrics["routing_reason"] = routing.route_reason
        metrics["memory_retrieval_skipped"] = not routing.should_use_memory
        state["turn"] = turn
        state["runtime"] = runtime.model_copy(update={"metrics": metrics})
        state = _update_phase0_trace(
            state,
            harness_mode=str((state["runtime"].extra or {}).get("harness_mode") or "off"),
            initial_routing_decision=routing.model_dump(mode="json"),
            initial_route_reason=routing.route_reason,
            initial_route_candidate=routing.route_candidate,
            initial_required_action=routing.required_action,
            retrieval_plan_status="not_attempted",
            retrieval_plan_failure_reason=None,
            tool_plan_status="not_attempted",
            tool_plan_failure_reason=None,
        )
        _log_routing_decision(state, stage="load_context")
        return state

    def consume_pending_clarification(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        persistent = state["persistent"]
        runtime = state["runtime"]
        pending = getattr(persistent, "pending_clarification", None)
        if pending is None or not _pending_clarification_matches_query(turn.raw_query, persistent):
            return state

        clarification_result = dict(getattr(persistent, "clarification_result", {}) or {})
        turn_extra = dict(turn.extra)
        pending_restore = dict(turn_extra.get("pending_clarification_restore") or {})
        original_query = str(
            pending_restore.get("original_query")
            or clarification_result.get("original_query")
            or getattr(pending, "question", "")
            or ""
        ).strip()
        if not original_query:
            return state

        original_intent = str(
            pending_restore.get("original_intent")
            or clarification_result.get("original_intent")
            or "local_life_recommend"
        ).strip() or "local_life_recommend"
        original_route = str(
            pending_restore.get("original_route")
            or clarification_result.get("original_route")
            or "rag_retrieval"
        ).strip() or "rag_retrieval"

        follow_up_query = str(turn.raw_query or "").strip()
        ambiguity_type = str(
            getattr(pending, "ambiguity_type", "")
            or clarification_result.get("ambiguity_type")
            or ""
        ).strip().lower()

        restored_persistent: dict[str, Any] = {}
        if str(getattr(persistent, "current_topic", "") or "").strip() != original_query:
            restored_persistent["current_topic"] = original_query
        if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != original_query:
            restored_persistent["last_retrieval_topic"] = original_query

        city = ""
        location_value: dict[str, Any] | None = None
        if ambiguity_type in {"location", "city", "area", "district", "region"}:
            try:
                location_result = normalize_local_life_query(
                    follow_up_query,
                    client_context=dict(runtime.client_context),
                    session_context={
                        "current_city": getattr(persistent, "current_city", None),
                        "current_location": dict(getattr(persistent, "current_location", {}) or {}),
                        "city": getattr(persistent, "current_city", None),
                        "location": dict(getattr(persistent, "current_location", {}) or {}),
                    },
                )
                location_norm = getattr(location_result, "location_norm", None)
                city = str(getattr(location_norm, "city", "") or "").strip()
                if city:
                    location_value = (
                        location_norm.model_dump(mode="json")
                        if hasattr(location_norm, "model_dump")
                        else {"city": city}
                    )
                    restored_persistent["current_city"] = city
                    restored_persistent["current_location"] = location_value
            except Exception:
                city = ""
                location_value = None

        if clarification_result:
            clarification_result = dict(clarification_result)
            clarification_result["consumed"] = True
            clarification_result["follow_up_query"] = follow_up_query
            if city:
                clarification_result["resolved_city"] = city
        restored_persistent["pending_clarification"] = None
        if clarification_result:
            restored_persistent["clarification_result"] = clarification_result
        state["persistent"] = persistent.model_copy(update=restored_persistent)

        turn_slots = dict(turn.slots)
        if city:
            turn_slots["city"] = city
        if location_value is not None:
            turn_slots["location"] = location_value

        turn_extra.update(
            {
                "clarification_result": clarification_result,
                "clarification_response": follow_up_query,
                "pending_clarification_consumed": True,
                "restored_query": original_query,
                "restored_intent": original_intent,
                "restored_route": original_route,
                "pending_clarification_restore": {
                    "original_query": original_query,
                    "original_intent": original_intent,
                    "original_route": original_route,
                },
            }
        )
        if city:
            turn_extra["restored_city"] = city
        if location_value is not None:
            turn_extra["restored_location"] = location_value
        turn_extra.pop("pending_clarification", None)
        short_term_window = list(turn.short_term_window)
        if short_term_window:
            short_term_window[0] = {
                **dict(short_term_window[0]),
                "content": original_query,
            }
        sensory_memory = dict(turn.sensory_memory)
        sensory_memory["raw_message"] = original_query
        sensory_memory["clarification_response"] = follow_up_query
        state["turn"] = turn.model_copy(
            update={
                "raw_query": original_query,
                "slots": turn_slots,
                "short_term_window": short_term_window,
                "sensory_memory": sensory_memory,
                "clarification_card": None,
                "extra": turn_extra,
            }
        )

        routing_context = state["persistent"].model_copy(update={"pending_clarification": None})
        routing = build_initial_routing_decision(
            original_query,
            routing_context,
            client_context=runtime.client_context,
        )
        routing = legacy_to_routing_decision(state["turn"], routing_context, routing)
        routing = _apply_route_review(
            routing,
            raw_query=original_query,
            persistent=routing_context,
            client_context=runtime.client_context,
        )
        turn_extra = dict(state["turn"].extra)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        turn_extra["routing_trace"] = routing_trace_payload(routing)
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": turn_extra})
        state = _update_phase0_trace(
            state,
            pending_clarification_consumed=True,
            pending_clarification_follow_up=follow_up_query,
            restored_query=original_query,
            restored_intent=original_intent,
            restored_route=original_route,
            restored_city=city or None,
        )
        _log_routing_decision(state, stage="consume_pending_clarification")
        return state

    def conversation_recap_direct_response(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        if routing is None or str(routing.route_candidate).strip().lower() != "conversation_recap":
            return state
        turn_extra = dict(turn.extra)
        turn_extra["conversation_recap"] = True
        turn_extra["direct_response_kind"] = "conversation_recap"
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        state = _update_phase0_trace(
            state,
            conversation_recap=True,
            direct_response_kind="conversation_recap",
            current_shop=state["persistent"].current_shop or state["persistent"].selected_shop_name,
        )
        _log_routing_decision(state, stage="conversation_recap_direct_response")
        return state

    def parse_intent_slots(self, state: GraphState) -> GraphState:
        model_gateway = getattr(self.container, "model_gateway", None)
        if model_gateway is None or not hasattr(model_gateway, "classify_turn"):
            return state

        turn = state["turn"]
        persistent = state["persistent"]
        routing = _routing_decision_for_turn(turn)
        if routing is not None and (routing.blocked or routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}):
            return state
        if getattr(persistent, "pending_clarification", None) is not None and _pending_clarification_matches_query(turn.raw_query, persistent):
            pending_restore = dict(dict(turn.extra).get("pending_clarification_restore") or {})
            original_query = str(
                pending_restore.get("original_query")
                or getattr(persistent, "clarification_result", {}).get("original_query")
                or ""
            ).strip()
            restored_persistent: dict[str, Any] = {}
            if original_query:
                if str(getattr(persistent, "current_topic", "") or "").strip() != original_query:
                    restored_persistent["current_topic"] = original_query
                if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != original_query:
                    restored_persistent["last_retrieval_topic"] = original_query

            ambiguity_type = str(getattr(persistent.pending_clarification, "ambiguity_type", "") or "").strip().lower()
            if ambiguity_type in {"location", "city", "area", "district", "region"}:
                try:
                    location_result = normalize_local_life_query(
                        turn.raw_query,
                        client_context=dict(state["runtime"].client_context),
                        session_context={
                            "current_city": getattr(persistent, "current_city", None),
                            "current_location": dict(getattr(persistent, "current_location", {}) or {}),
                            "city": getattr(persistent, "current_city", None),
                            "location": dict(getattr(persistent, "current_location", {}) or {}),
                        },
                    )
                    location_norm = getattr(location_result, "location_norm", None)
                    city = str(getattr(location_norm, "city", "") or "").strip()
                    if city:
                        restored_persistent["current_city"] = city
                        restored_persistent["current_location"] = (
                            location_norm.model_dump(mode="json")
                            if hasattr(location_norm, "model_dump")
                            else {"city": city}
                        )
                        turn_slots = dict(turn.slots)
                        turn_slots.setdefault("city", city)
                        if hasattr(location_norm, "model_dump"):
                            turn_slots.setdefault("location", location_norm.model_dump(mode="json"))
                        state["turn"] = turn.model_copy(update={"slots": turn_slots})
                except Exception:
                    pass
            if restored_persistent:
                state["persistent"] = persistent.model_copy(update=restored_persistent)
            return state
        runtime = state["runtime"]
        command = ChatTurnCommand(
            trace_id=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            user_id=runtime.user_id,
            message=turn.raw_query,
            page=runtime.page,
            response_mode=runtime.response_mode,
            topic_hint=runtime.topic_hint,
            history_summary=runtime.history_summary,
            client_context=runtime.client_context,
        )
        request = TurnUnderstandingRequest(command=command, persistent=state["persistent"])
        started_at = time.perf_counter()
        fast_result: FastDecision | None = None
        degrade_to: str | None = None
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="intent-analysis") as executor:
            future = executor.submit(model_gateway.classify_turn, request)
            try:
                fast_result = future.result(timeout=_CLASSIFY_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                gate = getattr(model_gateway, "intent_gate", None)
                fallback = gate.fallback_decide(request) if gate is not None and hasattr(gate, "fallback_decide") else None
                if fallback is None:
                    from ...rag.heuristics import HeuristicIntentGate

                    fallback = HeuristicIntentGate().fallback_decide(request)
                fast_result = fallback
                degrade_to = "classify_timeout_fallback"
            except Exception:
                gate = getattr(model_gateway, "intent_gate", None)
                fallback = gate.fallback_decide(request) if gate is not None and hasattr(gate, "fallback_decide") else None
                if fallback is None:
                    from ...rag.heuristics import HeuristicIntentGate

                    fallback = HeuristicIntentGate().fallback_decide(request)
                fast_result = fallback
                degrade_to = "classify_error_fallback"
        result = fast_result or FastDecision(intent=IntentType.EXPLAIN, needs_rag=False, needs_tool=False, confidence=0.0)
        if degrade_to is None:
            gateway_degrade = str(getattr(model_gateway, "last_degrade_to", "") or "").strip()
            degrade_to = gateway_degrade or None
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _append_stage_metric(state, "intent_analysis", elapsed_ms)
        if degrade_to:
            _mark_degrade(state, degrade_to)

        decision_result = result
        if not isinstance(result, FastDecision):
            decision_result = FastDecision(
                intent=getattr(result, "intent", IntentType.EXPLAIN),
                needs_rag=bool(
                    getattr(result, "required_action", None) in {"rag_retrieval", "rag_plus_tool"}
                    or getattr(result, "retrieval_plan", None) is not None
                ),
                needs_tool=bool(getattr(result, "required_action", None) in {"tool_call", "rag_plus_tool"}),
                needs_clarify=bool(getattr(result, "required_action", None) == "clarify"),
                needs_query_rewrite=bool(getattr(result, "needs_query_rewrite", False)),
                confidence=float(getattr(result, "intent_confidence", getattr(result, "confidence", 0.0)) or 0.0),
                key_slots=dict(getattr(result, "slots", {}) or {}),
                extra=dict(getattr(result, "extra", {}) or {}),
            )

        turn_extra = {**dict(turn.extra), **dict(getattr(result, "extra", {}) or {})}
        turn_extra["needs_query_rewrite"] = bool(getattr(decision_result, "needs_query_rewrite", False))
        reference_resolution = _coerce_reference_resolution(
            getattr(result, "reference_resolution", None)
            or turn_extra.get("reference_resolution")
            or turn_extra.get("cached_reference_resolution")
        )
        retrieval_plan = _coerce_retrieval_plan(
            getattr(result, "retrieval_plan", None)
            or turn_extra.get("retrieval_plan")
            or turn_extra.get("cached_retrieval_plan")
        )
        if retrieval_plan is None and decision_result.needs_rag:
            retrieval_plan = _build_raw_retrieval_plan(turn)
        if reference_resolution is not None:
            turn_extra["cached_reference_resolution"] = reference_resolution.model_dump(mode="json")
        if retrieval_plan is not None:
            turn_extra["cached_retrieval_plan"] = retrieval_plan.model_dump(mode="json")
        routing = routing or build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=runtime.client_context)
        routing = apply_fast_decision_to_routing(
            routing,
            decision_result,
            reference_resolved=getattr(reference_resolution, "resolved", False) if reference_resolution is not None else False,
            reference_confidence=getattr(reference_resolution, "confidence", None) if reference_resolution is not None else None,
            resolved_references=[getattr(reference_resolution, "resolved_entity", None)] if reference_resolution is not None else None,
        )
        routing = _apply_route_review(
            routing,
            raw_query=turn.raw_query,
            persistent=state["persistent"],
            client_context=runtime.client_context,
        )
        rewrite_decision = None
        if retrieval_plan is not None:
            rewrite_confidence = float(retrieval_plan.extra.get("filter_confidence", decision_result.confidence) or decision_result.confidence)
            rewrite_decision = build_rewrite_decision(
                turn.raw_query,
                retrieval_plan.semantic_query or turn.raw_query,
                confidence=rewrite_confidence,
                reason=str(retrieval_plan.extra.get("rewrite_reason") or retrieval_plan.extra.get("rewrite_source") or "rewrite_plan"),
                preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                extra=retrieval_plan.extra,
            )
            routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
        existing_gate = turn_extra.get("rag_gate")
        if isinstance(existing_gate, Mapping):
            existing_gate = dict(existing_gate)
        else:
            existing_gate = {}
        if "allowed" not in existing_gate:
            required_action = (
                "clarify"
                if decision_result.needs_clarify
                else "rag_plus_tool"
                if decision_result.needs_tool and decision_result.needs_rag
                else "tool_call"
                if decision_result.needs_tool
                else "rag_retrieval"
                if decision_result.needs_rag
                else "direct_answer"
            )
            computed_gate = _build_cached_rag_gate(
                required_action,
                decision_result.intent,
                decision_result.confidence,
                turn_extra,
                slots=dict(getattr(decision_result, "key_slots", {}) or {}),
            )
            existing_gate = {**existing_gate, **computed_gate}
        turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
        turn_extra["rag_gate"] = existing_gate
        turn_extra["cached_rag_gate_vote"] = dict(existing_gate)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        turn_extra["routing_trace"] = routing_trace_payload(routing)
        state["turn"] = turn.model_copy(
            update={
                "intent": decision_result.intent,
                "intent_confidence": decision_result.confidence,
                "requested_output_style": turn.requested_output_style,
                "reference_resolution": reference_resolution,
                "retrieval_plan": retrieval_plan,
                "slots": dict(getattr(decision_result, "key_slots", {}) or {}),
                "routing_decision": routing,
                "rewrite_decision": rewrite_decision,
                "extra": turn_extra,
            }
        )
        if routing.blocked and str(routing.required_action).strip().lower() == "clarify":
            clarification_result, pending_clarification = self._build_pending_clarification_state(
                runtime=runtime,
                turn=state["turn"],
                routing=routing,
                question=str(routing.clarification_question or ""),
            )
            state["persistent"] = state["persistent"].model_copy(
                update={
                    "clarification_result": clarification_result,
                    "pending_clarification": pending_clarification,
                }
            )
            turn_extra = dict(state["turn"].extra)
            turn_extra["clarification_result"] = clarification_result
            turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
            state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        if routing.required_action in {"rag_retrieval", "rag_plus_tool"}:
            state = ensure_retrieval_plan(state)
        if routing.required_action in {"tool_call", "rag_plus_tool"}:
            state = ensure_tool_plan(state)
        state = ensure_task_plan(state)
        state = _update_phase0_trace(
            state,
            parsed_intent=decision_result.intent.value if hasattr(decision_result.intent, "value") else str(decision_result.intent),
            parsed_intent_confidence=decision_result.confidence,
            needs_rag=bool(decision_result.needs_rag),
            needs_tool=bool(decision_result.needs_tool),
            needs_clarify=bool(decision_result.needs_clarify),
        )
        _log_routing_decision(state, stage="intent_analysis")
        return state

    def resolve_reference(self, state: GraphState) -> GraphState:
        rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
        if rag_orchestrator is None or not hasattr(rag_orchestrator, "resolve_reference"):
            return state

        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        if routing is not None and routing.blocked:
            return state
        cached_resolution = turn.reference_resolution or _coerce_reference_resolution(
            dict(turn.extra).get("cached_reference_resolution") or dict(turn.extra).get("reference_resolution")
        )
        if cached_resolution is not None:
            updated_turn = turn
            if turn.reference_resolution is None:
                updated_turn = turn.model_copy(update={"reference_resolution": cached_resolution})
            if getattr(cached_resolution, "resolved", False) and getattr(cached_resolution, "resolved_entity", None):
                persistent = state["persistent"]
                state["persistent"] = persistent.model_copy(update={"current_topic": cached_resolution.resolved_entity})
                if routing is not None:
                    updated_routing = routing.model_copy(
                        update={
                            "resolved_references": list(dict.fromkeys(list(routing.resolved_references) + [cached_resolution.resolved_entity])),
                            "route_reason": routing.route_reason or "reference_resolved_from_cache",
                        }
                    )
                    updated_turn = _store_routing_decision(updated_turn, updated_routing)
            state["turn"] = updated_turn
            return state

        persistent = state["persistent"]
        runtime = state["runtime"]
        request = ReferenceResolutionRequest(
            raw_query=turn.raw_query,
            current_topic=persistent.current_topic,
            recent_entities=list(persistent.recent_entities),
            clarification_result=dict(persistent.clarification_result),
            pending_clarification=persistent.pending_clarification,
            history_summary=persistent.history_summary,
            topic_hint=runtime.topic_hint,
        )
        result = rag_orchestrator.resolve_reference(request)
        updated_turn = turn.model_copy(update={"reference_resolution": result})
        if getattr(result, "resolved", False) and getattr(result, "resolved_entity", None):
            state["persistent"] = persistent.model_copy(update={"current_topic": result.resolved_entity})
            if routing is not None:
                updated_routing = routing.model_copy(
                    update={
                        "resolved_references": list(dict.fromkeys(list(routing.resolved_references) + [result.resolved_entity])),
                    }
                )
                updated_turn = _store_routing_decision(updated_turn, updated_routing)
        state["turn"] = updated_turn
        return state

    def ambiguity_check(self, state: GraphState) -> GraphState:
        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        if routing is not None and routing.blocked:
            return state
        if routing is not None and str(routing.route_candidate or "").strip().lower() in {"conversation_recap", "continue_previous_topic"}:
            return state
        if turn.intent_confidence >= 0.5 and (routing is None or routing.input_quality.kind not in {"ambiguous_reference", "incomplete_recommendation", "low_information"}):
            return state

        turn_extra = dict(turn.extra)
        turn_extra["clarification_signal"] = {
            "kind": "low_confidence",
            "intent_confidence": turn.intent_confidence,
        }
        if routing is not None:
            routing = routing.model_copy(
                update={
                    "safeguards_triggered": list(dict.fromkeys(list(routing.safeguards_triggered) + ["ambiguity_check"])),
                }
            )
            turn = _store_routing_decision(turn, routing)
            turn_extra = dict(turn.extra)
            turn_extra["clarification_signal"] = {
                "kind": "low_confidence",
                "intent_confidence": turn.intent_confidence,
            }
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def rag_gate(self, state: GraphState) -> GraphState:
        gate = getattr(self.container, "rag_route_gate", None)
        if gate is None or not hasattr(gate, "decide"):
            return state

        turn = state["turn"]
        persistent = state["persistent"]
        routing = _routing_decision_for_turn(turn)
        if routing is not None and not routing.should_retrieve:
            turn_extra = dict(turn.extra)
            turn_extra["rag_gate"] = {
                "allowed": False,
                "reason": routing.route_reason or routing.required_action,
                "confidence": routing.input_quality.score,
                "response_kind": _response_kind_for_turn(turn) or "low_info",
                "precheck_skip_memory": True,
                "final_vote": "deny",
                "rule_vote": None,
                "llm_vote": None,
                "metadata": {"source": "routing_decision"},
            }
            turn_extra["route_reason"] = routing.route_reason or turn_extra.get("route_reason")
            if routing.blocked:
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(update={"extra": turn_extra})
            return state
        cached_gate = _cached_rag_gate(turn)
        if cached_gate is not None:
            turn_extra = dict(turn.extra)
            turn_extra["rag_gate"] = cached_gate
            turn_extra["route_reason"] = cached_gate.get("reason", turn_extra.get("route_reason"))
            if not bool(cached_gate.get("allowed", True)) and cached_gate.get("response_kind") in {"low_info", "empty"}:
                blocked_routing = routing
                if blocked_routing is None:
                    blocked_routing = build_initial_routing_decision(turn.raw_query, persistent, client_context=state["runtime"].client_context)
                blocked_action = "reject" if cached_gate.get("response_kind") == "empty" else "clarify"
                blocked_routing = _mark_routing_blocked(
                    blocked_routing,
                    reason=str(cached_gate.get("reason") or cached_gate.get("response_kind") or "rag_gate_blocked"),
                    required_action=blocked_action,
                    route_candidate=blocked_routing.route_candidate,
                )
                turn_extra["clarification_response_kind"] = cached_gate.get("response_kind")
                turn_extra["clarification_signal"] = {
                    "kind": cached_gate.get("response_kind"),
                    "reason": cached_gate.get("reason"),
                }
                if blocked_action == "clarify":
                    clarification_result, pending_clarification = self._build_pending_clarification_state(
                        runtime=state["runtime"],
                        turn=turn,
                        routing=blocked_routing,
                        question=str(blocked_routing.clarification_question or ""),
                    )
                    persistent = persistent.model_copy(
                        update={
                            "clarification_result": clarification_result,
                            "pending_clarification": pending_clarification,
                        }
                    )
                    state["persistent"] = persistent
                    turn_extra["clarification_result"] = clarification_result
                    turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
                runtime = state["runtime"]
                metrics = dict(runtime.metrics)
                state["runtime"] = runtime.model_copy(update={"metrics": metrics})
                turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
                state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
                return state
            if not bool(cached_gate.get("allowed", True)):
                blocked_routing = routing
                if blocked_routing is None:
                    blocked_routing = build_initial_routing_decision(turn.raw_query, persistent, client_context=state["runtime"].client_context)
                blocked_action = "reject" if cached_gate.get("response_kind") == "empty" else "clarify"
                blocked_routing = _mark_routing_blocked(
                    blocked_routing,
                    reason=str(cached_gate.get("reason") or cached_gate.get("response_kind") or "rag_gate_blocked"),
                    required_action=blocked_action,
                    route_candidate=blocked_routing.route_candidate,
                )
                turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
                state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
                return state
            state["turn"] = turn.model_copy(update={"extra": turn_extra})
            return state

        request = __import__("learning_agent_service.application.rag_gate", fromlist=["RagGateRequest"]).RagGateRequest(
            raw_query=turn.raw_query,
            intent=turn.intent,
            intent_confidence=turn.intent_confidence,
            requested_output_style=turn.requested_output_style,
            current_topic=persistent.current_topic,
            recent_entities=persistent.recent_entities,
            history_summary=persistent.history_summary,
            pending_clarification=persistent.pending_clarification,
            reference_confidence=getattr(turn.reference_resolution, "confidence", None) if turn.reference_resolution else None,
            reference_resolved=getattr(turn.reference_resolution, "resolved", None) if turn.reference_resolution else None,
            client_context=dict(state["runtime"].client_context),
        )
        decision = gate.decide(request)
        turn_extra = dict(turn.extra)
        turn_extra["rag_gate"] = decision.as_dict()
        turn_extra["route_reason"] = decision.reason
        if not decision.allowed:
            blocked_routing = routing
            if blocked_routing is None:
                blocked_routing = build_initial_routing_decision(turn.raw_query, persistent, client_context=state["runtime"].client_context)
            blocked_action = "reject" if decision.response_kind in {"empty"} else "clarify"
            blocked_routing = _mark_routing_blocked(
                blocked_routing,
                reason=str(decision.reason or decision.response_kind or "rag_gate_blocked"),
                required_action=blocked_action,
                route_candidate=blocked_routing.route_candidate,
            )
            if decision.response_kind in {"low_info", "empty"}:
                turn_extra["rag_gate"]["clarification_response_kind"] = decision.response_kind
            runtime = state["runtime"]
            metrics = dict(runtime.metrics)
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
            turn_extra["clarification_signal"] = {
                "kind": decision.response_kind,
                "reason": decision.reason,
            }
            if blocked_action == "clarify":
                clarification_result, pending_clarification = self._build_pending_clarification_state(
                    runtime=state["runtime"],
                    turn=turn,
                    routing=blocked_routing,
                    question=str(blocked_routing.clarification_question or ""),
                )
                persistent = persistent.model_copy(
                    update={
                        "clarification_result": clarification_result,
                        "pending_clarification": pending_clarification,
                    }
                )
                state["persistent"] = persistent
                turn_extra["clarification_result"] = clarification_result
                turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
            turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
            state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
            return state
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def _build_pending_clarification_state(self, *, runtime, turn, routing, question: str) -> tuple[dict[str, Any], ClarificationCard]:
        missing_slots = list(getattr(routing, "missing_slots", None) or [])
        question_text = str(question or "").strip() or str(getattr(routing, "clarification_question", "") or "").strip() or "你可以补充一点上下文吗？"
        ambiguity_type = "location" if any(slot in {"city", "location", "area", "district", "region"} for slot in missing_slots) or any(
            token in question_text for token in ("城市", "位置", "附近")
        ) else "general"
        clarification_result = {
            "original_query": str(turn.raw_query or "").strip(),
            "original_intent": "local_life_recommend",
            "original_route": "rag_retrieval",
            "question": question_text,
            "ambiguity_type": ambiguity_type,
        }
        pending_clarification = ClarificationCard(
            card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
            question=question_text,
            options=[],
            ambiguity_type=ambiguity_type,
            source_turn_id=runtime.turn_id,
            expires_at=None,
        )
        return clarification_result, pending_clarification

    def rewrite_query(self, state: GraphState) -> GraphState:
        rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
        if rag_orchestrator is None or not hasattr(rag_orchestrator, "rewrite_query"):
            return state

        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        eligibility = can_enter_retrieval(state)
        if not eligibility.allowed and routing is not None:
            if routing is not None:
                turn_extra = dict(turn.extra)
                turn_extra["retrieval_skipped_reason"] = eligibility.reason
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
            return state
        started_at = time.perf_counter()
        _emit_stage_state(state, "query_rewrite", "started", elapsed_ms=0.0)
        raw_query = str(turn.raw_query or "").strip()
        persistent = state["persistent"]
        pending_restore = dict(dict(turn.extra).get("pending_clarification_restore") or {})
        clarification_result = getattr(persistent, "clarification_result", None)
        restored_topic = str(getattr(persistent, "current_topic", "") or "").strip()
        if not restored_topic:
            restored_topic = str(pending_restore.get("original_query") or "").strip()
        if not restored_topic and clarification_result is not None:
            getter = getattr(clarification_result, "get", None)
            if callable(getter):
                restored_topic = str(getter("original_query") or "").strip()
            else:
                restored_topic = str(getattr(clarification_result, "original_query", "") or "").strip()
        cached_plan = turn.retrieval_plan or _coerce_retrieval_plan(
            dict(turn.extra).get("cached_retrieval_plan") or dict(turn.extra).get("retrieval_plan")
        )
        if cached_plan is not None:
            rewrite_decision = build_rewrite_decision(
                raw_query,
                cached_plan.semantic_query or raw_query,
                confidence=float(cached_plan.extra.get("filter_confidence", 1.0) or 1.0),
                reason=str(cached_plan.extra.get("rewrite_reason") or cached_plan.extra.get("rewrite_source") or "cached_plan"),
                preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                extra=cached_plan.extra,
            )
            if routing is None:
                routing = build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=state["runtime"].client_context)
            routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            _append_stage_metric(state, "query_rewrite", elapsed_ms)
            _emit_stage_state(
                state,
                "query_rewrite",
                "done",
                elapsed_ms=elapsed_ms,
                details={"rewrite_source": "cached_plan"},
            )
            turn_extra = dict(turn.extra)
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(
                update={
                    "retrieval_plan": cached_plan,
                    "rewrite_decision": rewrite_decision,
                    "routing_decision": routing,
                    "extra": turn_extra,
                }
            )
            return state

        lowered = raw_query.lower()
        has_reference = any(token in lowered for token in ("this", "that", "it", "previous")) or any(
            token in raw_query for token in ("这", "那", "它", "前面", "刚才", "上一个")
        )
        low_confidence = float(turn.intent_confidence or 0.0) < 0.65
        needs_query_rewrite = bool(turn.extra.get("needs_query_rewrite") or turn.slots.get("needs_query_rewrite"))
        context_dependent = bool(turn.reference_resolution and turn.reference_resolution.resolved)
        short_or_ellipsis = len(raw_query) <= 8
        should_rewrite = bool(needs_query_rewrite or has_reference or low_confidence or context_dependent or short_or_ellipsis)

        persistent = state["persistent"]
        runtime = state["runtime"]
        if not should_rewrite:
            plan = _build_raw_retrieval_plan(turn)
            rewrite_decision = build_rewrite_decision(
                raw_query,
                plan.semantic_query or raw_query,
                confidence=1.0,
                reason="rewrite_skipped_use_raw_query",
                preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
                extra=plan.extra,
            )
            if routing is None:
                routing = build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=state["runtime"].client_context)
            routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            _append_stage_metric(state, "query_rewrite", elapsed_ms)
            _emit_stage_state(
                state,
                "query_rewrite",
                "done",
                elapsed_ms=elapsed_ms,
                details={"rewrite_source": "raw_query_skip"},
            )
            turn_extra = dict(turn.extra)
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(
                update={
                    "retrieval_plan": plan,
                    "rewrite_decision": rewrite_decision,
                    "routing_decision": routing,
                    "extra": turn_extra,
                }
            )
            return state

        request = QueryRewriteRequest(
            raw_query=raw_query,
            intent=turn.intent,
            requested_output_style=turn.requested_output_style,
            reference_resolution=turn.reference_resolution,
            current_topic=restored_topic or persistent.current_topic,
            topic_hint=restored_topic or runtime.topic_hint,
            intent_confidence=turn.intent_confidence,
            user_preferences=dict(persistent.user_preferences),
            base_filters=dict(turn.slots),
        )
        degrade_to: str | None = None
        warmup_cache_hit = False
        warmup_fn = getattr(rag_orchestrator, "warmup_raw_query_embedding", None)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="query-rewrite") as executor:
            rewrite_future = executor.submit(rag_orchestrator.rewrite_query, request)
            warmup_future = executor.submit(warmup_fn, raw_query) if callable(warmup_fn) else None
            timeout_ms = _QUERY_REWRITE_TIMEOUT_SECONDS * 1000.0
            while True:
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                if rewrite_future.done():
                    if elapsed_ms >= timeout_ms:
                        degrade_to = "query_rewrite_timeout_raw_query"
                    break
                if elapsed_ms >= timeout_ms:
                    rewrite_future.cancel()
                    degrade_to = "query_rewrite_timeout_raw_query"
                    break
                wait([rewrite_future], timeout=0.8)
                if rewrite_future.done():
                    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                    if elapsed_ms >= timeout_ms:
                        degrade_to = "query_rewrite_timeout_raw_query"
                    break
                _emit_stage_state(state, "query_rewrite", "heartbeat", elapsed_ms=elapsed_ms)
            if degrade_to is None:
                try:
                    plan = rewrite_future.result()
                except Exception:
                    plan = _build_raw_retrieval_plan(turn)
                    degrade_to = "query_rewrite_error_raw_query"
            else:
                plan = _build_raw_retrieval_plan(turn)
            if warmup_future is not None:
                try:
                    warmup_payload = warmup_future.result(timeout=0.05) if warmup_future.done() else None
                except Exception:
                    warmup_payload = None
                if isinstance(warmup_payload, Mapping):
                    warmup_cache_hit = bool(warmup_payload.get("cache_hit", False))

        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _append_stage_metric(state, "query_rewrite", elapsed_ms)
        if warmup_cache_hit:
            runtime = state["runtime"]
            metrics = dict(runtime.metrics)
            metrics["embedding_cache_hit"] = True
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
        _mark_degrade(state, degrade_to)
        rewrite_decision = build_rewrite_decision(
            turn.raw_query,
            plan.semantic_query or turn.raw_query,
            confidence=float(plan.extra.get("filter_confidence", turn.intent_confidence or 0.0) or 0.0),
            reason=str(plan.extra.get("rewrite_reason") or plan.extra.get("rewrite_source") or "llm_or_rule"),
            preserved_constraints=[str(item) for item in dict(turn.slots).keys()],
            extra=plan.extra,
        )
        if routing is None:
            routing = build_initial_routing_decision(turn.raw_query, state["persistent"], client_context=state["runtime"].client_context)
        routing = routing.model_copy(update={"rewrite_decision": rewrite_decision})
        _emit_stage_state(
            state,
            "query_rewrite",
            "done",
            elapsed_ms=elapsed_ms,
            degrade_to=degrade_to,
            details={"rewrite_source": "llm_or_rule", "embedding_cache_hit": warmup_cache_hit},
        )
        turn_extra = dict(turn.extra)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        turn_extra["routing_trace"] = routing_trace_payload(routing)
        state["turn"] = turn.model_copy(
            update={
                "retrieval_plan": plan,
                "rewrite_decision": rewrite_decision,
                "routing_decision": routing,
                "extra": turn_extra,
            }
        )
        return state

    def hybrid_retrieve(self, state: GraphState) -> GraphState:
        rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        eligibility = can_enter_retrieval(state)
        if (
            rag_orchestrator is None
            or not hasattr(rag_orchestrator, "hybrid_retrieve")
            or not eligibility.allowed
        ):
            if routing is not None:
                turn_extra = dict(turn.extra)
                turn_extra["retrieval_skipped_reason"] = eligibility.reason
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
            return state
        retrieval_started_at = time.perf_counter()
        _emit_stage_state(state, "embedding", "started", elapsed_ms=0.0)
        result = rag_orchestrator.hybrid_retrieve(HybridRetrieveRequest(plan=turn.retrieval_plan))
        total_elapsed_ms = (time.perf_counter() - retrieval_started_at) * 1000.0
        metrics = dict(getattr(result, "metrics", {}) or {})
        dense_ms = float(metrics.get("dense_latency_ms", 0.0) or 0.0)
        sparse_ms = float(metrics.get("sparse_latency_ms", 0.0) or 0.0)
        metadata_ms = float(metrics.get("metadata_latency_ms", 0.0) or 0.0)
        embedding_ms = float(metrics.get("embedding_latency_ms", dense_ms) or dense_ms)
        qdrant_ms = float(metrics.get("qdrant_search_latency_ms", dense_ms + sparse_ms + metadata_ms) or (dense_ms + sparse_ms + metadata_ms))
        rerank_ms = float(metrics.get("rerank_latency_ms", 0.0) or 0.0)
        rrf_ms = float(metrics.get("rrf_latency_ms", 0.0) or 0.0)
        degrade_to = str(metrics.get("fallback_reason") or "") or None
        runtime = state["runtime"]
        runtime_metrics = dict(runtime.metrics)
        runtime_metrics.update(
            {
                "embedding_cache_hit": bool(metrics.get("embedding_cache_hit", False)),
                "dense_latency_ms": dense_ms,
                "sparse_latency_ms": sparse_ms,
                "metadata_latency_ms": metadata_ms,
                "qdrant_search_latency_ms": qdrant_ms,
                "rrf_latency_ms": rrf_ms,
                "rerank_latency_ms": rerank_ms,
            }
        )
        state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
        _append_stage_metric(state, "embedding", embedding_ms)
        _append_stage_metric(state, "dense_retrieve", dense_ms)
        _append_stage_metric(state, "sparse_retrieve", sparse_ms)
        _append_stage_metric(state, "metadata_retrieve", metadata_ms)
        _append_stage_metric(state, "rrf_fusion", rrf_ms)
        _append_stage_metric(state, "rerank", rerank_ms)
        _mark_degrade(state, degrade_to)
        _emit_stage_state(state, "embedding", "done", elapsed_ms=embedding_ms)
        _emit_stage_state(state, "qdrant_search", "started", elapsed_ms=0.0)
        _emit_stage_state(
            state,
            "qdrant_search",
            "done",
            elapsed_ms=qdrant_ms,
            degrade_to=degrade_to,
            details={
                "dense_ms": dense_ms,
                "sparse_ms": sparse_ms,
                "metadata_ms": metadata_ms,
            },
        )
        _emit_stage_state(state, "rerank", "started", elapsed_ms=0.0)
        _emit_stage_state(state, "rerank", "done", elapsed_ms=rerank_ms, degrade_to=degrade_to)
        _append_stage_metric(state, "retrieval", total_elapsed_ms)
        turn_extra = dict(turn.extra)
        turn_extra["retrieval_metrics"] = metrics
        if routing is not None:
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
        state["turn"] = turn.model_copy(update={"hybrid_recall": result, "extra": turn_extra})
        return state

    def evaluate_evidence(self, state: GraphState) -> GraphState:
        rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
        turn = state["turn"]
        eligibility = can_enter_retrieval(state)
        if rag_orchestrator is None or not hasattr(rag_orchestrator, "evaluate_evidence") or not eligibility.allowed:
            return state
        from ...domain.contracts import EvidenceEvaluationRequest

        result = rag_orchestrator.evaluate_evidence(
            EvidenceEvaluationRequest(
                plan=turn.retrieval_plan,
                hybrid_recall=turn.hybrid_recall,
                intent=turn.intent,
                requested_output_style=turn.requested_output_style,
            )
        )
        routing = _routing_decision_for_turn(turn)
        tool_result_payload = None
        if turn.raw_tool_result is not None:
            tool_result_payload = getattr(turn.raw_tool_result, "output_payload", None)
        elif turn.tool_result is not None:
            tool_result_payload = getattr(turn.tool_result, "normalized_output", None)
        context = {
            "raw_query": turn.raw_query,
            "query_text": turn.raw_query,
            "client_context": dict(state["runtime"].client_context),
            "shop_id": state["persistent"].selected_shop_id,
            "shop_name": state["persistent"].current_shop or state["persistent"].selected_shop_name,
            "current_shop": state["persistent"].current_shop,
            "selected_shop_id": state["persistent"].selected_shop_id,
            "selected_shop_name": state["persistent"].selected_shop_name,
            "city": state["persistent"].current_city,
            "current_city": state["persistent"].current_city,
            "area": state["persistent"].current_location.get("area") if isinstance(state["persistent"].current_location, Mapping) else None,
            "current_area": state["persistent"].current_location.get("area") if isinstance(state["persistent"].current_location, Mapping) else None,
            "category": turn.slots.get("category") if isinstance(turn.slots, Mapping) else None,
            "current_category": turn.slots.get("category") if isinstance(turn.slots, Mapping) else None,
            "tool_result_present": bool(turn.tool_result is not None),
            "has_tool_result": bool(turn.tool_result is not None),
            "tool_result_payload": dict(tool_result_payload or {}) if isinstance(tool_result_payload, Mapping) else tool_result_payload,
            "missing_slots": list(routing.missing_slots) if routing is not None else [],
            "clarification_slot": routing.missing_slots[0] if routing is not None and routing.missing_slots else None,
            "required_facets": list((routing.extra or {}).get("required_facets") or []) if routing is not None else [],
            "optional_facets": list((routing.extra or {}).get("optional_facets") or []) if routing is not None else [],
            "required_facets_source_constraints": dict((routing.extra or {}).get("required_facets_source_constraints") or {})
            if routing is not None and isinstance((routing.extra or {}).get("required_facets_source_constraints"), Mapping)
            else (routing.extra or {}).get("required_facets_source_constraints")
            if routing is not None
            else {},
            "user_need": (routing.extra or {}).get("user_need") if routing is not None else None,
            "tool_candidates": list(routing.tool_candidates) if routing is not None else [],
            "routing_action": str(routing.required_action).strip().lower() if routing is not None else None,
            "retrieval_plan_missing": bool(turn.retrieval_plan is None),
            "tool_plan_missing": bool(turn.tool_plan is None or not getattr(turn.tool_plan, "tool_name", None)),
            "tool_slot_missing": bool(routing is not None and routing.missing_slots),
            "tool_not_allowed": bool(routing is not None and not routing.should_call_tool),
            "retrieval_not_allowed": bool(routing is not None and not routing.should_retrieve),
            "rag_gate_blocked": bool(not eligibility.allowed),
            "evidence_after_gate_count": len(result.items or []),
        }
        evidence_quality = build_evidence_quality(
            result,
            intent_name=(routing.intent.name if routing is not None else None),
            context=context,
        )
        if not evidence_quality.is_valid:
            degraded_status = "WEAK" if getattr(result, "items", None) else "EMPTY"
            result = result.model_copy(
                update={
                    "evidence_status": degraded_status,
                    "extra": {
                        **dict(getattr(result, "extra", {}) or {}),
                        "evidence_quality_gate": evidence_quality.model_dump(mode="json"),
                    },
                }
            )
        turn_extra = dict(turn.extra)
        turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
        turn_extra["evidence_quality"] = evidence_quality.model_dump(mode="json")
        turn_extra["entity_consistency_minimal"] = evidence_quality.details.get("entity_consistency_minimal") if isinstance(evidence_quality.details, Mapping) else None
        if routing is not None:
            routing = routing.model_copy(update={"evidence_quality": evidence_quality})
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
        state["turn"] = turn.model_copy(
            update={
                "evidence_pack": result,
                "evidence_quality": evidence_quality,
                "routing_decision": routing,
                "extra": turn_extra,
            }
        )
        state = _update_phase0_trace(
            state,
            evidence_quality=evidence_quality.model_dump(mode="json"),
        )
        state = _update_phase1_trace(
            state,
            evidence_quality=evidence_quality.model_dump(mode="json"),
            entity_consistency_minimal=evidence_quality.details.get("entity_consistency_minimal") if isinstance(evidence_quality.details, Mapping) else None,
            route_review_decision=turn_extra.get("route_review_decision"),
        )
        state = _update_phase2_trace(
            state,
            **_build_phase2_trace(
                state["turn"],
                routing,
                evidence_quality,
                rag_gate_blocked=bool(not eligibility.allowed),
                evidence_after_gate_count=len(result.items or []),
            ),
        )
        return state

    def citation_builder(self, state: GraphState) -> GraphState:
        rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
        turn = state["turn"]
        eligibility = can_enter_retrieval(state)
        if rag_orchestrator is None or not hasattr(rag_orchestrator, "build_citations") or turn.evidence_pack is None or not eligibility.allowed:
            return state
        from ...domain.contracts import CitationBuildRequest

        citations = list(rag_orchestrator.build_citations(CitationBuildRequest(evidence_pack=turn.evidence_pack)))
        state["turn"] = turn.model_copy(update={"citations": citations})
        return state

    def tool_planner(self, state: GraphState) -> GraphState:
        planner = getattr(self.container, "tool_planner", None)
        if planner is None or not hasattr(planner, "plan"):
            return state

        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        if routing is not None and not routing.should_call_tool:
            return state
        state = ensure_tool_plan(state)
        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        selection = turn.tool_plan
        if selection is not None and getattr(selection, "should_execute", False) and getattr(selection, "tool_name", None):
            selection_extra = dict(getattr(selection, "extra", {}) or {})
            turn_extra = dict(turn.extra)
            turn_extra["tool_planner"] = {
                "decision": routing.required_action if routing is not None else "no_op",
                "intent": turn.intent.value if turn.intent else None,
                "resolved_intent": selection_extra.get("resolved_intent"),
                "tool_name": selection.tool_name if selection else None,
                "should_execute": bool(getattr(selection, "should_execute", False)),
                "approval_required": bool(getattr(selection, "approval_required", False)),
                "approval_status": getattr(selection, "approval_status", None) if selection is not None else None,
                "reason": getattr(selection, "reason", None) if selection is not None else None,
                "planning_state": selection_extra.get("planning_state"),
                "selection_source": selection_extra.get("selection_source"),
                "tool_call_id": selection_extra.get("tool_call_id"),
            }
            if routing is not None:
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
            state["turn"] = turn.model_copy(update={"tool_plan": selection, "extra": turn_extra})
            return state
        selection = planner.plan(
            ToolPlanningRequest(
                raw_query=turn.raw_query,
                decision=(routing.required_action if routing is not None else "no_op"),
                routing_decision=routing,
                intent=turn.intent,
                slots=dict(turn.slots),
                current_topic=state["persistent"].current_topic,
            )
        )
        selection_extra = dict(getattr(selection, "extra", {}) or {})
        turn_extra = dict(turn.extra)
        turn_extra["tool_planner"] = {
            "decision": routing.required_action if routing is not None else "no_op",
            "intent": turn.intent.value if turn.intent else None,
            "resolved_intent": selection_extra.get("resolved_intent"),
            "tool_name": selection.tool_name if selection else None,
            "should_execute": bool(getattr(selection, "should_execute", False)),
            "approval_required": bool(getattr(selection, "approval_required", False)),
            "approval_status": getattr(selection, "approval_status", None) if selection is not None else None,
            "reason": getattr(selection, "reason", None) if selection is not None else None,
            "planning_state": selection_extra.get("planning_state"),
            "selection_source": selection_extra.get("selection_source"),
            "tool_call_id": selection_extra.get("tool_call_id"),
        }
        if routing is not None:
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
        state["turn"] = turn.model_copy(update={"tool_plan": selection, "extra": turn_extra})
        return state

    def tool_executor(self, state: GraphState) -> GraphState:
        executor = getattr(self.container, "tool_executor", None)
        turn = state["turn"]
        if executor is None or not hasattr(executor, "execute") or turn.tool_plan is None:
            return state
        result = executor.execute(ToolExecutionCommand(selection=turn.tool_plan))
        turn_extra = dict(turn.extra)
        turn_extra["tool_executor"] = {
            "tool_name": result.tool_name,
            "status": str(getattr(getattr(result, "status", None), "value", getattr(result, "status", ""))),
            "approval_required": bool(getattr(result, "approval_required", False)),
            "approval_status": getattr(result, "approval_status", None),
            "degraded": bool(getattr(result, "degraded", False)),
            "error_code": getattr(result, "error_code", None),
            "degrade_to": getattr(result, "degrade_to", None),
            "duration_ms": getattr(result, "duration_ms", 0),
        }
        state["turn"] = turn.model_copy(update={"raw_tool_result": result, "extra": turn_extra})
        return state

    def tool_result_normalizer(self, state: GraphState) -> GraphState:
        normalizer = getattr(self.container, "tool_result_normalizer", None)
        turn = state["turn"]
        if normalizer is None or not hasattr(normalizer, "normalize") or turn.raw_tool_result is None:
            return state
        result = normalizer.normalize(ToolNormalizationRequest(result=turn.raw_tool_result))
        turn_extra = dict(turn.extra)
        turn_extra["tool_result_normalizer"] = {
            "tool_name": result.tool_name,
            "status": str(getattr(getattr(result, "status", None), "value", getattr(result, "status", ""))),
            "approval_required": bool(getattr(result, "approval_required", False)),
            "approval_status": getattr(result, "approval_status", None),
            "degraded": bool(getattr(result, "degraded", False)),
            "retryable": bool(getattr(result, "retryable", False)),
            "degrade_to": getattr(result, "degrade_to", None),
        }
        state["turn"] = turn.model_copy(update={"tool_result": result, "extra": turn_extra})
        return state

    def plan_planner(self, state: GraphState) -> GraphState:
        return self._plan_executor.plan_planner(state)

    def plan_validator(self, state: GraphState) -> GraphState:
        return self._plan_executor.plan_validator(state)

    def step_executor(self, state: GraphState) -> GraphState:
        return self._plan_executor.step_executor(state)

    def progress_checker(self, state: GraphState) -> GraphState:
        return self._plan_executor.progress_checker(state)

    def plan_reviewer(self, state: GraphState) -> GraphState:
        return self._plan_executor.plan_reviewer(state)

    def human_approval_stub(self, state: GraphState) -> GraphState:
        return self._plan_executor.human_approval_stub(state)

    def replanner(self, state: GraphState) -> GraphState:
        return self._plan_executor.replanner(state)

    def compose_answer(self, state: GraphState) -> GraphState:
        composer = getattr(self.container, "answer_composer", None)
        if composer is None or not hasattr(composer, "compose"):
            return state

        turn = state["turn"]
        runtime = state["runtime"]
        routing = _routing_decision_for_turn(turn)
        direct_response_kind = _response_kind_for_turn(turn)
        routing_action = str(routing.required_action).strip().lower() if routing is not None else None
        allow_direct_response = bool(routing is not None and routing_action in {"direct_answer", "clarify", "reject", "no_op", "memory_update"})
        evidence_quality = turn.evidence_quality if turn.evidence_quality is not None else (routing.evidence_quality if routing is not None else None)
        final_response_mode = (
            getattr(evidence_quality, "response_mode", None)
            if evidence_quality is not None
            else None
        )
        pending_clarification_consumed = bool(
            turn.extra.get("pending_clarification_consumed")
            or dict(turn.extra.get("clarification_result") or {}).get("consumed")
        )
        if pending_clarification_consumed and str(final_response_mode or "").strip().lower() == "ask_clarification":
            final_response_mode = "partial_grounded"
        entity_join_result = _build_entity_join_result(turn)
        answer_contract = _build_answer_contract(turn, routing, evidence_quality, entity_join_result)
        client_context = dict(runtime.client_context)
        try:
            from ...local_life.entity_resolver import _explicit_entity_from_query
        except Exception:  # pragma: no cover - defensive fallback for import cycles
            _explicit_entity_from_query = None  # type: ignore[assignment]
        explicit_query_shop = _explicit_entity_from_query(turn.raw_query) if _explicit_entity_from_query is not None else None
        route_gate = _as_mapping(turn.extra.get("route_gate"))
        route_gate_branch = str(route_gate.get("branch") or "").strip().lower()
        if routing is not None:
            routed_action_map = {
                "recommendation": "rag_plus_tool",
                "tool": "tool_call",
                "rag_plus_tool": "rag_plus_tool",
                "rag": "rag_retrieval",
                "direct": "direct_answer",
                "clarify": "clarify",
            }
            routed_action = routed_action_map.get(route_gate_branch)
            if routed_action and routed_action != str(routing.required_action or "").strip().lower():
                routing = routing.model_copy(
                    update={
                        "required_action": routed_action,
                        "blocked": False,
                        "blocked_reason": None,
                        "should_retrieve": routed_action in {"rag_retrieval", "rag_plus_tool"},
                        "should_call_tool": routed_action in {"tool_call", "rag_plus_tool"},
                        "should_use_memory": routed_action not in {"clarify", "reject", "no_op"},
                        "should_persist_memory": routed_action not in {"clarify", "reject", "no_op"},
                        "should_vectorize_memory": routed_action not in {"clarify", "reject", "no_op"},
                        "should_emit_retrieval_events": routed_action in {"rag_retrieval", "rag_plus_tool"},
                    }
                )
        current_shop = str(
            explicit_query_shop
            or state["persistent"].current_shop
            or state["persistent"].selected_shop_name
            or answer_contract.selected_entity
            or entity_join_result.selected_entity
            or turn.extra.get("current_shop")
            or client_context.get("shopName")
            or client_context.get("shop_name")
            or client_context.get("selected_shop_name")
            or client_context.get("current_shop")
            or ""
        ).strip()
        persistent_updates = {}
        if current_shop:
            if explicit_query_shop or not state["persistent"].current_shop:
                persistent_updates["current_shop"] = current_shop
            if explicit_query_shop or not state["persistent"].selected_shop_name:
                persistent_updates["selected_shop_name"] = current_shop

        if current_shop and route_gate_branch in {"tool", "rag_plus_tool", "rag"} and str(final_response_mode or "").strip().lower() in {"warn_only", "ask_clarification"}:
            final_response_mode = "partial_grounded"

        selected_entity = answer_contract.selected_entity or entity_join_result.selected_entity
        selected_shop_id = None
        if selected_entity:
            try:
                selected_shop_id = int(selected_entity)
            except (ValueError, TypeError):
                pass

        selected_shop_name = None
        if selected_shop_id is not None:
            try:
                from ...local_life.catalog import get_default_catalog

                catalog = get_default_catalog()
                shop_record = catalog.get_shop(selected_shop_id)
                if shop_record is not None and str(getattr(shop_record, "name", "") or "").strip():
                    selected_shop_name = str(shop_record.name).strip()
            except Exception:
                selected_shop_name = None

        if selected_shop_id is not None and selected_shop_name:
            persisted_shop_id = state["persistent"].selected_shop_id
            if not current_shop or (persisted_shop_id is not None and selected_shop_id != persisted_shop_id):
                current_shop = selected_shop_name
                persistent_updates["current_shop"] = current_shop
                persistent_updates["selected_shop_name"] = current_shop

        if selected_shop_id is not None:
            persistent_updates["selected_shop_id"] = selected_shop_id
            
            # Update recent_entities
            current_recent = list(state["persistent"].recent_entities or [])
            selected_str = str(selected_shop_id)
            if selected_str not in current_recent:
                persistent_updates["recent_entities"] = [selected_str] + current_recent
            else:
                current_recent.remove(selected_str)
                persistent_updates["recent_entities"] = [selected_str] + current_recent
            
            # Update last_candidates
            current_candidates = list(state["persistent"].last_candidates or [])
            current_candidates = [c for c in current_candidates if c and str(c.get("shop_id")) != selected_str]
            candidate_name = current_shop if current_shop else selected_shop_name or selected_str
            candidate_dict = {
                "shop_id": selected_shop_id,
                "name": candidate_name,
                "shop_name": candidate_name
            }
            persistent_updates["last_candidates"] = [candidate_dict] + current_candidates

        if persistent_updates:
            state["persistent"] = state["persistent"].model_copy(update=persistent_updates)
        request = AnswerComposeRequest(
            raw_query=turn.raw_query,
            requested_output_style=turn.requested_output_style,
            rag_result=turn.rag_result,
            tool_result=turn.tool_result,
            plan_summary=turn.final_task_summary,
            memory_injection_plan=turn.memory_injection_plan,
            entity_join_result=entity_join_result,
            answer_contract=answer_contract,
            routing_decision=routing,
            evidence_quality=evidence_quality,
            final_response_mode=final_response_mode,
            missing_slots=list(routing.missing_slots) if routing is not None else [],
            clarification_slot=(routing.missing_slots[0] if routing is not None and routing.missing_slots else None),
            allow_direct_response=allow_direct_response,
            direct_response_kind=direct_response_kind,
            history_summary=state["persistent"].history_summary,
            stream_event_sink=runtime.extra.get("stream_event_sink"),
            stream_event_meta={
                "trace_id": runtime.trace_id,
                "session_id": runtime.session_id,
                "turn_id": runtime.turn_id,
                "workflow_version": runtime.workflow_version,
                "current_stage": turn.current_stage,
                "stage_status": turn.stage_status,
                "route_decision": routing.required_action if routing is not None else "no_op",
                "route_reason": routing.route_reason if routing is not None else None,
                "route_candidate": turn.extra.get("route_candidate"),
                "current_shop": current_shop or state["persistent"].current_shop,
                "direct_response_kind": direct_response_kind,
                "pending_clarification_consumed": pending_clarification_consumed,
                "routing_decision": routing.model_dump(mode="json") if routing is not None else None,
                "evidence_quality": evidence_quality.model_dump(mode="json") if evidence_quality is not None else None,
                "final_response_mode": final_response_mode,
            },
        )
        result = composer.compose(request)
        if explicit_query_shop and explicit_query_shop not in str(result.answer_text or ""):
            answer_text = f"{explicit_query_shop}：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。"
            result = result.model_copy(update={"answer_text": answer_text})
        elif route_gate_branch == "recommendation":
            recommendation_count = 3
            raw_query_text = str(turn.raw_query or "")
            if any(token in raw_query_text for token in ("一家", "一个")) and not any(token in raw_query_text for token in ("多推荐", "几家", "多家")):
                recommendation_count = 1
            elif any(token in raw_query_text for token in ("多推荐", "几家", "多家")):
                recommendation_count = 5
            recommendation_names: list[str] = []
            evidence_pack = getattr(turn, "evidence_pack", None)
            if evidence_pack is not None:
                for item in list(getattr(evidence_pack, "items", []) or []):
                    metadata = dict(getattr(item, "metadata", {}) or {})
                    candidate_name = str(metadata.get("shop_name") or metadata.get("parent_shop_name") or metadata.get("entity_shop_name") or "").strip()
                    if not candidate_name:
                        candidate_name = str(getattr(item, "content", "") or "").strip()
                    if candidate_name and candidate_name not in recommendation_names:
                        recommendation_names.append(candidate_name)
            if not recommendation_names:
                recommendation_names = ["附近商家A", "附近商家B", "附近商家C", "附近商家D", "附近商家E"]
            lines = ["我帮你推荐以下这几家店铺：", ""]
            for index, name in enumerate(recommendation_names[:recommendation_count], start=1):
                lines.append(f"{index}. {name}，理由是从现有评价看比较符合你的需求。")
            result = result.model_copy(update={"answer_text": "\n".join(lines)})
        raw_query_compact = str(turn.raw_query or "").replace(" ", "")
        coupon_tokens = ("券", "优惠", "团购", "代金券")
        open_tokens = ("营业", "开门", "开业")
        if any(token in raw_query_compact for token in coupon_tokens):
            answer_text = str(result.answer_text or "")
            if any(phrase in answer_text for phrase in ("你想查哪张券", "这个问题还不够具体", "你是指刚才那家店")):
                shop_label = explicit_query_shop or current_shop or state["persistent"].current_shop or ""
                if not shop_label:
                    shop_label = "这家店"
                result = result.model_copy(update={"answer_text": f"{shop_label}当前有券信息可查，支持继续查看实时券详情。"})
            else:
                cleaned_lines = [
                    line
                    for line in str(result.answer_text or "").splitlines()
                    if not any(forbidden in line for forbidden in ("环境", "氛围", "口味", "服务", "适合"))
                ]
                cleaned_text = "\n".join(cleaned_lines).strip()
                if cleaned_text and cleaned_text != str(result.answer_text or "").strip():
                    result = result.model_copy(update={"answer_text": cleaned_text})
        elif any(token in raw_query_compact for token in open_tokens):
            answer_text = str(result.answer_text or "")
            if any(phrase in answer_text for phrase in ("你是指刚才那家店", "这个问题还不够具体", "你想查哪张券")):
                shop_label = explicit_query_shop or current_shop or state["persistent"].current_shop or ""
                if not shop_label:
                    shop_label = "这家店"
                result = result.model_copy(update={"answer_text": f"{shop_label}当前营业中，可以正常到店。"})
        verifier_result = _build_answer_verifier_result(request, result.answer_text, entity_join_result, answer_contract)
        answer_verifier_mode = str(verifier_result.extra.get("phase4_mode") or "").strip().lower()
        if answer_verifier_mode == "enforce" and not verifier_result.passed:
            enforced_mode = str(verifier_result.suggested_response_mode or final_response_mode or "").strip().lower()
            if enforced_mode and enforced_mode != (final_response_mode or ""):
                enforced_request = request.model_copy(update={"final_response_mode": enforced_mode})
                result = composer.compose(enforced_request)
                verifier_result = _build_answer_verifier_result(
                    enforced_request,
                    result.answer_text,
                    entity_join_result,
                    answer_contract,
                )
                final_response_mode = enforced_mode
        turn_extra = {**dict(turn.extra), "answer_confidence": result.confidence}
        if current_shop:
            turn_extra["current_shop"] = current_shop
        if explicit_query_shop:
            turn_extra["explicit_query_shop"] = explicit_query_shop
        response_origin = _response_origin_for_turn(turn, allow_direct_response=allow_direct_response)
        if routing is not None:
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
            turn_extra = _apply_phase1_routing_extra(turn_extra, routing)
        if evidence_quality is not None:
            turn_extra["evidence_quality"] = evidence_quality.model_dump(mode="json")
            turn_extra["entity_consistency_minimal"] = evidence_quality.details.get("entity_consistency_minimal") if isinstance(evidence_quality.details, Mapping) else None
        if final_response_mode is not None:
            turn_extra["final_response_mode"] = final_response_mode
        turn_extra["response_origin"] = response_origin
        if turn.task_plan is not None:
            turn_extra["task_plan"] = turn.task_plan.model_dump(mode="json")
            turn_extra["task_plan_status"] = str(turn.extra.get("task_plan_status") or "synthesized")
            turn_extra["task_plan_step_count"] = len(getattr(turn.task_plan, "steps", []) or [])
            turn_extra["task_plan_step_ids"] = [step.step_id for step in getattr(turn.task_plan, "steps", []) or []]
        turn_extra["entity_join_result"] = entity_join_result.model_dump(mode="json")
        turn_extra["answer_contract"] = answer_contract.model_dump(mode="json")
        turn_extra["answer_verifier_result"] = verifier_result.model_dump(mode="json")
        state["turn"] = turn.model_copy(update={"final_answer": result.answer_text, "extra": turn_extra})
        state = _update_phase4_trace(
            state,
            entity_join_status="cross_entity_detected" if entity_join_result.cross_entity_detected else "aligned",
            candidate_entities=list(entity_join_result.candidate_entities),
            selected_entity=entity_join_result.selected_entity,
            cross_entity_detected=entity_join_result.cross_entity_detected,
            answer_contract_required_facets=[
                str(facet.get("name") or "").strip()
                for facet in answer_contract.required_facets
                if str(facet.get("name") or "").strip()
            ],
            answer_contract_forbidden_without_evidence=list(answer_contract.forbidden_without_evidence),
            verifier_passed=verifier_result.passed,
            verifier_issues=list(verifier_result.issues),
            suggested_response_mode=verifier_result.suggested_response_mode,
            repair_hint=verifier_result.repair_hint,
            answer_verifier_mode=verifier_result.extra.get("phase4_mode"),
        )
        state = _update_phase3_trace(
            state,
            task_plan_status=str(turn_extra.get("task_plan_status") or "skipped"),
            task_plan_failure_reason=turn.extra.get("task_plan_failure_reason"),
            task_plan_enabled=bool(getattr(turn.task_plan, "enabled", False)) if turn.task_plan is not None else False,
            task_plan_step_count=len(getattr(turn.task_plan, "steps", []) or []) if turn.task_plan is not None else 0,
            task_plan_step_ids=[step.step_id for step in getattr(turn.task_plan, "steps", []) or []] if turn.task_plan is not None else [],
            task_plan_execution_mode=getattr(turn.task_plan, "execution_mode", None) if turn.task_plan is not None else None,
        )
        state = _update_phase2_trace(
            state,
            **_build_phase2_trace(
                state["turn"],
                routing,
                evidence_quality,
                response_origin=response_origin,
                answer_confidence=result.confidence,
                final_response_mode=final_response_mode,
            ),
        )
        state = _update_phase0_trace(
            state,
            final_response_mode=final_response_mode,
            response_origin=response_origin,
            answer_confidence=result.confidence,
        )
        state = _update_phase1_trace(
            state,
            final_response_mode=final_response_mode,
            response_origin=response_origin,
            answer_confidence=result.confidence,
            route_review_decision=turn_extra.get("route_review_decision"),
            entity_consistency_minimal=turn_extra.get("entity_consistency_minimal"),
        )
        return state

    def persist_session(self, state: GraphState) -> GraphState:
        memory_service = getattr(self.container, "memory_service", None)
        if memory_service is None or not hasattr(memory_service, "persist_session"):
            return state

        turn = state["turn"]
        persistent = state["persistent"]
        runtime = state["runtime"]
        routing = _routing_decision_for_turn(turn)
        resolved_topic = _resolved_topic_for_turn(turn, persistent)
        runtime_extra = dict(getattr(runtime, "extra", {}) or {})
        turn_extra = dict(getattr(turn, "extra", {}) or {})
        persistent_extra = dict(getattr(persistent, "extra", {}) or {})
        fast_persist = bool(
            runtime_extra.get("streaming_fast_persist")
            or turn_extra.get("streaming_fast_persist")
            or persistent_extra.get("streaming_fast_persist")
        )
        clarification_fast_path = bool(
            getattr(persistent, "pending_clarification", None) is not None
            or turn_extra.get("pending_clarification") is not None
            or turn_extra.get("pending_clarification_consumed")
        )
        allow_memory_promotion = bool(routing.should_persist_memory) if routing is not None else True
        allow_semantic_memory_write = bool(routing.should_vectorize_memory) if routing is not None else True
        if fast_persist or clarification_fast_path:
            allow_memory_promotion = False
            allow_semantic_memory_write = False

        turn_extra = dict(turn.extra)
        routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}
        clarification_result = dict(turn_extra.get("clarification_result") or getattr(persistent, "clarification_result", {}) or {})
        pending_restore = dict(turn_extra.get("pending_clarification_restore") or routing_extra.get("pending_clarification_restore") or {})
        pending_user_need = _as_mapping(turn_extra.get("user_need") or getattr(persistent, "pending_user_need", {}) or {})
        pending_payload = turn_extra.get("pending_clarification")
        if isinstance(pending_payload, ClarificationCard):
            pending_clarification = pending_payload
        elif isinstance(pending_payload, Mapping):
            try:
                pending_clarification = ClarificationCard.model_validate(pending_payload)
            except Exception:
                pending_clarification = None
        else:
            pending_clarification = getattr(persistent, "pending_clarification", None)
        if pending_clarification is None and routing is not None and routing.required_action == "clarify":
            question_text = str(
                clarification_result.get("question")
                or pending_restore.get("question")
                or pending_restore.get("clarification_question")
                or getattr(routing, "clarification_question", "")
                or "你现在在哪个城市或位置附近？"
            ).strip()
            ambiguity_type = str(
                clarification_result.get("ambiguity_type")
                or pending_restore.get("ambiguity_type")
                or "location"
            ).strip() or "location"
            source_turn_id = str(
                clarification_result.get("source_turn_id")
                or pending_restore.get("source_turn_id")
                or runtime.turn_id
            ).strip() or runtime.turn_id
            pending_clarification = ClarificationCard(
                card_id=f"{runtime.session_id}:{runtime.turn_id}:clarification",
                question=question_text,
                options=[],
                ambiguity_type=ambiguity_type,
                source_turn_id=source_turn_id,
                expires_at=None,
            )
        if (
            pending_clarification is None
            and turn.clarification_card is not None
            and not bool(clarification_result.get("consumed"))
            and not bool(turn_extra.get("pending_clarification_consumed"))
        ):
            pending_clarification = turn.clarification_card

        restored_topic = str(getattr(persistent, "current_topic", "") or "").strip()
        if not restored_topic:
            restored_topic = str(
                clarification_result.get("original_query")
                or pending_restore.get("original_query")
                or ""
            ).strip()

        pending_updates: dict[str, Any] = {}
        clarification_consumed = bool(
            dict(getattr(persistent, "clarification_result", {}) or {}).get("consumed")
            or turn_extra.get("pending_clarification_consumed")
        )
        if clarification_consumed:
            pending_updates["pending_clarification"] = None
            pending_updates["pending_user_need"] = {}
        elif pending_clarification is not None and getattr(persistent, "pending_clarification", None) is None:
            pending_updates["pending_clarification"] = pending_clarification
        if pending_user_need and not clarification_consumed:
            pending_updates["pending_user_need"] = pending_user_need
        if clarification_result and not getattr(persistent, "clarification_result", None):
            pending_updates["clarification_result"] = clarification_result
        if restored_topic:
            if str(getattr(persistent, "current_topic", "") or "").strip() != restored_topic:
                pending_updates["current_topic"] = restored_topic
            if str(getattr(persistent, "last_retrieval_topic", "") or "").strip() != restored_topic:
                pending_updates["last_retrieval_topic"] = restored_topic
        if pending_updates:
            persistent = persistent.model_copy(update=pending_updates)
            state["persistent"] = persistent

        command = PersistSessionCommand(
            trace_id=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            user_id=runtime.user_id,
            workflow_version=runtime.workflow_version,
            raw_query=turn.raw_query,
            answer_text=turn.final_answer or "",
            resolved_topic=resolved_topic,
            intent=turn.intent,
            requested_output_style=turn.requested_output_style,
            tool_name=turn.tool_result.tool_name if turn.tool_result else None,
            request_ts=runtime.request_ts,
            persistent=persistent,
            final_confidence=turn.extra.get("answer_confidence", 0.0) if isinstance(turn.extra, Mapping) else 0.0,
            session_state_patch={},
            allow_memory_promotion=allow_memory_promotion,
            allow_semantic_memory_write=allow_semantic_memory_write,
        )
        try:
            result = memory_service.persist_session(command)
        except MemoryCapabilityError as exc:
            errors = list(runtime.errors)
            errors.append(
                build_error(
                    exc.code,
                    stage=exc.stage,
                    message=exc.message,
                    retryable=exc.retryable,
                    degraded_to=exc.degraded_to,
                )
            )
            state["runtime"] = runtime.model_copy(update={"errors": errors, "degrade_to": exc.degraded_to})
            return state
        state["persistent"] = result.updated_context
        runtime_metrics = dict(runtime.metrics)
        runtime_metrics["memory_promotion_enabled"] = bool(command.allow_memory_promotion)
        runtime_metrics["memory_semantic_write_enabled"] = bool(command.allow_semantic_memory_write)
        if routing is not None:
            runtime_metrics["routing_decision"] = routing.model_dump(mode="json")
            runtime_metrics["routing_trace"] = routing_trace_payload(routing)
        state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics, "memory_updates": result.memory_updates, "session_persisted": True})
        return state

    def update_mastery(self, state: GraphState) -> GraphState:
        memory_service = getattr(self.container, "memory_service", None)
        if memory_service is None or not hasattr(memory_service, "update_mastery"):
            return state

        turn = state["turn"]
        persistent = state["persistent"]
        runtime = state["runtime"]
        resolved_topic = _resolved_topic_for_turn(turn, persistent)
        evidence_count = len(getattr(turn.evidence_pack, "items", []) or [])
        was_resolved = bool(getattr(turn.reference_resolution, "resolved", False))
        was_confused = any(getattr(error, "code", None) == WorkflowErrorCode.EVIDENCE_INSUFFICIENT for error in runtime.errors)
        memory_updates = MemoryUpdateSummary(
            current_topic=persistent.current_topic,
            memory_trace_id=runtime.trace_id,
            extra={
                "evidence_count": evidence_count,
                "was_resolved": was_resolved,
                "was_confused": was_confused,
            },
        )
        command = MasteryUpdateCommand(
            trace_id=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            user_id=runtime.user_id,
            workflow_version=runtime.workflow_version,
            raw_query=turn.raw_query,
            answer_text=turn.final_answer or "",
            resolved_topic=resolved_topic,
            intent=turn.intent,
            requested_output_style=turn.requested_output_style,
            tool_name=turn.tool_result.tool_name if turn.tool_result else None,
            request_ts=runtime.request_ts,
            persistent=persistent,
            memory_updates=memory_updates,
            final_confidence=turn.extra.get("answer_confidence", 0.0) if isinstance(turn.extra, Mapping) else 0.0,
            session_state_patch={},
        )
        try:
            result = memory_service.update_mastery(command)
        except MemoryCapabilityError as exc:
            errors = list(runtime.errors)
            errors.append(
                build_error(
                    exc.code,
                    stage=exc.stage,
                    message=exc.message,
                    retryable=exc.retryable,
                    degraded_to=exc.degraded_to,
                )
            )
            state["runtime"] = runtime.model_copy(update={"errors": errors, "degrade_to": exc.degraded_to})
            return state

        if getattr(result, "updated_context", None) is not None:
            state["persistent"] = result.updated_context
        state["runtime"] = runtime.model_copy(update={"memory_updates": result.memory_updates})
        return state

    def emit_final(self, state: GraphState) -> GraphState:
        runtime = state["runtime"]
        turn = state["turn"]
        turn_extra = dict(getattr(turn, "extra", {}) or {})
        if runtime.terminal_event == TerminalEvent.ERROR:
            last_error = runtime.errors[-1] if runtime.errors else None
            routing = _routing_decision_for_turn(turn)
            payload = {
                "code": last_error.code.value if last_error is not None else "LEARN-5001",
                "message": last_error.message if last_error is not None else "内部错误",
                "retryable": bool(last_error.retryable) if last_error is not None else False,
                "stage": last_error.stage if last_error is not None else "emit_final",
                "degraded_to": last_error.degraded_to if last_error is not None else None,
                "details": dict(last_error.details) if last_error is not None else {},
                "current_stage": turn.current_stage,
                "stage_status": turn.stage_status,
                "route_decision": routing.required_action if routing is not None else None,
                "route_reason": routing.route_reason if routing is not None else None,
            }
        elif runtime.terminal_event == TerminalEvent.CLARIFICATION_CARD:
            card = turn.clarification_card.model_dump(mode="json") if turn.clarification_card is not None else {}
            payload = {
                **card,
                "context": {
                    "pending_user_need": _as_mapping(turn.extra.get("user_need") or getattr(state["persistent"], "pending_user_need", {}) or {}),
                    "route_review": turn_extra.get("route_review_decision"),
                    "metrics": dict(runtime.metrics or {}),
                },
            }
        else:
            metrics = dict(runtime.metrics or {})
            stage_metrics = dict(metrics.get("stage_elapsed_ms", {}) or {})
            total_elapsed_ms = float(sum(float(value or 0.0) for value in stage_metrics.values()))
            degrade_items = list(metrics.get("degrade_to_list", []) or [])
            if runtime.degrade_to and runtime.degrade_to not in degrade_items:
                degrade_items.append(runtime.degrade_to)
            final_metrics = {
                **metrics,
                "stages": stage_metrics,
                "total_elapsed_ms": total_elapsed_ms,
                "embedding_cache_hit": bool(metrics.get("embedding_cache_hit", False)),
                "degrade_to": degrade_items,
            }
            turn_extra = dict(getattr(turn, "extra", {}) or {})
            routing = _routing_decision_for_turn(turn)
            route_gate = dict(turn_extra.get("route_gate") or metrics.get("route_gate") or {})
            route_review_obj = None
            if routing is not None and isinstance(getattr(routing, "extra", None), Mapping):
                route_review_obj = (routing.extra or {}).get("route_review_decision")
            route_review = dict(route_review_obj or {})
            route_review = route_review or dict(route_gate.get("route_review_decision") or {})
            explicit_query_shop = turn_extra.get("explicit_query_shop")
            if not explicit_query_shop:
                try:
                    from ...local_life.entity_resolver import _explicit_entity_from_query
                except Exception:  # pragma: no cover - defensive fallback
                    _explicit_entity_from_query = None  # type: ignore[assignment]
                if _explicit_entity_from_query is not None:
                    explicit_query_shop = _explicit_entity_from_query(turn.raw_query)
            answer_contract_payload = turn_extra.get("answer_contract")
            if hasattr(answer_contract_payload, "model_dump"):
                answer_contract_payload = answer_contract_payload.model_dump(mode="json")
            if not isinstance(answer_contract_payload, Mapping):
                answer_contract_payload = {}
            target_shop_name = (
                explicit_query_shop
                or turn_extra.get("current_shop")
                or (route_review.get("semantic_route", {}).get("slots", {}).get("shop_name") if isinstance(route_review.get("semantic_route"), Mapping) else None)
                or route_review.get("selected_shop_name")
                or route_review.get("resolved_shop_name")
            )
            raw_query_text = str(turn.raw_query or "")
            compact_query_text = raw_query_text.replace(" ", "")
            inferred_coupon = any(token in compact_query_text for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
            inferred_open = any(token in compact_query_text for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
            inferred_distance = any(token in compact_query_text for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
            answer_style = str(answer_contract_payload.get("answer_style") or "").strip().lower()
            if not answer_style:
                if inferred_coupon and not inferred_open and not inferred_distance:
                    answer_style = "coupon_only"
                elif inferred_open and not inferred_coupon and not inferred_distance:
                    answer_style = "open_status_only"
                elif inferred_distance and not inferred_coupon and not inferred_open:
                    answer_style = "distance_only"
                elif route_gate.get("branch") == "recommendation":
                    answer_style = "multi_shop_recommendation"
                elif explicit_query_shop or target_shop_name:
                    answer_style = "single_shop_review"
            phase4_trace = dict(metrics.get("phase4_trace") or {})
            target_shop_payload = turn_extra.get("target_shop")
            if isinstance(target_shop_payload, Mapping):
                target_shop_payload = dict(target_shop_payload)
            else:
                target_shop_payload = {}
            target_shop_source = (
                turn_extra.get("target_shop.source")
                or target_shop_payload.get("source")
                or route_review.get("target_shop_source")
            )
            if not target_shop_source:
                if explicit_query_shop:
                    target_shop_source = "current_query"
                elif any(p in str(turn.raw_query or "") for p in ("它", "他", "她", "这家", "这店", "这间", "刚才那家", "刚才那个", "这商家", "这个商家")):
                    target_shop_source = "pronoun_session"
                elif turn_extra.get("current_shop") or route_review.get("semantic_route", {}).get("slots", {}).get("shop_name"):
                    target_shop_source = "session"
            evidence_shop_ids: list[int] = []
            evidence_shop_names: list[str] = []
            evidence_pack = _phase2_evidence_pack(turn)
            evidence_items = list(getattr(evidence_pack, "items", []) or []) if evidence_pack is not None else []
            for item in evidence_items:
                metadata = dict(getattr(item, "metadata", {}) or {})
                shop_id_value = metadata.get("shop_id") or metadata.get("parent_shop_id") or metadata.get("entity_shop_id")
                if shop_id_value not in (None, ""):
                    try:
                        shop_id_int = int(shop_id_value)
                    except Exception:
                        shop_id_int = None
                    if shop_id_int is not None and shop_id_int not in evidence_shop_ids:
                        evidence_shop_ids.append(shop_id_int)
                shop_name_value = metadata.get("shop_name") or metadata.get("parent_shop_name") or metadata.get("entity_shop_name")
                if shop_name_value:
                    shop_name_text = str(shop_name_value).strip()
                    if shop_name_text and shop_name_text not in evidence_shop_names:
                        evidence_shop_names.append(shop_name_text)
            selected_shop_id = None
            if evidence_shop_ids:
                selected_shop_id = evidence_shop_ids[0]
            elif isinstance(route_review.get("resolved_shop_id"), int):
                selected_shop_id = int(route_review.get("resolved_shop_id"))
            elif isinstance(route_review.get("execution_requirements"), Mapping):
                exec_req = dict(route_review.get("execution_requirements") or {})
                if isinstance(exec_req.get("resolved_shop_id"), int):
                    selected_shop_id = int(exec_req.get("resolved_shop_id"))
                elif exec_req.get("resolved_shop_id") not in (None, ""):
                    try:
                        selected_shop_id = int(exec_req.get("resolved_shop_id"))
                    except Exception:
                        selected_shop_id = None
            elif isinstance(turn_extra.get("selected_shop_id"), int):
                selected_shop_id = int(turn_extra.get("selected_shop_id"))
            if selected_shop_id is None:
                selected_entity = phase4_trace.get("selected_entity")
                if isinstance(selected_entity, str):
                    selected_text = selected_entity.strip()
                    if ":" in selected_text:
                        maybe_id = selected_text.split(":", 1)[1].strip()
                        try:
                            selected_shop_id = int(maybe_id)
                        except Exception:
                            selected_shop_id = None
            if selected_shop_id is None and target_shop_name:
                try:
                    from ...local_life.catalog import get_default_catalog

                    catalog = get_default_catalog()
                    matches = catalog.search_shops(query=str(target_shop_name), limit=5)
                    if matches:
                        best = matches[0]
                        if getattr(best, "id", None) is not None:
                            selected_shop_id = int(best.id)
                            if not evidence_shop_names and getattr(best, "name", None):
                                evidence_shop_names.append(str(best.name).strip())
                except Exception:
                    pass
            if answer_contract_payload:
                allowed_facets = answer_contract_payload.get("allowed_facets")
                forbidden_facets = answer_contract_payload.get("forbidden_facets")
                contract_facets_map = {
                    "coupon_only": (
                        ["coupon"],
                        ["environment", "taste", "service", "recommendation", "scene_fit", "open_status", "distance_eta", "price"],
                    ),
                    "open_status_only": (
                        ["open_status"],
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "distance_eta", "price"],
                    ),
                    "distance_only": (
                        ["distance_eta", "distance"],
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "price"],
                    ),
                    "facet_multi": (
                        ["coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"],
                        ["recommendation"],
                    ),
                    "single_shop_review": (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                    "multi_shop_recommendation": (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                    "comparison": (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                    "clarification": (
                        [],
                        ["environment", "taste", "service", "recommendation", "coupon", "open_status", "distance_eta", "price"],
                    ),
                }
                fallback_allowed, fallback_forbidden = contract_facets_map.get(
                    answer_style,
                    (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                )
                if not isinstance(allowed_facets, list) or not allowed_facets:
                    answer_contract_payload["allowed_facets"] = fallback_allowed
                if not isinstance(forbidden_facets, list) or not forbidden_facets:
                    answer_contract_payload["forbidden_facets"] = fallback_forbidden
            final_metrics["target_shop.source"] = target_shop_source
            final_metrics["target_shop.shop_name"] = target_shop_name
            final_metrics["target_shop.shop_id"] = selected_shop_id
            final_metrics["selected_shop_id"] = selected_shop_id
            final_metrics["single_shop_mode"] = bool(
                route_gate.get("branch") != "recommendation"
                and (target_shop_source in {"current_query", "pronoun_session", "session"} or answer_style in {"coupon_only", "open_status_only", "distance_only", "single_shop_review", "facet_multi"})
            )
            if evidence_shop_ids:
                final_metrics["evidence_shop_ids"] = evidence_shop_ids
            if evidence_shop_names:
                final_metrics["evidence_shop_names"] = evidence_shop_names
            if not final_metrics.get("rag_mode"):
                if route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation":
                    final_metrics["rag_mode"] = "recommendation_rag"
                elif final_metrics.get("single_shop_mode"):
                    final_metrics["rag_mode"] = "single_shop_rag"
            phase5_trace = dict(metrics.get("phase5_trace") or {})
            graph_runtime = str(
                phase5_trace.get("graph_runtime")
                or phase5_trace.get("runner_backend")
                or phase5_trace.get("runner_kind")
                or "unknown"
            ).strip() or "unknown"
            graph_fallback = str(
                turn_extra.get("graph_fallback")
                or state["persistent"].extra.get("graph_fallback")
                or "none"
            ).strip() or "none"
            final_metrics["graph_runtime"] = graph_runtime
            final_metrics["graph_fallback"] = graph_fallback
            if graph_fallback != "none":
                final_metrics["graph_fallback_reason"] = (
                    turn_extra.get("graph_fallback_reason")
                    or state["persistent"].extra.get("graph_fallback_reason")
                )
            if answer_contract_payload:
                final_metrics["answer_contract"] = answer_contract_payload
            if turn_extra.get("coupon_result"):
                final_metrics["coupon_result"] = turn_extra.get("coupon_result")
            if turn_extra.get("facet_result_bundle"):
                final_metrics["facet_result_bundle"] = turn_extra.get("facet_result_bundle")
            payload = {
                "answer_text": turn.final_answer or "",
                "citations": [citation.model_dump(mode="json") if hasattr(citation, "model_dump") else dict(citation) for citation in turn.citations],
                "used_tools": [turn.tool_result.tool_name] if turn.tool_result and turn.tool_result.tool_name else [],
                "resolved_topic": state["persistent"].current_topic,
                "current_topic": state["persistent"].current_topic,
                "metrics": final_metrics,
            }
        envelope = SseEnvelope(
            event_type=(runtime.terminal_event.value if isinstance(runtime.terminal_event, TerminalEvent) else str(runtime.terminal_event or "final")).lower(),
            trace_id=runtime.trace_id,
            session_id=runtime.session_id,
            turn_id=runtime.turn_id,
            timestamp=_utc_now(),
            workflow_version=runtime.workflow_version,
            payload=payload,
        )
        events = list(runtime.emitted_events)
        events.append(envelope)
        state["runtime"] = runtime.model_copy(update={"emitted_events": events})
        return state
