"""orchestration_router_shadow — Phase 4 secondary routing node.

This node writes a shadow orchestration decision for observability only.
It must not alter the active LangGraph path or invoke business tools.
"""

from __future__ import annotations

import logging
from typing import Any

from .._compat import _log, _state_delta
from ...domain.graph_state import GraphState
from ...observability.file_logger import get_python_service_logger, log_kv
from ...planning.orchestration_router import route_orchestration

_LOGGER = get_python_service_logger()


def h_orchestration_router_shadow(state: GraphState) -> dict[str, Any]:
    """Outer wrapper: build a shadow orchestration decision, then continue."""
    before = dict(state)
    log_kv(
        _LOGGER,
        logging.INFO,
        "[SUBGRAPH_ENTER]",
        tone="route",
        subgraph="orchestration_router_shadow",
        trace_id=state.get("trace_id", ""),
        top_intent=state.get("top_intent", ""),
        task_type=state.get("task_type", ""),
    )
    shadow_patch = route_orchestration(state)
    after = {
        **state,
        **shadow_patch,
        **_log(
            state,
            "orchestration_router_shadow",
            orchestration_pattern=shadow_patch.get("orchestration_pattern", ""),
            workflow_name=shadow_patch.get("workflow_name", ""),
            response_mode=shadow_patch.get("response_mode", ""),
            next_action=shadow_patch.get("next_action", ""),
            error_code=shadow_patch.get("orchestration_error_code", ""),
        ),
    }
    log_kv(
        _LOGGER,
        logging.INFO,
        "[ROUTE_DECISION]",
        tone="route",
        subgraph="orchestration_router_shadow",
        orchestration_pattern=shadow_patch.get("orchestration_pattern", ""),
        workflow_name=shadow_patch.get("workflow_name", ""),
        response_mode=shadow_patch.get("response_mode", ""),
        next_action=shadow_patch.get("next_action", ""),
        error_code=shadow_patch.get("orchestration_error_code", ""),
    )
    return _state_delta(
        before,
        after,
        always_include={
            "orchestration_decision",
            "orchestration_pattern",
            "workflow_name",
            "workflow_reason",
            "task_complexity",
            "requires_tool",
            "requires_clarification",
            "response_mode",
            "next_action",
            "orchestration_error_code",
            "orchestration_error_message",
        },
    )
