"""planning_subgraph — goal planning, target resolution, and evidence planning.

This subgraph takes the parsed semantic frame and:
1. Plans the user's goal (GoalPlanner + GoalReview)
2. Resolves target shops / candidates (TargetResolve)
3. Decides whether to clarify or proceed (ClarifyDecide)
4. Plans what evidence to collect (EvidencePlanner)
5. Validates the execution plan (PlanValidator)
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from .._compat import (
    _log,
    _run_step,
    _run_steps,
    _state_delta,
    _session_state_dict,
    _session_store_state,
    _to_dict,
    _user_location,
    _unwrap_resolve_shop_result,
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_EXECUTE,
    _OUTER_ROUTE_FALLBACK,
    _OUTER_ROUTE_REJECT,
)
from ...domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateSpec,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
    ResolutionStage,
)
from ...domain.enums import TaskType
from ...domain.graph_state import GraphState
from ...domain.schemas import (
    ExecutionPlan,
    ResolveShopResult,
    SemanticFrame,
    ShopCandidate,
    ShopRef,
    ToolResult,
)
from ...domain.facets import build_target_resolution_result, normalize_query_facets
from ...domain.state import SessionState
from ...planning.plans.candidate_review import review_candidate_set
from ...planning.evidence.evidence_planner import (
    plan_evidence as plan_evidence_from_candidates,
    plan_evidence_with_llm,
)
from ...planning.plans.execution_plan_builder import build_recommendation_execution_plan
from ...planning.goal.goal_draft import build_candidate_spec, build_local_life_goal_draft
from ...planning.goal.goal_planner import plan_goal as p2_plan_goal, plan_goal_with_llm
from ...planning.goal.goal_review import review_goal as p2_review_goal
from ...planning.plans.plan_validator import ExecutionPlanValidator
from ...planning.policies.replan_policy import increment_expand_search, increment_replan_evidence
from ...planning.policies.review_policy import NextAction
from ...target.candidate_resolver import CandidateResolver
from ...target.clarification import build_pending_clarification, format_pending_prompt, handle_clarification_reply
from ... import config
from ...observability.file_logger import get_python_service_logger, log_kv
from ...core import CandidateCore, PlanningCore

_LOGGER = get_python_service_logger()
_PLANNING_WRAPPER_EXCLUDE_FIELDS = _OUTER_WRAPPER_EXCLUDE_FIELDS - {"event_log"}
_PLANNING_CORE = PlanningCore()
_CANDIDATE_CORE = CandidateCore()


def _pending_candidate_targets(candidate_set: CandidateSet) -> list[dict[str, Any]]:
    candidates = list(candidate_set.candidates or [])

    def _sort_key(candidate: Any) -> tuple[float, float, str, str]:
        confidence = float(getattr(candidate, "confidence", 0.0) or 0.0)
        rating = float(getattr(candidate, "rating", 0.0) or 0.0)
        shop_name = str(getattr(candidate, "shop_name", "") or "")
        shop_id = str(getattr(candidate, "shop_id", "") or "")
        return (-confidence, -rating, shop_name, shop_id)

    pending_candidates: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=_sort_key):
        pending_candidates.append(
            {
                "shop_id": str(getattr(candidate, "shop_id", "") or "").strip(),
                "shop_name": str(getattr(candidate, "shop_name", "") or "").strip(),
                "address": str((getattr(candidate, "raw", {}) or {}).get("address", "") or ""),
            }
        )
    return pending_candidates


def h_planning_subgraph(state: GraphState) -> dict:
    """Outer wrapper: goal plan → review → target resolve → evidence → plan validate → route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="planning_subgraph", trace_id=state.get("trace_id", ""), top_intent=state.get("top_intent", ""))
    working = _run_steps(state, [_h_goal_planner, _h_goal_review])
    goal_review = working.get("goal_review_result")
    next_action = str(getattr(goal_review, "next_action", "") or _to_dict(goal_review).get("next_action", "") or "")
    if next_action in {"CLARIFY"}:
        after = {**working, "planning_route": _OUTER_ROUTE_CLARIFY, "response_mode": _OUTER_ROUTE_CLARIFY}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, next_action=next_action)
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"UNSUPPORTED_ANSWER"}:
        after = {**working, "planning_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_REJECT}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_REJECT, next_action=next_action)
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)
    if next_action in {"FALLBACK"}:
        after = {**working, "planning_route": _OUTER_ROUTE_FALLBACK, "response_mode": _OUTER_ROUTE_FALLBACK}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_FALLBACK, response_mode=_OUTER_ROUTE_FALLBACK, next_action=next_action)
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    working = _run_steps(working, [_h_target_resolve])
    resolve_result = working.get("resolve_shop_result") or working.get("resolved_target")
    resolve_dict = _to_dict(resolve_result)
    task_type_value = str(getattr(state.get("task_type"), "value", state.get("task_type")) or _to_dict(working.get("semantic_frame")).get("task_type", "") or "")
    comparison_resolution = _to_dict(working.get("comparison_target_resolution"))
    comparison_status = str(comparison_resolution.get("status", "") or "").upper()
    comparison_needs_clarify = task_type_value == TaskType.comparison.value and comparison_status in {"NEED_CLARIFICATION", "NOT_FOUND", "TOO_MANY", "PARTIAL"}

    if comparison_needs_clarify:
        pending = working.get("pending_clarification")
        if pending is None:
            candidate_targets = list(working.get("comparison_targets") or [])
            already_resolved_targets = list(candidate_targets)
            unresolved_targets = list(comparison_resolution.get("unresolved_targets") or [])
            explicit_candidates: list[dict[str, Any]] = []
            try:
                from ..graph_builder import resolve_shop as _resolve_shop
            except Exception:
                _resolve_shop = None
            for unresolved in unresolved_targets:
                unresolved_dict = _to_dict(unresolved)
                if str(unresolved_dict.get("reference", "") or "").strip() != "explicit":
                    continue
                query = str(unresolved_dict.get("query", "") or unresolved_dict.get("source_ref", "") or "").strip()
                if not query or _resolve_shop is None:
                    continue
                try:
                    resolved = _unwrap_resolve_shop_result(_to_dict(_resolve_shop(query, location={})))
                except Exception:
                    resolved = {}
                resolved_dict = _to_dict(resolved)
                resolved_status = str(resolved_dict.get("status", "") or "").upper()
                if resolved_status == "AMBIGUOUS":
                    for candidate in resolved_dict.get("candidates", []) or []:
                        candidate_dict = _to_dict(candidate.get("shop") if isinstance(candidate, dict) else candidate)
                        if candidate_dict.get("shop_id") or candidate_dict.get("shop_name"):
                            explicit_candidates.append(candidate_dict)
                elif resolved_status == "RESOLVED":
                    shop = resolved_dict.get("shop") or resolved_dict.get("resolved_shop") or {}
                    shop_dict = _to_dict(shop)
                    if shop_dict.get("shop_id") or shop_dict.get("shop_name"):
                        explicit_candidates.append(shop_dict)
            if explicit_candidates:
                candidate_targets = explicit_candidates
                resolved_target_ids = {
                    str(item.get("shop_id", "") or "").strip()
                    for item in explicit_candidates
                    if str(item.get("shop_id", "") or "").strip()
                }
                resolved_target_names = {
                    str(item.get("shop_name", "") or "").strip()
                    for item in explicit_candidates
                    if str(item.get("shop_name", "") or "").strip()
                }
                already_resolved_targets = [
                    _to_dict(item)
                    for item in list(comparison_resolution.get("targets") or working.get("comparison_targets") or [])
                    if str(_to_dict(item).get("shop_id", "") or "").strip() not in resolved_target_ids
                    and str(_to_dict(item).get("shop_name", "") or "").strip() not in resolved_target_names
                ]
            if not candidate_targets:
                session_state = state.get("session_state_before") or state.get("session_state")
                if session_state is not None:
                    if isinstance(session_state, dict):
                        candidate_targets = list(session_state.get("last_recommendation_list", []) or [])
                    else:
                        candidate_targets = list(getattr(session_state, "last_recommendation_list", []) or [])
                already_resolved_targets = list(candidate_targets)
            if candidate_targets:
                original_semantic_frame = _to_dict(working.get("semantic_frame"))
                if not original_semantic_frame and working.get("semantic_frame") is not None:
                    original_semantic_frame = _session_state_dict(working.get("semantic_frame"))
                pending = build_pending_clarification(
                    original_text=str(state.get("raw_text", "") or ""),
                    original_semantic_frame=original_semantic_frame,
                    original_task_type=task_type_value or TaskType.comparison.value,
                    candidate_targets=[_to_dict(item) for item in candidate_targets],
                    reason=str(comparison_resolution.get("reason", "") or "comparison_targets_need_clarification"),
                    source_node="planning_subgraph",
                    already_resolved_targets=[_to_dict(item) for item in already_resolved_targets],
                )
        after = {
            **working,
            "pending_clarification": pending,
            "planning_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
        }
        log_kv(
            _LOGGER,
            logging.WARNING,
            "[ROUTE_DECISION]",
            tone="warn",
            subgraph="planning_subgraph",
            route=_OUTER_ROUTE_CLARIFY,
            response_mode=_OUTER_ROUTE_CLARIFY,
            resolve_status=comparison_status or resolve_dict.get("status", ""),
            reason="comparison_target_needs_clarification",
        )
        return _state_delta(before, after, always_include={"planning_route", "response_mode", "pending_clarification"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    if working.get("pending_clarification") is not None:
        working = _run_steps(working, [_h_clarify_decide])
        after = {
            **working,
            "planning_route": _OUTER_ROUTE_CLARIFY,
            "response_mode": _OUTER_ROUTE_CLARIFY,
        }
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=_OUTER_ROUTE_CLARIFY, response_mode=_OUTER_ROUTE_CLARIFY, resolve_status=resolve_dict.get("status", ""), reason="pending_clarification_from_target_resolve")
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    # Build execution plan regardless of target_resolve outcome.
    # recommendation/discovery queries with 0 candidates still need
    # a search plan; ambiguous shop references also go through tool
    # execution rather than short-circuiting to clarify.
    working = _run_steps(working, [_h_evidence_planner, _h_plan_validator])
    if working.get("error_code"):
        fallback_route = _planning_failure_route(working)
        after = {**working, "planning_route": fallback_route, "response_mode": fallback_route}
        log_kv(_LOGGER, logging.WARNING, "[ROUTE_DECISION]", tone="warn", subgraph="planning_subgraph", route=fallback_route, response_mode=fallback_route, error_code=working.get("error_code", ""), failed_stage=working.get("failed_stage", ""))
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    if resolve_dict.get("status") == "RESOLVED":
        after = {**working, "planning_route": _OUTER_ROUTE_EXECUTE, "response_mode": "answer"}
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="planning_subgraph", route=_OUTER_ROUTE_EXECUTE, response_mode="answer", resolve_status="RESOLVED")
        return _state_delta(before, after, always_include={"planning_route", "response_mode"}, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)

    # Not RESOLVED — clear pending_clarification so response_subgraph
    # does NOT enter the clarify branch.  Let Execute → Evidence Review
    # → LLM Answer handle insufficient/ambiguous results naturally.
    after = {
        **working,
        "planning_route": _OUTER_ROUTE_EXECUTE,
        "response_mode": "answer",
        "pending_clarification": None,
        "final_response": "",
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="planning_subgraph", route=_OUTER_ROUTE_EXECUTE, response_mode="answer", resolve_status=resolve_dict.get("status", ""))
    return _state_delta(before, after, always_include={
        "planning_route", "response_mode", "pending_clarification", "final_response",
    }, exclude=_PLANNING_WRAPPER_EXCLUDE_FIELDS)


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_goal_planner(state: GraphState) -> dict:
    """P2 GoalPlanner: generate a structured GoalPlan from the semantic frame."""
    sf = state.get("semantic_frame")
    session = state.get("session_state_before") or state.get("session_state")
    raw_text = str(state.get("raw_text", "") or "")
    from ..graph_builder import call_llm as _call_llm, get_llm_backend_snapshot as _get_llm_backend_snapshot
    backend_snapshot = _get_llm_backend_snapshot()
    strict_llm = str(backend_snapshot.get("backend_kind", "") or "") not in {"", "fake_llm", "fake"}
    plan, meta = _PLANNING_CORE.plan_goal_with_llm(sf, session, raw_text, llm_call=_call_llm, strict=strict_llm)
    if plan is None:
        result = {
            "goal_plan": None,
            "goal_plan_source": "",
            "planning_llm_backend": meta.get("llm_backend", ""),
            "planning_llm_called": True,
            "planning_failure_code": meta.get("error_code", "GOAL_PLANNER_FAILED"),
            "error_code": meta.get("error_code", "GOAL_PLANNER_FAILED"),
            "error_message": meta.get("error_message", "goal planner llm failed"),
            **_log(state, "goal_planner", status="failed", reason=meta.get("error_code", "GOAL_PLANNER_FAILED")),
        }
        return result
    # ── Backfill task_type ← goal_type (included in result, not mutating state) ──
    goal_type_from_plan = str(getattr(plan, "goal_type", "") or "")
    # ──────────────────────────────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "goal_plan": plan,
        "facet_set": normalize_query_facets(sf, session_state=session, raw_text=raw_text),
        "facets": list(getattr(plan, "facets", []) or []),
        "target_resolution": getattr(plan, "target_resolution", None),
        "conflicting_facets": list(getattr(plan, "conflicting_facets", []) or []),
        "ranking_policy": getattr(plan, "ranking_policy", None),
        "task_type": goal_type_from_plan if (goal_type_from_plan and not state.get("task_type")) else state.get("task_type", ""),
        "goal_plan_source": plan.planner_source or plan.source_origin or "llm_goal_planner",
        "planning_llm_backend": meta.get("llm_backend", ""),
        "planning_llm_called": True,
        "planning_failure_code": "",
        **_log(state, "goal_planner",
              goal_type=plan.goal_type, candidate_source=plan.candidate_source,
              unsupported=plan.unsupported, planner_source=plan.planner_source or "llm_goal_planner"),
    }
    ss = _session_store_state(state)
    ss.active_goal = plan.model_dump()
    result["session_state"] = ss
    return result


