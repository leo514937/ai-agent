from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...domain.contracts import (
    NormalizedToolResult,
    PlanExecutionSummary,
    RagResult,
    ToolExecutionResult,
    RoutingContract,
)
from ...domain.enums import RagStatus, ToolExecutionStatus
from ...domain.state import GraphState
from ..router import _update_phase3_trace, can_enter_retrieval, can_enter_tool
from ..router import route_execution_mode
from ..router import should_run_tool as routing_should_run_tool
from .state import append_runtime_error as _append_state_runtime_error
from .state import append_stage_timeline_entry as _append_stage_timeline_entry
from .services import (
    PlanExecuteSubgraphServices,
    RagSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
)

try:
    from langgraph.types import Command
except Exception:  # pragma: no cover - optional dependency path
    @dataclass
    class Command:
        update: Any
        goto: str

if not hasattr(Command, "__getitem__"):
    def _command_getitem(self, key: str):
        update = getattr(self, "update", None)
        if isinstance(update, dict):
            return update[key]
        raise TypeError(f"{type(self).__name__!s} does not support item access")

    Command.__getitem__ = _command_getitem  # type: ignore[attr-defined]

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
    if routing is not None and routing.blocked:
        return "compose_answer"
    return "understand_turn"


def run_load_context_node(state: GraphState, load_context_fn) -> Command:
    state = load_context_fn(state)
    target = route_after_load_context(state)
    return Command(update=state, goto=target)


