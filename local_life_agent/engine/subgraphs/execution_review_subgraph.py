"""execution_review_subgraph — tool execution, evidence building, and decision review.

Executes the validated plan (tool calls), builds evidence from results,
reviews evidence sufficiency, and runs decision planning/review to
determine whether to proceed, retry, or fall back.

This workflow uses workflow-internal batch tool/evidence aggregation only:
single-workflow batch execution is followed by single-owner evidence
aggregation and decision planning. It is not workflow-level fan-out, does
not produce multiple final responses, does not produce multiple
state_update_plan values, and reduces back into one workflow-owned
EvidencePack. It is not implemented as a LangGraph-native Send/reducer
fan-out graph.
"""

from __future__ import annotations

import logging
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
from ...core.execution_core import ExecutionCore
from ...planning.decision.decision_planner import (
    plan_decision as p2_plan_decision,
    plan_decision_with_llm,
)
from ...planning.decision.decision_review import review_decision as p2_review_decision
from ...planning.evidence.evidence_review import (
    review_evidence as review_evidence_sufficiency,
    review_evidence_with_llm,
)
from ...planning.budget.execution_budget import execution_budget_from_state
from ...planning.policies.replan_policy import increment_expand_search, increment_replan_evidence
from ...planning.policies.review_policy import review_policy_from_state
from ... import config
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()