def _h_goal_review(state: GraphState) -> dict:
    """P2 GoalReview: check if the goal is clear, executable, and supported."""
    from ...planning.goal.goal_review import review_goal as p2_review_goal
    from ...domain.goal import goal_plan_to_draft, GoalReviewResult

    gp = state.get("goal_plan")
    raw_text = str(state.get("raw_text", "") or "")
    session = state.get("session_state_before") or state.get("session_state")
    if gp is None:
        return {
            "goal_review_result": GoalReviewResult(
                status="unsupported", next_action="UNSUPPORTED_ANSWER", reason="no_goal_plan_produced",
            ),
            **_log(state, "goal_review", status="unsupported", reason="no_goal_plan"),
        }
    review = p2_review_goal(gp, raw_text, session)
    result: dict[str, Any] = {"goal_review_result": review}
    if review.next_action == "FINISH":
        draft = goal_plan_to_draft(gp)
        result["local_life_goal_draft"] = draft
        result["candidate_source_origin"] = gp.candidate_source
    ss = _session_store_state(state)
    rr = dict(ss.review_results or {})
    rr["goal_review"] = review
    ss.review_results = rr
    result["session_state"] = ss
    return {
        **result,
        **_log(state, "goal_review", status=review.status, next_action=review.next_action, reason=review.reason),
    }


