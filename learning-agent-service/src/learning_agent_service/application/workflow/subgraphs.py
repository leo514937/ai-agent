from __future__ import annotations

from datetime import datetime, timezone

from ...domain.contracts import NormalizedToolResult, PlanExecutionSummary, RagResult, ToolExecutionResult
from ...domain.enums import RagStatus, ToolExecutionStatus
from ...domain.state import GraphState
from ..routing import can_enter_retrieval, can_enter_tool, should_run_tool as routing_should_run_tool, _update_phase3_trace
from .services import PlanExecuteSubgraphServices, RagSubgraphServices, ToolSubgraphServices, UnderstandTurnServices


_RETRIEVAL_ACTIONS = {"rag_retrieval", "rag_plus_tool"}
_TOOL_ACTIONS = {"tool_call", "rag_plus_tool"}
_DIRECT_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject"}


def _status_text(value) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    return text or None


def _route_decision_for_turn(turn) -> str:
    routing = getattr(turn, "routing_decision", None)
    if routing is not None:
        return str(routing.required_action or "no_op")
    if turn.execution_mode == "plan_execute":
        return "plan_execute"
    return "no_op"


def route_after_load_context(state: GraphState) -> str:
    routing = state["turn"].routing_decision
    if routing is not None and (routing.blocked or str(routing.required_action).strip().lower() in _DIRECT_ACTIONS):
        return "compose_answer"
    return "understand_turn"


def route_gate(state: GraphState) -> GraphState:
    turn = state["turn"]
    runtime = state["runtime"]
    routing = getattr(turn, "routing_decision", None)
    branch = route_decider(state)
    effective_action_map = {
        "recommendation": "rag_plus_tool",
        "tool": "tool_call",
        "rag_plus_tool": "rag_plus_tool",
        "rag": "rag_retrieval",
        "direct": "direct_answer",
        "clarify": "clarify",
    }
    effective_action = effective_action_map.get(branch, str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else None)
    if routing is not None and effective_action and effective_action != str(getattr(routing, "required_action", "") or "").strip().lower():
        routing = routing.model_copy(
            update={
                "required_action": effective_action,
                "blocked": False,
                "blocked_reason": None,
                "should_retrieve": effective_action in {"rag_retrieval", "rag_plus_tool"},
                "should_call_tool": effective_action in {"tool_call", "rag_plus_tool"},
                "should_use_memory": effective_action not in {"clarify", "reject", "no_op"},
                "should_persist_memory": effective_action not in {"clarify", "reject", "no_op"},
                "should_vectorize_memory": effective_action not in {"clarify", "reject", "no_op"},
                "should_emit_retrieval_events": effective_action in {"rag_retrieval", "rag_plus_tool"},
            }
        )
        turn_extra = dict(turn.extra)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        state["turn"] = turn.model_copy(update={"routing_decision": routing, "extra": turn_extra})
        turn = state["turn"]
    required_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else None
    route_candidate = str(getattr(routing, "route_candidate", "") or "").strip().lower() if routing is not None else None
    route_reason = str(getattr(routing, "route_reason", "") or "").strip() if routing is not None else ""
    fallback_reason = _route_decision_for_turn(turn)
    gate_trace = {
        "branch": branch,
        "required_action": required_action,
        "route_candidate": route_candidate,
        "route_reason": route_reason or None,
    }

    turn_extra = dict(turn.extra)
    turn_extra["route_gate"] = gate_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["route_gate"] = gate_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})

    state = _mark_stage(
        state,
        "route_gate",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=gate_trace["route_reason"] or fallback_reason,
        detail=gate_trace,
    )
    return state


