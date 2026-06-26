"""execution_review_subgraph — tool execution, evidence building, and decision review.

Executes the validated plan (tool calls), builds evidence from results,
reviews evidence sufficiency, and runs decision planning/review to
determine whether to proceed, retry, or fall back.
"""

from __future__ import annotations

from typing import Any

from .._compat import (
    _log,
    _run_step,
    _run_steps,
    _session_store_state,
    _state_delta,
    _to_dict,
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_DEGRADE,
    _OUTER_ROUTE_ENOUGH,
    _OUTER_ROUTE_FALLBACK,
    _OUTER_ROUTE_RETRY,
)
from ...domain.graph_state import GraphState
from ...domain.schemas import EvidencePack, ExecutionPlan, ToolResult
from ...domain.state import SessionState
from ...planning.decision.decision_planner import plan_decision as p2_plan_decision
from ...planning.decision.decision_review import review_decision as p2_review_decision
from ...planning.evidence.evidence_review import review_evidence as review_evidence_sufficiency
from ...planning.policies.replan_policy import increment_expand_search, increment_replan_evidence
from ... import config


def h_execution_review_subgraph(state: GraphState) -> dict:
    """Outer wrapper: tool execute → evidence build → review → decision → route."""
    before = dict(state)
    working = _run_steps(state, [
        _h_tool_execute, _h_evidence_build, _h_evidence_review,
        _h_decision_planner, _h_decision_review,
    ])
    decision_review = working.get("decision_review_result")
    next_action = str(getattr(decision_review, "next_action", "") or _to_dict(decision_review).get("next_action", "") or "")
    if next_action in {"REPLAN_EVIDENCE"}:
        session = working.get("session_state")
        if isinstance(session, SessionState):
            increment_replan_evidence(session)
        after = {**working, "execution_review_route": _OUTER_ROUTE_RETRY, "response_mode": "answer"}
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"EXPAND_SEARCH"}:
        session = working.get("session_state")
        if isinstance(session, SessionState):
            increment_expand_search(session)
        after = {**working, "execution_review_route": _OUTER_ROUTE_RETRY, "response_mode": "answer"}
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"CLARIFY"}:
        after = {**working, "execution_review_route": _OUTER_ROUTE_CLARIFY, "response_mode": _OUTER_ROUTE_CLARIFY}
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"})
    if next_action in {"FALLBACK", "UNSUPPORTED_ANSWER"}:
        after = {**working, "execution_review_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_FALLBACK}
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    if next_action == "DEGRADE_ANSWER":
        after = {**working, "execution_review_route": _OUTER_ROUTE_DEGRADE, "response_mode": "answer"}
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    after = {**working, "execution_review_route": _OUTER_ROUTE_ENOUGH, "response_mode": "answer"}
    return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_tool_execute(state: GraphState) -> dict:
    from ...tools.gateway import BatchToolExecutor
    from .._compat import _resolve_recommendation_spec, _to_dict
    from ...domain.enums import TaskType
    from ..graph_builder import dispatch_tool_call as _dispatch_tool_call

    plan = state.get("validated_plan") or state.get("execution_plan")
    results: dict[str, ToolResult] = {}
    if plan is not None:
        tool_calls = getattr(plan, "tool_calls", []) or []
        raw_results: dict[str, dict[str, Any]] = {
            str(call_id): _to_dict(result)
            for call_id, result in (state.get("precomputed_tool_results") or {}).items()
        }
        batch_executor = BatchToolExecutor(call_fn=_dispatch_tool_call)
        search_calls = []
        remaining_specs = []
        for spec in tool_calls:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            if call.get("tool_name") == "search_shops":
                search_calls.append(spec)
            else:
                remaining_specs.append(spec)

        if search_calls:
            raw_results.update(batch_executor.execute_sync(search_calls))

        resolved_batch: list[dict[str, Any]] = []
        error_results: dict[str, dict[str, Any]] = {}
        for spec in remaining_specs:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            resolved_call = call
            if str(getattr(plan, "task_type", call.get("task_type", "")) or call.get("task_type", "")) == TaskType.recommendation.value:
                search_result = raw_results.get("call_search_shops", {})
                resolved_call = _resolve_recommendation_spec(call, search_result)
            call_id = resolved_call.get("call_id", "") or resolved_call.get("tool_name", "")
            shop_id = str(resolved_call.get("target_shop_id", "") or resolved_call.get("args", {}).get("shop_id", "")).strip()
            if not shop_id:
                unresolved_shop_ref = str(call.get("target_shop_id", "") or call.get("args", {}).get("shop_id", "")).strip()
                error_results[call_id] = {
                    "call_id": call_id,
                    "shop_id": unresolved_shop_ref,
                    "tool_name": resolved_call.get("tool_name", ""),
                    "success": False,
                    "result_status": "unknown" if not resolved_call.get("required", True) else "failed",
                    "data": None,
                    "error_code": "INVALID_ARGUMENT",
                    "error_message": f"Tool '{resolved_call.get('tool_name', '')}' could not resolve shop_id from search result",
                    "source": config.TOOL_BACKEND,
                    "tool_backend": config.TOOL_BACKEND,
                    "backend_source": config.TOOL_BACKEND,
                    "degraded": not resolved_call.get("required", True),
                }
                continue
            resolved_batch.append(resolved_call)

        if resolved_batch:
            raw_results.update(batch_executor.execute_sync(resolved_batch))
        raw_results.update(error_results)

        for spec in tool_calls:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            call_id = call.get("call_id", "") or call.get("tool_name", "")
            raw_result = raw_results.get(call_id)
            if raw_result is None:
                raw_result = {
                    "call_id": call_id,
                    "shop_id": call.get("target_shop_id", "") or call.get("args", {}).get("shop_id", ""),
                    "tool_name": call.get("tool_name", ""),
                    "success": False,
                    "result_status": "unknown" if not call.get("required", True) else "failed",
                    "data": None,
                    "error_code": "TOOL_TIMEOUT",
                    "error_message": f"Tool '{call.get('tool_name', '')}' did not return a result",
                    "source": config.TOOL_BACKEND,
                    "tool_backend": config.TOOL_BACKEND,
                    "backend_source": config.TOOL_BACKEND,
                    "degraded": not call.get("required", True),
                }
            resolved_call = call
            if str(getattr(plan, "task_type", call.get("task_type", "")) or call.get("task_type", "")) == TaskType.recommendation.value:
                resolved_call = _resolve_recommendation_spec(call, raw_results.get("call_search_shops", {}))
            shop_id = resolved_call.get("target_shop_id", "") or resolved_call.get("args", {}).get("shop_id", "") or raw_result.get("shop_id", "")
            raw_result = {**raw_result, "call_id": call_id, "shop_id": shop_id, "tool_name": resolved_call.get("tool_name", "")}
            results[call_id or call.get("tool_name", "")] = ToolResult.model_validate(raw_result)
    failed_calls = [
        call_id for call_id, result in results.items()
        if str(getattr(result, "result_status", _to_dict(result).get("result_status", ""))).lower() in {"failed", "unknown", "circuit_open"}
    ]
    return {
        "tool_results": results,
        "tool_result_set": results,
        **_log(state, "tool_execute", tool_call_count=len(results), tool_failures=failed_calls, tool_calls=list(results.keys())),
    }


def _h_evidence_build(state: GraphState) -> dict:
    from ...planning.evidence.evidence_builder import build_evidence

    resolved_target = _to_dict(state.get("resolved_target"))
    validated_plan = state.get("validated_plan") or state.get("execution_plan")
    evidence_payload = build_evidence(
        state.get("tool_result_set") or state.get("tool_results", {}),
        resolved_target,
        _to_dict(validated_plan),
        state.get("recommendation_candidates"),
        state.get("comparison_targets"),
    )
    pack = EvidencePack.model_validate(evidence_payload)
    updates: dict[str, Any] = {}
    if "last_recommendation_list" in evidence_payload:
        updates["last_recommendation_list"] = evidence_payload.get("last_recommendation_list", [])
    ranking_snapshot = _to_dict(pack.ranking_snapshot if hasattr(pack, "ranking_snapshot") else evidence_payload.get("ranking_snapshot"))
    comparison_matrix = _to_dict(pack.comparison_matrix if hasattr(pack, "comparison_matrix") else evidence_payload.get("comparison_matrix"))
    candidate_count = len(ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or comparison_matrix.get("rows") or [])
    return {
        "evidence_pack": pack,
        **updates,
        **_log(state, "evidence_build", candidate_count=candidate_count,
               decision_type="comparison" if comparison_matrix.get("rows") else ("recommendation" if ranking_snapshot else "")),
    }


def _h_evidence_review(state: GraphState) -> dict:
    goal = state.get("local_life_goal_draft")
    evidence_pack = state.get("evidence_pack")
    if goal is None or evidence_pack is None:
        return {**_log(state, "evidence_review", status="SKIPPED", reason="missing_goal_or_evidence_pack")}
    pack_dict = evidence_pack.model_dump() if hasattr(evidence_pack, "model_dump") else _to_dict(evidence_pack)
    tool_results = state.get("tool_result_set") or state.get("tool_results", {})
    review = review_evidence_sufficiency(
        goal=goal, evidence_pack=pack_dict, tool_results=tool_results,
    )
    review_results = dict(state.get("review_results") or {})
    review_results["evidence_review"] = review
    result: dict[str, Any] = {
        "review_results": review_results,
        **_log(state, "evidence_review", next_action=review.next_action, status=review.status,
              required_ok=len(review.required_ok), required_failed=len(review.required_failed),
              unknown_as_false=review.unknown_as_false_detected,
              failed_as_empty=review.failed_as_empty_detected,
              evidence_incomplete=review.evidence_incomplete, reason=review.reason),
    }
    ss = _session_store_state(state)
    rr = dict(ss.review_results or {})
    rr["evidence_review"] = review
    ss.review_results = rr
    result["session_state"] = ss
    return result


def _h_decision_planner(state: GraphState) -> dict:
    """P2 DecisionPlanner: generate a structured DecisionPlan from evidence."""
    from ...domain.decision import DecisionPlan

    gp = _to_dict(state.get("goal_plan") or state.get("local_life_goal_draft"))
    cs = _to_dict(state.get("candidate_set"))
    ep = state.get("evidence_pack")
    ev = None
    rr = state.get("review_results") or {}
    if isinstance(rr, dict):
        ev = rr.get("evidence_review")

    decision_plan = p2_plan_decision(
        goal_plan=gp, candidate_set=cs, evidence_pack=ep, evidence_review=ev,
    )
    result: dict[str, Any] = {
        "p2_decision_plan": decision_plan,
        **_log(state, "decision_planner",
              decision_type=decision_plan.decision_type.value if hasattr(decision_plan.decision_type, "value") else str(decision_plan.decision_type),
              answerable=len(decision_plan.answerable_facets),
              unknown=len(decision_plan.unknown_facets),
              failed=len(decision_plan.failed_facets),
              has_winner=decision_plan.winner_shop_id is not None),
    }
    ss = _session_store_state(state)
    ss.last_decision_plan = decision_plan.model_dump()
    result["session_state"] = ss
    return result


def _h_decision_review(state: GraphState) -> dict:
    """P2 DecisionReview: evaluate DecisionPlan sufficiency."""
    from ...domain.decision import DecisionPlan, DecisionReviewResult
    from ...planning.decision.decision_review import review_decision as p2_review_decision

    from .._compat import _session_store_state, _to_dict

    dp = state.get("p2_decision_plan")
    gp = state.get("goal_plan")
    rr = state.get("review_results") or {}
    ev = rr.get("evidence_review") if isinstance(rr, dict) else None
    cr = rr.get("candidate_review") if isinstance(rr, dict) else None
    ss = _session_store_state(state)
    esc = int(ss.replan_counters.get("expand_search", 0))
    rec = int(ss.replan_counters.get("replan_evidence", 0))

    review = p2_review_decision(
        decision_plan=dp, goal_plan=gp, evidence_review=ev,
        candidate_review=cr, expand_search_count=esc, replan_evidence_count=rec,
    )
    updated_rr = dict(rr) if isinstance(rr, dict) else {}
    updated_rr["decision_review"] = review
    result: dict[str, Any] = {
        "decision_review_result": review,
        "review_results": updated_rr,
        **_log(state, "decision_review", status=review.status, next_action=review.next_action,
              reason=review.reason, is_deterministic=review.is_deterministic_winner),
    }
    srr = dict(ss.review_results or {})
    srr["decision_review"] = review
    ss.review_results = srr
    result["session_state"] = ss
    return result