def _h_target_resolve(state: GraphState) -> dict:
    sf = state.get("semantic_frame")
    return _h_target_resolve_candidate_set(state, sf)


def _h_target_resolve_candidate_set(state: GraphState, sf: Any) -> dict:
    """CandidateSet resolution path — builds goal → spec → resolver → review → route."""
    session_snapshot = state.get("session_state_before") or state.get("session_state") or SessionState()
    if hasattr(session_snapshot, "model_copy"):
        session_snapshot = session_snapshot.model_copy(deep=True)

    sf_dict = _to_dict(sf)
    if str(state.get("error_code", "") or "") == "SCHEMA_VALIDATION_FAILED" or sf_dict.get("shop_id") or sf_dict.get("tool_name"):
        return {
            "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason="schema_validation_failed"),
            "target_resolution_status": "NOT_FOUND",
            "session_state_after": session_snapshot,
            **_log(state, "target_resolve", status="NOT_FOUND", reason="schema_validation_failed"),
        }

    pre_resolved_target = state.get("resolved_target")
    if pre_resolved_target is not None:
        resolved_dict = _to_dict(pre_resolved_target)
        if resolved_dict.get("status") == "RESOLVED":
            resolved_shop = _to_dict(resolved_dict.get("resolved_shop") or resolved_dict.get("shop") or {})
            candidate = ResolvedCandidate(
                shop_id=str(resolved_shop.get("shop_id", "") or "").strip(),
                shop_name=str(resolved_shop.get("shop_name", "") or "").strip(),
                source=CandidateSource.CONTEXT,
                confidence=float(resolved_dict.get("confidence", 1.0) or 1.0),
                raw=resolved_shop,
            )
            candidate_set = CandidateSet(
                status=CandidateStatus.RESOLVED, source=CandidateSource.CONTEXT,
                candidates=[candidate], requested_count=1, min_required=1, max_allowed=1,
            )
            result = {
                "resolve_shop_result": pre_resolved_target,
                "resolved_target": pre_resolved_target,
                "target_resolution_status": "RESOLVED",
                "session_state_after": session_snapshot,
                "candidate_set": candidate_set,
                "effective_candidate_set": candidate_set,
                "recommendation_candidates": [candidate.model_dump()],
                "review_results": {
                    "candidate_review": {
                        "stage": "candidate_review", "status": "enough",
                        "next_action": "FINISH", "reason": "resolved_target_short_circuit",
                    }
                },
                "reference_resolution_source": str(state.get("reference_resolution_source") or "context_recovered"),
                **_log(state, "target_resolve", status="RESOLVED", target_resolve_mode="resolved_target",
                      candidate_source=str(state.get("candidate_source_origin") or "context"),
                      candidate_count=1, candidate_review_status="resolved_target",
                      candidate_review_next_action="FINISH", next_action="FINISH"),
            }
            return result

    # 1. Get goal draft
    goal = state.get("local_life_goal_draft")
    if goal is None:
        goal = build_local_life_goal_draft(sf, state)
    if goal is None or (hasattr(goal, "goal_type") and (goal.goal_type is None or goal.goal_type.value == "unsupported")):
        return {
            "resolve_shop_result": ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason="missing_goal_draft"),
            "target_resolution_status": "NOT_FOUND",
            "final_response": "暂时无法确认目标店铺，请补充更明确的店名或筛选条件。",
            "session_state_after": session_snapshot,
            **_log(state, "target_resolve", status="NOT_FOUND", reason="missing_goal_draft"),
        }

    # 2. Build candidate spec
    spec = build_candidate_spec(goal, sf, state)

    # 3. Resolve candidates
    candidate_set = _CANDIDATE_CORE.resolve(goal, spec, state)
    candidate_set.requested_count = goal.requested_count
    candidate_set.min_required = goal.min_required
    candidate_set.max_allowed = goal.max_allowed

    # 4. Review candidates
    review = review_candidate_set(goal, candidate_set)

    # 5. Build state update payload
    payload: dict[str, Any] = {
        "local_life_goal_draft": goal,
        "candidate_spec": spec,
        "candidate_set": candidate_set,
        "effective_candidate_set": candidate_set,
        "recommendation_candidates": [
            c.model_dump() if hasattr(c, "model_dump") else _to_dict(c)
            for c in (candidate_set.candidates or [])
        ],
        "review_results": {"candidate_review": review},
        # Propagate comparison_targets from context_recovery through to evidence/state
        "comparison_targets": state.get("comparison_targets", []),
    }

    # P2: persist last_candidate_set/spec for multi-turn references
    ss = _session_store_state(state)
    ss.last_candidate_set = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in (candidate_set.candidates or [])
    ]
    ss.last_candidate_spec = (
        spec.model_dump() if hasattr(spec, "model_dump") else _to_dict(spec)
    )
    payload["session_state"] = ss

    candidate_count = len(candidate_set.candidates or [])
    if (
        goal.goal_type == GoalType.SINGLE_SHOP_QUERY
        and candidate_count > 1
        and candidate_set.source in {CandidateSource.EXPLICIT, CandidateSource.DISCOVERY, CandidateSource.MIXED}
    ):
        reason = review.reason or "single_shop_query_multiple_candidates"
        ambiguous_candidates = [
            ShopCandidate(
                shop=ShopRef(shop_id=c.shop_id, shop_name=c.shop_name),
                match_score=float(getattr(c, "confidence", 0.0) or 0.0),
            )
            for c in (candidate_set.candidates or [])
        ]
        resolved = ResolveShopResult(
            status="AMBIGUOUS",
            candidates=ambiguous_candidates,
            confidence=0.0,
            reason=reason,
        )
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
            original_task_type=getattr(sf, "task_type", "") or state.get("task_type", ""),
            candidate_targets=_pending_candidate_targets(candidate_set),
            reason=reason,
            source_node="target_resolve",
        )
        payload["resolve_shop_result"] = resolved
        payload["pending_clarification"] = pending
        payload["target_resolution_status"] = "AMBIGUOUS"
        payload["final_response"] = format_pending_prompt(pending)
        payload["session_state_after"] = session_snapshot
        payload["review_results"] = {"candidate_review": review}
        payload.update(_log(state, "target_resolve", status="NEED_CLARIFICATION", target_resolve_mode="candidate_set",
                           candidate_source=candidate_set.source.value,
                           candidate_count=candidate_count,
                           candidate_review_status=str(review.status),
                           candidate_review_next_action=str(review.next_action),
                           next_action="CLARIFY", reason=reason))
        return payload

    # 6. Route based on next_action
    if review.next_action == NextAction.FINISH:
        candidates = list(candidate_set.candidates or [])
        goal_type = getattr(goal, "goal_type", None)
        goal_type_value = goal_type.value if goal_type else ""
        is_multi_candidate = len(candidates) > 1

        if candidates:
            first = candidates[0]
            # RECOMMENDATION/COMPARISON 多候选 → candidate_set_resolved（有候选集，无单一目标）
            # SINGLE_SHOP_QUERY 多候选（如序数引用"第一家"）→ 仍设 resolved_target
            needs_single_target = goal_type_value == GoalType.SINGLE_SHOP_QUERY.value
            if is_multi_candidate and not needs_single_target:
                resolution_stage = ResolutionStage.CANDIDATE_SET_RESOLVED
                # Mulit-candidate: ResolveShopResult with representative shop (NOT winner)
                resolved = ResolveShopResult(
                    status="RESOLVED",
                    resolved_shop=ShopRef(shop_id=first.shop_id, shop_name=first.shop_name),
                    confidence=1.0,
                    reason=f"candidate_set_{candidate_set.source.value}_multi",
                )
                payload["resolve_shop_result"] = resolved
                # Do NOT set resolved_target — no single target was resolved
                payload["target_resolution_status"] = "CANDIDATE_SET_RESOLVED"
                payload["resolution_stage"] = resolution_stage.value
                log_status = "CANDIDATE_SET_RESOLVED"
            else:
                resolution_stage = ResolutionStage.TARGET_RESOLVED
                resolved = ResolveShopResult(
                    status="RESOLVED",
                    resolved_shop=ShopRef(shop_id=first.shop_id, shop_name=first.shop_name),
                    confidence=1.0,
                    reason=f"candidate_set_{candidate_set.source.value}",
                )
                payload["resolve_shop_result"] = resolved
                payload["resolved_target"] = resolved
                payload["target_resolution_status"] = "RESOLVED"
                payload["resolution_stage"] = resolution_stage.value
                log_status = "RESOLVED"
        else:
            payload["target_resolution_status"] = "NOT_FOUND"
            payload["resolution_stage"] = ResolutionStage.TARGET_NOT_FOUND.value
            log_status = "NOT_FOUND"

        payload["reference_resolution_source"] = "candidate_set"
        payload.update(_log(state, "target_resolve", status=log_status, target_resolve_mode="candidate_set",
            candidate_source=candidate_set.source.value,
            candidate_count=len(candidates),
            candidate_review_status=str(review.status),
            candidate_review_next_action=str(review.next_action),
            next_action="FINISH"))
        return payload

    if review.next_action == NextAction.CLARIFY:
        reason = review.reason or "candidate_set_need_clarification"
        resolved = ResolveShopResult(status="NOT_FOUND", confidence=0.0, reason=reason)
        pending = build_pending_clarification(
            original_text=str(state.get("raw_text", "") or ""),
            original_semantic_frame=sf.model_dump(mode="json") if hasattr(sf, "model_dump") else _session_state_dict(sf),
            original_task_type=getattr(sf, "task_type", "") or state.get("task_type", ""),
            candidate_targets=_pending_candidate_targets(candidate_set),
            reason=reason,
            source_node="target_resolve",
        )
        payload["resolve_shop_result"] = resolved
        payload["pending_clarification"] = pending
        payload["target_resolution_status"] = "NOT_FOUND"
        payload["final_response"] = format_pending_prompt(pending)
        payload["session_state_after"] = session_snapshot
        payload.update(_log(state, "target_resolve", status="NEED_CLARIFICATION",
                           target_resolve_mode="candidate_set",
                           candidate_source=candidate_set.source.value,
                           candidate_count=len(candidate_set.candidates or []),
                           candidate_review_status=str(review.status),
                           candidate_review_next_action=str(review.next_action),
                           next_action="CLARIFY", reason=reason))
        return payload

    resolved = ResolveShopResult(status="NOT_FOUND", confidence=0.0,
                                  reason=review.reason or "candidate_set_unsupported")
    payload["resolve_shop_result"] = resolved
    payload["target_resolution_status"] = "NOT_FOUND"
    payload["final_response"] = "暂时无法完成这个请求，请换个说法试试。"
    payload["candidate_source_origin"] = candidate_set.source.value
    payload["fallback_reason"] = review.reason or "candidate_set_unsupported"
    payload["session_state_after"] = session_snapshot
    payload.update(_log(state, "target_resolve", status="NOT_FOUND",
                       target_resolve_mode="candidate_set",
                       candidate_source=candidate_set.source.value,
                       candidate_count=len(candidate_set.candidates or []),
                       candidate_review_status=str(review.status),
                       candidate_review_next_action=str(review.next_action),
                       next_action="FALLBACK", reason=review.reason))
    return payload


