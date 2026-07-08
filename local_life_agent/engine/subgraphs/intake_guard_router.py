"""intake_guard_router subgraph - entry routing.

Runs the input pipeline (receive -> load session -> validate -> normalize
-> hard_guard -> top_intent_router) and decides whether to route to
local-life understanding, merge a pending clarification, or go straight
to response.
"""

from __future__ import annotations

import logging
import re
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
from ...domain.contextualized_turn import build_contextual_follow_up
from ...domain.focus_context import FocusContext
from ...domain.graph_state import GraphState
from ...domain.state import SessionState
from ...input.hard_guard import check_hard_guard
from ...input.normalizer import normalize_text as input_normalize_text
from ...input.receiver import receive_input as assemble_turn_input
from ...input.validator import validate_basic_input
from .active_turn_resolver import _h_active_turn_resolver, _should_treat_as_topic_switch
from ...semantic.intent_parser import parse_top_intent
from ...target.focus_resolver import resolve_focus_context
from ...target.clarification import build_clarification_request
from ...session.store import get_session_store
from ...answer.response_directive import build_early_response_directive
from ...domain.schemas import ErrorEnvelope
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()
_LOCAL_LIFE_HINTS = ("推荐", "附近", "店", "券", "优惠", "团购", "营业", "开门", "对比", "比较", "哪家", "多少钱")
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _has_local_life_signal(text: str) -> bool:
    compact = str(text or "")
    return any(token in compact for token in _LOCAL_LIFE_HINTS)


def _should_keep_local_life_route(
    *,
    raw_text: str,
    normalized_text: str,
    top_intent: Any,
    session_state: Any,
    active_turn_result: dict[str, Any] | None,
) -> bool:
    intent_value = getattr(top_intent, "value", top_intent)
    if intent_value == TopIntent.local_life.value:
        return True
    text = str(normalized_text or raw_text or "")
    if not text.strip():
        return False
    focus_context = resolve_focus_context(
        text,
        session_state=session_state,
        semantic_frame={},
        active_turn_result=active_turn_result or {},
    )
    if focus_context.focus_type != "none":
        return True
    contextual_follow_up = build_contextual_follow_up(
        semantic_frame={},
        session_state=session_state,
        raw_text=text,
    )
    if contextual_follow_up is not None:
        return True
    if focus_context.clarification_needed and _has_local_life_signal(text):
        return True
    return _has_local_life_signal(text)


