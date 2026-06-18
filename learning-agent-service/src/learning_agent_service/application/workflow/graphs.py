from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ...domain.contracts import Citation, EvidencePack, EvidenceItem
from ...domain.state import GraphState, clone_graph_state
from .services import (
    EvidenceSubgraphServices,
    PlanExecuteSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
)
from .state import append_runtime_error as _append_state_runtime_error
from .subgraphs import (
    _ensure_evidence_result,
    _ensure_raw_tool_result,
    _ensure_tool_result,
    _filter_evidence_by_contract,
    _finalize_understand_turn,
    _mark_stage,
    _prepare_understand_turn,
    _route_decision_for_turn,
    _tool_stage_detail,
    can_enter_retrieval,
    should_run_tools,
)
from .adapters.helpers import _update_phase3_trace
from .topology import (
    MAIN_GRAPH_TOPOLOGY,
    describe_langgraph_topology as describe_main_graph_topology,
    export_langgraph_mermaid as export_main_graph_mermaid,
)
from ...local_life.boundary_prompts import get_boundary_prompt

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


_EVIDENCE_TOPOLOGY = _GraphTopology(
    entry_point="build_evidence_plan",
    terminal="END",
    nodes=(
        "build_evidence_plan",
        "collect_evidence",
        "filter_evidence",
        "rank_evidence",
        "build_evidence_pack",
        "finalize_evidence",
    ),
    edges=(
        ("build_evidence_plan", "collect_evidence"),
        ("collect_evidence", "filter_evidence"),
        ("filter_evidence", "rank_evidence"),
        ("rank_evidence", "build_evidence_pack"),
        ("build_evidence_pack", "finalize_evidence"),
        ("finalize_evidence", "END"),
    ),
)

_UNDERSTAND_TOPOLOGY = _GraphTopology(
    entry_point="parse_intent_slots",
    terminal="END",
    nodes=(
        "parse_intent_slots",
        "resolve_reference",
        "ambiguity_check",
        "finalize_understand_turn",
    ),
    edges=(
        ("parse_intent_slots", "resolve_reference"),
        ("resolve_reference", "ambiguity_check"),
        ("ambiguity_check", "finalize_understand_turn"),
        ("finalize_understand_turn", "END"),
    ),
)

_PLAN_EXECUTE_TOPOLOGY = _GraphTopology(
    entry_point="planner_node",
    terminal="END",
    nodes=(
        "planner_node",
        "plan_validator",
        "plan_executor",
        "execute_plan_step",
        "collect_step_result",
        "complex_review",
        "finalize_plan_execute",
    ),
    edges=(
        ("planner_node", "plan_validator"),
        ("plan_validator", "plan_executor"),
        ("plan_executor", "execute_plan_step"),
        ("execute_plan_step", "collect_step_result"),
        ("collect_step_result", "complex_review"),
        ("complex_review", "plan_executor"),
        ("complex_review", "finalize_plan_execute"),
        ("finalize_plan_execute", "END"),
    ),
)

_TOOL_TOPOLOGY = _GraphTopology(
    entry_point="tool_plan",
    terminal="END",
    nodes=(
        "tool_plan",
        "tool_executor",
        "finalize_tool",
    ),
    edges=(
        ("tool_plan", "tool_executor"),
        ("tool_executor", "finalize_tool"),
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
        ("reduce_shop_results", "dispatch_shop_analysis"),
        ("reduce_shop_results", "finalize_recommendation"),
        ("finalize_recommendation", "END"),
    ),
)

_MAIN_TOPOLOGY = MAIN_GRAPH_TOPOLOGY

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


def _prepare_evidence(state: GraphState) -> GraphState:
    return clone_graph_state(state)


def _collect_evidence(state: GraphState, services: EvidenceSubgraphServices) -> GraphState:
    contract = state["turn"].routing_contract
    evidence_allowed = (
        contract.rag_allowed if contract is not None else can_enter_retrieval(state).allowed
    )
    if not evidence_allowed:
        return _ensure_evidence_result(state)

    state = _mark_stage(
        state,
        "evidence",
        "running",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
    )
    try:
        state = services.hybrid_retrieve(state)
        state = services.evaluate_evidence(state)
        state = _filter_evidence_by_contract(state)
        state = services.citation_builder(state)
        state = _mark_stage(
            state,
            "evidence",
            "completed",
            route_decision=_route_decision_for_turn(state["turn"]),
            route_reason=str(
                state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
            ),
            detail={
                "evidence_count": len(state["turn"].evidence_pack.items)
                if state["turn"].evidence_pack
                else 0
            },
        )
    except Exception as exc:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Evidence collection stage failed.")
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
            stage="retrieval",
            message=f"Evidence collection failed: {exc}",
            retryable=False,
            is_terminal=False,
        )
        state = _append_state_runtime_error(state, err)
        runtime = state["runtime"]
        metrics = dict(getattr(runtime, "metrics", {}) or {})
        metrics["evidence_degraded"] = True
        metrics["evidence_error"] = str(exc)
        state["runtime"] = runtime.model_copy(
            update={"metrics": metrics, "degrade_to": "retrieval_degraded"}
        )
        turn = state["turn"]
        turn_extra = dict(turn.extra)
        failures = list(turn_extra.get("evidence_stage_failures", []) or [])
        failures.append({"stage": "recall", "error": str(exc)})
        turn_extra["evidence_stage_failures"] = failures
        turn_extra["evidence_failure_reason"] = str(exc)
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        raise
    return state


