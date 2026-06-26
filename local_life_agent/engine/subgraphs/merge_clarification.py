"""merge_clarification subgraph — handles pending clarifications.

When the user replies to a pending clarification (e.g. "你是说A店还是B店？"),
this subgraph decides whether to restore the semantic frame, switch topic,
or reject the reply.
"""

from __future__ import annotations

import logging
from typing import Any

from .._compat import _log, _run_step, _state_delta
from .._routes import (
    _OUTER_ROUTE_CLARIFY,
    _OUTER_ROUTE_FALLBACK,
    _OUTER_ROUTE_PROCEED,
)
from ...domain.graph_state import GraphState
from ...observability.file_logger import get_python_service_logger, log_kv
from ...target.clarification import handle_clarification_reply

_LOGGER = get_python_service_logger()


def h_merge_clarification(state: GraphState) -> dict:
    """Outer wrapper: check pending → route."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route", subgraph="merge_clarification", trace_id=state.get("trace_id", ""), has_pending=bool(state.get("pending_clarification")))
    working = _run_step(state, _h_check_pending)
    pending_result = str(working.get("pending_check_result", "") or "")
    if pending_result in {"restore", "topic_switch", "pass"}:
        route = _OUTER_ROUTE_PROCEED
        response_mode = "answer"
    else:
        route = _OUTER_ROUTE_CLARIFY
        response_mode = _OUTER_ROUTE_CLARIFY
    after = {
        **working,
        "merge_clarification_route": route,
        "response_mode": response_mode,
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route", subgraph="merge_clarification", route=route, response_mode=response_mode, pending_result=pending_result)
    return _state_delta(before, after, always_include={"merge_clarification_route", "response_mode"})


def _h_check_pending(state: GraphState) -> dict:
    pending = state.get("pending_clarification")
    if pending is None:
        return {
            "pending_check_result": "pass",
            **_log(state, "check_pending_clarification", has_pending=False),
        }

    reply = str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
    result = handle_clarification_reply(reply, pending, state.get("session_state"))
    action = str(result.get("status", "invalid"))

    updates: dict[str, Any] = {
        "pending_check_result": action,
    }

    if action == "restore":
        if result.get("pending_clarification") is None:
            updates["pending_clarification"] = None
        if result.get("semantic_frame") is not None:
            from ...domain.schemas import SemanticFrame
            restored_frame = result.get("semantic_frame")
            if isinstance(restored_frame, dict):
                try:
                    restored_frame = SemanticFrame.model_validate(restored_frame)
                except Exception:
                    pass
            updates["semantic_frame"] = restored_frame
        if result.get("task_type"):
            task_type_value = result.get("task_type")
            updates["task_type"] = str(task_type_value)
            updates["task_type_source"] = "pending_clarification_restore"
        if result.get("resolved_target") is not None:
            updates["resolved_target"] = result.get("resolved_target")
            updates["resolve_shop_result"] = result.get("resolved_target")
        if result.get("comparison_targets") is not None:
            updates["comparison_targets"] = result.get("comparison_targets")
        updates["final_response"] = ""
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    if action == "topic_switch":
        updates["pending_clarification"] = None
        updates["final_response"] = ""
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    if action == "expired":
        updates["pending_clarification"] = None
        updates["final_response"] = result.get("final_response", "")
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    if action in {"invalid", "out_of_range"}:
        updates["final_response"] = result.get("final_response", "")
        return {
            **updates,
            **_log(state, "check_pending_clarification", has_pending=True, action=action),
        }

    return {
        "pending_check_result": "pass",
        **_log(state, "check_pending_clarification", has_pending=True, action="pass"),
    }
