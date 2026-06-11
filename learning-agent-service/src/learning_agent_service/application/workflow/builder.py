from __future__ import annotations

import logging
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Monkeypatch JsonPlusSerializer for compatibility with newer langgraph-checkpoint releases
try:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    import ormsgpack

    if not hasattr(JsonPlusSerializer, "dumps"):
        def _jsonplus_dumps(self, obj):
            type_, data = self.dumps_typed(obj)
            return ormsgpack.packb((type_, data))
        JsonPlusSerializer.dumps = _jsonplus_dumps

    if not hasattr(JsonPlusSerializer, "loads"):
        def _jsonplus_loads(self, data):
            if not data:
                return {}
            type_, data_ = ormsgpack.unpackb(data)
            return self.loads_typed((type_, data_))
        JsonPlusSerializer.loads = _jsonplus_loads
except Exception:
    pass

from .runner import SequentialWorkflowRunner, _update_phase5_trace
from .services import WorkflowServices
from .state import append_runtime_event as _append_state_runtime_event
from ...domain.errors import TerminalEvent
from ...domain.state import GraphState, clone_graph_state
from ...domain import ChatTurnCommand, build_initial_state
from ...domain.contracts import PersistentSessionContext
from ...api.contracts import SseEnvelope
from collections.abc import Iterable, Mapping
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety
from learning_agent_service.local_life.response_builder.bundle import build_response_bundle
from learning_agent_service.local_life.business_metrics import business_metrics_collector, QueryMetrics
from learning_agent_service.local_life.realtime_conflict_resolver import resolve_realtime_conflict, REALTIME_FACETS
from learning_agent_service.application.router.stages.query_safety import check_query_safety
from learning_agent_service.application.router.stages.top_level_intent_router import route_top_level_intent
from .topology import MAIN_GRAPH_TOPOLOGY, describe_langgraph_topology as describe_main_graph_topology, export_langgraph_mermaid as export_main_graph_mermaid
from ..router import (
    _build_answer_contract,
    _build_entity_join_result,
    _build_source_contract,
    check_hard_guard,
    route_execution_mode,
)
from .subgraphs import (
    run_load_context_node,
    run_rag_subgraph,
    run_recommendation_subgraph,
    run_tool_subgraph,
    run_understand_turn,
    route_after_rag,
    route_after_understand,
    route_gate,
    route_decider,
)

StateGraph: Any = None
END: Any = "__end__"
try:
    from langgraph.graph import END as _END, StateGraph as _StateGraph  # type: ignore[import-not-found, import]
    END = _END
    StateGraph = _StateGraph
except ImportError:  # pragma: no cover - optional dependency
    END = "__end__"
    StateGraph = None


LANGGRAPH_AVAILABLE = StateGraph is not None
_CHECKPOINT_FALLBACKS: dict[str, dict[str, Any]] = {}


@dataclass
class _CheckpointSnapshot:
    values: dict[str, Any]


class _CheckpointAwareGraphProxy:
    def __init__(self, graph) -> None:
        self._graph = graph

    def invoke(self, state, config=None):
        thread_id = _thread_id_from_config(config) or _thread_id_from_state(state)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(state)
        result = self._graph.invoke(state, config=config)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(result)
        return result

    def get_state(self, config=None):
        getter = getattr(self._graph, "get_state", None)
        if callable(getter):
            try:
                snapshot = getter(config)
                if snapshot is not None and getattr(snapshot, "values", None):
                    return snapshot
            except Exception:
                pass
        thread_id = _thread_id_from_config(config)
        if thread_id and thread_id in _CHECKPOINT_FALLBACKS:
            return _CheckpointSnapshot(values=deepcopy(_CHECKPOINT_FALLBACKS[thread_id]))
        return _CheckpointSnapshot(values={})

    def __getattr__(self, item):
        return getattr(self._graph, item)