def route_gate(state: GraphState) -> Command:
    turn = state["turn"]
    runtime = state["runtime"]
    routing = getattr(turn, "routing_decision", None)
    execution_mode_result = route_execution_mode(routing) if routing is not None else None
    execution_mode = execution_mode_result.execution_mode if execution_mode_result is not None else "simple"
    execution_mode_reason = execution_mode_result.reason if execution_mode_result is not None else "no_routing_decision"
    execution_mode_signals = list(execution_mode_result.signals) if execution_mode_result is not None else ["missing_routing"]
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
    if routing is not None and effective_action:
        current_action = str(getattr(routing, "required_action", "") or "").strip().lower()
        routing_update = {
            "required_action": effective_action,
            "should_retrieve": effective_action in {"rag_retrieval", "rag_plus_tool"},
            "should_call_tool": effective_action in {"tool_call", "rag_plus_tool"},
            "should_use_memory": effective_action not in {"clarify", "reject", "no_op"},
            "should_persist_memory": effective_action not in {"clarify", "reject", "no_op"},
            "should_vectorize_memory": effective_action not in {"clarify", "reject", "no_op"},
            "should_emit_retrieval_events": effective_action in {"rag_retrieval", "rag_plus_tool"},
        }
        if effective_action != current_action:
            routing_update["blocked"] = False
            routing_update["blocked_reason"] = None
        routing = routing.model_copy(update=routing_update)
    if routing is not None:
        routing_extra = dict(getattr(routing, "extra", {}) or {})
        routing_extra["execution_mode"] = execution_mode
        routing_extra["execution_mode_reason"] = execution_mode_reason
        routing_extra["execution_mode_signals"] = execution_mode_signals
        routing = routing.model_copy(update={"execution_mode": execution_mode, "extra": routing_extra})
        turn_extra = dict(turn.extra)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        turn_extra["execution_mode"] = execution_mode
        turn_extra["execution_mode_reason"] = execution_mode_reason
        turn_extra["execution_mode_signals"] = execution_mode_signals
        state["turn"] = turn.model_copy(update={"routing_decision": routing, "extra": turn_extra})
        turn = state["turn"]
    if branch == "complex" and str(getattr(turn, "execution_mode", "") or "").strip().lower() != "plan_execute":
        # Normalize the complex routing branch into the plan executor's execution mode.
        state["turn"] = turn.model_copy(
            update={
                "execution_mode": "plan_execute",
                "task_complexity": "complex",
            }
        )
        turn = state["turn"]
    required_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else None
    route_candidate = str(getattr(routing, "route_candidate", "") or "").strip().lower() if routing is not None else None
    route_reason = str(getattr(routing, "route_reason", "") or "").strip() if routing is not None else ""
    fallback_reason = _route_decision_for_turn(turn)
    gate_trace = {
        "branch": branch,
        "execution_mode": execution_mode,
        "execution_mode_reason": execution_mode_reason,
        "execution_mode_signals": execution_mode_signals,
        "required_action": required_action,
        "route_candidate": route_candidate,
        "route_reason": route_reason or None,
    }

    from collections.abc import Mapping
    routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}
    raw_req_facets = routing_extra.get("required_facets") or []
    required_facets = []
    for f in raw_req_facets:
        if isinstance(f, Mapping):
            name = str(f.get("name") or "").strip()
        else:
            name = str(f or "").strip()
        if name and name not in required_facets:
            required_facets.append(name)
            
    raw_opt_facets = routing_extra.get("optional_facets") or []
    optional_facets = []
    for f in raw_opt_facets:
        if isinstance(f, Mapping):
            name = f.get("name")
        else:
            name = f
        name_str = str(name or "").strip()
        if name_str and name_str not in optional_facets:
            optional_facets.append(name_str)

    target_shop_id = None
    turn_extra = dict(turn.extra)
    target_shop_payload = turn_extra.get("target_shop")
    if isinstance(target_shop_payload, Mapping):
        target_shop_id = target_shop_payload.get("shop_id")
    if target_shop_id is None:
        target_shop_id = turn_extra.get("selected_shop_id") or turn_extra.get("target_shop_id")
    if target_shop_id is None and isinstance(routing_extra.get("route_review_decision"), Mapping):
        route_review = routing_extra.get("route_review_decision")
        target_shop_id = route_review.get("resolved_shop_id")
        if target_shop_id is None and isinstance(route_review.get("execution_requirements"), Mapping):
            target_shop_id = route_review.get("execution_requirements").get("resolved_shop_id")
    if target_shop_id is not None:
        try:
            target_shop_id = int(target_shop_id)
        except (ValueError, TypeError):
            target_shop_id = None

    candidate_shop_ids = []
    raw_candidates = turn_extra.get("candidate_shop_ids") or routing_extra.get("candidate_shop_ids") or []
    for cid in raw_candidates:
        try:
            candidate_shop_ids.append(int(cid))
        except (ValueError, TypeError):
            pass

    recommendation_mode = (branch == "recommendation")
    single_shop_mode = not recommendation_mode and (target_shop_id is not None or bool(turn_extra.get("explicit_query_shop") or turn_extra.get("target_shop_name")))

    raw_query = str(getattr(turn, "raw_query", "") or "")
    compact_query = raw_query.replace(" ", "")
    inferred_coupon = any(token in compact_query for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
    inferred_open = any(token in compact_query for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
    inferred_distance = any(token in compact_query for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
    
    user_focused_facets = [f for f in required_facets if f not in ("location", "category")]
    
    allowed_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"]
    forbidden_facets = []
    
    if len(user_focused_facets) == 1 and user_focused_facets[0] == "coupon":
        allowed_facets = ["coupon"]
        forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "open_status", "distance_eta", "price"]
    elif len(user_focused_facets) == 1 and user_focused_facets[0] == "open_status":
        allowed_facets = ["open_status"]
        forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "distance_eta", "price"]
    elif len(user_focused_facets) == 1 and user_focused_facets[0] == "distance_eta":
        allowed_facets = ["distance_eta", "distance"]
        forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "price"]
    elif inferred_coupon and not inferred_open and not inferred_distance:
        allowed_facets = ["coupon"]
        forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "open_status", "distance_eta", "price"]
    elif inferred_open and not inferred_coupon and not inferred_distance:
        allowed_facets = ["open_status"]
        forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "distance_eta", "price"]
    elif inferred_distance and not inferred_coupon and not inferred_open:
        allowed_facets = ["distance_eta", "distance"]
        forbidden_facets = ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "price"]
    elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
        if single_shop_mode:
            allowed_facets = ["environment", "taste", "service", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = ["recommendation"]
        else:
            allowed_facets = ["environment", "taste", "service", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = []
    elif branch == "clarify":
        allowed_facets = []
        forbidden_facets = ["environment", "taste", "service", "recommendation", "coupon", "open_status", "distance_eta", "price"]
    elif len([name for name in user_focused_facets if name in {"coupon", "open_status", "distance_eta"}]) > 1:
        if recommendation_mode:
            allowed_facets = ["coupon", "open_status", "distance_eta", "distance", "price", "scene_fit", "recommendation_reason", "shop_detail"]
            forbidden_facets = []
        else:
            allowed_facets = ["environment", "taste", "service", "coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"]
            forbidden_facets = ["recommendation"]

    compose_allowed_facets = [f for f in allowed_facets if f not in forbidden_facets]

    rag_allowed = bool(getattr(routing, "should_retrieve", True)) if routing is not None else True
    tool_allowed = bool(getattr(routing, "should_call_tool", True)) if routing is not None else True

    routing_contract = RoutingContract(
        required_action=effective_action or "no_op",
        required_facets=required_facets,
        optional_facets=optional_facets,
        forbidden_facets=forbidden_facets,
        target_shop_id=target_shop_id,
        candidate_shop_ids=candidate_shop_ids,
        single_shop_mode=single_shop_mode,
        recommendation_mode=recommendation_mode,
        rag_allowed=rag_allowed,
        tool_allowed=tool_allowed,
        compose_allowed_facets=compose_allowed_facets,
        input_invalid=bool(getattr(routing, "blocked", False)) if routing is not None else False,
        need_clarify=(effective_action == "clarify"),
        clarify_reason=str(getattr(routing, "blocked_reason", "") or "") if routing is not None else None,
    )

    turn_extra = dict(turn.extra)
    turn_extra["route_gate"] = gate_trace
    turn_extra["routing_contract"] = routing_contract.model_dump(mode="json")
    state["turn"] = turn.model_copy(update={
        "routing_contract": routing_contract,
        "extra": turn_extra
    })

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_metrics["route_gate"] = gate_trace
    runtime_metrics["execution_mode"] = execution_mode
    runtime_metrics["execution_mode_reason"] = execution_mode_reason
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})

    state = _mark_stage(
        state,
        "route_gate",
        "completed",
        route_decision=_route_decision_for_turn(state["turn"]),
        route_reason=gate_trace["route_reason"] or fallback_reason,
        detail=gate_trace,
    )
    target_map = {
        "clarify": "compose_answer",
        "tool": "tool_subgraph",
        "rag": "rag_subgraph",
        "rag_plus_tool": "rag_subgraph",
        "recommendation": "recommendation_subgraph",
        "direct": "compose_answer",
    }
    if execution_mode == "clarify":
        target = "compose_answer"
    elif execution_mode == "complex":
        target = "plan_execute_subgraph"
    else:
        target = target_map.get(branch, "compose_answer")
    return Command(update=state, goto=target)


