"""top_intent_router — standalone outer node for top-level intent routing.

This node is a LangGraph outer node that runs AFTER active_turn_resolver
has determined the user input is a normal query or topic switch.

It calls the LLM-based top_intent_router to classify the user's intent
(local_life / chat / capability / unsafe / out_of_scope / invalid)
and sets the route accordingly.

Only ``local_life`` intent proceeds to understanding_subgraph; all other
intents go to response_subgraph for direct reply.
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
from ...domain.enums import TopIntent
from ...domain.graph_state import GraphState
from ...semantic.intent_parser import parse_top_intent
from ...observability.file_logger import get_python_service_logger, log_kv

_LOGGER = get_python_service_logger()


def h_top_intent_router_outer(state: GraphState) -> dict:
    """Outer wrapper: run top_intent_router → route to understanding or response."""
    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route",
           subgraph="top_intent_router", trace_id=state.get("trace_id", ""),
           raw_text=state.get("raw_text", ""))
    working = _run_step(state, _h_top_intent_router)

    top_intent = working.get("top_intent")
    response_mode = "answer"
    error_code = working.get("error_code", "")

    if error_code:
        response_mode = _OUTER_ROUTE_REJECT
        route = _OUTER_ROUTE_TERMINAL
    elif top_intent in (TopIntent.local_life, "local_life"):
        route = _OUTER_ROUTE_LOCAL_LIFE
    else:
        response_mode = _response_mode_for_top_intent(top_intent)
        route = _OUTER_ROUTE_TERMINAL

    after = {
        **working,
        "top_intent_route": route,
        "response_mode": response_mode,
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route",
           subgraph="top_intent_router", route=route, response_mode=response_mode,
           top_intent=top_intent, error_code=error_code)
    return _state_delta(before, after, always_include={"top_intent_route", "response_mode"})


def _h_top_intent_router(state: GraphState) -> dict:
    """Step handler: call LLM top_intent_router on normalized text."""
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
        final_response = "请先输入一条有效的问题。"
    elif intent == TopIntent.chat:
        final_response = "我可以帮你查附近门店、优惠和营业状态。"
    elif intent == TopIntent.capability:
        final_response = "我可以帮你查附近门店、优惠、距离和营业状态。"
    elif intent in (TopIntent.unsafe, TopIntent.out_of_scope):
        final_response = "抱歉，我主要处理本地生活相关问题。"

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


# Import route constants at module level (after they're defined in _routes)
from .._routes import (
    _OUTER_ROUTE_LOCAL_LIFE,
    _OUTER_ROUTE_REJECT,
    _OUTER_ROUTE_TERMINAL,
)