def _h_clarify_decide(state: GraphState) -> dict:
    resolution_stage = state.get("resolution_stage") or ""
    # Multi-candidate (comparison/recommendation): candidate_set_resolved → proceed WITHOUT resolved_target
    if resolution_stage == ResolutionStage.CANDIDATE_SET_RESOLVED.value:
        return {
            "resolution_stage": resolution_stage,
            **_log(state, "clarify_decide", decision="proceed_candidate_set"),
        }
    if state.get("task_type") == TaskType.recommendation.value:
        return {
            "resolved_target": state.get("resolved_target") or state.get("resolve_shop_result"),
            **_log(state, "clarify_decide", decision="proceed_recommendation"),
        }
    rs = state.get("resolved_target") or state.get("resolve_shop_result")
    if rs is not None:
        rs_dict = _to_dict(rs)
        status = rs_dict.get("status", getattr(rs, "status", ""))
        reason = str(rs_dict.get("reason", getattr(rs, "reason", "")) or "")
        if status == "RESOLVED":
            return {"resolved_target": rs, "resolution_stage": resolution_stage,
                    **_log(state, "clarify_decide", decision="proceed")}
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return {**_log(state, "clarify_decide", decision="clarify")}
        if reason in {"comparison_requires_at_least_two_shops", "comparison_too_many_shops",
                       "pronoun_without_current_shop", "ordinal_out_of_range"}:
            from .._compat import _comparison_reason_response
            return {
                "final_response": str(state.get("final_response", "") or _comparison_reason_response(reason)),
                **_log(state, "clarify_decide", decision="comparison_prompt"),
            }
        return {"final_response": "没有找到这家店，请提供完整店名。",
                **_log(state, "clarify_decide", decision="not_found")}
    return _log(state, "clarify_decide", decision="no_result")