def run_rule_review_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = dict(turn.extra)
    turn_extra["rule_review"] = {
        "reviewed": True,
        "current_action": str(getattr(turn.routing_decision, "required_action", "") or "").strip().lower() if getattr(turn, "routing_decision", None) is not None else None,
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


def run_merge_rank_node(state: GraphState) -> GraphState:
    turn = state["turn"]
    turn_extra = dict(turn.extra)
    ranked_candidates = list(turn_extra.get("ranked_candidates") or [])
    evidence_claims = list(turn_extra.get("evidence_claims") or [])

    def _score(item: Any) -> float:
        if isinstance(item, Mapping):
            return float(item.get("score", 0.0) or 0.0)
        return float(getattr(item, "score", 0.0) or 0.0)

    ranked_candidates = sorted(ranked_candidates, key=_score, reverse=True)
    evidence_claims = sorted(evidence_claims, key=_score, reverse=True)
    turn_extra["ranked_candidates"] = ranked_candidates
    turn_extra["evidence_claims"] = evidence_claims
    turn_extra["merge_rank_node"] = {
        "reviewed": True,
        "ranked_candidate_count": len(ranked_candidates),
        "evidence_claim_count": len(evidence_claims),
        "top_candidate": (
            ranked_candidates[0].get("name") if ranked_candidates and isinstance(ranked_candidates[0], Mapping)
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


def run_contract_review_node(state: GraphState) -> GraphState:
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
    entry = _stage_entry(stage, status, route_decision=trace_route_decision, route_reason=trace_route_reason, detail=detail)
    state = _append_stage_timeline_entry(state, entry)
    state["turn"] = state["turn"].model_copy(update={"current_stage": stage, "stage_status": status})
    return state


def _ensure_rag_result(state: GraphState) -> GraphState:
    turn = state["turn"]
    if turn.rag_result is None:
        is_empty = (
            turn.evidence_pack is None 
            or not getattr(turn.evidence_pack, "items", [])
        )
        status = RagStatus.EMPTY if is_empty else RagStatus.OK
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
                    degraded_to=None,
                    error=None,
                    approval_status=None,
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


def run_understand_turn(state: GraphState, services: UnderstandTurnServices) -> Command:
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
        target = route_after_understand(state)
        return Command(update=state, goto=target)
    if rag_gate and not bool(rag_gate.get("allowed", True)):
        state = _mark_stage(state, "understand", "blocked", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(rag_gate.get("reason") or "rag_gate_blocked"), detail=rag_gate)
        target = route_after_understand(state)
        return Command(update=state, goto=target)
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
        target = route_after_understand(state)
        return Command(update=state, goto=target)
    if routing is not None and str(routing.required_action).strip().lower() in _RETRIEVAL_ACTIONS and state["turn"].retrieval_plan is None and can_enter_retrieval(state).allowed:
        state = services.rewrite_query(state)
    target = route_after_understand(state)
    return Command(update=state, goto=target)


def run_rag_subgraph(state: GraphState, services: RagSubgraphServices) -> Command:
    try:
        from .graphs import build_rag_graph
        compiled_graph = build_rag_graph(services)
    except Exception:
        compiled_graph = None
    if compiled_graph is not None:
        from ...domain.state import clone_graph_state

        try:
            compiled_state = compiled_graph.invoke(clone_graph_state(state))
            target = route_after_rag_graph(compiled_state)
            return Command(update=compiled_state, goto=target)
        except Exception:
            compiled_graph = None

    contract = state["turn"].routing_contract
    rag_allowed = contract.rag_allowed if contract is not None else can_enter_retrieval(state).allowed
    if not rag_allowed:
        state = _ensure_rag_result(state)
        target = route_after_rag(state)
        return Command(update=state, goto=target)

    state = _mark_stage(state, "rag", "running", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])))
    try:
        state = services.hybrid_retrieve(state)
        state = services.evaluate_evidence(state)
        state = _filter_evidence_by_contract(state)
        state = services.citation_builder(state)
        state = _mark_stage(state, "rag", "completed", route_decision=_route_decision_for_turn(state["turn"]), route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])), detail={"evidence_count": len(state["turn"].evidence_pack.items) if state["turn"].evidence_pack else 0})
    except Exception as exc:
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
            is_terminal=False
        )
        
        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["retrieval_degraded"] = True
        metrics["retrieval_error"] = str(exc)
        state = _append_state_runtime_error(state, err)
        state["runtime"] = state["runtime"].model_copy(update={
            "degrade_to": "retrieval_degraded",
            "metrics": metrics
        })
        
        turn = state["turn"]
        degraded_pack = EvidencePack(
            items=[],
            evidence_status="DEGRADED",
            extra={"degrade_reason": str(exc)}
        )
        state["turn"] = turn.model_copy(update={
            "evidence_pack": degraded_pack,
            "citations": [],
            "rag_result": RagResult(
                status=RagStatus.DEGRADED,
                evidence_pack=degraded_pack,
                citations=[],
                metrics={"error": str(exc)},
                extra={"degraded": True}
            )
        })
        state = _mark_stage(state, "rag", "failed", route_decision=_route_decision_for_turn(state["turn"]), route_reason=f"retrieval_degraded: {exc}")

    state = _ensure_rag_result(state)
    target = route_after_rag(state)
    return Command(update=state, goto=target)