def _filter_evidence(state: GraphState) -> GraphState:
    state = _ensure_evidence_result(state)
    try:
        state = state
        state = _filter_evidence_by_contract(state)
    except Exception as exc:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Evidence filtering stage failed.")
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
            stage="retrieval",
            message=f"Evidence filtering failed: {exc}",
            retryable=False,
            is_terminal=False,
        )
        state = _append_state_runtime_error(state, err)
        runtime = state["runtime"]
        metrics = dict(getattr(runtime, "metrics", {}) or {})
        metrics["evidence_degraded"] = True
        metrics["evidence_filter_error"] = str(exc)
        state["runtime"] = runtime.model_copy(
            update={"metrics": metrics, "degrade_to": "retrieval_degraded"}
        )
        turn = state["turn"]
        turn_extra = dict(turn.extra)
        failures = list(turn_extra.get("evidence_stage_failures", []) or [])
        failures.append({"stage": "filter", "error": str(exc)})
        turn_extra["evidence_stage_failures"] = failures
        turn_extra["evidence_failure_reason"] = str(exc)
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        raise
    return state


def _rank_evidence(state: GraphState) -> GraphState:
    turn = state["turn"]
    evidence_pack = getattr(turn, "evidence_pack", None)
    if evidence_pack is None or not getattr(evidence_pack, "items", None):
        return state

    items = list(getattr(evidence_pack, "items", []) or [])
    strong_items = sorted(
        [
            item
            for item in items
            if str(getattr(item, "tier", "strong") or "strong").strip().lower() != "weak"
        ],
        key=lambda item: float(getattr(item, "score", 0.0) or 0.0),
        reverse=True,
    )
    weak_items = sorted(
        [
            item
            for item in items
            if str(getattr(item, "tier", "strong") or "strong").strip().lower() == "weak"
        ],
        key=lambda item: float(getattr(item, "score", 0.0) or 0.0),
        reverse=True,
    )
    sorted_items = [*strong_items, *weak_items]
    top_scores = [float(getattr(item, "score", 0.0) or 0.0) for item in sorted_items[:5]]
    state["turn"] = turn.model_copy(
        update={
            "evidence_pack": evidence_pack.model_copy(
                update={
                    "items": sorted_items,
                    "strong_items": strong_items,
                    "weak_items": weak_items,
                    "top_scores": top_scores,
                }
            )
        }
    )
    return state


def _build_evidence_pack(state: GraphState, services: EvidenceSubgraphServices) -> GraphState:
    try:
        state = services.citation_builder(state)
    except Exception as exc:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Evidence pack construction failed.")
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
            stage="retrieval",
            message=f"Evidence pack failed: {exc}",
            retryable=False,
            is_terminal=False,
        )
        state = _append_state_runtime_error(state, err)
        runtime = state["runtime"]
        metrics = dict(getattr(runtime, "metrics", {}) or {})
        metrics["evidence_degraded"] = True
        metrics["evidence_citation_error"] = str(exc)
        state["runtime"] = runtime.model_copy(
            update={"metrics": metrics, "degrade_to": "retrieval_degraded"}
        )
        turn = state["turn"]
        turn_extra = dict(turn.extra)
        failures = list(turn_extra.get("evidence_stage_failures", []) or [])
        failures.append({"stage": "citation", "error": str(exc)})
        turn_extra["evidence_stage_failures"] = failures
        turn_extra["evidence_failure_reason"] = str(exc)
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        raise
    return _ensure_evidence_result(state)


def _execute_evidence_pipeline(state: GraphState, services: EvidenceSubgraphServices) -> GraphState:
    try:
        state = _collect_evidence(state, services)
        state = _filter_evidence(state)
        state = _rank_evidence(state)
        state = _build_evidence_pack(state, services)
        return state
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Evidence retrieval failed, applying degrade mechanism.")
        from learning_agent_service.domain.contracts import EvidencePack, RagResult
        from learning_agent_service.domain.enums import RagStatus
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
            stage="retrieval",
            message=f"Evidence retrieval degraded due to exception: {exc}",
            retryable=False,
            is_terminal=False,
        )

        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["retrieval_degraded"] = True
        metrics["retrieval_error"] = str(exc)

        state = _append_state_runtime_error(state, err)
        state["runtime"] = state["runtime"].model_copy(
            update={"degrade_to": "retrieval_degraded", "metrics": metrics}
        )

        turn = state["turn"]
        degraded_pack = EvidencePack(
            items=[], evidence_status="DEGRADED", extra={"degrade_reason": str(exc)}
        )
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
        state = _mark_stage(
            state,
            "evidence",
            "failed",
            route_decision=_route_decision_for_turn(state["turn"]),
            route_reason=f"retrieval_degraded: {exc}",
        )

    return _ensure_evidence_result(state)


