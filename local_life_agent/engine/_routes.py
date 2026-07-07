"""Route constants, functions, and maps extracted from graph_builder.py.

Every graph transition lives here — route constants define the labels,
route functions read state and return the next edge, route maps pair
functions with their destinations for LangGraph ``add_conditional_edges``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from .. import config
from ..domain.enums import TopIntent
from ..domain.graph_state import GraphState
from ..domain.state import SessionState
from ._compat import _to_dict

# ===================================================================
# Route constants  (outer-level names — labels on the architecture diagram)
# ===================================================================

_OUTER_ROUTE_TERMINAL = "terminal"
_OUTER_ROUTE_DIRECT = "direct"
_OUTER_ROUTE_REJECT = "reject"
_OUTER_ROUTE_LOCAL_LIFE = "local_life"
_OUTER_ROUTE_CLARIFICATION_REPLY = "clarification_reply"
_OUTER_ROUTE_PROCEED = "proceed"
_OUTER_ROUTE_EXECUTE = "execute"
_OUTER_ROUTE_ENOUGH = "enough"
_OUTER_ROUTE_DEGRADE = "degrade"
_OUTER_ROUTE_CLARIFY = "clarify"
_OUTER_ROUTE_FALLBACK = "fallback"
_OUTER_ROUTE_RETRY = "retry"
_OUTER_ROUTE_PASS = "pass"
_OUTER_ROUTE_FALLBACK_READY = "fallback_ready"
_OUTER_ROUTE_CLARIFY_READY = "clarify_ready"

# ===================================================================
# Legacy / inner-level route functions  (used inside subgraphs)
# ===================================================================


def _route_check_pending(state: GraphState) -> str:
    """§3 —Route check_pending_clarification."""
    result = str(state.get("pending_check_result", "") or "")
    if result == "restore":
        return "target_resolve"
    if result in ("invalid", "out_of_range", "expired"):
        return "clarify_response"
    return "basic_input_validate"


def _route_basic_validate(state: GraphState) -> str:
    """Route basic_input_validate."""
    err = state.get("error_code", "")
    if err:
        return "emit_response"
    return "normalize_text"


def _route_hard_guard(state: GraphState) -> str:
    """§3 —Route hard_guard."""
    result = state.get("guard_result", "")
    if result in ("safe", "ok"):
        return "top_intent_router"
    if result in ("invalid", "greeting", "capability"):
        return "emit_response"
    return "emit_response"


def _route_top_intent(state: GraphState) -> str:
    """§3 —Route top_intent_router."""
    intent = state.get("top_intent")
    if intent in (TopIntent.local_life, "local_life"):
        return "semantic_parse"
    if intent in (
        TopIntent.chat,
        "chat",
        TopIntent.out_of_scope,
        TopIntent.unsafe,
        TopIntent.invalid,
        TopIntent.capability,
        "out_of_scope",
        "unsafe",
        "invalid",
        "capability",
    ):
        return "emit_response"
    return "emit_response"


def _route_semantic_parse(state: GraphState) -> str:
    """§3 + §2 —Route semantic_parse."""
    err = state.get("error_code", "")
    if err == "LLM_JSON_PARSE_ERROR":
        return "clarify_response"
    if err:
        return "clarify_response"
    return "slot_extractor"


def _route_frame_validator(state: GraphState) -> str:
    """§2 —Route frame_validator."""
    err = state.get("error_code", "")
    if err:
        return "clarify_response"
    return "context_recovery"


# ===================================================================
# P2 route functions
# ===================================================================


def _route_goal_review(state: GraphState) -> str:
    """Route from goal_review based on next_action."""
    gr = state.get("goal_review_result")
    if gr is None:
        return "target_resolve"
    next_action = getattr(gr, "next_action", "FINISH") or "FINISH"
    if isinstance(next_action, Enum):
        next_action = next_action.value
    if next_action in ("FINISH",):
        return "target_resolve"
    if next_action in ("CLARIFY",):
        return "clarify_response"
    if next_action in ("UNSUPPORTED_ANSWER",):
        return "emit_response"
    if next_action in ("FALLBACK",):
        return "fallback_answer"
    return "target_resolve"


def _route_clarify_decide(state: GraphState) -> str:
    """§3 —Route clarify_decide based on resolve_shop_result.status."""
    rs = state.get("resolve_shop_result")
    if rs is not None:
        rs_dict = _to_dict(rs)
        status = rs_dict.get("status", getattr(rs, "status", ""))
        reason = str(rs_dict.get("reason", getattr(rs, "reason", "")) or "")
        if status == "RESOLVED":
            return "evidence_planner"
        if status in ("AMBIGUOUS", "LOW_CONFIDENCE"):
            return "clarify_response"
        if reason in {"comparison_requires_at_least_two_shops", "comparison_too_many_shops", "pronoun_without_current_shop", "ordinal_out_of_range"}:
            return "emit_response"
        if status == "NOT_FOUND":
            return "emit_response"
    return "clarify_response"


def _route_plan_validator(state: GraphState) -> str:
    """§3 —Route plan_validator."""
    err = state.get("error_code", "")
    if err:
        return "fallback_answer"
    return "tool_execute"


def _route_decision_review(state: GraphState) -> str:
    """Route from decision_review based on next_action."""
    dr = state.get("decision_review_result")
    if dr is None:
        return "fallback_answer"
    next_action = getattr(dr, "next_action", "FINISH") or "FINISH"
    if isinstance(next_action, Enum):
        next_action = next_action.value
    if next_action in (None, "", "None"):
        return "fallback_answer"

    from ..domain.state import SessionState

    # Track replan counters for loop prevention
    if next_action in ("REPLAN_EVIDENCE",):
        session = state.get("session_state")
        current = 0
        if isinstance(session, SessionState):
            current = session.replan_counters.get("replan_evidence", 0)
        if current >= config.MAX_REPLAN_EVIDENCE_ROUNDS:
            return "fallback_answer"
        if session is not None:
            from ..planning.replan_policy import increment_replan_evidence
            increment_replan_evidence(session)
        return "evidence_planner"

    if next_action in ("EXPAND_SEARCH",):
        session = state.get("session_state")
        current = 0
        if isinstance(session, SessionState):
            current = session.replan_counters.get("expand_search", 0)
        if current >= config.MAX_EXPAND_SEARCH_ROUNDS:
            return "fallback_answer"
        if session is not None:
            from ..planning.replan_policy import increment_expand_search
            increment_expand_search(session)
        return "expand_search"

    if next_action in ("DEGRADE_ANSWER",):
        return "answer_plan_build"
    if next_action in ("FALLBACK",):
        return "fallback_answer"
    if next_action in ("UNSUPPORTED_ANSWER",):
        return "emit_response"
    if next_action in ("CLARIFY",):
        return "clarify_response"
    if next_action in ("FINISH",):
        return "answer_plan_build"
    return "fallback_answer"


def _route_evidence_review(state: GraphState) -> str:
    """Route from evidence_review based on next_action.

    Routes only through the P2 decision path.
    """
    review_results = state.get("review_results") or {}
    evidence_review = review_results.get("evidence_review") if isinstance(review_results, dict) else None

    if evidence_review is None:
        return "decision_planner"
    action = getattr(evidence_review, "action", "") or ""
    if isinstance(action, Enum):
        action = action.value
    next_action = getattr(evidence_review, "next_action", "FINISH") or "FINISH"
    if isinstance(next_action, Enum):
        next_action = next_action.value
    route_action = str(action or "").strip().lower()
    if route_action and route_action != "proceed":
        next_action = {
            "retry": "REPLAN_EVIDENCE",
            "replan_missing_facets": "REPLAN_EVIDENCE",
            "expand_search": "EXPAND_SEARCH",
            "clarify": "CLARIFY",
            "degrade": "DEGRADE_ANSWER",
            "fallback": "FALLBACK",
        }.get(route_action, next_action)

    if next_action in ("REPLAN_EVIDENCE",):
        session = state.get("session_state")
        current = 0
        if isinstance(session, SessionState):
            current = session.replan_counters.get("replan_evidence", 0)
        if current >= config.MAX_REPLAN_EVIDENCE_ROUNDS:
            return "fallback_answer"
        if session is not None:
            from ..planning.replan_policy import increment_replan_evidence
            increment_replan_evidence(session)
        return "evidence_planner"

    if next_action in ("FALLBACK",):
        return "fallback_answer"
    if next_action in ("CLARIFY",):
        return "clarify_response"
    if next_action in ("DEGRADE_ANSWER", "FINISH"):
        return "decision_planner"
    return "fallback_answer"


def _route_tool_execute(state: GraphState) -> str:
    """§3 —Route tool_execute."""
    return "evidence_build"


def _route_answer_verify(state: GraphState) -> str:
    """§3 —Route answer_verify."""
    vr = state.get("verify_result", "pass")
    rc = state.get("rewrite_count", 0)
    if vr == "pass":
        return "final_response_build"
    if vr in ("rewrite_needed", "rewrite_exhausted"):
        if rc < _get_rewrite_limit():
            return "rewrite"
        return "fallback_answer"
    return "final_response_build"


def _get_rewrite_limit() -> int:
    return max(1, config.MAX_REWRITE_ATTEMPTS - 1)


# ===================================================================
# Outer-level route functions  (read by LangGraph conditional edges)
# ===================================================================


def _route_intake_guard(state: GraphState) -> str:
    return str(state.get("intake_route", "") or _OUTER_ROUTE_TERMINAL)


def _route_merge_clarification(state: GraphState) -> str:
    return str(state.get("merge_clarification_route", "") or _OUTER_ROUTE_CLARIFY)


def _route_understanding_subgraph(state: GraphState) -> str:
    return str(state.get("understanding_route", "") or _OUTER_ROUTE_CLARIFY)


def _route_planning_subgraph(state: GraphState) -> str:
    return str(state.get("planning_route", "") or _OUTER_ROUTE_FALLBACK)


def _route_execution_review_subgraph(state: GraphState) -> str:
    return str(state.get("execution_review_route", "") or _OUTER_ROUTE_FALLBACK)


def _route_response_subgraph(state: GraphState) -> str:
    return str(state.get("response_route", "") or _OUTER_ROUTE_PASS)


def _route_workflow_runner(state: GraphState) -> str:
    workflow_name = str(state.get("workflow_name", "") or "")
    workflow_entry_name = str(state.get("workflow_entry_name", "") or "")
    workflow_callable = str(state.get("workflow_callable", "") or "")
    response_mode = str(state.get("response_mode", "") or "")
    # discovery_decision 是主链路入口，但部分状态在经过 workflow_runner 后
    # 只会稳定保留 workflow_callable / response_mode。这里做三重判定，避免
    # 比较流因为单字段透传丢失被错误送回 response_subgraph。
    if workflow_name in {"discovery_decision", "recommendation_decision_workflow", "comparison_decision_workflow"} or workflow_entry_name in {"recommendation_decision_workflow", "comparison_decision_workflow"} or workflow_callable == "planning_subgraph" or response_mode == "comparison":
        return "planning_subgraph"
    return "response_subgraph"


# ===================================================================
# Route maps  (paired with route functions for LangGraph add_conditional_edges)
# ===================================================================

# Inner-level route maps (legacy nodes)
_CHECK_PENDING_ROUTES: dict[Any, str] = {
    "target_resolve": "target_resolve",
    "top_intent_router": "top_intent_router",
    "basic_input_validate": "basic_input_validate",
    "clarify_response": "clarify_response",
}

_BASIC_VALIDATE_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "normalize_text": "normalize_text",
}

_HARD_GUARD_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "top_intent_router": "top_intent_router",
}

_TOP_INTENT_ROUTES: dict[Any, str] = {
    "emit_response": "emit_response",
    "semantic_parse": "semantic_parse",
}

_SEMANTIC_PARSE_ROUTES: dict[Any, str] = {
    "clarify_response": "clarify_response",
    "frame_validator": "frame_validator",
    "slot_extractor": "slot_extractor",
}

_FRAME_VALIDATOR_ROUTES: dict[Any, str] = {
    "clarify_response": "clarify_response",
    "context_recovery": "context_recovery",
}

_CLARIFY_DECIDE_ROUTES: dict[Any, str] = {
    "evidence_planner": "evidence_planner",
    "clarify_response": "clarify_response",
    "emit_response": "emit_response",
}

_PLAN_VALIDATOR_ROUTES: dict[Any, str] = {
    "fallback_answer": "fallback_answer",
    "tool_execute": "tool_execute",
}

_GOAL_REVIEW_ROUTES: dict[Any, str] = {
    "target_resolve": "target_resolve",
    "clarify_response": "clarify_response",
    "emit_response": "emit_response",
    "fallback_answer": "fallback_answer",
}

_DECISION_REVIEW_ROUTES: dict[Any, str] = {
    "answer_plan_build": "answer_plan_build",
    "evidence_planner": "evidence_planner",
    "target_resolve": "target_resolve",
    "expand_search": "expand_search",
    "fallback_answer": "fallback_answer",
    "emit_response": "emit_response",
    "clarify_response": "clarify_response",
}

_EVIDENCE_REVIEW_ROUTES: dict[Any, str] = {
    "decision_planner": "decision_planner",
    "fallback_answer": "fallback_answer",
    "clarify_response": "clarify_response",
    "evidence_planner": "evidence_planner",
}

_TOOL_EXECUTE_ROUTES: dict[Any, str] = {
    "evidence_build": "evidence_build",
}

_ANSWER_VERIFY_ROUTES: dict[Any, str] = {
    "final_response_build": "final_response_build",
    "rewrite": "rewrite",
    "fallback_answer": "fallback_answer",
}

# Outer-level route maps (one per subgraph in the architecture diagram)
_GRAPH_INTAKE_ROUTES: dict[Any, str] = {
    _OUTER_ROUTE_DIRECT: "response_subgraph",
    _OUTER_ROUTE_REJECT: "response_subgraph",
    _OUTER_ROUTE_TERMINAL: "response_subgraph",
    _OUTER_ROUTE_CLARIFICATION_REPLY: "merge_clarification",
    _OUTER_ROUTE_LOCAL_LIFE: "understanding_subgraph",
}

_GRAPH_MERGE_ROUTES: dict[Any, str] = {
    _OUTER_ROUTE_PROCEED: "understanding_subgraph",
    _OUTER_ROUTE_EXECUTE: "planning_subgraph",
    _OUTER_ROUTE_CLARIFY: "response_subgraph",
    _OUTER_ROUTE_FALLBACK: "response_subgraph",
}

_GRAPH_UNDERSTANDING_ROUTES: dict[Any, str] = {
    _OUTER_ROUTE_PROCEED: "orchestration_router_shadow",
    _OUTER_ROUTE_CLARIFY: "response_subgraph",
    _OUTER_ROUTE_FALLBACK: "response_subgraph",
}

_GRAPH_PLANNING_ROUTES: dict[Any, str] = {
    _OUTER_ROUTE_EXECUTE: "execution_review_subgraph",
    _OUTER_ROUTE_CLARIFY: "response_subgraph",
    _OUTER_ROUTE_FALLBACK: "response_subgraph",
    _OUTER_ROUTE_RETRY: "planning_subgraph",
}

_GRAPH_EXECUTION_ROUTES: dict[Any, str] = {
    _OUTER_ROUTE_ENOUGH: "response_subgraph",
    _OUTER_ROUTE_DEGRADE: "response_subgraph",
    _OUTER_ROUTE_CLARIFY: "response_subgraph",
    _OUTER_ROUTE_FALLBACK: "response_subgraph",
    _OUTER_ROUTE_RETRY: "planning_subgraph",
}

_GRAPH_RESPONSE_ROUTES: dict[Any, str] = {
    _OUTER_ROUTE_PASS: "state_update_plan",
    _OUTER_ROUTE_FALLBACK_READY: "state_update_plan",
    _OUTER_ROUTE_CLARIFY_READY: "state_update_plan",
}

_WORKFLOW_RUNNER_ROUTES: dict[Any, str] = {
    "planning_subgraph": "planning_subgraph",
    "response_subgraph": "response_subgraph",
}

