from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ...domain.contracts import Citation, EvidencePack, EvidenceItem
from ...domain.state import GraphState, clone_graph_state
from .services import RagSubgraphServices, ToolSubgraphServices
from .state import append_runtime_error as _append_state_runtime_error
from .subgraphs import (
    _ensure_rag_result,
    _ensure_raw_tool_result,
    _ensure_tool_result,
    _filter_evidence_by_contract,
    _mark_stage,
    _route_decision_for_turn,
    _tool_stage_detail,
    can_enter_retrieval,
    route_after_rag,
    should_run_tools,
)

StateGraph: Any = None
Send: Any = None
END: Any = "__end__"
try:  # pragma: no cover - optional dependency
    from langgraph.graph import END as _END, StateGraph as _StateGraph  # type: ignore[import-not-found, import]
    from langgraph.types import Send as _Send  # type: ignore[import-not-found, import]

    END = _END
    StateGraph = _StateGraph
    Send = _Send
except Exception:  # pragma: no cover - optional dependency
    StateGraph = None
    Send = None


LANGGRAPH_AVAILABLE = StateGraph is not None
SEND_AVAILABLE = Send is not None


@dataclass(frozen=True)
class _GraphTopology:
    entry_point: str
    terminal: str
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]


_RAG_TOPOLOGY = _GraphTopology(
    entry_point="build_retrieval_plan",
    terminal="END",
    nodes=(
        "build_retrieval_plan",
        "execute_rag_pipeline",
        "finalize_rag",
    ),
    edges=(
        ("build_retrieval_plan", "execute_rag_pipeline"),
        ("execute_rag_pipeline", "finalize_rag"),
        ("finalize_rag", "END"),
    ),
)

_TOOL_TOPOLOGY = _GraphTopology(
    entry_point="tool_plan",
    terminal="END",
    nodes=(
        "tool_plan",
        "execute_tool_pipeline",
        "finalize_tool",
    ),
    edges=(
        ("tool_plan", "execute_tool_pipeline"),
        ("execute_tool_pipeline", "finalize_tool"),
        ("finalize_tool", "END"),
    ),
)

_RECOMMENDATION_TOPOLOGY = _GraphTopology(
    entry_point="prepare_recommendation",
    terminal="END",
    nodes=(
        "prepare_recommendation",
        "dispatch_shop_analysis",
        "analyze_one_shop",
        "reduce_shop_results",
        "finalize_recommendation",
    ),
    edges=(
        ("prepare_recommendation", "dispatch_shop_analysis"),
        ("dispatch_shop_analysis", "analyze_one_shop"),
        ("analyze_one_shop", "reduce_shop_results"),
        ("reduce_shop_results", "finalize_recommendation"),
        ("finalize_recommendation", "END"),
    ),
)

_GRAPH_CACHE: dict[tuple[str, int], Any] = {}
_RECOMMENDATION_BRANCH_CACHE: dict[str, GraphState] = {}


def _cache_key(name: str, services: object) -> tuple[str, int]:
    return name, id(services)


def _graph_cached(name: str, services: object, builder) -> Any:
    if not LANGGRAPH_AVAILABLE:
        return None
    key = _cache_key(name, services)
    graph = _GRAPH_CACHE.get(key)
    if graph is None:
        graph = builder()
        _GRAPH_CACHE[key] = graph
    return graph


def _prepare_rag(state: GraphState) -> GraphState:
    return clone_graph_state(state)