def _stage_entry(stage: str, status: str, *, route_decision: str | None = None, route_reason: str | None = None, detail=None):
    return {
        "stage": stage,
        "status": status,
        "route_decision": route_decision,
        "route_reason": route_reason,
        "detail": dict(detail or {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _mark_stage(state: GraphState, stage: str, status: str, *, route_decision: str | None = None, route_reason: str | None = None, detail=None) -> GraphState:
    turn = state["turn"]
    routing = getattr(turn, "routing_decision", None)
    trace_route_decision = route_decision or (routing.required_action if routing is not None else None)
    trace_route_reason = route_reason or (routing.route_reason if routing is not None else trace_route_decision)
    timeline = list(turn.stage_timeline)
    turn = turn.model_copy(
        update={
            "current_stage": stage,
            "stage_status": status,
            "stage_timeline": timeline + [_stage_entry(stage, status, route_decision=trace_route_decision, route_reason=trace_route_reason, detail=detail)],
        }
    )
    state["turn"] = turn
    return state


def _ensure_rag_result(state: GraphState) -> GraphState:
    turn = state["turn"]
    if turn.rag_result is None:
        status = RagStatus.EMPTY if turn.evidence_pack is None else RagStatus.OK
        state["turn"] = turn.model_copy(
            update={
                "rag_result": RagResult(
                    status=status,
                    evidence_pack=turn.evidence_pack,
                    citations=list(turn.citations),
                )
            }
        )
    return state


def _ensure_tool_result(state: GraphState) -> GraphState:
    turn = state["turn"]
    if turn.tool_result is None:
        selection = turn.tool_plan
        tool_name = selection.tool_name if selection and selection.tool_name else "no_tool_mapping"
        planner_meta = dict(turn.extra.get("tool_planner", {}) or {})
        failure_category = None
        planning_state = planner_meta.get("planning_state")
        selection_source = planner_meta.get("selection_source")
        if selection is None:
            failure_category = "no_tool_mapping"
        elif not selection.should_execute:
            failure_category = selection.reason or planning_state or "no_tool_mapping"
        state["turn"] = turn.model_copy(
            update={
                "tool_result": NormalizedToolResult(
                    status=ToolExecutionStatus.SKIPPED,
                    tool_name=tool_name,
                    approval_required=bool(getattr(selection, "approval_required", False) or planner_meta.get("approval_required", False)),
                    approval_status=getattr(selection, "approval_status", None) if selection is not None else planner_meta.get("approval_status"),
                    approval_request=dict(getattr(selection, "approval_request", {}) or planner_meta.get("approval_request", {}) or {}),
                    extra={
                        "failure_category": failure_category,
                        "planning_state": planning_state,
                        "selection_source": selection_source,
                        "tool_plan_state": planning_state or failure_category or "no_tool_mapping",
                    },
                )
            }
        )
    return state


def _ensure_raw_tool_result(state: GraphState) -> GraphState:
    turn = state["turn"]
    if turn.raw_tool_result is None and turn.tool_plan is not None:
        state["turn"] = turn.model_copy(
            update={
                "raw_tool_result": ToolExecutionResult(
                    status=ToolExecutionStatus.SKIPPED,
                    tool_name=turn.tool_plan.tool_name,
                )
            }
        )
    return state


def _tool_stage_detail(turn) -> dict[str, object]:
    selection = turn.tool_plan
    raw_result = turn.raw_tool_result
    normalized_result = turn.tool_result
    planner_meta = dict(turn.extra.get("tool_planner", {}) or {})
    selection_meta = dict(selection.extra or {}) if selection is not None else planner_meta
    routing = getattr(turn, "routing_decision", None)
    detail: dict[str, object] = {
        "decision": str(routing.required_action if routing is not None else "no_op"),
        "intent": turn.intent.value if turn.intent else None,
        "tool_name": selection.tool_name if selection else None,
        "should_execute": bool(selection.should_execute) if selection is not None else False,
        "approval_required": bool(selection.approval_required) if selection is not None else False,
        "approval_status": selection.approval_status if selection is not None else None,
        "tool_reason": selection.reason if selection is not None else None,
        "tool_call_id": selection_meta.get("tool_call_id"),
        "resolved_intent": selection_meta.get("resolved_intent"),
        "planning_state": selection_meta.get("planning_state"),
        "selection_source": selection_meta.get("selection_source"),
    }
    if selection is None:
        detail["tool_plan_state"] = planner_meta.get("planning_state") or "no_tool_mapping"
        if planner_meta.get("reason"):
            detail["tool_reason"] = planner_meta.get("reason")
        return detail
    if not selection.should_execute:
        detail["tool_plan_state"] = selection.reason or selection_meta.get("planning_state") or "no_tool_mapping"
        return detail
    approval_status = _status_text(selection.approval_status)
    if selection.approval_required and approval_status not in {None, "approved"}:
        detail["tool_plan_state"] = approval_status or "pending_approval"
        return detail
    if raw_result is not None:
        detail["tool_plan_state"] = _status_text(raw_result.status) or "executed"
        detail["tool_execution_status"] = _status_text(raw_result.status)
    if normalized_result is not None:
        detail["tool_result_status"] = _status_text(normalized_result.status)
    if "tool_plan_state" not in detail:
        detail["tool_plan_state"] = "executed"
    return detail


def run_understand_turn(state: GraphState, services: UnderstandTurnServices) -> GraphState:
    state = services.parse_intent_slots(state)
    state = services.resolve_reference(state)
    state = services.ambiguity_check(state)
    state = services.rag_gate(state)
    rag_gate = dict(state["turn"].extra.get("rag_gate", {}))
    routing = state["turn"].routing_decision
    if routing is not None and routing.blocked:
        state = _mark_stage(
            state,
            "understand",
            "blocked",
            route_decision=_route_decision_for_turn(state["turn"]),
            route_reason=str(routing.blocked_reason or rag_gate.get("reason") or "routing_blocked"),
            detail=rag_gate or {"blocked_reason": routing.blocked_reason},
        )
        return state
    if rag_gate and not bool(rag_gate.get("allowed", True)):
        state = _mark_stage(state, "understand", "blocked", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(rag_gate.get("reason") or "rag_gate_blocked"), detail=rag_gate)
        return state
    state = _mark_stage(
        state,
        "understand",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str((state["turn"].routing_decision.route_reason if state["turn"].routing_decision else None) or state["turn"].extra.get("route_reason") or "routing"),
        detail={
            "decision": _route_decision_for_turn(state["turn"]),
            "intent": state["turn"].intent.value if state["turn"].intent else None,
            "route_candidate": state["turn"].extra.get("route_candidate"),
            "route_candidates": list(state["turn"].extra.get("route_candidates") or []),
            "direct_response_kind": state["turn"].extra.get("direct_response_kind"),
        },
    )
    routing = state["turn"].routing_decision
    if routing is not None and str(routing.required_action).strip().lower() in {"clarify", "reject", "direct_answer", "memory_update", "no_op"}:
        return state
    if routing is not None and str(routing.required_action).strip().lower() in _RETRIEVAL_ACTIONS and state["turn"].retrieval_plan is None and can_enter_retrieval(state).allowed:
        state = services.rewrite_query(state)
    return state


def run_rag_subgraph(state: GraphState, services: RagSubgraphServices) -> GraphState:
    if not can_enter_retrieval(state).allowed:
        return _ensure_rag_result(state)

    state = _mark_stage(state, "rag", "running", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])))
    state = services.hybrid_retrieve(state)
    state = services.evaluate_evidence(state)
    state = services.citation_builder(state)
    state = _mark_stage(state, "rag", "completed", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])), detail={"evidence_count": len(state["turn"].evidence_pack.items) if state["turn"].evidence_pack else 0})
    return _ensure_rag_result(state)


