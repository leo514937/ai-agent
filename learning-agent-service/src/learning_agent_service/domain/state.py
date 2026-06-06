from __future__ import annotations

import os
import operator
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from .contracts import ChatTurnCommand, GraphRuntimeMeta, PersistentSessionContext, SseEnvelope, TurnRuntimeState


class GraphState(TypedDict):
    persistent: PersistentSessionContext
    turn: TurnRuntimeState
    runtime: GraphRuntimeMeta
    runtime_context: dict[str, Any]
    sse_events: Annotated[list[SseEnvelope], operator.add]
    errors: Annotated[list[Any], operator.add]
    stage_timeline: Annotated[list[dict[str, Any]], operator.add]
    retrieval_traces: Annotated[list[dict[str, Any]], operator.add]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    shop_analyses: Annotated[list[dict[str, Any]], operator.add]


def build_initial_state(
    command: ChatTurnCommand,
    workflow_version: str = "learn-agent/v1",
    persistent: PersistentSessionContext | None = None,
) -> GraphState:
    request_ts = datetime.now(timezone.utc)
    base_persistent = persistent or PersistentSessionContext()
    if command.history_summary and not base_persistent.history_summary:
        base_persistent = base_persistent.model_copy(update={"history_summary": command.history_summary})
    return GraphState(
        persistent=base_persistent,
        turn=TurnRuntimeState(
            raw_query=command.message,
            decision="direct_answer",
            sensory_memory={
                "raw_message": command.message,
                "topic_hint": command.topic_hint,
                "page": command.page,
                "response_mode": getattr(command.response_mode, "value", command.response_mode),
                "client_context": deepcopy(command.client_context),
            },
            short_term_window=[
                {
                    "role": "user",
                    "content": command.message,
                    "turn_id": command.turn_id,
                }
            ],
        ),
        runtime=GraphRuntimeMeta(
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            workflow_version=workflow_version,
            request_ts=request_ts,
            user_id=command.user_id,
            response_mode=command.response_mode,
            page=command.page,
            topic_hint=command.topic_hint,
            history_summary=command.history_summary,
            client_context=command.client_context,
        ),
        runtime_context={
            "trace_id": command.trace_id,
            "session_id": command.session_id,
            "turn_id": command.turn_id,
            "workflow_version": workflow_version,
            "request_ts": request_ts,
            "user_id": command.user_id,
            "page": command.page,
            "response_mode": command.response_mode,
            "topic_hint": command.topic_hint,
            "history_summary": command.history_summary,
            "client_context": deepcopy(command.client_context),
            "graph_recursion_limit": _env_int("LEARNING_AGENT_GRAPH_RECURSION_LIMIT", 50),
            "tool_loop_limit": _env_int("LEARNING_AGENT_TOOL_LOOP_LIMIT", 3),
            "rewrite_loop_limit": _env_int("LEARNING_AGENT_REWRITE_LOOP_LIMIT", 2),
            "recommendation_expand_max_rounds": _env_int("LEARNING_AGENT_RECOMMENDATION_EXPAND_MAX_ROUNDS", 2),
            "recommendation_top_n": _env_int("LEARNING_AGENT_RECOMMENDATION_TOP_N", 3),
        },
        sse_events=[],
        errors=[],
        stage_timeline=[],
        retrieval_traces=[],
        tool_results=[],
        shop_analyses=[],
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)
    return max(1, value)


def clone_graph_state(state: GraphState) -> GraphState:
    return deepcopy(state)