def run_recommendation_subgraph(state: GraphState, services: RagSubgraphServices) -> GraphState:
    try:
        from .graphs import build_recommendation_graph
        compiled_graph = build_recommendation_graph(services)
    except Exception:
        compiled_graph = None
    if compiled_graph is not None:
        from ...domain.state import clone_graph_state
        result = compiled_graph.invoke(clone_graph_state(state))
        if not list(result["turn"].stage_timeline or []):
            if not tool_allowed:
                result = _mark_stage(
                    result,
                    "tool",
                    "completed",
                    route_decision=_route_decision_for_turn(result["turn"]),
                    route_reason=str(result["turn"].extra.get("route_reason") or _route_decision_for_turn(result["turn"])),
                    detail={"decision": _route_decision_for_turn(result["turn"]), "intent": result["turn"].intent.value if result["turn"].intent else None, "tool_allowed": False},
                )
        return result

    from .graphs import _execute_recommendation_pipeline, _finalize_recommendation, _prepare_recommendation

    state = _prepare_recommendation(state)
    state = _execute_recommendation_pipeline(state, services)
    state = _finalize_recommendation(state)
    return state


def run_tool_subgraph(state: GraphState, services: ToolSubgraphServices) -> GraphState:
    selection = getattr(state["turn"], "tool_plan", None)
    try:
        from .graphs import build_tool_graph
        compiled_graph = build_tool_graph(services)
    except Exception:
        compiled_graph = None
    if compiled_graph is not None:
        from ...domain.state import clone_graph_state
        result = compiled_graph.invoke(clone_graph_state(state))
        if not list(result["turn"].stage_timeline or []):
            if selection is None or not getattr(selection, "should_execute", False):
                result = _mark_stage(
                    result,
                    "tool",
                    "completed",
                    route_decision=_route_decision_for_turn(result["turn"]),
                    route_reason=str(result["turn"].extra.get("route_reason") or _route_decision_for_turn(result["turn"])),
                    detail=_tool_stage_detail(result["turn"]),
                )
        return result

    contract = state["turn"].routing_contract
    tool_allowed = contract.tool_allowed if contract is not None else should_run_tools(state)
    if not tool_allowed:
        state = _mark_stage(
            state,
            "tool",
            "completed",
            route_decision=_route_decision_for_turn(state["turn"]),
            route_reason=str(state["turn"].extra.get("route_reason") or _route_decision_for_turn(state["turn"])),
            detail=_tool_stage_detail(state["turn"]),
        )
        state = _ensure_raw_tool_result(state)
        state = _ensure_tool_result(state)
        return state

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
    try:
        state = services.tool_planner(state)
        selection = state["turn"].tool_plan
        if selection is None or not selection.should_execute:
            state = _ensure_raw_tool_result(state)
        else:
            state = services.tool_executor(state)
            state = _ensure_raw_tool_result(state)

        state = services.tool_result_normalizer(state)
    except Exception as exc:
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
            is_terminal=False
        )
        
        runtime = state["runtime"]
        metrics = dict(runtime.metrics)
        metrics["tool_degraded"] = True
        metrics["tool_error"] = str(exc)
        state = _append_state_runtime_error(state, err)
        state["runtime"] = state["runtime"].model_copy(update={
            "metrics": metrics
        })
        
        turn = state["turn"]
        tool_name = turn.tool_plan.tool_name if turn.tool_plan else "unknown_tool"
        
        state["turn"] = turn.model_copy(update={
            "raw_tool_result": ToolExecutionResult(
                status=ToolExecutionStatus.FAILED,
                tool_name=tool_name,
                degraded_to=None,
                error=WorkflowErrorCode.INFRASTRUCTURE_ERROR,
                approval_status=None,
                output_payload={"error": str(exc)}
            ),
            "tool_result": NormalizedToolResult(
                status=ToolExecutionStatus.DEGRADED,
                tool_name=tool_name,
                normalized_output={"status": "degraded", "error": str(exc), "message": "实时券信息暂不可用"},
                used_tools=[tool_name]
            )
        })

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

    try:
        from .graphs import build_plan_execute_graph

        compiled_graph = build_plan_execute_graph(services)
    except Exception:
        compiled_graph = None
    if compiled_graph is not None:
        from ...domain.state import clone_graph_state

        try:
            return compiled_graph.invoke(clone_graph_state(state))
        except Exception:
            compiled_graph = None

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
    routing = state["turn"].routing_decision
    if routing is not None and routing.blocked:
        return "compose_answer"
    return "rule_review"