def _execute_rag_pipeline(state: GraphState, services: RagSubgraphServices) -> GraphState:
    contract = state["turn"].routing_contract
    rag_allowed = contract.rag_allowed if contract is not None else can_enter_retrieval(state).allowed
    if not rag_allowed:
        return _ensure_rag_result(state)

    state = _mark_stage(state, "rag", "running", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])))
    try:
        state = services.hybrid_retrieve(state)
        state = services.evaluate_evidence(state)
        state = _filter_evidence_by_contract(state)
        state = services.citation_builder(state)
        state = _mark_stage(
            state,
            "rag",
            "completed",
            route_decision=_route_decision_for_turn(state["turn"]),
            route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
            detail={"evidence_count": len(state["turn"].evidence_pack.items) if state["turn"].evidence_pack else 0},
        )
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("RAG retrieval failed, applying degrade mechanism.")
        from learning_agent_service.domain.contracts import EvidencePack, RagResult
        from learning_agent_service.domain.enums import RagStatus
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
            stage="retrieval",
            message=f"RAG retrieval degraded due to exception: {exc}",
            retryable=False,
            is_terminal=False,
        )

        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["retrieval_degraded"] = True
        metrics["retrieval_error"] = str(exc)

        state = _append_state_runtime_error(state, err)
        state["runtime"] = state["runtime"].model_copy(update={"degrade_to": "retrieval_degraded", "metrics": metrics})

        turn = state["turn"]
        degraded_pack = EvidencePack(items=[], evidence_status="DEGRADED", extra={"degrade_reason": str(exc)})
        state["turn"] = turn.model_copy(
            update={
                "evidence_pack": degraded_pack,
                "citations": [],
                "rag_result": RagResult(
                    status=RagStatus.DEGRADED,
                    evidence_pack=degraded_pack,
                    citations=[],
                    metrics={"error": str(exc)},
                    extra={"degraded": True},
                ),
            }
        )
        state = _mark_stage(state, "rag", "failed", route_decision=_route_decision_for_turn(state["turn"]), route_reason=f"retrieval_degraded: {exc}")

    return _ensure_rag_result(state)


def _finalize_rag(state: GraphState) -> GraphState:
    return _ensure_rag_result(state)


def _prepare_tool(state: GraphState) -> GraphState:
    return clone_graph_state(state)


def _execute_tool_pipeline(state: GraphState, services: ToolSubgraphServices) -> GraphState:
    contract = state["turn"].routing_contract
    tool_allowed = contract.tool_allowed if contract is not None else should_run_tools(state)
    if not tool_allowed:
        state = _ensure_raw_tool_result(state)
        return _ensure_tool_result(state)

    state = _mark_stage(
        state,
        "tool",
        "running",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail={"decision": _route_decision_for_turn(state["turn"]), "intent": state["turn"].intent.value if state["turn"].intent else None},
    )
    try:
        state = services.tool_planner(state)
        selection = state["turn"].tool_plan
        if selection is None or not selection.should_execute:
            state = _ensure_raw_tool_result(state)
        else:
            state = services.tool_executor(state)
            state = _ensure_raw_tool_result(state)

        state = services.tool_result_normalizer(state)
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Tool execution failed, applying degrade mechanism.")
        from learning_agent_service.domain.contracts import NormalizedToolResult, ToolExecutionResult
        from learning_agent_service.domain.enums import ToolExecutionStatus
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INFRASTRUCTURE_ERROR,
            stage="tool",
            message=f"Tool execution degraded due to exception: {exc}",
            retryable=False,
            is_terminal=False,
        )

        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["tool_degraded"] = True
        metrics["tool_error"] = str(exc)

        state = _append_state_runtime_error(state, err)
        state["runtime"] = state["runtime"].model_copy(update={"metrics": metrics})

        turn = state["turn"]
        tool_name = turn.tool_plan.tool_name if turn.tool_plan else "unknown_tool"
        state["turn"] = turn.model_copy(
            update={
                "raw_tool_result": ToolExecutionResult(
                    status=ToolExecutionStatus.FAILED,
                    tool_name=tool_name,
                    degraded_to=None,
                    error=WorkflowErrorCode.INFRASTRUCTURE_ERROR,
                    approval_status=None,
                    output_payload={"error": str(exc)},
                ),
                "tool_result": NormalizedToolResult(
                    status=ToolExecutionStatus.DEGRADED,
                    tool_name=tool_name,
                    normalized_output={"status": "degraded", "error": str(exc), "message": "实时券信息暂不可用"},
                    used_tools=[tool_name],
                ),
            }
        )

    state = _mark_stage(
        state,
        "tool",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail=_tool_stage_detail(state["turn"]),
    )
    return _ensure_tool_result(state)


def _finalize_tool(state: GraphState) -> GraphState:
    return _ensure_tool_result(state)


def _prepare_recommendation(state: GraphState) -> GraphState:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(turn.extra)
    turn_extra["recommendation_mode"] = True
    turn_extra["route_gate"] = {**dict(turn_extra.get("route_gate", {}) or {}), "branch": "recommendation"}
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["recommendation_mode"] = True
    runtime_metrics["rag_mode"] = "recommendation_rag"
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})

    state = _mark_stage(state, "recommendation", "running", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])), detail={"branch": "recommendation"})
    return state