def h_execution_review_subgraph(state: GraphState) -> dict:
    """Outer wrapper: tool execute → evidence build → review → decision → route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="execution_review_subgraph", trace_id=state.get("trace_id", ""), execution_plan=state.get("validated_plan") or state.get("execution_plan"))
    working = _run_steps(state, [_h_tool_execute, _h_evidence_build])
    working = _run_step(working, _h_evidence_review)
    if working.get("error_code") and str(working.get("failed_stage", "") or "") == "evidence_review":
        after = {**working, "execution_review_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_FALLBACK}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_FALLBACK, failed_stage="evidence_review", error_code=working.get("error_code", ""))
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    working = _run_step(working, _h_decision_planner)
    if working.get("error_code") and str(working.get("failed_stage", "") or "") == "decision_planner":
        after = {**working, "execution_review_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_FALLBACK}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_FALLBACK, failed_stage="decision_planner", error_code=working.get("error_code", ""))
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    working = _run_step(working, _h_decision_review)
    decision_review = working.get("decision_review_result")
    next_action = str(getattr(decision_review, "next_action", "") or _to_dict(decision_review).get("next_action", "") or "")
    if next_action in {"REPLAN_EVIDENCE"}:
        session = working.get("session_state")
        if isinstance(session, SessionState):
            increment_replan_evidence(session)
        after = {**working, "execution_review_route": _OUTER_ROUTE_RETRY, "response_mode": "answer"}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_RETRY, response_mode="answer", next_action=next_action)
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"EXPAND_SEARCH"}:
        session = working.get("session_state")
        if isinstance(session, SessionState):
            increment_expand_search(session)
        after = {**working, "execution_review_route": _OUTER_ROUTE_RETRY, "response_mode": "answer"}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_RETRY, response_mode="answer", next_action=next_action)
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"CLARIFY"}:
        after = {**working, "execution_review_route": _OUTER_ROUTE_CLARIFY, "response_mode": _OUTER_ROUTE_CLARIFY}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, next_action=next_action)
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"})
    if next_action in {"FALLBACK", "UNSUPPORTED_ANSWER"}:
        after = {**working, "execution_review_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_FALLBACK}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_FALLBACK, next_action=next_action)
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    if next_action == "DEGRADE_ANSWER":
        after = {**working, "execution_review_route": _OUTER_ROUTE_DEGRADE, "response_mode": "answer"}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_DEGRADE, response_mode="answer", next_action=next_action)
        return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)
    after = {**working, "execution_review_route": _OUTER_ROUTE_ENOUGH, "response_mode": "answer"}
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="execution_review_subgraph", route=_OUTER_ROUTE_ENOUGH, response_mode="answer", next_action=next_action)
    return _state_delta(before, after, always_include={"execution_review_route", "response_mode"}, exclude=_OUTER_WRAPPER_EXCLUDE_FIELDS)


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_tool_execute(state: GraphState) -> dict:
    from .._compat import _resolve_recommendation_spec, _to_dict
    from ...domain.enums import TaskType
    from ..graph_builder import dispatch_tool_call as _dispatch_tool_call
    from ...planning.evidence.stage_tool_executor import StageToolExecutor

    plan = state.get("validated_plan") or state.get("execution_plan")
    raw_text = str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
    if plan is not None and getattr(plan, "task_type", "") == TaskType.single_shop_query.value:
        tool_calls = list(getattr(plan, "tool_calls", []) or [])
        if tool_calls:
            facet_tokens: list[tuple[str, tuple[str, ...]]] = [
                ("coupon", ("有券", "优惠券", "coupon", "团购", "套餐")),
                ("open_status", ("营业", "开门", "open")),
                ("distance", ("距离", "多远", "多久", "eta")),
                ("review_summary", ("评价", "口碑", "review")),
                ("price", ("价格", "多少钱", "人均", "price")),
            ]
            inferred_facet = ""
            for facet_name, tokens in facet_tokens:
                if any(token in raw_text for token in tokens):
                    inferred_facet = facet_name
                    break
    if plan is not None and getattr(plan, "stages", None) and str(getattr(plan, "task_type", "") or "") != TaskType.recommendation.value:
        stage_executor = StageToolExecutor(call_fn=_dispatch_tool_call)
        stage_result = stage_executor.execute(plan)
        results = {
            call_id: ToolResult.model_validate(payload)
            for call_id, payload in (stage_result.results or {}).items()
        }
        failed_calls = [
            call_id for call_id, result in results.items()
            if str(getattr(result, "result_status", _to_dict(result).get("result_status", ""))).lower() in {"failed", "unknown", "circuit_open"}
        ]
        return {
            "tool_results": results,
            "tool_result_set": results,
            "tool_result_cache_hit_count": stage_result.cache_hits,
            **_log(state, "tool_execute", tool_call_count=len(results), tool_failures=failed_calls, tool_calls=list(results.keys())),
        }
    results: dict[str, ToolResult] = {}
    if plan is not None:
        tool_calls = getattr(plan, "tool_calls", []) or []
        raw_results: dict[str, dict[str, Any]] = {
            str(call_id): _to_dict(result)
            for call_id, result in (state.get("precomputed_tool_results") or {}).items()
        }
        search_calls = []
        remaining_specs = []
        for spec in tool_calls:
            call = spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
            if call.get("tool_name") == "search_shops":
                search_calls.append(spec)
            else:
                remaining_specs.append(spec)

        batch_executor = ExecutionCore(call_fn=_dispatch_tool_call)
        if search_calls:
            # Batch-concurrent map stage: search calls are executed together
            # and then merged into the local raw_results dict.
            raw_results.update(batch_executor.execute_batch(search_calls))

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
            # Second batch pass for resolved follow-up calls. The merge stays
            # in Python state, not in a LangGraph reducer.
            raw_results.update(batch_executor.execute_batch(resolved_batch))
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
    from ...planning.evidence.evidence_cache import get_default_evidence_cache

    resolved_target = _to_dict(state.get("resolved_target"))
    validated_plan = state.get("validated_plan") or state.get("execution_plan")
    evidence_payload = build_evidence(
        state.get("tool_result_set") or state.get("tool_results", {}),
        resolved_target,
        _to_dict(validated_plan),
        state.get("recommendation_candidates"),
        state.get("comparison_targets"),
        cache=get_default_evidence_cache(),
        cache_scope={
            "workflow": "execution_review_subgraph",
            "trace_id": state.get("trace_id", ""),
            "session_id": state.get("session_id", ""),
            "turn_id": state.get("turn_id", ""),
        },
    )
    pack = EvidencePack.model_validate(evidence_payload)
    if "last_recommendation_list" in evidence_payload:
        last_recommendation_list = evidence_payload.get("last_recommendation_list", [])
    ranking_snapshot = _to_dict(pack.ranking_snapshot if hasattr(pack, "ranking_snapshot") else evidence_payload.get("ranking_snapshot"))
    comparison_matrix = _to_dict(pack.comparison_matrix if hasattr(pack, "comparison_matrix") else evidence_payload.get("comparison_matrix"))
    candidate_count = len(ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or comparison_matrix.get("rows") or [])
    return {
        "evidence_pack": pack,
        **({"last_recommendation_list": last_recommendation_list} if "last_recommendation_list" in evidence_payload else {}),
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
    from ..graph_builder import call_llm as _call_llm, get_llm_backend_snapshot as _get_llm_backend_snapshot
    backend_snapshot = _get_llm_backend_snapshot()
    strict_llm = str(backend_snapshot.get("backend_kind", "") or "") not in {"", "fake_llm", "fake"}
    review, meta = review_evidence_with_llm(
        goal=goal,
        evidence_pack=pack_dict,
        tool_results=tool_results,
        candidate_review=(state.get("review_results") or {}).get("candidate_review") if isinstance(state.get("review_results"), dict) else None,
        llm_call=_call_llm,
        strict=strict_llm,
    )
    if review is None:
        return {
            "review_results": dict(state.get("review_results") or {}),
            "error_code": meta.get("error_code", "EVIDENCE_REVIEW_FAILED"),
            "error_message": meta.get("error_message", "evidence review llm failed"),
            "failed_stage": "evidence_review",
            "planning_llm_backend": meta.get("llm_backend", ""),
            "planning_llm_called": True,
            "planning_failure_code": meta.get("error_code", "EVIDENCE_REVIEW_FAILED"),
            **_log(state, "evidence_review", status="failed", reason=meta.get("error_code", "EVIDENCE_REVIEW_FAILED")),
        }
    review_results = dict(state.get("review_results") or {})
    review_results["evidence_review"] = review
    result: dict[str, Any] = {
        "review_results": review_results,
        "planning_llm_backend": meta.get("llm_backend", ""),
        "planning_llm_called": True,
        "planning_failure_code": "",
        **_log(state, "evidence_review", next_action=review.next_action, status=review.status,
              required_ok=len(review.required_ok), required_failed=len(review.required_failed),
              unknown_as_false=review.unknown_as_false_detected,
              failed_as_empty=review.failed_as_empty_detected,
              review_source=review.review_source or "llm_evidence_review",
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

    from ..graph_builder import call_llm as _call_llm, get_llm_backend_snapshot as _get_llm_backend_snapshot
    backend_snapshot = _get_llm_backend_snapshot()
    strict_llm = str(backend_snapshot.get("backend_kind", "") or "") not in {"", "fake_llm", "fake"}
    decision_plan, meta = plan_decision_with_llm(
        goal_plan=gp, candidate_set=cs, evidence_pack=ep, evidence_review=ev,
        llm_call=_call_llm,
        strict=strict_llm,
    )
    if decision_plan is None:
        return {
            "p2_decision_plan": None,
            "error_code": meta.get("error_code", "DECISION_PLANNER_FAILED"),
            "error_message": meta.get("error_message", "decision planner llm failed"),
            "failed_stage": "decision_planner",
            "planning_llm_backend": meta.get("llm_backend", ""),
            "planning_llm_called": True,
            "planning_failure_code": meta.get("error_code", "DECISION_PLANNER_FAILED"),
            **_log(state, "decision_planner", status="failed", reason=meta.get("error_code", "DECISION_PLANNER_FAILED")),
        }
    result: dict[str, Any] = {
        "p2_decision_plan": decision_plan,
        "planning_llm_backend": meta.get("llm_backend", ""),
        "planning_llm_called": True,
        "planning_failure_code": "",
        **_log(state, "decision_planner",
              decision_type=decision_plan.decision_type.value if hasattr(decision_plan.decision_type, "value") else str(decision_plan.decision_type),
              answerable=len(decision_plan.answerable_facets),
              unknown=len(decision_plan.unknown_facets),
              failed=len(decision_plan.failed_facets),
              has_winner=decision_plan.winner_shop_id is not None,
              decision_source=decision_plan.decision_source or "llm_decision_planner"),
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

    review_policy = review_policy_from_state(state)
    execution_budget = execution_budget_from_state(state)
    review = p2_review_decision(
        decision_plan=dp, goal_plan=gp, evidence_review=ev,
        candidate_review=cr, expand_search_count=esc, replan_evidence_count=rec,
        review_policy=review_policy, execution_budget=execution_budget,
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