def _h_evidence_planner(state: GraphState) -> dict:
    goal = state.get("local_life_goal_draft")
    candidate_set = state.get("effective_candidate_set") or state.get("candidate_set")
    if goal is None or candidate_set is None:
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "goal and effective_candidate_set are required",
            "failed_stage": "evidence_planner",
            **_log(state, "evidence_planner", status="failed", evidence_plan_source="strict",
                  missing_goal=goal is None, missing_candidate_set=candidate_set is None,
                  reason="missing_goal_or_effective_candidate_set"),
        }
    if getattr(goal, "goal_type", None) == GoalType.RECOMMENDATION:
        plan_payload = build_recommendation_execution_plan(
            state.get("semantic_frame") or {},
            location=_user_location(state),
            fallback_query=str(state.get("raw_text", "") or ""),
        )
        plan = ExecutionPlan.model_validate(plan_payload.get("plan") or {})
        plan.plan_source = plan.plan_source or "deterministic_recommendation_builder"
        return {
            "execution_plan": plan,
            "execution_plan_source": plan.plan_source,
            "planning_llm_backend": "",
            "planning_llm_called": False,
            "planning_failure_code": "",
            "task_type": plan.task_type,
            "task_type_source": "evidence_planner",
            "reference_resolution_source": "candidate_set",
            **_log(
                state,
                "evidence_planner",
                evidence_plan_source="deterministic_recommendation_builder",
                missing_goal=False,
                missing_candidate_set=False,
                tool_calls=len(plan.tool_calls),
                task_type=plan.task_type,
                planner_source=plan.plan_source or "deterministic_recommendation_builder",
                candidate_count=len(candidate_set.candidates or []),
            ),
        }
    from ..graph_builder import call_llm as _call_llm, get_llm_backend_snapshot as _get_llm_backend_snapshot
    backend_snapshot = _get_llm_backend_snapshot()
    strict_llm = str(backend_snapshot.get("backend_kind", "") or "") not in {"", "fake_llm", "fake"}
    plan, meta = plan_evidence_with_llm(
        goal=goal,
        candidate_set=candidate_set,
        location=_user_location(state),
        semantic_frame=state.get("semantic_frame"),
        raw_text=str(state.get("raw_text", "") or ""),
        llm_call=_call_llm,
        strict=strict_llm,
    )
    if plan is None:
        return {
            "error_code": meta.get("error_code", "EVIDENCE_PLANNER_FAILED"),
            "error_message": meta.get("error_message", "evidence planner llm failed"),
            "failed_stage": "evidence_planner",
            "planning_llm_backend": meta.get("llm_backend", ""),
            "planning_llm_called": True,
            "planning_failure_code": meta.get("error_code", "EVIDENCE_PLANNER_FAILED"),
            **_log(state, "evidence_planner", status="failed", evidence_plan_source="llm",
                  reason=meta.get("error_code", "EVIDENCE_PLANNER_FAILED")),
        }
    task_type = str(plan.task_type or "")
    return {
        "execution_plan": plan,
        "execution_plan_source": plan.plan_source or "llm_evidence_planner",
        "planning_llm_backend": meta.get("llm_backend", ""),
        "planning_llm_called": True,
        "planning_failure_code": "",
        "task_type": task_type,
        "task_type_source": "evidence_planner",
        "reference_resolution_source": "candidate_set",
        **_log(state, "evidence_planner", evidence_plan_source="strict",
              missing_goal=False, missing_candidate_set=False,
              tool_calls=len(plan.tool_calls), task_type=task_type,
              planner_source=plan.plan_source or "llm_evidence_planner",
              candidate_count=len(candidate_set.candidates or [])),
    }