def _finalize_evidence(state: GraphState) -> GraphState:
    return _ensure_evidence_result(state)


def _prepare_plan_execute(state: GraphState) -> GraphState:
    return clone_graph_state(state)


def _ensure_plan_progress_state(state: GraphState) -> GraphState:
    turn = state["turn"]
    plan = list(getattr(turn, "plan", []) or [])
    normalized_plan = []
    for item in plan:
        if hasattr(item, "model_dump"):
            normalized_plan.append(item)
            continue
        if isinstance(item, dict):
            try:
                from ...domain.contracts import PlanStep

                normalized_plan.append(PlanStep.model_validate(item))
            except Exception:
                continue
    step_results = list(getattr(turn, "step_results", []) or [])
    current_step_index = int(getattr(turn, "current_step_index", 0) or 0)
    current_step = getattr(turn, "current_step", None)
    if current_step is None and normalized_plan:
        safe_index = min(max(current_step_index, 0), len(normalized_plan) - 1)
        current_step = normalized_plan[safe_index]
    state["turn"] = turn.model_copy(
        update={
            "plan": normalized_plan,
            "step_results": step_results,
            "current_step_index": max(0, current_step_index),
            "current_step": current_step,
            "need_replan": bool(getattr(turn, "need_replan", False)),
            "need_human_approval": bool(getattr(turn, "need_human_approval", False)),
        }
    )
    return state


def _ensure_plan_summary(state: GraphState) -> GraphState:
    turn = state["turn"]
    summary = getattr(turn, "final_task_summary", None)
    if summary is None:
        plan = list(getattr(turn, "plan", []) or [])
        step_results = list(getattr(turn, "step_results", []) or [])
        completed_steps = len(
            [item for item in step_results if getattr(item, "status", None) == "success"]
        )
        total_steps = len(plan)
        if getattr(turn, "need_human_approval", False):
            status = "need_approval"
        elif getattr(turn, "need_replan", False) and completed_steps < total_steps:
            status = "partial" if completed_steps > 0 else "failed"
        elif total_steps and completed_steps >= total_steps:
            status = "completed"
        elif completed_steps > 0:
            status = "partial"
        else:
            status = "failed"

        key_findings: list[str] = []
        for result in step_results:
            observations = list(getattr(result, "observations", []) or [])
            if observations:
                key_findings.append(str(observations[0]))
        final_decision = getattr(turn, "replan_reason", None) or getattr(turn, "final_answer", None)
        if not final_decision and step_results:
            last_result = step_results[-1]
            payload = getattr(last_result, "result", None)
            if isinstance(payload, dict):
                final_decision = str(payload.get("summary") or payload.get("detail") or "")
            elif isinstance(payload, str):
                final_decision = payload
        if not final_decision:
            final_decision = (
                "等待人工审批" if getattr(turn, "need_human_approval", False) else "计划已完成"
            )

        from ...domain.contracts import PlanExecutionSummary

        summary = PlanExecutionSummary(
            status=status,  # type: ignore[arg-type]
            completed_steps=completed_steps,
            total_steps=total_steps,
            key_findings=key_findings[:5],
            final_decision=final_decision,
        )

    state["turn"] = turn.model_copy(update={"final_task_summary": summary})
    return state


def _planner_node(state: GraphState, services: PlanExecuteSubgraphServices) -> GraphState:
    turn = state["turn"]
    if (
        turn.task_plan is None
        and turn.execution_mode != "plan_execute"
        and not (
            turn.execution_mode == "auto"
            and (
                turn.task_complexity == "complex"
                or turn.need_human_approval
                or turn.risk_level in {"medium", "high"}
            )
        )
    ):
        return state

    state = _mark_stage(
        state,
        "plan_execute",
        "running",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
    )
    state = services.plan_planner(state)
    state = _ensure_plan_progress_state(state)
    return state


def _plan_validator(state: GraphState, services: PlanExecuteSubgraphServices) -> GraphState:
    state = services.plan_validator(state)
    return _ensure_plan_progress_state(state)


def _plan_executor(state: GraphState) -> GraphState:
    state = _ensure_plan_progress_state(state)
    return state


def _execute_plan_step(state: GraphState, services: PlanExecuteSubgraphServices) -> GraphState:
    state = services.step_executor(state)
    state = _ensure_plan_progress_state(state)
    return state


def _collect_step_result(state: GraphState, services: PlanExecuteSubgraphServices) -> GraphState:
    state = _ensure_plan_progress_state(state)
    state = services.progress_checker(state)
    return state


def _complex_review(state: GraphState, services: PlanExecuteSubgraphServices) -> GraphState:
    state = services.plan_reviewer(state)
    turn = state["turn"]
    if turn.need_human_approval:
        state = services.human_approval_stub(state)
        state = _mark_stage(
            state,
            "plan_execute",
            "blocked",
            route_decision=_route_decision_for_turn(state["turn"]),
            route_reason=str(
                state["turn"].replan_reason
                or state["turn"].approval_request.get("reason")
                or "need_human_approval"
            ),
        )
        return state

    if turn.need_replan:
        state = services.replanner(state)
        state = _ensure_plan_progress_state(state)
        if state["turn"].need_replan:
            state = services.plan_reviewer(state)
            state = _mark_stage(
                state,
                "plan_execute",
                "blocked",
                route_decision=_route_decision_for_turn(state["turn"]),
                route_reason=str(state["turn"].replan_reason or "need_replan"),
            )
            return state
        return state

    return state