def h_intake_guard_router(state: GraphState) -> dict:
    """Outer wrapper: intake -> guard -> route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="intake_guard_router", trace_id=state.get("trace_id", ""), raw_text=state.get("raw_text", ""))
    working = _run_step(state, _h_receive_input)
    working = _run_step(working, _h_basic_validate)
    if working.get("error_code"):
        after = {
            **working,
            "intake_route": _OUTER_ROUTE_TERMINAL,
            "response_mode": _OUTER_ROUTE_REJECT,
        }
        log_kv(
            _LOGGER,
            logging.INFO,
            "[ROUTE_DECISION]",
            tone="route",
            subgraph="intake_guard_router",
            route=_OUTER_ROUTE_TERMINAL,
            response_mode=_OUTER_ROUTE_REJECT,
            reason="basic_input_validate",
        )
        return _state_delta(before, after, always_include={"intake_route", "response_mode"})
    working = _run_step(working, _h_load_session)
    working = _run_step(working, _h_expand_session_context)
    working = _run_step(working, _h_normalize_text)
    working = _run_step(working, _h_hard_guard)
    has_pending = bool(working.get("pending_clarification"))
    if str(working.get("guard_result", "") or "") not in {"safe", "ok"}:
        session_before = working.get("session_state_before") or working.get("session_state")
        has_pending = bool(
            getattr(session_before, "pending_clarification", None)
            if session_before is not None
            else False
        )
        response_mode = "reject" if working.get("response_directive") is not None else _response_mode_for_top_intent(working.get("top_intent"))
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

    working = _run_step(working, _h_active_turn_resolver)
    active_turn_result = working.get("active_turn_result") or {}
    active_route = str(active_turn_result.get("route", "") or "normal_query")
    if active_route == "topic_switch":
        working = {
            **working,
            "pending_clarification": None,
            "clarification_request": None,
            "pending_check_result": "topic_switch",
            "merge_clarification_result": "topic_switch",
            "clarification_result": "topic_switch",
            "last_candidate_set": [],
            "last_candidate_spec": None,
            "active_goal": None,
            "resolved_target": None,
            "resolve_shop_result": None,
        }
    elif active_route in {"pending_restored", "pending_out_of_range", "pending_expired", "pending_invalid", "pending_cancelled"}:
        if active_route == "pending_cancelled" and _should_treat_as_topic_switch(str(state.get("raw_text", "") or state.get("normalized_text", "") or "")):
            working = {
                **working,
                "pending_clarification": None,
                "clarification_request": None,
                "pending_check_result": "topic_switch",
                "merge_clarification_result": "topic_switch",
                "clarification_result": "topic_switch",
                "last_candidate_set": [],
                "last_candidate_spec": None,
                "active_goal": None,
                "resolved_target": None,
                "resolve_shop_result": None,
            }
        elif has_pending:
            response_mode = "answer"
            after = {
                **working,
                "intake_route": _OUTER_ROUTE_CLARIFICATION_REPLY,
                "response_mode": response_mode,
            }
            log_kv(
                _LOGGER,
                logging.INFO,
                "[ROUTE_DECISION]",
                tone="route",
                subgraph="intake_guard_router",
                route=_OUTER_ROUTE_CLARIFICATION_REPLY,
                response_mode=response_mode,
                active_turn_route=active_route,
                reason=str(active_turn_result.get("reason", "") or "active_turn_pending"),
            )
            return _state_delta(before, after, always_include={"intake_route", "response_mode"})
        else:
            # No real pending clarification exists, so keep the turn in the
            # normal local-life routing path. This lets ordinal references like
            # "第二家有券吗" continue into planning instead of being short-circuited
            # into a clarification-only response.
            pass

    working = _run_step(working, _h_top_intent_router)
    session_before = working.get("session_state_before") or working.get("session_state")
    has_pending = bool(working.get("pending_clarification"))
    top_intent = working.get("top_intent")
    response_mode = "answer"
    keep_local_life = _should_keep_local_life_route(
        raw_text=str(working.get("raw_text", "") or ""),
        normalized_text=str(working.get("normalized_text", "") or ""),
        top_intent=top_intent,
        session_state=session_before,
        active_turn_result=active_turn_result,
    )
    if working.get("error_code"):
        response_mode = _OUTER_ROUTE_REJECT
        route = _OUTER_ROUTE_TERMINAL
    elif str(working.get("guard_result", "") or "") not in {"ok", "safe"}:
        response_mode = _OUTER_ROUTE_REJECT
        route = _OUTER_ROUTE_TERMINAL
    elif has_pending:
        route = _OUTER_ROUTE_CLARIFICATION_REPLY
    elif keep_local_life:
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
        **_log(state, "load_session_state"),
    }


def _validate_session_id(session_id: Any) -> dict[str, Any]:
    text = str(session_id or "").strip()
    if not text:
        return {"valid": True, "error_code": "", "error_message": ""}
    if len(text) > 128:
        return {
            "valid": False,
            "error_code": "INVALID_SESSION_ID",
            "error_message": "session_id exceeds 128 characters",
        }
    if not _SESSION_ID_PATTERN.fullmatch(text):
        return {
            "valid": False,
            "error_code": "INVALID_SESSION_ID",
            "error_message": "session_id contains unsupported characters",
        }
    return {"valid": True, "error_code": "", "error_message": ""}


def validate_session_input(state: GraphState) -> dict[str, Any]:
    """Pure input validation before any session I/O."""
    raw = state.get("raw_text", "")
    validation = validate_basic_input(raw)
    if not validation["valid"]:
        return {
            "input_type": validation["input_type"],
            "error_code": validation["error_code"],
            "error_message": validation["error_message"],
            "final_response": "璇峰厛杈撳叆涓€鏉℃湁鏁堢殑闂銆?",
        }

    session_validation = _validate_session_id(state.get("session_id", ""))
    if not session_validation["valid"]:
        return {
            "input_type": "text",
            "error_code": session_validation["error_code"],
            "error_message": session_validation["error_message"],
            "final_response": "璇锋彁渚涘悎娉曠殑 session_id 銆?",
        }

    return {
        "input_type": "text",
        "error_code": "",
        "error_message": "",
    }


def _h_basic_validate(state: GraphState) -> dict:
    validation = validate_session_input(state)
    if validation.get("error_code"):
        return {
            **validation,
            **_log(state, "basic_input_validate", valid=False, error_code=validation["error_code"]),
        }
    return {
        **validation,
        **_log(state, "basic_input_validate", valid=True),
    }


def _session_state_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _expand_focus_context(session_state: Any) -> FocusContext | None:
    if session_state is None:
        return None

    current_shop = _session_state_dict(getattr(session_state, "current_shop", None))
    if current_shop.get("shop_id") or current_shop.get("shop_name"):
        return FocusContext.from_trace(
            focus_type="current_shop",
            focus_object=current_shop,
            focus_source="session_state.current_shop",
            resolution_status="restored",
            clarification_needed=False,
            confidence=1.0,
        )

    comparison_targets = [
        _session_state_dict(item)
        for item in (getattr(session_state, "comparison_targets", None) or [])
        if _session_state_dict(item)
    ]
    if comparison_targets:
        return FocusContext.from_trace(
            focus_type="comparison_targets",
            focus_object=comparison_targets[0],
            comparison_targets=comparison_targets,
            focus_source="session_state.comparison_targets",
            resolution_status="restored",
            clarification_needed=False,
            confidence=0.8,
        )

    recommendation_list = [
        _session_state_dict(item)
        for item in (getattr(session_state, "last_recommendation_list", None) or [])
        if _session_state_dict(item)
    ]
    if recommendation_list:
        return FocusContext.from_trace(
            focus_type="recommendation_item",
            focus_object=recommendation_list[0],
            recommendation_item=recommendation_list[0],
            focus_index=1,
            focus_source="session_state.last_recommendation_list",
            resolution_status="restored",
            clarification_needed=False,
            confidence=0.6,
        )

    return FocusContext.from_trace(
        focus_type="none",
        focus_source="session_state",
        resolution_status="empty",
        clarification_needed=False,
        confidence=0.0,
    )


def _h_expand_session_context(state: GraphState) -> dict:
    session_state = state.get("session_state")
    if not isinstance(session_state, SessionState):
        session_state = SessionState()
    pending_request = None
    if session_state.pending_clarification is not None:
        try:
            pending_request = build_clarification_request(session_state.pending_clarification, source_stage="session_load")
        except Exception:
            pending_request = None
    focus_context = _expand_focus_context(session_state)
    return {
        "current_shop": session_state.current_shop,
        "last_recommendation_list": session_state.last_recommendation_list,
        "active_constraints": session_state.active_constraints,
        "comparison_result": session_state.comparison_result,
        "pending_clarification": session_state.pending_clarification,
        "clarification_request": pending_request,
        "comparison_targets": session_state.comparison_targets,
        "focus_context": focus_context,
        **_log(state, "expand_session_context"),
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
    error_envelope = None
    response_directive = None
    if not result.get("passed", False):
        error_envelope = ErrorEnvelope(
            error_code=str(result.get("reason", "") or result.get("label", "") or "hard_guard_reject"),
            message=str(result.get("reply", "") or ""),
            severity="warning" if result.get("label") in {"greeting", "capability"} else "error",
            recoverable=False,
            source_stage="hard_guard",
            trace_id=str(state.get("trace_id", "") or ""),
            details={
                "label": str(result.get("label", "") or ""),
                "reason": str(result.get("reason", "") or ""),
            },
        )
        response_directive = build_early_response_directive(
            answer_text=str(result.get("reply", "") or ""),
            answer_type=str(state.get("task_type", "") or ""),
            response_mode="reject",
            reason=str(result.get("reason", "") or ""),
            fallback_reason=str(result.get("reason", "") or ""),
            trace_id=str(state.get("trace_id", "") or ""),
            answer_source="hard_guard",
            error_envelope=error_envelope,
        )
    return {
        "guard_result": guard_result,
        "final_response": result.get("reply", "") if not result.get("passed", False) else state.get("final_response", ""),
        "error_envelope": error_envelope,
        "response_directive": response_directive,
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