def run_recommendation_subgraph(state: GraphState, services: RagSubgraphServices) -> GraphState:
    turn = state["turn"]
    runtime = state["runtime"]
    turn_extra = dict(turn.extra)
    turn_extra["recommendation_mode"] = True
    turn_extra["route_gate"] = {
        **dict(turn_extra.get("route_gate", {}) or {}),
        "branch": "recommendation",
    }
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["recommendation_mode"] = True
    runtime_metrics["rag_mode"] = "recommendation_rag"
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})

    state = _mark_stage(
        state,
        "recommendation",
        "running",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail={"branch": "recommendation"},
    )
    state = run_rag_subgraph(state, services)
    state = _mark_stage(
        state,
        "recommendation",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail={"branch": "recommendation"},
    )
    return state


def run_tool_subgraph(state: GraphState, services: ToolSubgraphServices) -> GraphState:
    state = _mark_stage(
        state,
        "tool",
        "running",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail={
            "decision": _route_decision_for_turn(state["turn"]),
            "intent": state["turn"].intent.value if state["turn"].intent else None,
        },
    )
    state = services.tool_planner(state)
    selection = state["turn"].tool_plan
    if selection is None or not selection.should_execute:
        state = _ensure_raw_tool_result(state)
    else:
        state = services.tool_executor(state)
        state = _ensure_raw_tool_result(state)

    state = services.tool_result_normalizer(state)
    state = _mark_stage(
        state,
        "tool",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
        detail=_tool_stage_detail(state["turn"]),
    )
    return _ensure_tool_result(state)


