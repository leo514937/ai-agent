"""state_update_plan subgraph — session persistence and response emission.

Plans what session fields to update based on turn outcome, persists
the session state to the store, and emits the final response as the
terminal step of the graph.
"""

from __future__ import annotations

from typing import Any

from .._compat import (
    _log,
    _run_step,
    _run_steps,
    _session_state_dict,
    _session_store_state,
    _state_delta,
    _to_dict,
)
from ...domain.graph_state import GraphState
from ...domain.state import SessionState, SessionWriteDirective
from ...planning.plans.state_update_planner import plan_state_update
from ...session.store import get_session_store


def h_state_update_plan_outer(state: GraphState) -> dict:
    """Outer wrapper: plan state update → persist → emit."""
    before = dict(state)
    working = _run_steps(state, [_h_state_update_plan, _h_persist_session, _h_emit_response])
    return _state_delta(before, working)


# ---------------------------------------------------------------------------
# Internal step handlers
# ---------------------------------------------------------------------------


def _h_state_update_plan(state: GraphState) -> dict:
    resolve_shop_result = state.get("resolve_shop_result")
    pending = state.get("pending_clarification")
    resolved = state.get("resolved_target") or resolve_shop_result
    if pending is not None and resolve_shop_result is not None:
        resolved = resolve_shop_result
    resolved_status = ""
    if resolved is not None:
        resolved_status = getattr(resolved, "status", "") or _session_state_dict(resolved).get("status", "")
    task_type = state.get("task_type")
    task_type_value = task_type.value if hasattr(task_type, "value") else str(task_type or "")
    turn_context = {
        "resolved_target": resolved,
        "resolved_shop": resolved,
        "current_shop": state.get("current_shop"),
        "pending_clarification": pending,
        "last_recommendation_list": state.get("last_recommendation_list", []),
        "comparison_targets": state.get("comparison_targets", []),
        "comparison_result": _to_dict(state.get("evidence_pack")).get("comparison_matrix") if state.get("evidence_pack") is not None else state.get("comparison_result"),
        "tool_result_set": state.get("tool_result_set") or state.get("tool_results", {}),
        "execution_plan": state.get("validated_plan") or state.get("execution_plan"),
    }
    plan_dict = plan_state_update(
        turn_context,
        task_type_value,
        resolved_status,
        pending_check_result=str(state.get("pending_check_result", "") or ""),
    )
    directive = SessionWriteDirective(
        set_fields=plan_dict.get("set_fields", {}),
        clear_fields=plan_dict.get("clear_fields", []),
    )
    return {
        "state_update_plan": directive,
        **_log(state, "state_update_plan",
              set_fields=list(directive.set_fields.keys()),
              clear_fields=list(directive.clear_fields)),
    }


def _h_persist_session(state: GraphState) -> dict:
    session_state = state.get("session_state") or SessionState()
    directive = state.get("state_update_plan")
    if directive is not None:
        directive = directive if isinstance(directive, SessionWriteDirective) else SessionWriteDirective(
            set_fields=_session_state_dict(directive).get("set_fields", {}),
            clear_fields=_session_state_dict(directive).get("clear_fields", []),
        )
        for field_name, value in directive.set_fields.items():
            resolved = state.get(field_name) if value is None else value
            if resolved is not None:
                setattr(session_state, field_name,
                        _session_state_dict(resolved) if field_name in {"current_shop", "pending_clarification"} and not isinstance(resolved, dict) else resolved)
        for field_name in directive.clear_fields:
            default_value = getattr(SessionState(), field_name)
            if hasattr(default_value, "model_copy"):
                default_value = default_value.model_copy(deep=True)
            elif isinstance(default_value, (list, dict, set)):
                default_value = type(default_value)(default_value)
            setattr(session_state, field_name, default_value)
    store = get_session_store()
    store.save(str(state.get("session_id", "") or ""), session_state)
    return {
        "session_state": session_state,
        "session_state_after": session_state.model_copy(deep=True),
        "current_shop": session_state.current_shop,
        "last_recommendation_list": session_state.last_recommendation_list,
        "active_constraints": session_state.active_constraints,
        "comparison_result": session_state.comparison_result,
        "pending_clarification": session_state.pending_clarification,
        "comparison_targets": session_state.comparison_targets,
        **_log(state, "persist_session_state"),
    }


def _h_emit_response(state: GraphState) -> dict:
    return _log(state, "emit_response")