def _finalize_plan_execute(state: GraphState) -> GraphState:
    state = _mark_stage(
        state,
        "plan_execute",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
    )
    summary = state["turn"].final_task_summary
    state = _update_phase3_trace(
        state,
        task_plan_execution_status=getattr(summary, "status", "completed")
        if summary is not None
        else "completed",
        task_plan_completed_steps=getattr(summary, "completed_steps", 0)
        if summary is not None
        else len([result for result in state["turn"].step_results if result.status == "success"]),
        task_plan_total_steps=getattr(summary, "total_steps", 0)
        if summary is not None
        else len(state["turn"].plan),
        task_plan_final_decision=getattr(summary, "final_decision", None)
        if summary is not None
        else state["turn"].final_answer,
        task_plan_step_results=len(state["turn"].step_results),
    )
    return _ensure_plan_summary(state)


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
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
        detail={
            "decision": _route_decision_for_turn(state["turn"]),
            "intent": state["turn"].intent.value if state["turn"].intent else None,
        },
    )
    try:
        state = services.tool_planner(state)
        selection = state["turn"].tool_plan
        if selection is not None and selection.should_execute:
            # 从路由决策中注入 resolved_shop_id 到单店工具 payload
            routing = getattr(state["turn"], "routing_decision", None)
            if routing is not None:
                resolved_shop_id = getattr(routing, "resolved_shop_id", None)
                if resolved_shop_id is not None:
                    payload = dict(selection.input_payload)
                    if payload.get("shop_id") is None:
                        payload["shop_id"] = resolved_shop_id
                        state["turn"] = state["turn"].model_copy(
                            update={
                                "tool_plan": selection.model_copy(
                                    update={"input_payload": payload}
                                ),
                            }
                        )
            state = services.tool_executor(state)
            state = _ensure_raw_tool_result(state)

        state = services.tool_result_normalizer(state)
    except Exception as exc:  # pragma: no cover - exercised via integration tests
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Tool execution failed, applying degrade mechanism.")
        from learning_agent_service.domain.contracts import (
            NormalizedToolResult,
            ToolExecutionResult,
        )
        from learning_agent_service.domain.enums import ToolExecutionStatus
        from learning_agent_service.domain.errors import WorkflowErrorCode, build_error

        err = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
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
        turn_extra = dict(turn.extra)
        failures = list(turn_extra.get("tool_stage_failures", []) or [])
        failures.append({"stage": "execute", "tool_name": tool_name, "error": str(exc)})
        turn_extra["tool_stage_failures"] = failures
        turn_extra["tool_failure_reason"] = str(exc)
        state["turn"] = turn.model_copy(
            update={
                "raw_tool_result": ToolExecutionResult(
                    status=ToolExecutionStatus.FAILED,
                    tool_name=tool_name,
                    degraded_to=None,
                    error=WorkflowErrorCode.INTERNAL_ERROR,
                    approval_status=None,
                    output_payload={"error": str(exc)},
                ),
                "tool_result": NormalizedToolResult(
                    status=ToolExecutionStatus.DEGRADED,
                    tool_name=tool_name,
                    normalized_output={
                        "status": "degraded",
                        "error": str(exc),
                        "message": get_boundary_prompt("service_unavailable"),
                    },
                    used_tools=[tool_name] if tool_name else [],
                    approval_status=None,
                ),
                "extra": turn_extra,
            }
        )

    state = _mark_stage(
        state,
        "tool",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
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
    turn_extra["recommendation_candidates"] = _recommendation_candidate_shop_ids(state)
    turn_extra["recommendation_index"] = 0
    turn_extra["recommendation_done"] = False
    turn_extra["route_gate"] = {
        **dict(turn_extra.get("route_gate", {}) or {}),
        "branch": "recommendation",
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["recommendation_mode"] = True
    runtime_metrics["evidence_mode"] = "recommendation_evidence"
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})

    state = _mark_stage(
        state,
        "recommendation",
        "running",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
        detail={"branch": "recommendation"},
    )
    return state