def run_plan_execute_subgraph(state: GraphState, services: PlanExecuteSubgraphServices) -> GraphState:
    turn = state["turn"]
    if turn.task_plan is None and turn.execution_mode != "plan_execute" and not (
        turn.execution_mode == "auto"
        and (
            turn.task_complexity == "complex"
            or turn.need_human_approval
            or turn.risk_level in {"medium", "high"}
        )
    ):
        return state

    state = _mark_stage(state, "plan_execute", "running", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])))
    state = services.plan_planner(state)
    state = _ensure_plan_progress_state(state)
    state = services.plan_validator(state)
    state = services.step_executor(state)
    state = _ensure_plan_progress_state(state)
    state = services.progress_checker(state)
    state = services.plan_reviewer(state)

    if state["turn"].need_human_approval:
        state = services.human_approval_stub(state)
        state = _mark_stage(state, "plan_execute", "blocked", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].replan_reason or state["turn"].approval_request.get("reason") or "need_human_approval"))
        summary = state["turn"].final_task_summary
        state = _update_phase3_trace(
            state,
            task_plan_execution_status="blocked",
            task_plan_completed_steps=getattr(summary, "completed_steps", 0) if summary is not None else 0,
            task_plan_total_steps=getattr(summary, "total_steps", 0) if summary is not None else len(state["turn"].plan),
            task_plan_final_decision=getattr(summary, "final_decision", None) if summary is not None else None,
            task_plan_step_results=len(state["turn"].step_results),
        )
        return _ensure_plan_summary(state)

    if state["turn"].need_replan:
        state = services.replanner(state)
        state = _ensure_plan_progress_state(state)
        if state["turn"].need_replan:
            state = services.plan_reviewer(state)
            state = _mark_stage(state, "plan_execute", "blocked", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].replan_reason or "need_replan"))
            summary = state["turn"].final_task_summary
            state = _update_phase3_trace(
                state,
                task_plan_execution_status="blocked",
                task_plan_completed_steps=getattr(summary, "completed_steps", 0) if summary is not None else 0,
                task_plan_total_steps=getattr(summary, "total_steps", 0) if summary is not None else len(state["turn"].plan),
                task_plan_final_decision=getattr(summary, "final_decision", None) if summary is not None else None,
                task_plan_step_results=len(state["turn"].step_results),
            )
            return _ensure_plan_summary(state)
        state = services.step_executor(state)
        state = _ensure_plan_progress_state(state)
        state = services.progress_checker(state)
        state = services.plan_reviewer(state)
        if state["turn"].need_human_approval:
            state = services.human_approval_stub(state)
            state = _mark_stage(state, "plan_execute", "blocked", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].replan_reason or state["turn"].approval_request.get("reason") or "need_human_approval"))
            summary = state["turn"].final_task_summary
            state = _update_phase3_trace(
                state,
                task_plan_execution_status="blocked",
                task_plan_completed_steps=getattr(summary, "completed_steps", 0) if summary is not None else 0,
                task_plan_total_steps=getattr(summary, "total_steps", 0) if summary is not None else len(state["turn"].plan),
                task_plan_final_decision=getattr(summary, "final_decision", None) if summary is not None else None,
                task_plan_step_results=len(state["turn"].step_results),
            )
            return _ensure_plan_summary(state)

    state = _mark_stage(state, "plan_execute", "completed", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])))
    summary = state["turn"].final_task_summary
    state = _update_phase3_trace(
        state,
        task_plan_execution_status=getattr(summary, "status", "completed") if summary is not None else "completed",
        task_plan_completed_steps=getattr(summary, "completed_steps", 0) if summary is not None else len([result for result in state["turn"].step_results if result.status == "success"]),
        task_plan_total_steps=getattr(summary, "total_steps", 0) if summary is not None else len(state["turn"].plan),
        task_plan_final_decision=getattr(summary, "final_decision", None) if summary is not None else state["turn"].final_answer,
        task_plan_step_results=len(state["turn"].step_results),
    )
    return _ensure_plan_summary(state)


def should_clarify(state: GraphState) -> bool:
    routing = state["turn"].routing_decision
    if routing is not None:
        return str(routing.required_action).strip().lower() == "clarify"
    return False


def should_run_rag(state: GraphState) -> bool:
    eligibility = can_enter_retrieval(state)
    return bool(eligibility.allowed)


def should_run_tools(state: GraphState) -> bool:
    routing = state["turn"].routing_decision
    if routing is not None:
        return routing_should_run_tool(routing)
    return False