def route_decider(state: GraphState) -> str:
    turn = state["turn"]
    routing = getattr(turn, "routing_decision", None)
    if routing is None:
        return "direct"

    execution_mode = str(getattr(routing, "execution_mode", "") or "").strip().lower()
    if execution_mode == "complex":
        return "complex"

    action = str(routing.required_action or "").strip().lower()
    if action == "clarify":
        return "clarify"
    route_candidate = str(getattr(routing, "route_candidate", "") or "").strip().lower()
    extra = dict(getattr(turn, "extra", {}) or {})
    route_review = extra.get("route_review_decision")
    if not isinstance(route_review, dict):
        route_review = dict(getattr(routing, "extra", {}) or {}).get("route_review_decision")
        if isinstance(route_review, dict):
            route_review = dict(route_review)
        else:
            route_review = {}

    raw_query_text = str(getattr(turn, "raw_query", "") or "")
    compact_query_text = raw_query_text.replace(" ", "")
    recommendation_like_query = any(
        token in compact_query_text
        for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
    )
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
        or route_candidate in {"recommendation", "local_life.nearby_recommend", "nearby_recommend", "local_life_recommend"}
        or (route_candidate.startswith("local_life.") and "recommend" in route_candidate)
        or recommendation_like_query
    )

    if routing.blocked and effective_action == action:
        return "clarify"
    if effective_action == "clarify":
        return "clarify"
    if recommendation_mode:
        return "recommendation"
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


