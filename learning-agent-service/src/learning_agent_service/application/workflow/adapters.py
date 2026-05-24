from __future__ import annotations

import json
import logging
import time

from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, wait
from typing import Any, Mapping

from ...domain.contracts import (
    AnswerComposeRequest,
    ChatTurnCommand,
    ClarificationCard,
    ClarificationOption,
    CitationBuildRequest,
    EvidenceEvaluationRequest,
    GraphRuntimeMeta,
    FastDecision,
    EvidenceQualityDecision,
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
from ..routing import (
    apply_fast_decision_to_routing,
    build_evidence_quality,
    build_initial_routing_decision,
    build_rewrite_decision,
    can_enter_retrieval,
    ensure_retrieval_plan,
    ensure_tool_plan,
    normalize_query,
    _mark_routing_blocked,
    routing_trace_payload,
    should_persist_memory as routing_should_persist_memory,
)
from ..rag_gate import RagGateRequest
from .legacy_routing_migration import legacy_to_routing_decision
from .plan_execute import ReactStepExecutor

_DIRECT_RESPONSE_KINDS = {"greeting", "thanks", "farewell", "empty", "low_info", "profile", "memory_update"}
_LOGGER = logging.getLogger(__name__)
_CLASSIFY_TIMEOUT_SECONDS = 1.2
_QUERY_REWRITE_TIMEOUT_SECONDS = 1.0


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
    if routing.required_action == "memory_update":
        return "memory_update"
    if routing.required_action == "reject":
        return "empty" if routing.input_quality.kind in {"empty_input", "pure_punctuation"} else "low_info"
    if routing.required_action == "clarify":
        return "low_info"
    if routing.required_action == "direct_answer":
        if candidate in {"greeting", "thanks", "profile", "farewell"}:
            return candidate
        return "low_info"
    return None


def _routing_decision_for_turn(turn: Any) -> RoutingDecision | None:
    routing = getattr(turn, "routing_decision", None)
    if isinstance(routing, RoutingDecision):
        return routing
    return None


def _store_routing_decision(turn: Any, routing: RoutingDecision) -> Any:
    turn_extra = dict(getattr(turn, "extra", {}) or {})
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
        routing = build_initial_routing_decision(
            turn.raw_query,
            persistent,
            client_context=state["runtime"].client_context,
        )
        routing = legacy_to_routing_decision(turn, persistent, routing)
        turn = _store_routing_decision(turn, routing)
        if routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}:
            state["turn"] = turn
            runtime = state["runtime"]
            metrics = dict(runtime.metrics)
            metrics["memory_retrieval_skipped"] = True
            metrics["routing_decision"] = routing.model_dump(mode="json")
            metrics["routing_required_action"] = routing.required_action
            metrics["routing_reason"] = routing.route_reason
            state["runtime"] = runtime.model_copy(update={"metrics": metrics})
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
                reference_confidence=getattr(turn.reference_resolution, "confidence", None) if turn.reference_resolution else None,
                reference_resolved=getattr(turn.reference_resolution, "resolved", None) if turn.reference_resolution else None,
                client_context=dict(state["runtime"].client_context),
            )
            vote = gate.precheck(request)
            turn_extra = dict(turn.extra)
            turn_extra["rag_gate"] = {
                **dict(turn_extra.get("rag_gate", {})),
                "precheck_vote": vote.vote,
                "precheck_reason": vote.reason,
                "precheck_response_kind": vote.response_kind,
            }
            turn = turn.model_copy(update={"extra": turn_extra})

        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["routing_decision"] = routing.model_dump(mode="json")
        metrics["routing_required_action"] = routing.required_action
        metrics["routing_reason"] = routing.route_reason
        metrics["memory_retrieval_skipped"] = not routing.should_use_memory
        state["turn"] = turn
        state["runtime"] = runtime.model_copy(update={"metrics": metrics})
        _log_routing_decision(state, stage="load_context")
        return state

    def parse_intent_slots(self, state: GraphState) -> GraphState:
        model_gateway = getattr(self.container, "model_gateway", None)
        if model_gateway is None or not hasattr(model_gateway, "classify_turn"):
            return state

        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        if routing is not None and (routing.blocked or routing.required_action in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}):
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
        if routing.required_action in {"rag_retrieval", "rag_plus_tool"}:
            state = ensure_retrieval_plan(state)
        if routing.required_action in {"tool_call", "rag_plus_tool"}:
            state = ensure_tool_plan(state)
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
            turn_extra["routing_decision"] = blocked_routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(blocked_routing)
            state["turn"] = turn.model_copy(update={"routing_decision": blocked_routing, "extra": turn_extra})
            return state
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    def rewrite_query(self, state: GraphState) -> GraphState:
        rag_orchestrator = getattr(self.container, "rag_orchestrator", None)
        if rag_orchestrator is None or not hasattr(rag_orchestrator, "rewrite_query"):
            return state

        turn = state["turn"]
        routing = _routing_decision_for_turn(turn)
        eligibility = can_enter_retrieval(state)
        if not eligibility.allowed:
            if routing is not None:
                turn_extra = dict(turn.extra)
                turn_extra["retrieval_skipped_reason"] = eligibility.reason
                turn_extra["routing_decision"] = routing.model_dump(mode="json")
                turn_extra["routing_trace"] = routing_trace_payload(routing)
                state["turn"] = turn.model_copy(update={"extra": turn_extra})
            return state
        started_at = time.perf_counter()
        _emit_stage_state(state, "query_rewrite", "started", elapsed_ms=0.0)
        cached_plan = turn.retrieval_plan or _coerce_retrieval_plan(
            dict(turn.extra).get("cached_retrieval_plan") or dict(turn.extra).get("retrieval_plan")
        )
        if cached_plan is not None:
            rewrite_decision = build_rewrite_decision(
                turn.raw_query,
                cached_plan.semantic_query or turn.raw_query,
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

        raw_query = str(turn.raw_query or "").strip()
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
                turn.raw_query,
                plan.semantic_query or turn.raw_query,
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
            raw_query=turn.raw_query,
            intent=turn.intent,
            requested_output_style=turn.requested_output_style,
            reference_resolution=turn.reference_resolution,
            current_topic=persistent.current_topic,
            topic_hint=runtime.topic_hint,
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
        context = {
            "raw_query": turn.raw_query,
            "query_text": turn.raw_query,
            "shop_id": state["persistent"].selected_shop_id,
            "shop_name": state["persistent"].selected_shop_name,
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
        turn_extra["evidence_quality"] = evidence_quality.model_dump(mode="json")
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
        request = AnswerComposeRequest(
            raw_query=turn.raw_query,
            requested_output_style=turn.requested_output_style,
            rag_result=turn.rag_result,
            tool_result=turn.tool_result,
            plan_summary=turn.final_task_summary,
            memory_injection_plan=turn.memory_injection_plan,
            routing_decision=routing,
            evidence_quality=evidence_quality,
            final_response_mode=final_response_mode,
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
                "direct_response_kind": direct_response_kind,
                "routing_decision": routing.model_dump(mode="json") if routing is not None else None,
                "evidence_quality": evidence_quality.model_dump(mode="json") if evidence_quality is not None else None,
                "final_response_mode": final_response_mode,
            },
        )
        result = composer.compose(request)
        turn_extra = {**dict(turn.extra), "answer_confidence": result.confidence}
        if routing is not None:
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
            turn_extra["routing_trace"] = routing_trace_payload(routing)
        if evidence_quality is not None:
            turn_extra["evidence_quality"] = evidence_quality.model_dump(mode="json")
        if final_response_mode is not None:
            turn_extra["final_response_mode"] = final_response_mode
        state["turn"] = turn.model_copy(update={"final_answer": result.answer_text, "extra": turn_extra})
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
            allow_memory_promotion=bool(routing.should_persist_memory) if routing is not None else True,
            allow_semantic_memory_write=bool(routing.should_vectorize_memory) if routing is not None else True,
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
            payload = card
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