def _thread_id_from_config(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    thread_id = configurable.get("thread_id")
    text = str(thread_id or "").strip()
    return text or None


def _thread_id_from_state(state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    runtime = state.get("runtime")
    session_id = getattr(runtime, "session_id", None) if runtime is not None else None
    text = str(session_id or "").strip()
    return text or None


class LangGraphWorkflowRunner(SequentialWorkflowRunner):
    def __init__(
        self,
        services: WorkflowServices,
        workflow_version: str = "learn-agent/v1",
        checkpointer: Any = None,
    ) -> None:
        super().__init__(services=services, workflow_version=workflow_version, runner_kind="langgraph")
        self._checkpointer = checkpointer
        self._graph = _CheckpointAwareGraphProxy(_build_langgraph_runner(services, checkpointer=checkpointer))
        self._graph_without_checkpointer = self._graph if checkpointer is None else _CheckpointAwareGraphProxy(
            _build_langgraph_runner(services, checkpointer=None)
        )

    def _execution_graph(self):
        if os.name == "nt" and self._checkpointer is not None:
            return self._graph_without_checkpointer
        return self._graph

    def run_state(self, state):
        execution_mode = str(getattr(state.get("turn"), "execution_mode", "") or "").strip().lower() if isinstance(state, dict) else ""
        if execution_mode == "plan_execute":
            fallback_runner = SequentialWorkflowRunner(services=self.services, workflow_version=self.workflow_version)
            result = fallback_runner.run_state(state)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)
        state = self._annotate_runner_context(state)
        if self._is_terminal(state):
            result = self._finalize_terminal(state)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        graph = self._execution_graph()
        try:
            result = graph.invoke(state, config=_build_graph_config(state))
        except Exception as exc:
            result = self._record_unexpected_error(state, "langgraph.invoke", exc)
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        runtime = result["runtime"]
        if runtime.emitted_events:
            if runtime.terminal_event is None:
                default_terminal = TerminalEvent.ERROR if runtime.errors else TerminalEvent.FINAL
                result["runtime"] = runtime.model_copy(update={"terminal_event": default_terminal})
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        if result["runtime"].terminal_event == TerminalEvent.ERROR:
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)
        result = self._finalize_terminal(result, default_terminal=TerminalEvent.FINAL)
        self._record_checkpoint_fallback(result)
        return self._annotate_runner_context(result)

    def run_stream(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> Iterable[SseEnvelope]:
        if str(getattr(command, "execution_mode", "") or "").strip().lower() == "plan_execute":
            fallback_runner = SequentialWorkflowRunner(services=self.services, workflow_version=self.workflow_version)
            yield from fallback_runner.run_stream(command, persistent_context=persistent_context)
            return
        state = build_initial_state(
            command=command,
            workflow_version=self.workflow_version,
            persistent=persistent_context,
        )
        state = self._annotate_runner_context(state)
        state = clone_graph_state(state)

        graph = self._execution_graph()
        if hasattr(graph, "stream"):
            try:
                yield from self._run_graph_stream(state, graph)
                return
            except Exception:
                pass
        
        try:
            result = graph.invoke(state, config=_build_graph_config(state))
        except Exception as exc:
            result = self._record_unexpected_error(state, "langgraph.invoke", exc)
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            yield from self._normalize_emitted_events(result["runtime"].emitted_events, result)
            return

        yield from self._normalize_emitted_events(result["runtime"].emitted_events, result)

    @staticmethod
    def _normalize_emitted_events(events, state):
        turn = state.get("turn") if isinstance(state, dict) else None
        final_answer = str(getattr(turn, "final_answer", "") or "").strip() if turn is not None else ""
        for event in events:
            yield LangGraphWorkflowRunner._normalize_emitted_event(event, final_answer)

    def _run_graph_stream(self, state, graph=None):
        emitted_count = 0
        graph = graph or self._graph

        def drain_emitted_events():
            nonlocal emitted_count
            events = list(state["runtime"].emitted_events)
            for event in events[emitted_count:]:
                yield self._normalize_emitted_event(event, str(state.get("turn").final_answer or "").strip())
            emitted_count = len(events)

        stream = graph.stream(state, config=_build_graph_config(state), stream_mode="values")
        for chunk in stream:
            if isinstance(chunk, dict) and "runtime" in chunk:
                state = chunk
                yield from drain_emitted_events()
        yield from drain_emitted_events()

    @staticmethod
    def _normalize_emitted_event(event, final_answer: str):
        event_type = getattr(event, "event_type", None)
        if event_type != "final":
            return event
        payload = getattr(event, "payload", None)
        payload_dict = None
        if hasattr(payload, "model_dump"):
            payload_dict = payload.model_dump(mode="json")
        elif isinstance(payload, dict):
            payload_dict = dict(payload)
        if not isinstance(payload_dict, dict):
            return event
        existing_answer_text = str(payload_dict.get("answer_text") or "").strip()
        if not existing_answer_text and final_answer:
            payload_dict["answer_text"] = final_answer
            existing_answer_text = final_answer
        metrics = payload_dict.get("metrics")
        if isinstance(metrics, dict):
            answer_quality = dict(metrics.get("answer_quality") or {})
            if not str(answer_quality.get("final_answer") or "").strip() and existing_answer_text:
                answer_quality["final_answer"] = existing_answer_text
            metrics["answer_quality"] = answer_quality
            payload_dict["metrics"] = metrics
        if hasattr(event, "model_copy"):
            return event.model_copy(update={"payload": payload_dict})
        if isinstance(event, dict):
            new_event = dict(event)
            new_event["payload"] = payload_dict
            return new_event
        return event

    def _annotate_runner_context(self, state):
        state = _update_phase5_trace(
            state,
            runner_kind=self.runner_kind,
            runner_backend="langgraph",
            graph_runtime="langgraph",
            runner_class=self.__class__.__name__,
            compare_ready=True,
        )
        runtime_context = dict(state.get("runtime_context", {}) or {})
        runtime_context.update(
            {
                "runner_kind": self.runner_kind,
                "runner_backend": "langgraph",
                "graph_runtime": "langgraph",
                "runner_class": self.__class__.__name__,
                "compare_ready": True,
            }
        )
        state["runtime_context"] = runtime_context
        return state

    def _record_checkpoint_fallback(self, state):
        if self._checkpointer is None:
            return
        thread_id = _thread_id_from_state(state)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(state)


def _build_graph_config(state):
    runtime = state["runtime"]
    runtime_context = dict(state.get("runtime_context", {}) or {})
    recursion_limit = int(runtime_context.get("graph_recursion_limit") or 50)
    return {
        "configurable": {"thread_id": runtime.session_id},
        "recursion_limit": max(1, recursion_limit),
    }


def _turn_raw_query(state: GraphState) -> str:
    return str(getattr(state["turn"], "raw_query", "") or "")


def _turn_compact_query(state: GraphState) -> str:
    return _turn_raw_query(state).replace(" ", "")


def _turn_extra(state: GraphState) -> dict[str, Any]:
    return dict(getattr(state["turn"], "extra", {}) or {})


def _routing_decision(state: GraphState):
    return getattr(state["turn"], "routing_decision", None)


def _routing_action(state: GraphState) -> str:
    routing = _routing_decision(state)
    return str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""


def _route_branch(state: GraphState) -> str:
    try:
        return str(route_decider(state) or "").strip().lower()
    except Exception:
        return ""


def _route_execution_mode(state: GraphState) -> str:
    routing = _routing_decision(state)
    if routing is None:
        return "simple"
    try:
        return str(route_execution_mode(routing).execution_mode or "").strip().lower() or "simple"
    except Exception:
        return "simple"


def _update_turn_extra(state: GraphState, **updates: Any) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    turn_extra.update(updates)
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _update_runtime_metrics(state: GraphState, **updates: Any) -> GraphState:
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics.update(updates)
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _rewrite_routing_decision(
    state: GraphState,
    *,
    required_action: str | None = None,
    route_candidate: str | None = None,
    route_reason: str | None = None,
) -> GraphState:
    turn = state["turn"]
    routing = _routing_decision(state)
    if routing is None:
        return state
    updates: dict[str, Any] = {"blocked": False, "blocked_reason": None}
    if required_action is not None:
        updates["required_action"] = required_action
    if route_candidate is not None:
        updates["route_candidate"] = route_candidate
    if route_reason is not None:
        updates["route_reason"] = route_reason
    state["turn"] = turn.model_copy(update={"routing_decision": routing.model_copy(update=updates)})
    return state


def _resolve_target_shop_stage(state: GraphState) -> GraphState:
    command = route_gate(state)
    updated = getattr(command, "update", None)
    if isinstance(updated, dict):
        state = updated
    turn_extra = _turn_extra(state)
    detail = {
        "branch": _route_branch(state) or None,
        "execution_mode": _route_execution_mode(state),
        "target_shop_id": turn_extra.get("target_shop_id"),
        "candidate_shop_ids": list(turn_extra.get("candidate_shop_ids") or []),
    }
    state = _update_turn_extra(
        state,
        resolve_target_shop=detail,
    )
    state = _update_runtime_metrics(state, resolve_target_shop=detail)
    return state


def _clarification_or_reject_stage(state: GraphState) -> GraphState:
    return _update_turn_extra(
        state,
        clarification_or_reject={
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
        },
    )


def _build_answer_contract_stage(state: GraphState) -> GraphState:
    turn = state["turn"]
    routing = _routing_decision(state)
    entity_join_result = _build_entity_join_result(turn)
    evidence_quality = getattr(turn, "evidence_quality", None)
    answer_contract = _build_answer_contract(turn, routing, evidence_quality, entity_join_result)
    turn_extra = _turn_extra(state)
    turn_extra["answer_contract"] = answer_contract.model_dump(mode="json")
    turn_extra["build_answer_contract"] = {
        "answer_style": getattr(answer_contract, "answer_style", None),
        "scope_kind": getattr(answer_contract, "scope_kind", None),
        "required_facets": [str(facet.get("name") or "").strip() for facet in answer_contract.required_facets if str(facet.get("name") or "").strip()],
    }
    state["turn"] = turn.model_copy(update={"answer_contract": answer_contract, "extra": turn_extra})
    state = _update_runtime_metrics(state, build_answer_contract=turn_extra["build_answer_contract"])
    return state


def _build_source_contract_stage(state: GraphState) -> GraphState:
    turn = state["turn"]
    routing = _routing_decision(state)
    turn_extra = _turn_extra(state)
    answer_contract = getattr(turn, "answer_contract", None)
    if answer_contract is None:
        entity_join_result = _build_entity_join_result(turn)
        answer_contract = _build_answer_contract(turn, routing, getattr(turn, "evidence_quality", None), entity_join_result)
    selected_shop_id = turn_extra.get("selected_shop_id") or turn_extra.get("target_shop_id")
    try:
        selected_shop_id = int(selected_shop_id) if selected_shop_id not in (None, "") else None
    except (TypeError, ValueError):
        selected_shop_id = None
    current_shop = str(turn_extra.get("current_shop") or "").strip() or None
    explicit_query_shop = str(turn_extra.get("explicit_query_shop") or "").strip() or None
    source_contract = _build_source_contract(
        turn,
        routing,
        answer_contract,
        selected_shop_id=selected_shop_id,
        current_shop=current_shop,
        explicit_query_shop=explicit_query_shop,
    )
    turn_extra["source_contract"] = source_contract.model_dump(mode="json")
    turn_extra["build_source_contract"] = {
        "scope_kind": getattr(source_contract, "scope_kind", None),
        "target_shop_id": getattr(source_contract, "target_shop_id", None),
        "candidate_shop_ids": list(getattr(source_contract, "candidate_shop_ids", []) or []),
    }
    state["turn"] = turn.model_copy(update={"source_contract": source_contract, "extra": turn_extra})
    state = _update_runtime_metrics(state, build_source_contract=turn_extra["build_source_contract"])
    return state


def _complexity_router_stage(state: GraphState) -> GraphState:
    routing = _routing_decision(state)
    complexity = route_execution_mode(routing)
    return _update_turn_extra(
        state,
        complexity_router=complexity.to_dict(),
    )


def _hard_guard_stage(state: GraphState) -> GraphState:
    turn = state["turn"]
    persistent = state.get("persistent")
    client_context = dict(getattr(state.get("runtime"), "client_context", {}) or {})
    result = check_hard_guard(
        str(getattr(turn, "raw_query", "") or ""),
        persistent,
        client_context,
    )
    if result.blocked and result.required_action:
        state = _rewrite_routing_decision(
            state,
            required_action=result.required_action,
            route_candidate=result.route_candidate,
            route_reason=result.reason,
        )
    return _update_turn_extra(
        state,
        hard_guard={
            "blocked": bool(result.blocked),
            "reason": result.reason,
            "required_action": result.required_action,
            "route_candidate": result.route_candidate,
        },
    )


def _complexity_router_route(state: GraphState) -> str:
    execution_mode = _route_execution_mode(state)
    if execution_mode == "clarify":
        return "clarification_node"
    if execution_mode == "complex":
        return "planner_node"
    if execution_mode == "standard":
        return "workflow_executor"
    return "direct_executor"


def _direct_executor_stage(state: GraphState) -> GraphState:
    return _update_turn_extra(
        state,
        direct_executor={
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
        },
    )


def _workflow_executor_stage(state: GraphState) -> GraphState:
    return _update_turn_extra(
        state,
        workflow_executor={
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
        },
    )


def _clarification_node_stage(state: GraphState) -> GraphState:
    return _update_turn_extra(
        state,
        clarification_node={
            "branch": _route_branch(state) or None,
            "execution_mode": _route_execution_mode(state),
        },
    )


def _preset_response(
    state: GraphState,
    *,
    response_node: str,
    answer_text: str,
    route_candidate: str | None = None,
    route_reason: str | None = None,
) -> GraphState:
    state = _rewrite_routing_decision(
        state,
        required_action="direct_answer",
        route_candidate=route_candidate,
        route_reason=route_reason,
    )
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    turn_extra.update(
        {
            "response_node": response_node,
            "response_path": response_node,
            "preset_response_text": answer_text,
            "response_kind": route_candidate,
        }
    )
    state["turn"] = turn.model_copy(update={"final_answer": answer_text, "extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["response_node"] = response_node
    runtime_metrics["response_path"] = response_node
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _request_legality_route(state: GraphState) -> str:
    routing = _routing_decision(state)
    if routing is None:
        return "hard_guard"
    if str(getattr(state["turn"], "execution_mode", "") or "").strip().lower() == "plan_execute":
        return "hard_guard"
    required_action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if bool(getattr(routing, "blocked", False)) or required_action == "reject":
        return "illegal_request_response"
    return "hard_guard"


def _hard_guard_route(state: GraphState) -> str:
    result = _turn_extra(state).get("hard_guard") or {}
    if bool(result.get("blocked")):
        return "clarification_or_reject"
    return "query_safety"


def _query_safety_route(state: GraphState) -> str:
    routing = _routing_decision(state)
    if str(getattr(state["turn"], "execution_mode", "") or "").strip().lower() == "plan_execute":
        return "query_merge_for_local_life"
    if routing is not None and str(getattr(routing, "required_action", "") or "").strip().lower() == "reject":
        return "safety_reject_response"
    return "query_merge_for_local_life"


def _requires_query_merge(state: GraphState) -> bool:
    compact = _turn_compact_query(state)
    if not compact:
        return False
    merge_tokens = ("对比", "比较", "和", "以及", "还是", "一起", "附近", "推荐")
    return any(token in compact for token in merge_tokens) and any(token in compact for token in ("店", "券", "营业", "路线", "优惠", "推荐"))


def _query_merge_route(state: GraphState) -> str:
    return "merged_query_safety" if _requires_query_merge(state) else "top_level_intent_router"


def _top_level_intent_route(state: GraphState) -> str:
    logger = logging.getLogger(__name__)
    
    routing = _routing_decision(state)
    if routing is not None and (bool(getattr(routing, "blocked", False)) or str(getattr(routing, "required_action", "") or "").strip().lower() == "reject"):
        return "safety_reject_response"
    
    turn_extra = _turn_extra(state)
    existing_intent_info = turn_extra.get("top_level_intent")
    
    if existing_intent_info and isinstance(existing_intent_info, dict):
        intent = existing_intent_info.get("intent")
        requires_current_shop = existing_intent_info.get("requires_current_shop", False)
        requires_candidate_context = existing_intent_info.get("requires_candidate_context", False)
        source = existing_intent_info.get("source", "existing")
        confidence = existing_intent_info.get("confidence", 0.0)
        reason = existing_intent_info.get("reason", "")
        matched_signals = existing_intent_info.get("matched_signals", [])
    else:
        raw_query = _turn_raw_query(state)
        persistent = state.get("persistent")
        client_context = dict(getattr(state.get("runtime"), "client_context", {}) or {})
        
        result = route_top_level_intent(raw_query, persistent=persistent, client_context=client_context)
        
        turn_extra["top_level_intent"] = {
            "intent": result.intent,
            "confidence": result.confidence,
            "reason": result.reason,
            "domain": result.domain,
            "required_action": result.required_action,
            "route_candidate": result.route_candidate,
            "matched_signals": result.matched_signals,
            "requires_current_shop": result.requires_current_shop,
            "requires_candidate_context": result.requires_candidate_context,
            "source": "top_level_intent_router",
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        
        intent = result.intent
        requires_current_shop = result.requires_current_shop
        requires_candidate_context = result.requires_candidate_context
        source = "top_level_intent_router"
        confidence = result.confidence
        reason = result.reason
        matched_signals = result.matched_signals or []
    
    route = "unknown"
    if intent in {"identity", "capability", "help"}:
        if intent == "identity":
            route = "identity_answer"
        elif intent == "capability":
            route = "capability_answer"
        elif intent == "help":
            route = "capability_answer"
    elif intent in {"direct_chat"}:
        route = "direct_chat_answer"
    elif intent in {"unsafe", "math_or_code", "document_or_knowledge", "planning"}:
        route = "out_of_scope_response"
    elif intent in {"local_life", "recommendation", "comparison"}:
        if requires_candidate_context:
            persistent = state.get("persistent")
            last_candidates = list(getattr(persistent, "last_candidates", None) or [])
            if not last_candidates:
                route = "clarification_node"
            else:
                route = "resolve_target_shop"
        elif requires_current_shop:
            has_current_shop = bool(turn_extra.get("current_shop") or turn_extra.get("selected_shop_id"))
            if not has_current_shop:
                route = "clarification_node"
            else:
                route = "resolve_target_shop"
        else:
            route = "resolve_target_shop"
    else:
        route = "clarification_node"
    
    raw_query = _turn_raw_query(state)
    normalized_query = raw_query.replace(" ", "")
    
    logger.info(
        "top_level_intent_route raw_query=%s normalized_query=%s intent=%s route=%s confidence=%.2f source=%s matched_signals=%s reason=%s requires_current_shop=%s requires_candidate_context=%s",
        raw_query,
        normalized_query,
        intent,
        route,
        confidence,
        source,
        matched_signals,
        reason,
        requires_current_shop,
        requires_candidate_context,
    )
    
    return route


def _merged_query_safety_route(state: GraphState) -> str:
    merged = _turn_extra(state).get("merged_query_safety") or {}
    if bool(merged.get("blocked")):
        return "safety_reject_response"
    return "understand_turn"


def _route_after_select_required_sources(state: GraphState) -> str:
    branch = _route_branch(state)
    if branch == "recommendation":
        return "recommendation_executor"
    if branch == "tool":
        return "tool_executor"
    if branch in {"rag", "rag_plus_tool"}:
        return "rag_executor"
    return "rag_executor"


def _route_after_rag_executor(state: GraphState) -> str:
    branch = _route_branch(state)
    if branch in {"tool", "rag_plus_tool"}:
        return "tool_executor"
    if branch == "recommendation":
        return "recommendation_executor"
    return "merge_or_rank"


def _route_after_tool_executor(state: GraphState) -> str:
    return "recommendation_executor" if _route_branch(state) == "recommendation" else "merge_or_rank"


def _route_after_execute_plan_step(state: GraphState) -> str:
    step = getattr(state["turn"], "current_step", None)
    step_id = str(getattr(step, "step_id", "") or "").strip().lower()
    goal = str(getattr(step, "goal", "") or "").strip().lower()
    allowed_tools = " ".join(str(tool or "").strip().lower() for tool in list(getattr(step, "allowed_tools", []) or []))
    haystack = " ".join(part for part in (step_id, goal, allowed_tools) if part)
    if "compose" in haystack or "answer" in haystack:
        return "compose_draft"
    if "merge" in haystack:
        return "merge_executor"
    if "rank" in haystack or "rerank" in haystack:
        return "rank_executor"
    if any(token in haystack for token in ("recommend", "compare", "multi")):
        return "recommendation_executor_complex"
    if any(token in haystack for token in ("tool", "coupon", "open", "book", "reserve", "search", "lookup")):
        return "tool_executor_complex"
    return "rag_executor_complex"


def _route_after_complex_review(state: GraphState) -> str:
    turn = state["turn"]
    attempts = int(getattr(turn, "extra", {}).get("complex_review_attempts", 0) or 0)
    summary = getattr(turn, "final_task_summary", None)
    status = str(getattr(summary, "status", "") or "").strip().lower() if summary is not None else ""
    if bool(getattr(turn, "need_replan", False)):
        if attempts < 1:
            return "execute_plan_step"
        return "planner_node"
    if status == "completed":
        return "final_answer"
    if status == "need_approval":
        return "final_with_limitations"
    if status in {"partial", "failed"}:
        return "repair_answer"
    return "final_with_limitations"


def _complex_step_node(state: GraphState, node_name: str) -> GraphState:
    turn_extra = _turn_extra(state)
    turn_extra["complex_step_node"] = {
        "node": node_name,
        "current_step_id": str(getattr(getattr(state["turn"], "current_step", None), "step_id", "") or "").strip() or None,
    }
    state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["complex_step_node"] = node_name
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _all_steps_done_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    plan = list(getattr(turn, "plan", []) or [])
    step_results = list(getattr(turn, "step_results", []) or [])
    completed_steps = len([item for item in step_results if getattr(item, "status", None) == "success"])
    total_steps = len(plan)
    is_done = bool(total_steps) and completed_steps >= total_steps and not bool(getattr(turn, "need_human_approval", False))
    turn_extra = _turn_extra(state)
    turn_extra["all_steps_done"] = {
        "completed": is_done,
        "completed_steps": completed_steps,
        "total_steps": total_steps,
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["all_steps_done"] = is_done
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _route_after_all_steps_done(state: GraphState) -> str:
    turn = state["turn"]
    plan = list(getattr(turn, "plan", []) or [])
    step_results = list(getattr(turn, "step_results", []) or [])
    completed_steps = len([item for item in step_results if getattr(item, "status", None) == "success"])
    total_steps = len(plan)
    is_done = bool(total_steps) and completed_steps >= total_steps and not bool(getattr(turn, "need_human_approval", False))
    return "complex_review" if is_done else "execute_plan_step"


def _route_after_final_answer_safety(state: GraphState) -> str:
    safety_result = _turn_extra(state).get("final_answer_safety") or {}
    if bool(safety_result.get("blocked")):
        return "final_safety_fallback"
    return "response_builder"


def _route_after_final_safety_fallback(state: GraphState) -> str:
    return "response_builder"


def _route_after_repair_answer(state: GraphState) -> str:
    return "final_answer"


def _route_after_final_with_limitations(state: GraphState) -> str:
    return "final_answer"


def _request_legality_node(state: GraphState) -> GraphState:
    routing = _routing_decision(state)
    state = _update_turn_extra(
        state,
        request_legality={
            "checked": True,
            "blocked": bool(getattr(routing, "blocked", False)) if routing is not None else False,
            "required_action": _routing_action(state) or None,
            "route_reason": str(getattr(routing, "route_reason", "") or "").strip() if routing is not None else None,
        },
    )
    return state


def _query_safety_node(state: GraphState) -> GraphState:
    routing = _routing_decision(state)
    return _update_turn_extra(
        state,
        query_safety={
            "checked": True,
            "blocked": bool(getattr(routing, "blocked", False)) if routing is not None else False,
            "required_action": _routing_action(state) or None,
        },
    )


def _query_merge_node(state: GraphState) -> GraphState:
    return _update_turn_extra(
        state,
        query_merge_for_local_life={
            "checked": True,
            "needs_merge": _requires_query_merge(state),
        },
    )


def _merged_query_safety_node(state: GraphState) -> GraphState:
    routing = _routing_decision(state)
    client_context = dict(getattr(state.get("runtime"), "client_context", {}) or {})
    result = check_query_safety(_turn_raw_query(state), client_context=client_context)
    if routing is not None and bool(getattr(routing, "blocked", False)):
        result = result.model_copy(
            update={
                "blocked": True,
                "allowed": False,
                "required_action": "reject",
                "reason": str(getattr(routing, "blocked_reason", "") or getattr(routing, "route_reason", "") or result.reason),
            }
        )
    return _update_turn_extra(
        state,
        merged_query_safety={
            "checked": True,
            "query": _turn_raw_query(state),
            "blocked": bool(result.blocked),
            "allowed": bool(result.allowed),
            "required_action": str(getattr(result, "required_action", "") or "").strip() or None,
            "reason": str(getattr(result, "reason", "") or "").strip() or None,
        },
    )


def _top_level_intent_router_node(state: GraphState) -> GraphState:
    route = _top_level_intent_route(state)
    return _update_turn_extra(
        state,
        top_level_intent_router={
            "route": route,
            "query": _turn_raw_query(state),
        },
    )


def _identity_answer_node(state: GraphState) -> GraphState:
    return _preset_response(
        state,
        response_node="identity_answer",
        answer_text="我是本地生活助手，可以帮你查店铺信息、优惠券、营业状态和推荐。",
        route_candidate="profile",
        route_reason="top_level_identity",
    )


def _capability_answer_node(state: GraphState) -> GraphState:
    return _preset_response(
        state,
        response_node="capability_answer",
        answer_text="我可以帮你查店铺详情、优惠券、营业时间、距离和推荐。",
        route_candidate="low_info",
        route_reason="top_level_capability",
    )


def _direct_chat_answer_node(state: GraphState) -> GraphState:
    return _preset_response(
        state,
        response_node="direct_chat_answer",
        answer_text="可以，我在。你也可以继续问我本地生活相关问题。",
        route_candidate="greeting",
        route_reason="top_level_direct_chat",
    )


def _out_of_scope_response_node(state: GraphState) -> GraphState:
    return _preset_response(
        state,
        response_node="out_of_scope_response",
        answer_text="这个问题超出了本地生活查询范围，我先帮你处理店铺相关的问题。",
        route_candidate="empty",
        route_reason="top_level_out_of_scope",
    )


def _illegal_request_response_node(state: GraphState) -> GraphState:
    return _preset_response(
        state,
        response_node="illegal_request_response",
        answer_text="抱歉，这个请求目前无法处理。",
        route_candidate="low_info",
        route_reason="request_legality_failed",
    )


def _safety_reject_response_node(state: GraphState) -> GraphState:
    return _preset_response(
        state,
        response_node="safety_reject_response",
        answer_text="抱歉，这个问题涉及安全限制，我不能继续处理。",
        route_candidate="low_info",
        route_reason="query_safety_rejected",
    )


def _final_answer_node(state: GraphState, services: WorkflowServices) -> GraphState:
    turn = state["turn"]
    if not str(getattr(turn, "final_answer", "") or "").strip():
        state = services.compose_answer(state)
        turn = state["turn"]

    if str(getattr(turn, "execution_mode", "") or "").strip().lower() == "plan_execute":
        summary = getattr(turn, "final_task_summary", None)
        if summary is not None:
            summary_text = str(getattr(summary, "final_decision", "") or "").strip()
            summary_status = str(getattr(summary, "status", "") or "").strip()
            planned_answer = f"Plan execution {summary_status}: {summary_text}".strip()
            if summary_text:
                turn_extra = _turn_extra(state)
                turn_extra["plan_execution_answer"] = planned_answer
                turn = turn.model_copy(update={"final_answer": planned_answer, "extra": turn_extra})
                state["turn"] = turn

    turn_extra = _turn_extra(state)
    turn_extra["final_answer_ready"] = True
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["final_answer"] = True
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _collect_query_metrics(state: GraphState, bundle: Any = None) -> None:
    """Collect business metrics for the current query."""
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    persistent = state.get("persistent")

    raw_query = str(getattr(turn, "raw_query", "") or "")
    answer_contract = turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None)
    intent = str(getattr(answer_contract, "intent", "") or turn_extra.get("intent", "") or "")
    route = str(_routing_action(state) or "")
    answer_style = str(getattr(answer_contract, "answer_style", "") or "")

    target_shop_id = turn_extra.get("selected_shop_id") or getattr(persistent, "selected_shop_id", None)
    answer_shop_ids = list(turn_extra.get("answer_shop_ids") or [])

    forbidden_facets = list(getattr(answer_contract, "forbidden_facets", []) or [])
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])

    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    tool_results = list(turn_extra.get("tool_results") or [])

    degraded = bool(turn_extra.get("degraded") or getattr(state["runtime"], "degrade_to", ""))
    degraded_reason = str(getattr(state["runtime"], "degrade_to", "") or turn_extra.get("degraded_reason", "") or "")
    fallback = bool(turn_extra.get("fallback"))

    clarification_asked = bool(turn_extra.get("clarification_asked"))
    clarification_needed = bool(turn_extra.get("clarification_needed"))

    answer_text = str(getattr(turn, "final_answer", "") or "")

    metrics = QueryMetrics(
        query=raw_query,
        intent=intent,
        route=route,
        answer_style=answer_style,
        single_shop_mode=answer_style == "single_shop_review",
        recommendation_mode=answer_style == "multi_shop_recommendation",
        tool_called=bool(tool_results),
        tools_called=[str(r.get("tool_name", "")) for r in tool_results if isinstance(r, dict)],
        evidence_count=len(evidence_claims),
        target_shop_id=target_shop_id,
        answer_shop_ids=answer_shop_ids,
        forbidden_facets=forbidden_facets,
        realtime_facets=realtime_facets,
        degraded=degraded,
        degraded_reason=degraded_reason or None,
        fallback=fallback,
        clarification_asked=clarification_asked,
        clarification_needed=clarification_needed,
        answer_text=answer_text,
    )

    business_metrics_collector.record_query(metrics)


def _resolve_facet_conflicts(state: GraphState) -> None:
    """Resolve conflicts between RAG and tool results for realtime facets."""
    turn_extra = _turn_extra(state)
    answer_contract = turn_extra.get("answer_contract") or getattr(state["turn"], "answer_contract", None)

    if answer_contract is None:
        return

    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    if not realtime_facets:
        return

    tool_results = list(turn_extra.get("tool_results") or [])
    tool_result_map: dict[str, Any] = {}
    for tr in tool_results:
        if isinstance(tr, dict):
            facet = tr.get("facet") or tr.get("tool_name", "")
            tool_result_map[facet] = tr

    evidence_claims = list(turn_extra.get("evidence_claims") or [])

    for facet in realtime_facets:
        if facet in REALTIME_FACETS:
            tool_result = tool_result_map.get(facet)
            rag_result = None
            for claim in evidence_claims:
                claim_facet = str(getattr(claim, "facet", "") or (claim.get("facet", "") if isinstance(claim, dict) else ""))
                if claim_facet == facet:
                    rag_result = claim
                    break

            if tool_result or rag_result:
                resolution = resolve_realtime_conflict(
                    facet=facet,
                    tool_result=tool_result,
                    rag_result=rag_result,
                )
                if resolution:
                    turn_extra[f"conflict_resolution_{facet}"] = {
                        "chosen_source": resolution.chosen_source,
                        "resolution_reason": resolution.resolution_reason,
                    }


def _response_builder_node(state: GraphState, services: WorkflowServices) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    
    # Update dialog state
    from learning_agent_service.local_life.dialog_state_machine import dialog_state_machine, DialogState
    
    persistent = state.get("persistent")
    if persistent:
        from learning_agent_service.local_life.dialog_state_machine import DialogContext
        
        dialog_ctx = DialogContext(
            current_state=DialogState(str(getattr(persistent, "dialog_state", "") or DialogState.IDLE.value)),
            transition_count=int(getattr(persistent, "dialog_transition_count", 0) or 0),
        )
        
        # Determine trigger based on current situation
        has_clarification = bool(turn_extra.get("clarification_needed"))
        has_results = bool(turn_extra.get("evidence_claims"))
        answer_contract = turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None)
        is_comparison = str(getattr(answer_contract, "answer_style", "") or "") == "comparison"
        
        trigger = dialog_state_machine.determine_trigger(
            dialog_ctx,
            has_clarification=has_clarification,
            has_results=has_results,
            is_comparison=is_comparison,
        )
        
        if trigger:
            new_ctx = dialog_state_machine.transition(dialog_ctx, trigger)
            persistent.dialog_state = new_ctx.current_state.value
            persistent.dialog_transition_count = new_ctx.transition_count
    
    bundle = None
    try:
        bundle = build_response_bundle(
            raw_query=str(getattr(turn, "raw_query", "") or ""),
            slots=getattr(turn, "slots", None),
            answer_contract=turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None),
            ranked_candidates=list(turn_extra.get("ranked_candidates") or []),
            evidence_claims=list(turn_extra.get("evidence_claims") or []),
            answer_plan=turn_extra.get("task_plan") or getattr(turn, "task_plan", None),
            verification_result=turn_extra.get("answer_verifier_result"),
            evidence_pack=getattr(turn, "evidence_pack", None),
            page=str((state.get("runtime_context", {}) or {}).get("page") or (state["runtime"].client_context or {}).get("page") or ""),
            current_topic=str(getattr(state["persistent"], "current_topic", "") or ""),
            selected_shop_id=turn_extra.get("selected_shop_id"),
            current_shop=str(turn_extra.get("current_shop") or getattr(state["persistent"], "current_shop", "") or ""),
            client_context=dict(getattr(state["runtime"], "client_context", {}) or {}),
            approval_required=bool(getattr(turn, "need_human_approval", False)),
            approval_request=turn_extra.get("approval_request"),
            transaction_draft=turn_extra.get("transaction_draft"),
            safety_result=turn_extra.get("final_answer_safety"),
            route_decision=_routing_action(state) or None,
            route_reason=str(getattr(_routing_decision(state), "route_reason", "") or ""),
            current_stage=getattr(turn, "current_stage", None),
            stage_status=getattr(turn, "stage_status", None),
            stage_timeline=list((state["runtime"].metrics or {}).get("stage_timeline", []) or []),
            model_hint=turn_extra,
            source_mode=str(turn_extra.get("source_mode") or ""),
            degraded_reason=str(getattr(state["runtime"], "degrade_to", "") or ""),
            knowledge_freshness=turn_extra.get("knowledge_freshness"),
            user_need=turn_extra.get("user_need"),
            facet_result_bundle=turn_extra.get("facet_result_bundle"),
            graph_trace=turn_extra.get("phase5_trace") or turn_extra.get("phase4_trace"),
        )
        turn_extra["response_bundle"] = bundle.model_dump(mode="json") if hasattr(bundle, "model_dump") else dict(bundle)
    except Exception:
        pass

    # Collect business metrics after response is built
    try:
        _collect_query_metrics(state, bundle)
    except Exception:
        pass

    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["response_builder"] = True
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _merge_or_rank_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)

    # Resolve realtime facet conflicts before recording metrics
    try:
        _resolve_facet_conflicts(state)
    except Exception:
        pass

    ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    turn_extra["merge_or_rank"] = {
        "ranked_candidate_count": len(ranked_candidates),
        "evidence_claim_count": len(evidence_claims),
        "route_branch": _route_branch(state) or None,
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _contract_review_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    turn_extra["contract_review"] = {
        "reviewed": True,
        "branch": _route_branch(state) or None,
        "route_candidate": getattr(_routing_decision(state), "route_candidate", None),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _prepare_retry_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    review_report = turn_extra.get("review_report")
    if review_report:
        from learning_agent_service.domain.contracts import RewriteDecision
        
        retry_count = int(getattr(review_report, "retry_count", 0)) + 1
        setattr(review_report, "retry_count", retry_count)
        
        repair_hint = getattr(review_report, "repair_hint", "")
        
        rewrite = RewriteDecision(
            should_rewrite=True,
            rewritten_query=str(getattr(turn, "raw_query", "")) + f" {repair_hint}",
            reason="retry_repair_answer",
            top_k_override=10,
            extra={"failed_facets": getattr(review_report, "failed_facets", [])}
        )
        
        turn_extra["rewrite_decision"] = rewrite
        routing = getattr(turn, "routing_decision", None)
        if routing is not None:
            turn = turn.model_copy(update={"routing_decision": routing.model_copy(update={"rewrite_decision": rewrite})})

        if "rag_result" in turn_extra:
            del turn_extra["rag_result"]
        turn_extra["review_report"] = review_report
        
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _route_after_contract_review(state: GraphState) -> str:
    turn_extra = _turn_extra(state)
    review_report = turn_extra.get("review_report")
    if not review_report:
        return "final_answer"
    
    decision = getattr(review_report, "decision", "")
    if decision == "repair_answer":
        retry_count = int(getattr(review_report, "retry_count", 0))
        max_retry_count = int(getattr(review_report, "max_retry_count", 0))
        
        if retry_count < max_retry_count:
            return "prepare_retry"
            
    return "final_answer"


def _final_answer_safety_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
    raw_answer = str(
        plan_execution_answer
        or getattr(turn, "final_answer", "")
        or turn_extra.get("preset_response_text")
        or ""
    ).strip()
    ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    shop_lookup: dict[int, str] = {}
    for candidate in ranked_candidates:
        if not isinstance(candidate, Mapping):
            continue
        shop_id = candidate.get("shop_id")
        shop_name = candidate.get("name") or candidate.get("shop_name")
        if shop_id not in (None, "") and shop_name:
            try:
                shop_lookup[int(shop_id)] = str(shop_name)
            except Exception:
                pass
    safety_result = apply_final_answer_safety(
        answer_text=raw_answer,
        answer_contract=turn_extra.get("answer_contract") or getattr(turn, "answer_contract", None),
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        evidence_pack=getattr(turn, "evidence_pack", None),
        facet_result_bundle=turn_extra.get("facet_result_bundle"),
        user_need=turn_extra.get("user_need"),
        route_gate=turn_extra.get("route_gate"),
        source_contract=turn_extra.get("source_contract"),
        review_report=turn_extra.get("review_report"),
        tool_results=list(turn_extra.get("tool_results") or []),
        shop_lookup=shop_lookup or None,
    )
    if getattr(safety_result, "answer_text", None):
        final_text = str(safety_result.answer_text or "").strip()
        if plan_execution_answer:
            final_text = plan_execution_answer
        turn = turn.model_copy(update={"final_answer": final_text})
    turn_extra["final_answer_safety"] = safety_result.to_dict() if hasattr(safety_result, "to_dict") else dict(safety_result)
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["final_answer_safety"] = turn_extra["final_answer_safety"]
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _final_safety_fallback_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    safety_result = dict(turn_extra.get("final_answer_safety") or {})
    plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
    if safety_result.get("blocked") and not str(getattr(turn, "final_answer", "") or "").strip():
        fallback_text = str(safety_result.get("answer_text") or "抱歉，这条回复暂时无法安全输出。").strip()
        turn = turn.model_copy(update={"final_answer": plan_execution_answer or fallback_text})
    turn_extra["final_safety_fallback"] = {
        "applied": bool(safety_result.get("blocked")),
        "blocked": bool(safety_result.get("blocked")),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _repair_answer_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    safety_result = dict(turn_extra.get("final_answer_safety") or {})
    plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
    repaired_text = str(
        plan_execution_answer
        or safety_result.get("answer_text")
        or turn_extra.get("preset_response_text")
        or getattr(turn, "final_answer", "")
        or ""
    ).strip()
    if repaired_text:
        turn = turn.model_copy(update={"final_answer": repaired_text})
    turn_extra["repair_answer"] = {
        "repaired": bool(safety_result.get("repaired_text")),
        "severity": safety_result.get("severity"),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


def _final_with_limitations_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = _turn_extra(state)
    safety_result = dict(turn_extra.get("final_answer_safety") or {})
    plan_execution_answer = str(turn_extra.get("plan_execution_answer") or "").strip()
    issues = list(safety_result.get("issues") or [])
    current_answer = str(plan_execution_answer or getattr(turn, "final_answer", "") or "").strip()
    if issues and current_answer and not current_answer.endswith("。"):
        turn = turn.model_copy(update={"final_answer": f"{current_answer}（以上为当前可确认信息）"})
    turn_extra["final_with_limitations"] = {
        "issues": issues,
        "severity": safety_result.get("severity"),
        "passed": safety_result.get("passed"),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return state


_LANGGRAPH_TOPOLOGY = describe_main_graph_topology()


def describe_langgraph_topology() -> dict[str, Any]:
    return _LANGGRAPH_TOPOLOGY


def export_langgraph_mermaid() -> str:
    return export_main_graph_mermaid()


def _mermaid_node_id(prefix: str, label: str) -> str:
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in label).strip("_")
    return f"{prefix}_{safe}" if prefix else safe


def _main_graph_mermaid_nodes(prefix: str = "main") -> list[tuple[str, str]]:
    return [(_mermaid_node_id(prefix, node), node) for node in _LANGGRAPH_TOPOLOGY["nodes"]]


def _main_graph_mermaid_edges(prefix: str = "main") -> list[tuple[str, str, str | None]]:
    edges: list[tuple[str, str, str | None]] = []
    for edge in _LANGGRAPH_TOPOLOGY["edges"]:
        source = _mermaid_node_id(prefix, str(edge["source"]))
        target = _mermaid_node_id(prefix, str(edge["target"]))
        label = edge.get("label")
        edges.append((source, target, str(label) if label is not None else None))
    return edges


def export_full_langgraph_mermaid() -> str:
    lines = ["graph TD"]
    lines.append("  subgraph main[Main Graph]")
    for node_id, label in _main_graph_mermaid_nodes():
        lines.append(f"    {node_id}[{label}]")
    lines.append("  end")
    lines.extend(
        [
            "  subgraph rag[RAG Subgraph]",
            "    rag_build_plan[build_retrieval_plan]",
            "    rag_execute[rag_executor]",
            "    rag_finalize[finalize_rag]",
            "  end",
            "  subgraph tool[Tool Subgraph]",
            "    tool_plan[tool_plan]",
            "    tool_execute[tool_executor]",
            "    tool_finalize[finalize_tool]",
            "  end",
            "  subgraph recommendation[Recommendation Subgraph]",
            "    rec_prepare[prepare_recommendation]",
            "    rec_dispatch[recommendation_executor]",
            "    rec_finalize[finalize_recommendation]",
            "  end",
            "  subgraph stages[Workflow Stages]",
            "    stage_load_context[load_context]",
            "    stage_parse_intent_slots[parse_intent_slots]",
            "    stage_rag_gate[rag_gate]",
            "    stage_query_rewrite[query_rewrite]",
            "    stage_embedding[embedding]",
            "    stage_qdrant_search[qdrant_search]",
            "    stage_rerank[rerank]",
            "    stage_hybrid_retrieve[hybrid_retrieve]",
            "    stage_evaluate_evidence[evaluate_evidence]",
            "    stage_citation_builder[citation_builder]",
            "    stage_tool_planner[tool_planner]",
            "    stage_tool_executor[tool_executor]",
            "    stage_tool_result_normalizer[tool_result_normalizer]",
            "  end",
    ]
    )
    for source, target, label in _main_graph_mermaid_edges():
        if label:
            lines.append(f"  {source} -->|{label}| {target}")
        else:
            lines.append(f"  {source} --> {target}")
    lines.extend(
        [
            "  rag_build_plan --> rag_execute",
            "  rag_execute --> rag_finalize",
            "  rag_finalize --> main_final_answer",
            "  tool_plan --> tool_execute",
            "  tool_execute --> tool_finalize",
            "  tool_finalize --> main_final_answer",
            "  rec_prepare --> rec_dispatch",
            "  rec_dispatch --> rec_finalize",
            "  rec_finalize --> main_final_answer",
            "  stage_load_context --> stage_parse_intent_slots",
            "  stage_parse_intent_slots --> stage_rag_gate",
            "  stage_rag_gate --> stage_query_rewrite",
            "  stage_query_rewrite --> stage_embedding",
            "  stage_embedding --> stage_qdrant_search",
            "  stage_qdrant_search --> stage_rerank",
            "  stage_rerank --> stage_hybrid_retrieve",
            "  stage_hybrid_retrieve --> stage_evaluate_evidence",
            "  stage_evaluate_evidence --> stage_citation_builder",
            "  stage_citation_builder --> stage_tool_planner",
            "  stage_tool_planner --> stage_tool_executor",
            "  stage_tool_executor --> stage_tool_result_normalizer",
        ]
    )
    return "\n".join(lines)


def _resolve_compiled_graph(graph: Any) -> Any:
    getter = getattr(graph, "get_graph", None)
    if not callable(getter):
        return graph

    for kwargs in ({"xray": True}, {}):
        try:
            return getter(**kwargs)
        except TypeError:
            continue
        except Exception:
            continue
    return graph


def _draw_compiled_graph_mermaid(graph: Any, fallback: str) -> str:
    drawable = _resolve_compiled_graph(graph)
    draw_mermaid = getattr(drawable, "draw_mermaid", None)
    if callable(draw_mermaid):
        try:
            mermaid = draw_mermaid()
            if isinstance(mermaid, str) and mermaid.strip():
                return mermaid
        except Exception:
            pass
    return fallback


def _draw_compiled_graph_png(graph: Any) -> bytes | None:
    drawable = _resolve_compiled_graph(graph)
    for method_name in ("draw_mermaid_png", "draw_png"):
        draw_png = getattr(drawable, method_name, None)
        if not callable(draw_png):
            continue
        try:
            rendered = draw_png()
        except Exception:
            continue
        if isinstance(rendered, bytes) and rendered:
            return rendered
        if hasattr(rendered, "save"):
            from io import BytesIO

            buffer = BytesIO()
            rendered.save(buffer, format="PNG")
            data = buffer.getvalue()
            if data:
                return data
    return None


def _render_full_graph_png(_mermaid_text: str) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    def _load_font(size: int = 16):
        font_candidates = [
            Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts" / "arial.ttf",
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
        ]
        for candidate in font_candidates:
            if candidate.exists():
                try:
                    return ImageFont.truetype(str(candidate), size=size)
                except Exception:
                    continue
        return ImageFont.load_default()

    font = _load_font(15)
    title_font = _load_font(20)
    small_font = _load_font(13)
    main_nodes = _main_graph_mermaid_nodes()
    main_edges = [(source, target) for source, target, _label in _main_graph_mermaid_edges()]

    groups = [
        {
            "title": "Main Graph",
            "x": 120,
            "y": 80,
            "width": 1960,
            "nodes": main_nodes,
            "fill": (243, 247, 255),
            "outline": (121, 143, 201),
        },
        {
            "title": "RAG Subgraph",
            "x": 120,
            "y": 540,
            "width": 560,
            "nodes": [
                ("rag_build_plan", "build_retrieval_plan"),
                ("rag_execute", "rag_executor"),
                ("rag_finalize", "finalize_rag"),
            ],
            "fill": (242, 250, 244),
            "outline": (112, 163, 125),
        },
        {
            "title": "Tool Subgraph",
            "x": 780,
            "y": 540,
            "width": 560,
            "nodes": [
                ("tool_plan", "tool_plan"),
                ("tool_execute", "tool_executor"),
                ("tool_finalize", "finalize_tool"),
            ],
            "fill": (255, 248, 240),
            "outline": (204, 149, 90),
        },
        {
            "title": "Recommendation Subgraph",
            "x": 1440,
            "y": 540,
            "width": 640,
            "nodes": [
                ("rec_prepare", "prepare_recommendation"),
                ("rec_dispatch", "recommendation_executor"),
                ("rec_finalize", "finalize_recommendation"),
            ],
            "fill": (249, 242, 255),
            "outline": (160, 121, 201),
        },
        {
            "title": "Workflow Stages",
            "x": 120,
            "y": 980,
            "width": 1960,
            "nodes": [
                ("stage_load_context", "load_context"),
                ("stage_parse_intent_slots", "parse_intent_slots"),
                ("stage_rag_gate", "rag_gate"),
                ("stage_query_rewrite", "query_rewrite"),
                ("stage_embedding", "embedding"),
                ("stage_qdrant_search", "qdrant_search"),
                ("stage_rerank", "rerank"),
                ("stage_hybrid_retrieve", "hybrid_retrieve"),
                ("stage_evaluate_evidence", "evaluate_evidence"),
                ("stage_citation_builder", "citation_builder"),
                ("stage_tool_planner", "tool_planner"),
                ("stage_tool_executor", "tool_executor"),
                ("stage_tool_result_normalizer", "tool_result_normalizer"),
            ],
            "fill": (240, 248, 255),
            "outline": (100, 145, 185),
        },
    ]

    node_w = 320
    node_h = 42
    node_gap = 14
    header_h = 44
    group_pad = 26
    canvas_w = 2200
    canvas_h = 1800
    image = Image.new("RGBA", (canvas_w, canvas_h), (250, 251, 252, 255))
    draw = ImageDraw.Draw(image)

    node_boxes: dict[str, tuple[int, int, int, int]] = {}

    for group in groups:
        nodes = group["nodes"]
        group_height = header_h + group_pad + len(nodes) * (node_h + node_gap) + group_pad - node_gap
        x0 = group["x"]
        y0 = group["y"]
        x1 = x0 + group["width"]
        y1 = y0 + group_height
        draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=group["fill"], outline=group["outline"], width=3)
        draw.text((x0 + 18, y0 + 10), group["title"], fill=(30, 30, 30), font=title_font)

        base_y = y0 + header_h
        for index, (node_id, label) in enumerate(nodes):
            center_x = x0 + group["width"] // 2
            top = base_y + group_pad + index * (node_h + node_gap)
            left = center_x - node_w // 2
            right = left + node_w
            bottom = top + node_h
            node_boxes[node_id] = (left, top, right, bottom)
            draw.rounded_rectangle((left, top, right, bottom), radius=12, fill=(255, 255, 255), outline=group["outline"], width=2)
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            draw.text(
                (left + (node_w - text_w) / 2, top + (node_h - text_h) / 2 - 1),
                label,
                fill=(25, 25, 25),
                font=font,
            )

    edges = [
        ("main_load_context", "main_request_legality"),
        ("main_request_legality", "main_illegal_request_response"),
        ("main_request_legality", "main_hard_guard"),
        ("main_illegal_request_response", "main_final_answer"),
        ("main_hard_guard", "main_clarification_or_reject"),
        ("main_hard_guard", "main_query_safety"),
        ("main_clarification_or_reject", "main_final_answer"),
        ("main_query_safety", "main_safety_reject_response"),
        ("main_query_safety", "main_query_merge_for_local_life"),
        ("main_safety_reject_response", "main_final_answer"),
        ("main_query_merge_for_local_life", "main_merged_query_safety"),
        ("main_query_merge_for_local_life", "main_top_level_intent_router"),
        ("main_merged_query_safety", "main_top_level_intent_router"),
        ("main_top_level_intent_router", "main_identity_answer"),
        ("main_top_level_intent_router", "main_capability_answer"),
        ("main_top_level_intent_router", "main_direct_chat_answer"),
        ("main_top_level_intent_router", "main_out_of_scope_response"),
        ("main_top_level_intent_router", "main_understand_turn"),
        ("main_identity_answer", "main_final_answer"),
        ("main_capability_answer", "main_final_answer"),
        ("main_direct_chat_answer", "main_final_answer"),
        ("main_out_of_scope_response", "main_final_answer"),
        ("main_understand_turn", "main_resolve_target_shop"),
        ("main_resolve_target_shop", "main_build_answer_contract"),
        ("main_build_answer_contract", "main_build_source_contract"),
        ("main_build_source_contract", "main_complexity_router"),
        ("main_complexity_router", "main_clarification_node"),
        ("main_complexity_router", "main_direct_executor"),
        ("main_complexity_router", "main_workflow_executor"),
        ("main_complexity_router", "main_planner_node"),
        ("main_clarification_node", "main_final_answer"),
        ("main_direct_executor", "main_rule_review"),
        ("main_rule_review", "main_final_answer"),
        ("main_workflow_executor", "main_select_required_sources"),
        ("main_select_required_sources", "main_planner_node"),
        ("main_select_required_sources", "main_rag_executor"),
        ("main_select_required_sources", "main_tool_executor"),
        ("main_select_required_sources", "main_recommendation_executor"),
        ("main_select_required_sources", "main_merge_or_rank"),
        ("main_planner_node", "main_plan_validator"),
        ("main_plan_validator", "main_plan_executor"),
        ("main_plan_executor", "main_execute_plan_step"),
        ("main_execute_plan_step", "main_collect_step_result"),
        ("main_collect_step_result", "main_complex_review"),
        ("main_complex_review", "main_plan_executor"),
        ("main_complex_review", "main_merge_or_rank"),
        ("main_rag_executor", "main_tool_executor"),
        ("main_rag_executor", "main_recommendation_executor"),
        ("main_rag_executor", "main_merge_or_rank"),
        ("main_tool_executor", "main_recommendation_executor"),
        ("main_tool_executor", "main_merge_or_rank"),
        ("main_recommendation_executor", "main_merge_or_rank"),
        ("main_merge_or_rank", "main_contract_review"),
        ("main_contract_review", "main_final_answer"),
        ("main_final_answer", "main_final_answer_safety"),
        ("main_final_answer_safety", "main_final_safety_fallback"),
        ("main_final_safety_fallback", "main_repair_answer"),
        ("main_repair_answer", "main_final_with_limitations"),
        ("main_final_with_limitations", "main_persist_session"),
        ("main_persist_session", "main_emit_final"),
        ("rag_build_plan", "rag_execute"),
        ("rag_execute", "rag_finalize"),
        ("rag_finalize", "main_final_answer"),
        ("tool_plan", "tool_execute"),
        ("tool_execute", "tool_finalize"),
        ("tool_finalize", "main_final_answer"),
        ("rec_prepare", "rec_dispatch"),
        ("rec_dispatch", "rec_finalize"),
        ("rec_finalize", "main_final_answer"),
        ("stage_load_context", "stage_parse_intent_slots"),
        ("stage_parse_intent_slots", "stage_rag_gate"),
        ("stage_rag_gate", "stage_query_rewrite"),
        ("stage_query_rewrite", "stage_embedding"),
        ("stage_embedding", "stage_qdrant_search"),
        ("stage_qdrant_search", "stage_rerank"),
        ("stage_rerank", "stage_hybrid_retrieve"),
        ("stage_hybrid_retrieve", "stage_evaluate_evidence"),
        ("stage_evaluate_evidence", "stage_citation_builder"),
        ("stage_citation_builder", "stage_tool_planner"),
        ("stage_tool_planner", "stage_tool_executor"),
        ("stage_tool_executor", "stage_tool_result_normalizer"),
    ]

    def draw_arrow(src: tuple[int, int, int, int], dst: tuple[int, int, int, int]) -> None:
        sx = (src[0] + src[2]) / 2
        sy = src[3]
        dx = (dst[0] + dst[2]) / 2
        dy = dst[1]
        mid_y = (sy + dy) / 2
        points = [(sx, sy), (sx, mid_y), (dx, mid_y), (dx, dy)]
        draw.line(points, fill=(82, 97, 120), width=3)
        arrow_size = 8
        draw.polygon(
            [
                (dx, dy),
                (dx - arrow_size, dy - arrow_size * 1.6),
                (dx + arrow_size, dy - arrow_size * 1.6),
            ],
            fill=(82, 97, 120),
        )

    for source, target in edges:
        src_box = node_boxes.get(source)
        dst_box = node_boxes.get(target)
        if src_box and dst_box:
            draw_arrow(src_box, dst_box)

    footer = "Combined overview: main graph, compiled subgraphs, and workflow stages"
    footer_bbox = draw.textbbox((0, 0), footer, font=small_font)
    draw.text((24, canvas_h - 40), footer, fill=(96, 104, 116), font=small_font)

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_mermaid_with_mmdc(mermaid_text: str, output_path: Path) -> bool:
    try:
        import subprocess
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as tmp:
            tmp.write(mermaid_text)
            tmp_path = tmp.name
        result = subprocess.run(
            ["npx", "@mermaid-js/mermaid-cli", "-i", tmp_path, "-o", str(output_path), "-b", "white", "-w", "2400", "-H", "1600"],
            capture_output=True,
            timeout=120,
        )
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return result.returncode == 0 and output_path.exists()
    except Exception:
        return False


def _render_mermaid_with_graphviz(mermaid_text: str, output_path: Path) -> bool:
    try:
        import subprocess
        dot_lines = ["digraph G {", "  rankdir=TB;", "  node [shape=box, style=filled, fillcolor=lightblue];"]
        edge_pattern = re.compile(r"^(?P<src>.+?)\s*-->(?:\|[^|]+\|)?\s*(?P<dst>.+?)\s*$")

        def _dot_node_id(token: str) -> str:
            token = token.strip().rstrip(";")
            token = re.sub(r"\[[^\]]+\]", "", token)
            token = re.sub(r"\{[^\}]+\}", "", token)
            token = re.sub(r"\([^\)]+\)", "", token)
            return token.strip()

        lines = mermaid_text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("---") or line.startswith("config:") or line.startswith("flowchart:") or line.startswith("curve:") or line == "graph TD;":
                continue
            match = edge_pattern.match(line.rstrip(";"))
            if match:
                src = _dot_node_id(match.group("src").replace(":::first", "").replace(":::last", ""))
                dst = _dot_node_id(match.group("dst").replace(":::first", "").replace(":::last", ""))
                if src and dst:
                    dot_lines.append(f'  "{src}" -> "{dst}";')
                continue
            if "(" in line and ")" in line and "-->" not in line:
                continue
        dot_lines.append("}")
        dot_content = "\n".join(dot_lines)
        result = subprocess.run(
            ["dot", "-Tpng", "-o", str(output_path)],
            input=dot_content,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0 and output_path.exists()
    except Exception:
        return False


def _write_graph_artifacts(
    target_dir: Path,
    stem: str,
    graph: Any,
    fallback_mermaid: str,
    include_png: bool = True,
    use_compiled_mermaid: bool = True,
    custom_png_renderer: Any = None,
) -> dict[str, str]:
    mermaid_text = _draw_compiled_graph_mermaid(graph, fallback_mermaid) if use_compiled_mermaid else fallback_mermaid
    mermaid_path = target_dir / f"{stem}.mmd"
    mermaid_path.write_text(mermaid_text, encoding="utf-8")

    written = {f"{stem}.mmd": str(mermaid_path)}

    if include_png:
        png_bytes = None
        if callable(custom_png_renderer):
            try:
                png_bytes = custom_png_renderer(mermaid_text)
            except Exception:
                png_bytes = None
        if png_bytes is None:
            png_path = target_dir / f"{stem}.png"
            if _render_mermaid_with_mmdc(mermaid_text, png_path):
                written[f"{stem}.png"] = str(png_path)
                return written
            if _render_mermaid_with_graphviz(mermaid_text, png_path):
                written[f"{stem}.png"] = str(png_path)
                return written
            png_bytes = _draw_compiled_graph_png(graph)
        if png_bytes:
            png_path = target_dir / f"{stem}.png"
            png_path.write_bytes(png_bytes)
            written[f"{stem}.png"] = str(png_path)

    return written


def write_langgraph_visualizations(
    output_dir: str | Path | None = None,
    services: WorkflowServices | None = None,
) -> dict[str, str]:
    from .graphs import (
        export_rag_graph_mermaid,
        export_recommendation_graph_mermaid,
        export_tool_graph_mermaid,
        describe_rag_graph_topology,
        describe_recommendation_graph_topology,
        describe_tool_graph_topology,
        build_rag_graph,
        build_recommendation_graph,
        build_tool_graph,
    )

    workflow_services = services or WorkflowServices()
    target_dir = Path(output_dir) if output_dir is not None else Path(__file__).resolve().parents[5] / "docs" / "langgraph"
    target_dir.mkdir(parents=True, exist_ok=True)

    main_graph = _build_langgraph_runner(workflow_services)
    rag_graph = build_rag_graph(workflow_services.rag_subgraph)
    tool_graph = build_tool_graph(workflow_services.tool_subgraph)
    recommendation_graph = build_recommendation_graph(workflow_services.rag_subgraph)

    files = {}
    files.update(
        _write_graph_artifacts(
            target_dir,
            "main_graph",
            main_graph,
            export_langgraph_mermaid(),
            use_compiled_mermaid=False,
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "full_graph",
            main_graph,
            export_full_langgraph_mermaid(),
            use_compiled_mermaid=False,
            custom_png_renderer=_render_full_graph_png,
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "rag_graph",
            rag_graph,
            export_rag_graph_mermaid(),
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "tool_graph",
            tool_graph,
            export_tool_graph_mermaid(),
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "recommendation_graph",
            recommendation_graph,
            export_recommendation_graph_mermaid(),
        )
    )

    topology_path = target_dir / "langgraph_topology.md"
    topology_path.write_text(
        "\n".join(
            [
                "# LangGraph Topology",
                "",
                "## Main Graph",
                f"- entry_point: {_LANGGRAPH_TOPOLOGY['entry_point']}",
                f"- terminal: {_LANGGRAPH_TOPOLOGY['terminal']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(main_graph, export_langgraph_mermaid()),
                "```",
                "",
                "## Full Graph",
                "",
                "```mermaid",
                export_full_langgraph_mermaid(),
                "```",
                "",
                "## Rag Graph",
                f"- entry_point: {describe_rag_graph_topology()['entry_point']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(rag_graph, export_rag_graph_mermaid()),
                "```",
                "",
                "## Tool Graph",
                f"- entry_point: {describe_tool_graph_topology()['entry_point']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(tool_graph, export_tool_graph_mermaid()),
                "```",
                "",
                "## Recommendation Graph",
                f"- entry_point: {describe_recommendation_graph_topology()['entry_point']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(recommendation_graph, export_recommendation_graph_mermaid()),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files["langgraph_topology.md"] = str(topology_path)
    return files


def _build_langgraph_runner(services: WorkflowServices, checkpointer: Any = None):
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed")

    from langgraph.types import RetryPolicy

    workflow_retry_policy = RetryPolicy(
        max_attempts=3,
        backoff_factor=2.0,
        initial_interval=1.0,
        retry_on=Exception,
    )

    graph = StateGraph(GraphState)  # type: ignore[type-var]
    def _route_gate_stage(state: GraphState) -> GraphState:
        command = route_gate(state)
        updated = getattr(command, "update", None)
        if isinstance(updated, dict):
            return updated
        return state

    def _rule_review_stage(state: GraphState) -> GraphState:
        turn_extra = _turn_extra(state)
        turn_extra["rule_review"] = {
            "reviewed": True,
            "required_action": _routing_action(state) or None,
            "route_branch": _route_branch(state) or None,
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def _select_required_sources_stage(state: GraphState) -> GraphState:
        turn_extra = _turn_extra(state)
        route = _route_after_select_required_sources(state)
        turn_extra["select_required_sources"] = {
            "selected_route": route,
            "execution_mode": str(getattr(state["turn"], "execution_mode", "") or "").strip().lower() or None,
            "branch": _route_branch(state) or None,
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def _plan_executor_stage(state: GraphState) -> GraphState:
        turn_extra = _turn_extra(state)
        turn_extra["plan_executor"] = {
            "running": True,
            "step_index": int(getattr(state["turn"], "current_step_index", 0) or 0),
        }
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def _plan_planner_stage(state: GraphState) -> GraphState:
        state = services.plan_execute.plan_planner(state)
        turn = state["turn"]
        if not bool(getattr(turn, "need_human_approval", False)) and not getattr(turn, "approval_request", None):
            for step in list(getattr(turn, "plan", []) or []):
                allowed_tools = [str(tool or "").strip() for tool in list(getattr(step, "allowed_tools", []) or [])]
                booking_tool = next((tool for tool in allowed_tools if tool and ("booking" in tool or "reserve" in tool or "reservation" in tool)), None)
                if booking_tool:
                    request = {
                        "step_id": getattr(step, "step_id", None),
                        "goal": getattr(step, "goal", None),
                        "tool_name": booking_tool,
                        "risk_level": getattr(step, "risk_level", None),
                        "reason": "步骤候选工具需要人工审批。",
                    }
                    state["turn"] = turn.model_copy(
                        update={
                            "need_human_approval": True,
                            "approval_request": request,
                            "current_step": step,
                        }
                    )
                    state = _append_state_runtime_event(
                        state,
                        "approval_required",
                        {
                            "step_id": request["step_id"],
                            "reason": request["reason"],
                            "approval_request": request,
                            "risk_level": request["risk_level"],
                        },
                    )
                    break
        return state

    def _plan_validator_stage(state: GraphState) -> GraphState:
        state = services.plan_execute.plan_validator(state)
        turn = state["turn"]
        if not bool(getattr(turn, "need_human_approval", False)) and not getattr(turn, "approval_request", None):
            for step in list(getattr(turn, "plan", []) or []):
                allowed_tools = [str(tool or "").strip() for tool in list(getattr(step, "allowed_tools", []) or [])]
                booking_tool = next((tool for tool in allowed_tools if tool and ("booking" in tool or "reserve" in tool or "reservation" in tool)), None)
                if booking_tool:
                    request = {
                        "step_id": getattr(step, "step_id", None),
                        "goal": getattr(step, "goal", None),
                        "tool_name": booking_tool,
                        "risk_level": getattr(step, "risk_level", None),
                        "reason": "步骤候选工具需要人工审批。",
                    }
                    state["turn"] = turn.model_copy(
                        update={
                            "need_human_approval": True,
                            "approval_request": request,
                            "current_step": step,
                        }
                    )
                    state = _append_state_runtime_event(
                        state,
                        "approval_required",
                        {
                            "step_id": request["step_id"],
                            "reason": request["reason"],
                            "approval_request": request,
                            "risk_level": request["risk_level"],
                        },
                    )
                    return state
        if bool(getattr(turn, "need_human_approval", False)) or bool(getattr(turn, "approval_request", None)):
            state = services.plan_execute.human_approval_stub(state)
        return state

    def _complex_review_stage(state: GraphState) -> GraphState:
        state = services.plan_execute.plan_reviewer(state)
        turn = state["turn"]
        if bool(getattr(turn, "need_human_approval", False)):
            state = services.plan_execute.human_approval_stub(state)
        elif bool(getattr(turn, "need_replan", False)):
            state = services.plan_execute.replanner(state)
        turn_extra = _turn_extra(state)
        turn_extra["complex_review_attempts"] = int(turn_extra.get("complex_review_attempts", 0) or 0) + 1
        turn_extra["complex_review"] = {
            "need_human_approval": bool(getattr(state["turn"], "need_human_approval", False)),
            "need_replan": bool(getattr(state["turn"], "need_replan", False)),
        }
        summary = getattr(state["turn"], "final_task_summary", None)
        if summary is not None:
            summary_text = str(getattr(summary, "final_decision", "") or "").strip()
            summary_status = str(getattr(summary, "status", "") or "").strip()
            if summary_text:
                turn_extra["plan_execution_answer"] = f"Plan execution {summary_status}: {summary_text}".strip()
                state["turn"] = state["turn"].model_copy(
                    update={
                        "final_answer": turn_extra["plan_execution_answer"],
                        "extra": turn_extra,
                    }
                )
                return state
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    graph.add_node("load_context", lambda state: services.load_context(state))
    graph.add_node("request_legality", _request_legality_node, retry_policy=workflow_retry_policy)
    graph.add_node("illegal_request_response", _illegal_request_response_node, retry_policy=workflow_retry_policy)
    graph.add_node("hard_guard", _hard_guard_stage, retry_policy=workflow_retry_policy)
    graph.add_node("clarification_or_reject", _clarification_or_reject_stage, retry_policy=workflow_retry_policy)
    graph.add_node("query_safety", _query_safety_node, retry_policy=workflow_retry_policy)
    graph.add_node("safety_reject_response", _safety_reject_response_node, retry_policy=workflow_retry_policy)
    graph.add_node("query_merge_for_local_life", _query_merge_node, retry_policy=workflow_retry_policy)
    graph.add_node("merged_query_safety", _merged_query_safety_node, retry_policy=workflow_retry_policy)
    graph.add_node("top_level_intent_router", _top_level_intent_router_node, retry_policy=workflow_retry_policy)
    graph.add_node("identity_answer", _identity_answer_node, retry_policy=workflow_retry_policy)
    graph.add_node("capability_answer", _capability_answer_node, retry_policy=workflow_retry_policy)
    graph.add_node("direct_chat_answer", _direct_chat_answer_node, retry_policy=workflow_retry_policy)
    graph.add_node("out_of_scope_response", _out_of_scope_response_node, retry_policy=workflow_retry_policy)
    graph.add_node("understand_turn", lambda state: run_understand_turn(state, services.understand_turn), retry_policy=workflow_retry_policy)
    graph.add_node("resolve_target_shop", _resolve_target_shop_stage, retry_policy=workflow_retry_policy)
    graph.add_node("build_answer_contract", _build_answer_contract_stage, retry_policy=workflow_retry_policy)
    graph.add_node("build_source_contract", _build_source_contract_stage, retry_policy=workflow_retry_policy)
    graph.add_node("complexity_router", _complexity_router_stage, retry_policy=workflow_retry_policy)
    graph.add_node("clarification_node", _clarification_node_stage, retry_policy=workflow_retry_policy)
    graph.add_node("direct_executor", _direct_executor_stage, retry_policy=workflow_retry_policy)
    graph.add_node("rule_review", _rule_review_stage, retry_policy=workflow_retry_policy)
    graph.add_node("workflow_executor", _workflow_executor_stage, retry_policy=workflow_retry_policy)
    graph.add_node("select_required_sources", _select_required_sources_stage, retry_policy=workflow_retry_policy)
    graph.add_node("rag_executor", lambda state: run_rag_subgraph(state, services.rag_subgraph), retry_policy=workflow_retry_policy)
    graph.add_node("tool_executor", lambda state: run_tool_subgraph(state, services.tool_subgraph), retry_policy=workflow_retry_policy)
    graph.add_node("recommendation_executor", lambda state: run_recommendation_subgraph(state, services.rag_subgraph), retry_policy=workflow_retry_policy)
    graph.add_node("merge_or_rank", _merge_or_rank_node, retry_policy=workflow_retry_policy)
    graph.add_node("contract_review", _contract_review_node, retry_policy=workflow_retry_policy)
    graph.add_node("prepare_retry", _prepare_retry_node, retry_policy=workflow_retry_policy)
    graph.add_node("planner_node", _plan_planner_stage, retry_policy=workflow_retry_policy)
    graph.add_node("plan_validator", _plan_validator_stage, retry_policy=workflow_retry_policy)
    graph.add_node("plan_executor", _plan_executor_stage, retry_policy=workflow_retry_policy)
    graph.add_node("execute_plan_step", lambda state: services.plan_execute.step_executor(state), retry_policy=workflow_retry_policy)
    graph.add_node("rag_executor_complex", lambda state: _complex_step_node(state, "rag_executor_complex"), retry_policy=workflow_retry_policy)
    graph.add_node("tool_executor_complex", lambda state: _complex_step_node(state, "tool_executor_complex"), retry_policy=workflow_retry_policy)
    graph.add_node("recommendation_executor_complex", lambda state: _complex_step_node(state, "recommendation_executor_complex"), retry_policy=workflow_retry_policy)
    graph.add_node("rank_executor", lambda state: _complex_step_node(state, "rank_executor"), retry_policy=workflow_retry_policy)
    graph.add_node("merge_executor", lambda state: _complex_step_node(state, "merge_executor"), retry_policy=workflow_retry_policy)
    graph.add_node("compose_draft", lambda state: _complex_step_node(state, "compose_draft"), retry_policy=workflow_retry_policy)
    graph.add_node("collect_step_result", lambda state: services.plan_execute.progress_checker(state), retry_policy=workflow_retry_policy)
    graph.add_node("all_steps_done?", _all_steps_done_node, retry_policy=workflow_retry_policy)
    graph.add_node("complex_review", _complex_review_stage, retry_policy=workflow_retry_policy)
    graph.add_node("final_answer", lambda state: _final_answer_node(state, services), retry_policy=workflow_retry_policy)
    graph.add_node("final_answer_safety", _final_answer_safety_node, retry_policy=workflow_retry_policy)
    graph.add_node("final_safety_fallback", _final_safety_fallback_node, retry_policy=workflow_retry_policy)
    graph.add_node("repair_answer", _repair_answer_node, retry_policy=workflow_retry_policy)
    graph.add_node("final_with_limitations", _final_with_limitations_node, retry_policy=workflow_retry_policy)
    graph.add_node("response_builder", lambda state: _response_builder_node(state, services), retry_policy=workflow_retry_policy)
    graph.add_node("persist_session", lambda state: services.persist_session(state), retry_policy=workflow_retry_policy)
    graph.add_node("emit_final", lambda state: services.emit_final(state), retry_policy=workflow_retry_policy)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "request_legality")
    graph.add_conditional_edges(
        "request_legality",
        _request_legality_route,
        {
            "illegal_request_response": "illegal_request_response",
            "hard_guard": "hard_guard",
        },
    )
    graph.add_edge("illegal_request_response", "final_answer")
    graph.add_conditional_edges(
        "hard_guard",
        _hard_guard_route,
        {
            "clarification_or_reject": "clarification_or_reject",
            "query_safety": "query_safety",
        },
    )
    graph.add_edge("clarification_or_reject", "final_answer")
    graph.add_conditional_edges(
        "query_safety",
        _query_safety_route,
        {
            "safety_reject_response": "safety_reject_response",
            "query_merge_for_local_life": "query_merge_for_local_life",
        },
    )
    graph.add_edge("safety_reject_response", "final_answer")
    graph.add_edge("query_merge_for_local_life", "merged_query_safety")
    graph.add_conditional_edges(
        "merged_query_safety",
        _merged_query_safety_route,
        {
            "safety_reject_response": "safety_reject_response",
            "understand_turn": "understand_turn",
        },
    )
    graph.add_conditional_edges(
        "top_level_intent_router",
        _top_level_intent_route,
        {
            "identity_answer": "identity_answer",
            "capability_answer": "capability_answer",
            "direct_chat_answer": "direct_chat_answer",
            "out_of_scope_response": "out_of_scope_response",
            "safety_reject_response": "safety_reject_response",
            "resolve_target_shop": "resolve_target_shop",
        },
    )
    graph.add_edge("identity_answer", "final_answer")
    graph.add_edge("capability_answer", "final_answer")
    graph.add_edge("direct_chat_answer", "final_answer")
    graph.add_edge("out_of_scope_response", "final_answer")
    graph.add_edge("understand_turn", "top_level_intent_router")
    graph.add_edge("resolve_target_shop", "build_answer_contract")
    graph.add_edge("build_answer_contract", "build_source_contract")
    graph.add_edge("build_source_contract", "complexity_router")
    graph.add_conditional_edges(
        "complexity_router",
        _complexity_router_route,
        {
            "clarification_node": "clarification_node",
            "direct_executor": "direct_executor",
            "workflow_executor": "workflow_executor",
            "planner_node": "planner_node",
        },
    )
    graph.add_edge("clarification_node", "final_answer")
    graph.add_edge("direct_executor", "rule_review")
    graph.add_edge("rule_review", "final_answer")
    graph.add_edge("workflow_executor", "select_required_sources")
    graph.add_conditional_edges(
        "select_required_sources",
        _route_after_select_required_sources,
        {
            "rag_executor": "rag_executor",
            "tool_executor": "tool_executor",
            "recommendation_executor": "recommendation_executor",
        },
    )
    graph.add_edge("planner_node", "plan_validator")
    graph.add_edge("plan_validator", "plan_executor")
    graph.add_edge("plan_executor", "execute_plan_step")
    graph.add_conditional_edges(
        "execute_plan_step",
        _route_after_execute_plan_step,
        {
            "rag_executor_complex": "rag_executor_complex",
            "tool_executor_complex": "tool_executor_complex",
            "recommendation_executor_complex": "recommendation_executor_complex",
            "rank_executor": "rank_executor",
            "merge_executor": "merge_executor",
            "compose_draft": "compose_draft",
        },
    )
    graph.add_edge("rag_executor_complex", "collect_step_result")
    graph.add_edge("tool_executor_complex", "collect_step_result")
    graph.add_edge("recommendation_executor_complex", "collect_step_result")
    graph.add_edge("rank_executor", "collect_step_result")
    graph.add_edge("merge_executor", "collect_step_result")
    graph.add_edge("compose_draft", "collect_step_result")
    graph.add_edge("collect_step_result", "all_steps_done?")
    graph.add_conditional_edges(
        "all_steps_done?",
        _route_after_all_steps_done,
        {
            "execute_plan_step": "execute_plan_step",
            "complex_review": "complex_review",
        },
    )
    graph.add_conditional_edges(
        "complex_review",
        _route_after_complex_review,
        {
            "final_answer": "final_answer",
            "repair_answer": "repair_answer",
            "execute_plan_step": "execute_plan_step",
            "planner_node": "planner_node",
            "final_with_limitations": "final_with_limitations",
        },
    )
    graph.add_conditional_edges(
        "rag_executor",
        _route_after_rag_executor,
        {
            "tool_executor": "tool_executor",
            "recommendation_executor": "recommendation_executor",
            "merge_or_rank": "merge_or_rank",
        },
    )
    graph.add_conditional_edges(
        "tool_executor",
        _route_after_tool_executor,
        {
            "recommendation_executor": "recommendation_executor",
            "merge_or_rank": "merge_or_rank",
        },
    )
    graph.add_edge("recommendation_executor", "merge_or_rank")
    graph.add_edge("merge_or_rank", "contract_review")
    graph.add_conditional_edges(
        "contract_review",
        _route_after_contract_review,
        {
            "prepare_retry": "prepare_retry",
            "final_answer": "final_answer",
        }
    )
    graph.add_edge("prepare_retry", "rag_executor")
    graph.add_edge("final_answer", "final_answer_safety")
    graph.add_conditional_edges(
        "final_answer_safety",
        _route_after_final_answer_safety,
        {
            "final_safety_fallback": "final_safety_fallback",
            "response_builder": "response_builder",
        },
    )
    graph.add_edge("final_safety_fallback", "response_builder")
    graph.add_edge("repair_answer", "final_answer")
    graph.add_edge("final_with_limitations", "final_answer")
    graph.add_edge("response_builder", "persist_session")
    graph.add_edge("persist_session", "emit_final")
    graph.add_edge("emit_final", END)
    compiled = graph.compile(checkpointer=checkpointer)
    return compiled



def create_workflow_runner(
    services: WorkflowServices,
    prefer_langgraph: bool = True,
    workflow_version: str = "learn-agent/v1",
    checkpointer: Any = None,
):
    if prefer_langgraph and LANGGRAPH_AVAILABLE:
        return LangGraphWorkflowRunner(
            services=services,
            workflow_version=workflow_version,
            checkpointer=checkpointer,
        )
    return SequentialWorkflowRunner(services=services, workflow_version=workflow_version)