def _recommendation_candidate_shop_ids(state: GraphState) -> list[int]:
    turn = state["turn"]
    routing = getattr(turn, "routing_contract", None)
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    runtime_context = dict(state.get("runtime_context", {}) or {})
    raw_candidates = []
    if routing is not None:
        raw_candidates.extend(list(getattr(routing, "candidate_shop_ids", []) or []))
    raw_candidates.extend(list(turn_extra.get("candidate_shop_ids") or []))
    raw_candidates.extend(list(runtime_context.get("candidate_shop_ids") or []))
    candidate_ids: list[int] = []
    for value in raw_candidates:
        try:
            candidate_id = int(value)
        except (TypeError, ValueError):
            continue
        if candidate_id not in candidate_ids:
            candidate_ids.append(candidate_id)
    return candidate_ids


def _analysis_score_from_state(state: GraphState) -> float:
    turn = state["turn"]
    pack = getattr(turn, "evidence_pack", None)
    if pack is not None:
        top_scores = list(getattr(pack, "top_scores", []) or [])
        if top_scores:
            try:
                return float(max(top_scores))
            except (TypeError, ValueError):
                pass
        items = list(getattr(pack, "items", []) or [])
        if items:
            try:
                return float(max(float(getattr(item, "score", 0.0) or 0.0) for item in items))
            except (TypeError, ValueError):
                pass
    tool_result = getattr(turn, "tool_result", None)
    if tool_result is not None:
        try:
            return float(getattr(tool_result, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _prepare_recommendation_branch_state(state: GraphState, shop_id: Any) -> GraphState:
    branch_state = clone_graph_state(state)
    branch_turn = branch_state["turn"]
    branch_contract = getattr(branch_turn, "routing_contract", None)
    if branch_contract is not None:
        branch_state["turn"] = branch_turn.model_copy(
            update={
                "routing_contract": branch_contract.model_copy(
                    update={
                        "target_shop_id": shop_id,
                        "candidate_shop_ids": [shop_id] if shop_id is not None else [],
                        "recommendation_mode": True,
                    }
                )
            }
        )
    branch_turn = branch_state["turn"]
    branch_state["turn"] = branch_turn.model_copy(
        update={
            "extra": {
                **dict(branch_turn.extra),
                "target_shop_id": shop_id,
                "recommendation_analysis_shop_id": shop_id,
            }
        }
    )
    branch_state["shop_id"] = shop_id
    return branch_state


def _store_recommendation_branch_state(state: GraphState, shop_id: Any) -> str:
    branch_state = _prepare_recommendation_branch_state(state, shop_id)
    runtime = state.get("runtime")
    runtime_context = dict(state.get("runtime_context", {}) or {})
    trace_id = str(getattr(runtime, "trace_id", None) or runtime_context.get("trace_id") or "recommendation")
    branch_id = f"{trace_id}:{shop_id}:{len(_RECOMMENDATION_BRANCH_CACHE) + 1}"
    _RECOMMENDATION_BRANCH_CACHE[branch_id] = branch_state
    return branch_id


def _analyze_one_shop(state: GraphState, services: RagSubgraphServices) -> GraphState:
    branch_id = state.get("branch_id")
    if branch_id is not None:
        cached_state = _RECOMMENDATION_BRANCH_CACHE.pop(str(branch_id), None)
        if cached_state is not None:
            state = cached_state
    turn = state.get("turn")
    shop_id = state.get("shop_id")
    if shop_id is None and turn is not None:
        shop_id = getattr(getattr(turn, "routing_contract", None), "target_shop_id", None)
    if turn is None:
        return state
    analysis_state = clone_graph_state(state)
    analysis_turn = analysis_state["turn"]
    analysis_turn_extra = dict(getattr(analysis_turn, "extra", {}) or {})
    analysis_turn_extra["recommendation_analysis_shop_id"] = shop_id
    analysis_state["turn"] = analysis_turn.model_copy(update={"extra": analysis_turn_extra})
    analysis_state = _execute_rag_pipeline(analysis_state, services)
    analysis_turn = analysis_state["turn"]
    evidence_pack = getattr(analysis_turn, "evidence_pack", None)
    analysis = {
        "shop_id": shop_id,
        "shop_name": analysis_turn.extra.get("target_shop_name") or analysis_turn.extra.get("selected_shop_name") or analysis_turn.extra.get("recommendation_analysis_shop_name"),
        "score": _analysis_score_from_state(analysis_state),
        "evidence_status": getattr(evidence_pack, "evidence_status", None),
        "evidence_count": len(getattr(evidence_pack, "items", []) or []),
        "citations": [citation.model_dump(mode="json") if hasattr(citation, "model_dump") else dict(citation) for citation in getattr(analysis_turn, "citations", [])],
        "summary": str(analysis_turn.extra.get("route_reason") or analysis_turn.extra.get("recommendation_analysis_reason") or "shop_analysis"),
    }
    state["shop_analyses"] = list(state.get("shop_analyses", []) or []) + [analysis]
    runtime = state["runtime"]
    metrics = dict(runtime.metrics)
    metrics["shop_analysis_count"] = len(state["shop_analyses"])
    state["runtime"] = runtime.model_copy(update={"metrics": metrics})
    return state


def _reduce_shop_results(state: GraphState) -> GraphState:
    analyses = list(state.get("shop_analyses", []) or [])
    if not analyses:
        return _ensure_rag_result(state)
    deduped: dict[Any, dict[str, Any]] = {}
    for item in analyses:
        key = item.get("shop_id")
        current = deduped.get(key)
        if current is None or float(item.get("score", 0.0) or 0.0) > float(current.get("score", 0.0) or 0.0):
            deduped[key] = dict(item)
    reduced = sorted(deduped.values(), key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    top_n = int(state.get("runtime_context", {}).get("recommendation_top_n", 3) or 3)
    reduced = reduced[: max(1, top_n)]
    state["shop_analyses"] = reduced
    runtime = state["runtime"]
    metrics = dict(runtime.metrics)
    metrics["recommendation_shop_count"] = len(reduced)
    metrics["recommendation_top_score"] = reduced[0].get("score", 0.0) if reduced else 0.0
    state["runtime"] = runtime.model_copy(update={"metrics": metrics})

    best = reduced[0] if reduced else None
    if best is not None:
        turn = state["turn"]
        evidence_pack = getattr(turn, "evidence_pack", None)
        if evidence_pack is not None:
            extra = dict(getattr(evidence_pack, "extra", {}) or {})
            extra["recommendation_top_shop_id"] = best.get("shop_id")
            state["turn"] = turn.model_copy(update={"evidence_pack": evidence_pack.model_copy(update={"extra": extra})})
        turn_extra = dict(turn.extra)
        turn_extra["recommendation_top_shop_id"] = best.get("shop_id")
        turn_extra["recommendation_top_shop_name"] = best.get("shop_name")
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
    return _ensure_rag_result(state)


def _dispatch_recommendation_send(state: GraphState):
    candidate_shop_ids = _recommendation_candidate_shop_ids(state)
    if not candidate_shop_ids:
        if SEND_AVAILABLE:
            branch_id = _store_recommendation_branch_state(state, None)
            return [Send("analyze_one_shop", {"branch_id": branch_id})]
        return ["analyze_one_shop"]
    if SEND_AVAILABLE:
        sends = []
        for shop_id in candidate_shop_ids:
            branch_id = _store_recommendation_branch_state(state, shop_id)
            sends.append(Send("analyze_one_shop", {"branch_id": branch_id}))
        return sends
    return ["analyze_one_shop"] * len(candidate_shop_ids)


def _execute_recommendation_pipeline(state: GraphState, services: RagSubgraphServices) -> GraphState:
    candidate_shop_ids = _recommendation_candidate_shop_ids(state)
    if not candidate_shop_ids:
        state = _analyze_one_shop(state, services)
        return _reduce_shop_results(state)
    turn = state["turn"]
    routing = getattr(turn, "routing_contract", None)
    base_state = clone_graph_state(state)
    analyses: list[dict[str, Any]] = []
    max_rounds = int(state.get("runtime_context", {}).get("recommendation_expand_max_rounds", len(candidate_shop_ids)) or len(candidate_shop_ids))
    for shop_id in candidate_shop_ids[: max(1, max_rounds)]:
        branch_state = _prepare_recommendation_branch_state(base_state, shop_id)
        branch_state = _analyze_one_shop(branch_state, services)
        analysis = list(branch_state.get("shop_analyses", []) or [])[-1] if branch_state.get("shop_analyses") else {}
        if analysis:
            analyses.append(dict(analysis))
    if not analyses:
        state = _analyze_one_shop(state, services)
        return _reduce_shop_results(state)
    state["shop_analyses"] = analyses
    state = _reduce_shop_results(state)
    if routing is not None:
        state["turn"] = state["turn"].model_copy(update={"routing_contract": routing})
    return state


def _finalize_recommendation(state: GraphState) -> GraphState:
    state = _reduce_shop_results(state)
    state = _mark_stage(state, "recommendation", "completed", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])), detail={"branch": "recommendation"})
    return {
        "runtime": state["runtime"],
        "turn": state["turn"],
    }