def _h_plan_validator(state: GraphState) -> dict:
    plan = state.get("execution_plan")
    if plan is None:
        return {
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "execution_plan is required",
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason="missing_execution_plan"),
        }
    if not plan.tool_calls and not plan.stages:
        return {
            "error_code": "INVALID_PLAN",
            "error_message": "execution_plan must contain tool_calls or stages",
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason="empty_plan"),
        }
    validator = ExecutionPlanValidator()
    from .._compat import _resolved_shop_ids_from_state, _plan_validation_error_code
    resolved_shop_ids = _resolved_shop_ids_from_state(state)
    report = validator.validate(plan, resolved_shop_ids=resolved_shop_ids or None)
    if not report.passed:
        error_code = _plan_validation_error_code(report.errors)
        error_message = "; ".join(report.errors)
        return {
            "error_code": error_code,
            "error_message": error_message,
            "plan_validation_result": "failed",
            "failed_stage": "plan_validator",
            "validated_plan": None,
            **_log(state, "plan_validator", status="failed", reason=error_code),
        }
    return {
        "error_code": "",
        "error_message": "",
        "plan_validation_result": "pass",
        "failed_stage": "",
        "validated_plan": plan,
        **_log(state, "plan_validator", status="pass"),
    }


def _h_expand_search(state: GraphState) -> dict:
    """P2 expand_search: relax candidate constraints and re-resolve."""
    from ...domain.candidate import CandidateSpec

    goal = state.get("local_life_goal_draft")
    spec = state.get("candidate_spec")
    if goal is None or spec is None:
        return {
            "fallback_reason": "expand_search_missing_goal_or_spec",
            **_log(state, "expand_search", status="FALLBACK", reason="missing_goal_or_candidate_spec"),
        }
    relaxed = deepcopy(spec)
    if isinstance(relaxed, CandidateSpec):
        old_limit = relaxed.limit or 3
        relaxed.limit = old_limit * 2 + 5
        relaxed.filters = {}
        relaxed.sort_by = []
    elif isinstance(relaxed, dict):
        old_limit = int(relaxed.get("limit", 3) or 3)
        relaxed["limit"] = old_limit * 2 + 5
        relaxed["filters"] = {}
        relaxed["sort_by"] = []
    else:
        old_limit = 3

    resolver = CandidateResolver()
    expanded_candidate_set = resolver.resolve(goal, relaxed, state)
    review = review_candidate_set(goal, expanded_candidate_set)

    payload: dict[str, Any] = {
        "candidate_spec": relaxed,
        "candidate_set": expanded_candidate_set,
        "review_results": dict(state.get("review_results") or {}),
    }
    payload["review_results"]["candidate_review"] = review

    ss = _session_store_state(state)
    ss.last_candidate_set = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in (expanded_candidate_set.candidates or [])
    ]
    ss.last_candidate_spec = (
        relaxed.model_dump() if hasattr(relaxed, "model_dump") else deepcopy(relaxed)
    )
    payload["session_state"] = ss
    payload.update(_log(state, "expand_search",
                        old_limit=old_limit,
                        new_limit=relaxed.limit if isinstance(relaxed, CandidateSpec) else relaxed.get("limit"),
                        candidates_before=len(state.get("candidate_set", {}).candidates if hasattr(state.get("candidate_set"), "candidates") else []),
                        candidates_after=len(expanded_candidate_set.candidates or []),
                        review_action=review.next_action, review_status=review.status))
    return payload


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _planning_failure_route(state: dict[str, Any]) -> str:
    from .._routes import _OUTER_ROUTE_CLARIFY, _OUTER_ROUTE_EXECUTE, _OUTER_ROUTE_FALLBACK

    error_code = str(state.get("error_code", "") or "")
    error_message = str(state.get("error_message", "") or "")
    failed_stage = str(state.get("failed_stage", "") or "")
    if "missing_goal" in error_message or "missing_candidate_set" in error_message or "missing_goal_draft" in error_message:
        return _OUTER_ROUTE_CLARIFY
    if error_code in {"SCHEMA_VALIDATION_FAILED"}:
        if any(token in error_message for token in ("goal", "candidate", "target")):
            return _OUTER_ROUTE_CLARIFY
    if error_code in {"TOOL_NOT_REGISTERED", "INVALID_ARGUMENT"} or failed_stage == "plan_validator":
        return _OUTER_ROUTE_FALLBACK
    if error_code:
        return _OUTER_ROUTE_FALLBACK
    return _OUTER_ROUTE_EXECUTE