def route_after_rag_graph(state: GraphState) -> str:
    routing = state["turn"].routing_decision
    if routing is not None and str(routing.required_action).strip().lower() == "rag_plus_tool" and can_enter_tool(state).allowed:
        return "tool_subgraph"
    return "merge_rank_node"


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
        status=status,  # type: ignore[arg-type]
        completed_steps=completed_steps,
        total_steps=total_steps,
        key_findings=key_findings[:5],
        final_decision=turn.replan_reason or turn.final_answer,
    )
    state["turn"] = turn.model_copy(update={"final_task_summary": summary})
    return state


def _filter_evidence_by_contract(state: GraphState) -> GraphState:
    turn = state["turn"]
    contract = getattr(turn, "routing_contract", None)
    if contract is None:
        return state
    
    evidence_pack = turn.evidence_pack
    if evidence_pack is None:
        return state
        
    from learning_agent_service.local_life.answer_linter import _infer_facets_from_text
    
    kept_items = []
    discarded_items = []
    
    for item in evidence_pack.items:
        # Check shop_id consistency
        item_shop_id = item.metadata.get("shop_id") or item.metadata.get("parent_shop_id") or item.metadata.get("entity_shop_id")
        if item_shop_id is not None:
            try:
                item_shop_id = int(str(item_shop_id))
            except (ValueError, TypeError):
                item_shop_id = None
        
        if contract.target_shop_id is not None and item_shop_id is not None and item_shop_id != contract.target_shop_id:
            discarded_items.append(item)
            continue
            
        # Check forbidden facets
        item_facets = set()
        for key in ("facet", "facets", "chunk_type"):
            val = item.metadata.get(key)
            if isinstance(val, list):
                item_facets.update(str(x).strip().lower() for x in val)
            elif val:
                item_facets.add(str(val).strip().lower())
        if item.chunk_type:
            item_facets.add(str(item.chunk_type).strip().lower())
        
        item_facets.update(_infer_facets_from_text(item.content))
        
        forbidden_found = [f for f in contract.forbidden_facets if f.strip().lower() in item_facets]
        if forbidden_found:
            discarded_items.append(item)
            continue
            
        kept_items.append(item)
        
    if len(kept_items) != len(evidence_pack.items):
        kept_strong = [x for x in kept_items if x.tier == "strong"]
        kept_weak = [x for x in kept_items if x.tier != "strong"]
        
        is_empty = len(kept_items) == 0
        status = "EMPTY" if is_empty else "OK"
        
        new_pack = evidence_pack.model_copy(update={
            "items": kept_items,
            "strong_items": kept_strong,
            "weak_items": kept_weak,
            "evidence_status": status,
            "top_scores": [x.score for x in kept_items[:3]]
        })
        
        state["turn"] = turn.model_copy(update={
            "evidence_pack": new_pack
        })
        
        quality = turn.evidence_quality
        if quality is not None:
            covered_facets = list(quality.covered_facets)
            missing_facets = list(quality.missing_facets)
            
            covered_facets = [f for f in covered_facets if f not in contract.forbidden_facets]
            for f in contract.forbidden_facets:
                if f in contract.required_facets and f not in missing_facets:
                    missing_facets.append(f)
                    
            is_valid = len(kept_strong) > 0 or not contract.single_shop_mode
            response_mode = "grounded" if not is_empty else "ask_clarification" if contract.need_clarify else "partial_grounded"
            
            new_quality = quality.model_copy(update={
                "evidence_count": len(kept_items),
                "covered_facets": covered_facets,
                "missing_facets": missing_facets,
                "is_valid": is_valid,
                "response_mode": response_mode,
                "top_score": kept_items[0].score if kept_items else 0.0
            })
            
            routing = turn.routing_decision
            if routing is not None:
                routing = routing.model_copy(update={"evidence_quality": new_quality})
            
            state["turn"] = state["turn"].model_copy(update={
                "evidence_quality": new_quality,
                "routing_decision": routing
            })
            
    return state