def _recommendation_candidate_shop_ids(state: GraphState) -> list[int]:
    turn = state["turn"]
    routing = getattr(turn, "routing_contract", None)
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    runtime_context = dict(state.get("runtime_context", {}) or {})

    def _shop_id_from_candidate(candidate: Any) -> Any:
        if isinstance(candidate, dict):
            return candidate.get("shop_id") or candidate.get("id")
        return getattr(candidate, "shop_id", None) or getattr(candidate, "id", None)

    raw_candidates = []
    if routing is not None:
        raw_candidates.extend(list(getattr(routing, "candidate_shop_ids", []) or []))
    raw_candidates.extend(list(turn_extra.get("candidate_shop_ids") or []))
    raw_candidates.extend(
        [
            _shop_id_from_candidate(candidate)
            for candidate in list(turn_extra.get("ranked_candidates") or [])
        ]
    )
    raw_candidates.extend(list(runtime_context.get("candidate_shop_ids") or []))
    ranked_candidates = list(getattr(turn, "ranked_candidates", []) or [])
    raw_candidates.extend([_shop_id_from_candidate(candidate) for candidate in ranked_candidates])
    evidence_pack = getattr(turn, "evidence_pack", None)
    if evidence_pack is not None:
        raw_candidates.extend(
            [
                _shop_id_from_candidate(candidate)
                for candidate in list(getattr(evidence_pack, "ranked_candidates", []) or [])
            ]
        )
        evidence_result = getattr(turn, "rag_result", None)
        evidence_pack_from_result = getattr(evidence_result, "evidence_pack", None)
        if evidence_pack_from_result is not None:
            raw_candidates.extend(
                [
                    _shop_id_from_candidate(candidate)
                    for candidate in list(
                        getattr(evidence_pack_from_result, "ranked_candidates", []) or []
                    )
                ]
            )
    candidate_ids: list[int] = []
    for value in raw_candidates:
        try:
            candidate_id = int(value)
        except (TypeError, ValueError):
            continue
        if candidate_id not in candidate_ids:
            candidate_ids.append(candidate_id)
    return candidate_ids