def _build_rag_graph(services: RagSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    graph.add_node("build_retrieval_plan", _prepare_rag)
    graph.add_node("execute_rag_pipeline", lambda state: _execute_rag_pipeline(state, services))
    graph.add_node("finalize_rag", _finalize_rag)
    graph.set_entry_point("build_retrieval_plan")
    graph.add_edge("build_retrieval_plan", "execute_rag_pipeline")
    graph.add_edge("execute_rag_pipeline", "finalize_rag")
    graph.add_edge("finalize_rag", END)
    return graph.compile()


def _build_tool_graph(services: ToolSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    graph.add_node("tool_plan", _prepare_tool)
    graph.add_node("execute_tool_pipeline", lambda state: _execute_tool_pipeline(state, services))
    graph.add_node("finalize_tool", _finalize_tool)
    graph.set_entry_point("tool_plan")
    graph.add_edge("tool_plan", "execute_tool_pipeline")
    graph.add_edge("execute_tool_pipeline", "finalize_tool")
    graph.add_edge("finalize_tool", END)
    return graph.compile()


def _build_recommendation_graph(services: RagSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    graph.add_node("prepare_recommendation", _prepare_recommendation)
    graph.add_node(
        "dispatch_shop_analysis",
        lambda state: (
            lambda result: {
                "shop_analyses": list(result.get("shop_analyses", []) or []),
                "runtime": result["runtime"],
                "turn": result["turn"],
            }
        )(_execute_recommendation_pipeline(clone_graph_state(state), services)),
    )
    graph.add_node("analyze_one_shop", lambda state: _analyze_one_shop(state, services))
    graph.add_node("reduce_shop_results", _reduce_shop_results)
    graph.add_node("finalize_recommendation", _finalize_recommendation)
    graph.set_entry_point("prepare_recommendation")
    graph.add_edge("prepare_recommendation", "dispatch_shop_analysis")
    graph.add_edge("dispatch_shop_analysis", "finalize_recommendation")
    graph.add_edge("finalize_recommendation", END)
    return graph.compile()


def build_rag_graph(services: RagSubgraphServices):
    return _graph_cached("rag", services, lambda: _build_rag_graph(services))


def build_tool_graph(services: ToolSubgraphServices):
    return _graph_cached("tool", services, lambda: _build_tool_graph(services))


def build_recommendation_graph(services: RagSubgraphServices):
    return _graph_cached("recommendation", services, lambda: _build_recommendation_graph(services))


def describe_rag_graph_topology() -> dict[str, Any]:
    return {
        "entry_point": _RAG_TOPOLOGY.entry_point,
        "terminal": _RAG_TOPOLOGY.terminal,
        "nodes": list(_RAG_TOPOLOGY.nodes),
        "edges": [tuple(edge) for edge in _RAG_TOPOLOGY.edges],
    }


def describe_tool_graph_topology() -> dict[str, Any]:
    return {
        "entry_point": _TOOL_TOPOLOGY.entry_point,
        "terminal": _TOOL_TOPOLOGY.terminal,
        "nodes": list(_TOOL_TOPOLOGY.nodes),
        "edges": [tuple(edge) for edge in _TOOL_TOPOLOGY.edges],
    }


def describe_recommendation_graph_topology() -> dict[str, Any]:
    return {
        "entry_point": _RECOMMENDATION_TOPOLOGY.entry_point,
        "terminal": _RECOMMENDATION_TOPOLOGY.terminal,
        "nodes": list(_RECOMMENDATION_TOPOLOGY.nodes),
        "edges": [tuple(edge) for edge in _RECOMMENDATION_TOPOLOGY.edges],
    }


def export_rag_graph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _RAG_TOPOLOGY.edges:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)


def export_tool_graph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _TOOL_TOPOLOGY.edges:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)


def export_recommendation_graph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _RECOMMENDATION_TOPOLOGY.edges:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)
