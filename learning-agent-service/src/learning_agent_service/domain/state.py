from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional, TypedDict

from .contracts import ChatTurnCommand, GraphRuntimeMeta, PersistentSessionContext, TurnRuntimeState


class GraphState(TypedDict):
    persistent: PersistentSessionContext
    turn: TurnRuntimeState
    runtime: GraphRuntimeMeta


def build_initial_state(
    command: ChatTurnCommand,
    workflow_version: str = "learn-agent/v1",
    persistent: Optional[PersistentSessionContext] = None,
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
    )


def clone_graph_state(state: GraphState) -> GraphState:
    return deepcopy(state)
