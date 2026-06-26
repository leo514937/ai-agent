"""intake_guard_router subgraph - entry routing.

Runs the input pipeline (receive -> load session -> validate -> normalize
-> hard_guard -> top_intent_router) and decides whether to route to
local-life understanding, merge a pending clarification, or go straight
to response.
"""

from __future__ import annotations

import logging
from typing import Any

from .._compat import (
    _OUTER_WRAPPER_EXCLUDE_FIELDS,
    _log,
    _response_mode_for_top_intent,
    _run_step,
    _state_delta,
)
from .._routes import (
    _OUTER_ROUTE_CLARIFICATION_REPLY,
    _OUTER_ROUTE_LOCAL_LIFE,
    _OUTER_ROUTE_REJECT,
    _OUTER_ROUTE_TERMINAL,
)
from ...domain.enums import TopIntent
from ...domain.graph_state import GraphState
from ...input.hard_guard import check_hard_guard
from ...input.normalizer import normalize_text as input_normalize_text
from ...input.receiver import receive_input as assemble_turn_input
from ...input.validator import validate_basic_input
from ...semantic.intent_parser import parse_top_intent
from ...session.store import get_session_store
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()


def h_intake_guard_router(state: GraphState) -> dict:
    """Outer wrapper: intake -> guard -> route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="intake_guard_router", trace_id=state.get("trace_id", ""), raw_text=state.get("raw_text", ""))
    working = _run_step(state, _h_receive_input)
    working = _run_step(working, _h_load_session)
    working = _run_step(working, _h_basic_validate)
    working = _run_step(working, _h_normalize_text)
    working = _run_step(working, _h_hard_guard)
    if str(working.get("guard_result", "") or "") not in {"safe", "ok"}:
        session_before = working.get("session_state_before") or working.get("session_state")
        has_pending = bool(
            getattr(session_before, "pending_clarification", None)
            if session_before is not None
            else False
        )
        response_mode = _response_mode_for_top_intent(working.get("top_intent"))
        if working.get("error_code"):
            response_mode = _OUTER_ROUTE_REJECT
            route = _OUTER_ROUTE_TERMINAL
        elif has_pending:
            route = _OUTER_ROUTE_CLARIFICATION_REPLY
        else:
            route = _OUTER_ROUTE_TERMINAL
        after = {
            **working,
            "intake_route": route,
            "response_mode": response_mode,
        }
        log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="intake_guard_router", route=route, response_mode=response_mode, reason="hard_guard_or_input_error")
        return _state_delta(before, after, always_include={"intake_route", "response_mode"})

    working = _run_step(working, _h_top_intent_router)
    session_before = working.get("session_state_before") or working.get("session_state")
    has_pending = bool(
        getattr(session_before, "pending_clarification", None)
        if session_before is not None
        else False
    )
    top_intent = working.get("top_intent")
    response_mode = "answer"
    if working.get("error_code"):
        response_mode = _OUTER_ROUTE_REJECT
        route = _OUTER_ROUTE_TERMINAL
    elif str(working.get("guard_result", "") or "") not in {"ok", "safe"}:
        response_mode = _OUTER_ROUTE_REJECT
        route = _OUTER_ROUTE_TERMINAL
    elif has_pending:
        route = _OUTER_ROUTE_CLARIFICATION_REPLY
    elif top_intent in (TopIntent.local_life, "local_life"):
        route = _OUTER_ROUTE_LOCAL_LIFE
    else:
        response_mode = _response_mode_for_top_intent(top_intent)
        route = _OUTER_ROUTE_TERMINAL
    after = {
        **working,
        "intake_route": route,
        "response_mode": response_mode,
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="intake_guard_router", route=route, response_mode=response_mode, top_intent=top_intent, error_code=working.get("error_code", ""))
    return _state_delta(before, after, always_include={"intake_route", "response_mode"})


def _h_receive_input(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    received = assemble_turn_input(raw)
    return {
        "normalized_text": raw,
        "input_type": received.get("input_type", "text"),
        "turn_id": state.get("turn_id", ""),
        **_log(state, "receive_input"),
    }


def _h_load_session(state: GraphState) -> dict:
    session_id = str(state.get("session_id", "") or "")
    store = get_session_store()
    existing = store.load(session_id)
    snapshot = existing.model_copy(deep=True)
    return {
        "session_state": existing,
        "session_state_before": snapshot,
        "session_state_after": None,
        "current_shop": existing.current_shop,
        "last_recommendation_list": existing.last_recommendation_list,
        "active_constraints": existing.active_constraints,
        "comparison_result": existing.comparison_result,
        "pending_clarification": existing.pending_clarification,
        "comparison_targets": existing.comparison_targets,
        "recommendation_candidates": [],
        "pending_check_result": "pass",
        **_log(state, "load_session_state"),
    }


def _h_basic_validate(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    validation = validate_basic_input(raw)
    if not validation["valid"]:
        return {
            "input_type": validation["input_type"],
            "error_code": validation["error_code"],
            "error_message": validation["error_message"],
            "final_response": "璇锋彁渚涗竴鏉℃湁鏁堢殑鏂囨湰鍐呭銆?",
            **_log(state, "basic_input_validate", valid=False, error_code=validation["error_code"]),
        }
    return {
        "input_type": "text",
        "error_code": "",
        "error_message": "",
        **_log(state, "basic_input_validate", valid=True),
    }


def _h_normalize_text(state: GraphState) -> dict:
    raw = state.get("raw_text", "")
    return {
        "normalized_text": input_normalize_text(raw),
        **_log(state, "normalize_text"),
    }


def _h_hard_guard(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    result = check_hard_guard(txt)
    guard_result = result.get("label", "invalid")
    if guard_result == "safe":
        guard_result = "ok"
    return {
        "guard_result": guard_result,
        "final_response": result.get("reply", "") if not result.get("passed", False) else state.get("final_response", ""),
        **_log(state, "hard_guard"),
    }


def _h_top_intent_router(state: GraphState) -> dict:
    txt = state.get("normalized_text", "")
    from ..graph_builder import call_llm as _call_llm
    from ..graph_builder import (
        ensure_real_llm_backend as _ensure_real,
        get_llm_backend_snapshot as _get_snapshot,
        has_llm_backend as _has_backend,
    )

    backend_snapshot_before = _get_snapshot()
    llm_available_before = bool(backend_snapshot_before.get("available")) or _has_backend()
    _ensure_real()
    backend_snapshot_after = _get_snapshot()
    result = parse_top_intent(txt, llm_call=_call_llm)
    intent = result.get("top_intent", TopIntent.out_of_scope)
    if not isinstance(intent, TopIntent):
        try:
            intent = TopIntent(intent)
        except Exception:
            intent = TopIntent.out_of_scope

    final_response = state.get("final_response", "")
    if intent == TopIntent.invalid:
        final_response = "璇峰厛杈撳叆涓€鏉℃湁鏁堢殑闂銆?"
    elif intent == TopIntent.chat:
        final_response = "鎴戝彲浠ュ府浣犳煡闄勮繎闂ㄥ簵銆佷紭鎯犲拰钀ヤ笟鐘舵€併€?"
    elif intent == TopIntent.capability:
        final_response = "鎴戝彲浠ュ府浣犳煡闄勮繎闂ㄥ簵銆佷紭鎯犮€佽窛绂诲拰钀ヤ笟鐘舵€併€?"
    elif intent in (TopIntent.unsafe, TopIntent.out_of_scope):
        final_response = "鎶辨瓑锛屾垜涓昏澶勭悊鏈湴鐢熸椿鐩稿叧闂銆?"

    route_error_code = result.get("error_code", "")
    route_error_message = result.get("error_message", "")
    if intent == TopIntent.local_life:
        route_error_code = ""
        route_error_message = ""

    return {
        "top_intent": intent,
        "error_code": route_error_code,
        "error_message": route_error_message,
        "top_intent_router_llm_available": llm_available_before or bool(backend_snapshot_after.get("available")),
        "top_intent_router_backend": backend_snapshot_after.get("backend", ""),
        "top_intent_router_error_type": "LLM_BACKEND_ERROR" if result.get("error_code") else "",
        "top_intent_router_error_message": result.get("error_message", ""),
        "top_intent_source": "llm" if not result.get("error_code") else "fallback",
        "final_response": final_response,
        **_log(state, "top_intent_router", intent=intent.value),
    }


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