def should_run_plan_execute(state: GraphState) -> bool:
    turn = state["turn"]
    return turn.task_plan is not None or turn.execution_mode == "plan_execute" or (
        turn.execution_mode == "auto"
        and (
            turn.task_complexity == "complex"
            or turn.need_human_approval
            or turn.risk_level in {"medium", "high"}
        )
    )


def route_after_understand(state: GraphState) -> str:
    if should_run_plan_execute(state):
        return "plan_execute_subgraph"
    return "route_gate"


def route_decider(state: GraphState) -> str:
    turn = state["turn"]
    routing = getattr(turn, "routing_decision", None)
    if routing is None:
        return "direct"

    action = str(routing.required_action or "").strip().lower()
    route_candidate = str(getattr(routing, "route_candidate", "") or "").strip().lower()
    extra = dict(getattr(turn, "extra", {}) or {})
    route_review = extra.get("route_review_decision")
    if not isinstance(route_review, dict):
        route_review = dict(getattr(routing, "extra", {}) or {}).get("route_review_decision")
        if isinstance(route_review, dict):
            route_review = dict(route_review)
        else:
            route_review = {}

    effective_action = action
    if route_review:
        current_action = str(route_review.get("current_action") or "").strip().lower()
        recommended_action = str(route_review.get("recommended_action") or "").strip().lower()
        if current_action in {"tool_call", "rag_plus_tool", "rag_retrieval", "direct_answer"}:
            if current_action == "rag_retrieval" and recommended_action in {"tool_call", "rag_plus_tool", "rag_retrieval", "direct_answer"}:
                effective_action = recommended_action
            else:
                effective_action = current_action
        elif current_action == "clarify" and recommended_action in {"tool_call", "rag_plus_tool", "rag_retrieval", "direct_answer"}:
            effective_action = recommended_action

    recommendation_mode = bool(
        extra.get("recommendation_mode")
        or effective_action == "local_life_recommend"
        or route_candidate in {"recommendation"}
        or (route_candidate.startswith("local_life.") and "recommend" in route_candidate)
    )

    if routing.blocked and effective_action == action:
        return "clarify"
    if recommendation_mode:
        return "recommendation"
    if effective_action == "clarify":
        return "clarify"
    if effective_action == "tool_call":
        return "tool"
    if effective_action == "rag_plus_tool":
        return "rag_plus_tool"
    if effective_action == "rag_retrieval":
        return "rag"
    if effective_action in {"direct_answer", "memory_update", "no_op", "reject"}:
        return "direct"
    return "direct"


def route_after_rag(state: GraphState) -> str:
    routing = state["turn"].routing_decision
    if routing is not None:
        if str(routing.required_action).strip().lower() == "rag_plus_tool" and can_enter_tool(state).allowed:
            return "tool_subgraph"
        return "compose_answer"
    return "compose_answer"


def _ensure_plan_progress_state(state: GraphState) -> GraphState:
    turn = state["turn"]
    if turn.current_step is None and turn.plan:
        index = min(max(turn.current_step_index, 0), len(turn.plan) - 1)
        state["turn"] = turn.model_copy(
            update={
                "current_step_index": index,
                "current_step": turn.plan[index],
            }
        )
    return state


def _ensure_plan_summary(state: GraphState) -> GraphState:
    turn = state["turn"]
    if turn.final_task_summary is not None:
        return state
    if not turn.plan and not turn.step_results and not turn.need_human_approval and not turn.approval_request:
        return state

    completed_steps = len([item for item in turn.step_results if item.status == "success"])
    total_steps = len(turn.plan) if turn.plan else len(turn.step_results)
    if turn.need_human_approval:
        status = "need_approval"
    elif turn.need_replan and completed_steps < total_steps:
        status = "partial" if completed_steps > 0 else "failed"
    elif total_steps and completed_steps >= total_steps:
        status = "completed"
    elif completed_steps > 0:
        status = "partial"
    else:
        status = "failed"

    key_findings: list[str] = []
    for result in turn.step_results:
        key_findings.extend(result.observations[:1])

    summary = PlanExecutionSummary(
        status=status,
        completed_steps=completed_steps,
        total_steps=total_steps,
        key_findings=key_findings[:5],
        final_decision=turn.replan_reason or turn.final_answer,
    )
    state["turn"] = turn.model_copy(update={"final_task_summary": summary})
    return state