def _dispatch_recommendation_shop(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = dict(getattr(turn, "extra", {}) or {})
    candidates = list(
        turn_extra.get("recommendation_candidates") or _recommendation_candidate_shop_ids(state)
    )
    index = int(turn_extra.get("recommendation_index", 0) or 0)
    shop_id = candidates[index] if 0 <= index < len(candidates) else None
    routing = getattr(turn, "routing_contract", None)
    if routing is not None:
        state["turn"] = turn.model_copy(
            update={
                "routing_contract": routing.model_copy(
                    update={
                        "target_shop_id": shop_id,
                        "candidate_shop_ids": [shop_id] if shop_id is not None else [],
                        "recommendation_mode": True,
                    }
                )
            }
        )
    turn_extra["recommendation_current_shop_id"] = shop_id
    turn_extra["recommendation_has_more"] = index < max(0, len(candidates))
    state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
    return state


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
    branch_state["shop_id"] = shop_id  # type: ignore[typeddict-item]
    return branch_state


def _store_recommendation_branch_state(state: GraphState, shop_id: Any) -> str:
    branch_state = _prepare_recommendation_branch_state(state, shop_id)
    runtime = state.get("runtime")
    runtime_context = dict(state.get("runtime_context", {}) or {})
    trace_id = str(
        getattr(runtime, "trace_id", None) or runtime_context.get("trace_id") or "recommendation"
    )
    branch_id = f"{trace_id}:{shop_id}:{len(_RECOMMENDATION_BRANCH_CACHE) + 1}"
    _RECOMMENDATION_BRANCH_CACHE[branch_id] = branch_state
    return branch_id


def _analyze_one_shop(state: GraphState, services: EvidenceSubgraphServices) -> GraphState:
    if bool(getattr(state["turn"], "extra", {}).get("recommendation_done")):
        return state
    branch_id = state.get("branch_id")  # type: ignore[typeddict-item]
    if branch_id is not None:
        cached_state = _RECOMMENDATION_BRANCH_CACHE.pop(str(branch_id), None)
        if cached_state is not None:
            state = cached_state
    turn = state.get("turn")
    shop_id = state.get("shop_id")  # type: ignore[typeddict-item]
    if shop_id is None and turn is not None:
        shop_id = getattr(getattr(turn, "routing_contract", None), "target_shop_id", None)
    if turn is None:
        return state
    analysis_state = clone_graph_state(state)
    analysis_turn = analysis_state["turn"]
    analysis_turn_extra = dict(getattr(analysis_turn, "extra", {}) or {})
    analysis_turn_extra["recommendation_analysis_shop_id"] = shop_id
    analysis_state["turn"] = analysis_turn.model_copy(update={"extra": analysis_turn_extra})
    analysis_state = _execute_evidence_pipeline(analysis_state, services)
    analysis_turn = analysis_state["turn"]
    evidence_pack = getattr(analysis_turn, "evidence_pack", None)
    analysis = {
        "shop_id": shop_id,
        "shop_name": analysis_turn.extra.get("target_shop_name")
        or analysis_turn.extra.get("selected_shop_name")
        or analysis_turn.extra.get("recommendation_analysis_shop_name"),
        "score": _analysis_score_from_state(analysis_state),
        "evidence_status": getattr(evidence_pack, "evidence_status", None),
        "evidence_count": len(getattr(evidence_pack, "items", []) or []),
        "citations": [
            citation.model_dump(mode="json") if hasattr(citation, "model_dump") else dict(citation)
            for citation in getattr(analysis_turn, "citations", [])
        ],
        "summary": str(
            analysis_turn.extra.get("route_reason")
            or analysis_turn.extra.get("recommendation_analysis_reason")
            or "shop_analysis"
        ),
    }
    state["shop_analyses"] = list(state.get("shop_analyses", []) or []) + [analysis]
    turn_extra = dict(getattr(state["turn"], "extra", {}) or {})
    turn_extra["recommendation_index"] = int(turn_extra.get("recommendation_index", 0) or 0) + 1
    turn_extra["recommendation_last_shop_id"] = shop_id
    state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
    runtime = state["runtime"]
    metrics = dict(runtime.metrics)
    metrics["shop_analysis_count"] = len(state["shop_analyses"])
    state["runtime"] = runtime.model_copy(update={"metrics": metrics})
    return state


def _reduce_shop_results(state: GraphState) -> GraphState:
    if bool(getattr(state["turn"], "extra", {}).get("recommendation_done")):
        return _ensure_evidence_result(state)
    analyses = list(state.get("shop_analyses", []) or [])
    if not analyses:
        return _ensure_evidence_result(state)
    deduped: dict[Any, dict[str, Any]] = {}
    for item in analyses:
        key = item.get("shop_id")
        current = deduped.get(key)
        if current is None or float(item.get("score", 0.0) or 0.0) > float(
            current.get("score", 0.0) or 0.0
        ):
            deduped[key] = dict(item)
    reduced = sorted(
        deduped.values(), key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True
    )
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
            state["turn"] = turn.model_copy(
                update={"evidence_pack": evidence_pack.model_copy(update={"extra": extra})}
            )
        turn_extra = dict(turn.extra)
        turn_extra["recommendation_top_shop_id"] = best.get("shop_id")
        turn_extra["recommendation_top_shop_name"] = best.get("shop_name")
        # 方案A 修复：将 shop_analyses 转为 ranked_candidates 写入 turn.extra
        # 这样 _merge_rank_node 和 compose_answer 都能正确读取候选列表，
        # 进而写入 persistent.last_candidates，支持下一轮代词解析。
        if "ranked_candidates" not in turn_extra or not turn_extra.get("ranked_candidates"):
            turn_extra["ranked_candidates"] = [
                {
                    "shop_id": item.get("shop_id"),
                    "name": item.get("shop_name"),
                    "shop_name": item.get("shop_name"),
                    "score": item.get("score", 0.0),
                }
                for item in reduced
                if item.get("shop_id") is not None
            ]
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
    return _ensure_evidence_result(state)


def _route_recommendation_after_reduce(state: GraphState) -> str:
    if bool(getattr(state["turn"], "extra", {}).get("recommendation_done")):
        return "finalize_recommendation"
    turn_extra = dict(getattr(state["turn"], "extra", {}) or {})
    candidates = list(
        turn_extra.get("recommendation_candidates") or _recommendation_candidate_shop_ids(state)
    )
    index = int(turn_extra.get("recommendation_index", 0) or 0)
    if index < len(candidates):
        return "dispatch_shop_analysis"
    return "finalize_recommendation"


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


def _execute_recommendation_pipeline(
    state: GraphState, services: EvidenceSubgraphServices
) -> GraphState:
    candidate_shop_ids = _recommendation_candidate_shop_ids(state)
    if not candidate_shop_ids:
        state = _analyze_one_shop(state, services)
        state = _reduce_shop_results(state)
        turn_extra = dict(state["turn"].extra)
        turn_extra["recommendation_done"] = True
        turn_extra["recommendation_index"] = len(candidate_shop_ids)
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state
    turn = state["turn"]
    routing = getattr(turn, "routing_contract", None)
    base_state = clone_graph_state(state)
    analyses: list[dict[str, Any]] = []
    max_rounds = int(
        state.get("runtime_context", {}).get(
            "recommendation_expand_max_rounds", len(candidate_shop_ids)
        )
        or len(candidate_shop_ids)
    )
    branch_shop_ids = candidate_shop_ids[: max(1, max_rounds)]
    if branch_shop_ids:

        def _run_branch(shop_id: int) -> dict[str, Any] | None:
            branch_state = _prepare_recommendation_branch_state(base_state, shop_id)
            branch_state = _analyze_one_shop(branch_state, services)
            if branch_state.get("shop_analyses"):
                analysis = list(branch_state.get("shop_analyses", []) or [])[-1]
                return dict(analysis) if analysis else None
            return None

        max_workers = min(max(1, len(branch_shop_ids)), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_branch, shop_id): shop_id for shop_id in branch_shop_ids
            }
            for future in as_completed(futures):
                try:
                    analysis = future.result()
                except Exception:
                    continue
                if analysis:
                    analyses.append(dict(analysis))
    if not analyses:
        state = _analyze_one_shop(state, services)
        state = _reduce_shop_results(state)
        turn_extra = dict(state["turn"].extra)
        turn_extra["recommendation_done"] = True
        turn_extra["recommendation_index"] = len(candidate_shop_ids)
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state
    state["shop_analyses"] = analyses
    state = _reduce_shop_results(state)
    if routing is not None:
        state["turn"] = state["turn"].model_copy(update={"routing_contract": routing})
    turn_extra = dict(state["turn"].extra)
    turn_extra["recommendation_done"] = True
    turn_extra["recommendation_index"] = len(candidate_shop_ids)
    state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
    return state


