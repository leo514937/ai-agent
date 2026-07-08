"""state_update_plan subgraph — session persistence and response emission.

Plans what session fields to update based on turn outcome, persists
the session state to the store, and emits the final response as the
terminal step of the graph.
"""

from __future__ import annotations

import logging
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
from ...domain.enums import TaskType
from ...domain.graph_state import GraphState
from ...domain.state import SessionState, SessionValueMeta, SessionWriteDirective
from ...memory.preferences import build_preference_memories_from_semantic_frame, merge_preference_memory_summaries
from ...observability.file_logger import get_python_service_logger, log_kv
from ...core import StateCore
from ...planning.plans.state_update_planner import plan_state_update
from ...session.store import get_session_store

_LOGGER = get_python_service_logger()
_STATE_CORE = StateCore()


def h_state_update_plan_outer(state: GraphState) -> dict:
    """Outer wrapper: plan state update → persist → emit."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="state_update_plan", trace_id=state.get("trace_id", ""), answer_source=state.get("answer_source", ""))
    working = _run_steps(state, [_h_state_update_plan, _h_persist_session, _h_emit_response])
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_EXIT]", tone="route", subgraph="state_update_plan", final_response=working.get("final_response", ""), session_id=working.get("session_id", ""))
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
    comparison_target_resolution = _to_dict(state.get("comparison_target_resolution"))
    semantic_frame = _to_dict(state.get("semantic_frame"))
    state_comparison_targets = list(state.get("comparison_targets", []) or [])
    semantic_comparison_targets = list(semantic_frame.get("comparison_targets", []) or [])
    comparison_targets_source = ""
    if state_comparison_targets:
        comparison_targets_source = "comparison_targets"
    elif comparison_target_resolution.get("targets"):
        comparison_targets_source = "comparison_target_resolution"
    elif semantic_comparison_targets:
        comparison_targets_source = "semantic_frame.comparison_targets"
    comparison_targets = (
        comparison_target_resolution.get("targets")
        or state_comparison_targets
        or semantic_comparison_targets
    )
    if not comparison_target_resolution and task_type_value == TaskType.comparison.value and comparison_targets:
        comparison_target_resolution = {
            "status": "RESOLVED" if len(comparison_targets) >= 2 else "NEED_CLARIFICATION",
            "targets": list(comparison_targets),
            "unresolved_targets": [],
            "reason": "comparison_targets_resolved" if len(comparison_targets) >= 2 else "comparison_targets_need_clarification",
        }
    turn_context = {
        "workflow_name": state.get("workflow_name"),
        "local_life_goal_draft": state.get("local_life_goal_draft"),
        "resolved_target": resolved,
        "resolved_shop": resolved,
        "target_resolution": state.get("target_resolution"),
        "current_shop": state.get("current_shop"),
        "active_constraints": state.get("active_constraints"),
        "pending_clarification": pending,
        "merge_clarification_result": state.get("merge_clarification_result"),
        "restored_task": state.get("restored_task"),
        "reference_resolution_source": state.get("reference_resolution_source"),
        "task_type_source": state.get("task_type_source"),
        "clarification_resolution": state.get("clarification_resolution"),
        "resume_strategy": state.get("resume_strategy"),
        "active_turn_result": state.get("active_turn_result"),
        "last_recommendation_list": state.get("last_recommendation_list", []),
        "comparison_targets": comparison_targets,
        "comparison_targets_source": comparison_targets_source,
        "comparison_target_resolution": comparison_target_resolution,
        "resolution_stage": state.get("resolution_stage", ""),
        "user_location": state.get("user_location"),
        "evidence_pack": state.get("evidence_pack"),
        "comparison_result": _to_dict(state.get("evidence_pack")).get("comparison_matrix") if state.get("evidence_pack") is not None else state.get("comparison_result"),
        "tool_result_set": state.get("tool_result_set") or state.get("tool_results", {}),
        "execution_plan": state.get("validated_plan") or state.get("execution_plan"),
    }
    comparison_result = turn_context.get("comparison_result")
    has_comparison_hint = bool(
        comparison_targets
        or comparison_result
        or _to_dict(turn_context.get("semantic_frame")).get("comparison_intent")
        or any(token in str(turn_context.get("raw_text", "") or "") for token in ("对比", "比较", "比一比", "哪个好", "谁更好"))
    )
    if turn_context.get("comparison_result") is None and turn_context.get("pending_clarification") is None and has_comparison_hint:
        synthesized_comparison_rows = [
            {
                "shop_id": str(item.get("shop_id", "")).strip(),
                "shop_name": str(item.get("shop_name", "")).strip(),
            }
            for item in (
                comparison_targets
                if comparison_targets
                else turn_context.get("last_recommendation_list", [])
            )
            if str(item.get("shop_id", "")).strip() or str(item.get("shop_name", "")).strip()
        ]
        if synthesized_comparison_rows:
            turn_context["comparison_result"] = {"rows": synthesized_comparison_rows}
    plan_dict = _STATE_CORE.plan_state_update(
        turn_context,
        task_type_value,
        resolved_status,
        pending_check_result=str(state.get("pending_check_result", "") or ""),
    )
    directive = _STATE_CORE.build_state_patch(
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
                if field_name.endswith("_meta") and isinstance(resolved, dict):
                    resolved = SessionValueMeta.model_validate(resolved)
                setattr(session_state, field_name,
                        _session_state_dict(resolved) if field_name in {"current_shop", "pending_clarification"} and not isinstance(resolved, dict) else resolved)
        for field_name in directive.clear_fields:
            default_value = getattr(SessionState(), field_name)
            if hasattr(default_value, "model_copy"):
                default_value = default_value.model_copy(deep=True)
            elif isinstance(default_value, (list, dict, set)):
                default_value = type(default_value)(default_value)
            setattr(session_state, field_name, default_value)
    semantic_frame = state.get("semantic_frame")
    user_id = str(state.get("user_id", "") or getattr(session_state, "user_id", "") or "").strip()
    session_identifier = str(state.get("session_id", "") or "").strip()
    preference_memories = build_preference_memories_from_semantic_frame(
        semantic_frame,
        user_id=user_id or session_identifier,
        session_id=session_identifier,
        evidence_ref=str(state.get("trace_id", "") or state.get("turn_id", "") or session_identifier),
    )
    if preference_memories:
        session_state.active_preferences = merge_preference_memory_summaries(
            getattr(session_state, "active_preferences", []),
            preference_memories,
        )
    if not getattr(session_state, "last_recommendation_list", None) and state.get("task_type") == TaskType.recommendation.value:
        evidence_dict = _to_dict(state.get("evidence_pack"))
        ranking_snapshot = _to_dict(evidence_dict.get("ranking_snapshot"))
        fallback_recommendations = [
            _to_dict(item)
            for item in (ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or evidence_dict.get("last_recommendation_list") or [])
            if _to_dict(item)
        ]
        if fallback_recommendations:
            session_state.last_recommendation_list = fallback_recommendations
            if not getattr(session_state, "last_recommendation_list_meta", None):
                session_state.last_recommendation_list_meta = SessionValueMeta(
                    source="evidence_pack",
                    evidence_ref=str(ranking_snapshot.get("snapshot_id", "") or ""),
                )
    comparison_resolution = _to_dict(state.get("comparison_target_resolution"))
    if str(comparison_resolution.get("status", "") or "").upper() == "RESOLVED":
        resolved_targets = [
            _to_dict(item)
            for item in (comparison_resolution.get("targets") or [])
            if str(_to_dict(item).get("shop_id", "") or "").strip() or str(_to_dict(item).get("shop_name", "") or "").strip()
        ]
        if resolved_targets:
            session_state.comparison_targets = resolved_targets
    if not getattr(session_state, "comparison_targets", None):
        comparison_result = _to_dict(state.get("comparison_result"))
        comparison_rows = [
            _to_dict(item)
            for item in (comparison_result.get("rows") or [])
            if str(_to_dict(item).get("shop_id", "") or "").strip() or str(_to_dict(item).get("shop_name", "") or "").strip()
        ]
        if comparison_rows and not state.get("pending_clarification"):
            session_state.comparison_targets = comparison_rows
    comparison_result = _to_dict(state.get("comparison_result"))
    if comparison_result:
        session_state.comparison_result = comparison_result
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