def _finalize_recommendation(state: GraphState) -> GraphState:
    state = _mark_stage(
        state,
        "recommendation",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(
            state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])
        ),
        detail={"branch": "recommendation"},
    )
    state = _ensure_evidence_result(state)
    return state


def _score_key(item: Any) -> float:
    if isinstance(item, dict):
        return float(item.get("score", 0.0) or 0.0)
    return float(getattr(item, "score", 0.0) or 0.0)


def _rule_review(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = dict(turn.extra)
    turn_extra["rule_review"] = {
        "reviewed": True,
        "current_action": str(getattr(turn.routing_decision, "required_action", "") or "")
        .strip()
        .lower()
        if getattr(turn, "routing_decision", None) is not None
        else None,
        "route_review_decision": dict(turn_extra.get("route_review_decision") or {}),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return _mark_stage(
        state,
        "rule_review",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(turn_extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail=turn_extra["rule_review"],
    )


def _merge_rank_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = dict(turn.extra)
    ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])
    ranked_candidates = sorted(ranked_candidates, key=_score_key, reverse=True)
    evidence_claims = sorted(evidence_claims, key=_score_key, reverse=True)
    turn_extra["ranked_candidates"] = ranked_candidates
    turn_extra["evidence_claims"] = evidence_claims
    turn_extra["merge_rank_node"] = {
        "reviewed": True,
        "ranked_candidate_count": len(ranked_candidates),
        "evidence_claim_count": len(evidence_claims),
        "top_candidate": (
            ranked_candidates[0].get("name")
            if ranked_candidates and isinstance(ranked_candidates[0], dict)
            else getattr(ranked_candidates[0], "name", None)
        )
        if ranked_candidates
        else None,
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return _mark_stage(
        state,
        "merge_rank",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(turn_extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail=turn_extra["merge_rank_node"],
    )


def _contract_review(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = dict(turn.extra)
    turn_extra["contract_review"] = {
        "reviewed": True,
        "branch": str(turn_extra.get("route_gate", {}).get("branch") or "").strip().lower() or None,
        "target_shop_id": turn_extra.get("target_shop_id"),
        "route_candidate": turn_extra.get("route_candidate"),
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})
    return _mark_stage(
        state,
        "contract_review",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(turn_extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail=turn_extra["contract_review"],
    )


def _build_evidence_graph(services: EvidenceSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    # 这里是证据子图的编排层，检索计划和排序是规则调度，真正的能力由注入服务完成。
    graph.add_node("build_evidence_plan", _prepare_evidence)
    graph.add_node("collect_evidence", lambda state: _collect_evidence(state, services))
    graph.add_node("filter_evidence", _filter_evidence)
    graph.add_node("rank_evidence", _rank_evidence)
    graph.add_node("build_evidence_pack", lambda state: _build_evidence_pack(state, services))
    graph.add_node("finalize_evidence", _finalize_evidence)
    graph.set_entry_point("build_evidence_plan")
    graph.add_edge("build_evidence_plan", "collect_evidence")
    graph.add_edge("collect_evidence", "filter_evidence")
    graph.add_edge("filter_evidence", "rank_evidence")
    graph.add_edge("rank_evidence", "build_evidence_pack")
    graph.add_edge("build_evidence_pack", "finalize_evidence")
    graph.add_edge("finalize_evidence", END)
    return graph.compile()


def _build_understand_turn_graph(services: UnderstandTurnServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    # understand_turn 子图里，parse_intent_slots 是模型分类节点，resolve_reference 走实体消歧服务，ambiguity_check 是规则判断。
    graph.add_node(
        "parse_intent_slots",
        lambda state: services.parse_intent_slots(_prepare_understand_turn(state)),
    )
    graph.add_node("resolve_reference", lambda state: services.resolve_reference(state))
    graph.add_node("ambiguity_check", lambda state: services.ambiguity_check(state))
    graph.add_node(
        "finalize_understand_turn", lambda state: _finalize_understand_turn(state, services)
    )
    graph.set_entry_point("parse_intent_slots")
    graph.add_edge("parse_intent_slots", "resolve_reference")
    graph.add_edge("resolve_reference", "ambiguity_check")
    graph.add_edge("ambiguity_check", "finalize_understand_turn")
    graph.add_edge("finalize_understand_turn", END)
    return graph.compile()


def _build_plan_execute_graph(services: PlanExecuteSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    # 计划执行子图以规则编排为主，planner/reviewer 负责总结，step_executor 负责逐步推进。
    graph.add_node("planner_node", _prepare_plan_execute)
    graph.add_node("plan_validator", lambda state: _plan_validator(state, services))
    graph.add_node("plan_executor", _plan_executor)
    graph.add_node("execute_plan_step", lambda state: _execute_plan_step(state, services))
    graph.add_node("collect_step_result", lambda state: _collect_step_result(state, services))
    graph.add_node("complex_review", lambda state: _complex_review(state, services))
    graph.add_node("finalize_plan_execute", _finalize_plan_execute)
    graph.set_entry_point("planner_node")
    graph.add_edge("planner_node", "plan_validator")
    graph.add_edge("plan_validator", "plan_executor")
    graph.add_edge("plan_executor", "execute_plan_step")
    graph.add_edge("execute_plan_step", "collect_step_result")
    graph.add_edge("collect_step_result", "complex_review")
    graph.add_edge("complex_review", "plan_executor")
    graph.add_edge("complex_review", "finalize_plan_execute")
    graph.add_edge("finalize_plan_execute", END)
    return graph.compile()


def _build_tool_graph(services: ToolSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    # 工具子图本身是调度层，真正的工具调用由注入的执行器处理。
    graph.add_node("tool_plan", _prepare_tool)
    graph.add_node("tool_executor", lambda state: _execute_tool_pipeline(state, services))
    graph.add_node("finalize_tool", _finalize_tool)
    graph.set_entry_point("tool_plan")
    graph.add_edge("tool_plan", "tool_executor")
    graph.add_edge("tool_executor", "finalize_tool")
    graph.add_edge("finalize_tool", END)
    return graph.compile()


def _build_recommendation_graph(services: EvidenceSubgraphServices):
    graph = StateGraph(GraphState)  # type: ignore[type-var]
    # 推荐子图同样是编排层，门店分析和聚合逻辑由注入服务实现。
    graph.add_node("prepare_recommendation", _prepare_recommendation)
    graph.add_node("dispatch_shop_analysis", lambda state: clone_graph_state(state))
    graph.add_node(
        "analyze_one_shop",
        lambda state: _execute_recommendation_pipeline(clone_graph_state(state), services),
    )
    graph.add_node("reduce_shop_results", _reduce_shop_results)
    graph.add_node("finalize_recommendation", _finalize_recommendation)
    graph.set_entry_point("prepare_recommendation")
    graph.add_edge("prepare_recommendation", "dispatch_shop_analysis")
    graph.add_edge("dispatch_shop_analysis", "analyze_one_shop")
    graph.add_edge("analyze_one_shop", "reduce_shop_results")
    graph.add_edge("reduce_shop_results", "finalize_recommendation")
    graph.add_edge("finalize_recommendation", END)
    return graph.compile()


def build_evidence_graph(services: EvidenceSubgraphServices):
    return _graph_cached("evidence", services, lambda: _build_evidence_graph(services))


def build_understand_turn_graph(services: UnderstandTurnServices):
    return _graph_cached(
        "understand_turn", services, lambda: _build_understand_turn_graph(services)
    )


def build_plan_execute_graph(services: PlanExecuteSubgraphServices):
    return _graph_cached("plan_execute", services, lambda: _build_plan_execute_graph(services))


def build_tool_graph(services: ToolSubgraphServices):
    return _graph_cached("tool", services, lambda: _build_tool_graph(services))


def build_recommendation_graph(services: EvidenceSubgraphServices):
    return _graph_cached("recommendation", services, lambda: _build_recommendation_graph(services))


def describe_langgraph_topology() -> dict[str, Any]:
    return {
        "entry_point": _MAIN_TOPOLOGY.entry_point,
        "terminal": _MAIN_TOPOLOGY.terminal,
        "nodes": list(_MAIN_TOPOLOGY.nodes),
        "edges": [(edge.source, edge.target) for edge in _MAIN_TOPOLOGY.edges],
    }


def describe_evidence_graph_topology() -> dict[str, Any]:
    return {
        "entry_point": _EVIDENCE_TOPOLOGY.entry_point,
        "terminal": _EVIDENCE_TOPOLOGY.terminal,
        "nodes": list(_EVIDENCE_TOPOLOGY.nodes),
        "edges": [tuple(edge) for edge in _EVIDENCE_TOPOLOGY.edges],
    }


def describe_understand_turn_graph_topology() -> dict[str, Any]:
    return {
        "entry_point": _UNDERSTAND_TOPOLOGY.entry_point,
        "terminal": _UNDERSTAND_TOPOLOGY.terminal,
        "nodes": list(_UNDERSTAND_TOPOLOGY.nodes),
        "edges": [tuple(edge) for edge in _UNDERSTAND_TOPOLOGY.edges],
    }


def describe_plan_execute_graph_topology() -> dict[str, Any]:
    return {
        "entry_point": _PLAN_EXECUTE_TOPOLOGY.entry_point,
        "terminal": _PLAN_EXECUTE_TOPOLOGY.terminal,
        "nodes": list(_PLAN_EXECUTE_TOPOLOGY.nodes),
        "edges": [tuple(edge) for edge in _PLAN_EXECUTE_TOPOLOGY.edges],
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


def export_evidence_graph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _EVIDENCE_TOPOLOGY.edges:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)


def export_understand_turn_graph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _UNDERSTAND_TOPOLOGY.edges:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)


def export_langgraph_mermaid() -> str:
    return export_main_graph_mermaid()


def export_plan_execute_graph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _PLAN_EXECUTE_TOPOLOGY.edges:
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
