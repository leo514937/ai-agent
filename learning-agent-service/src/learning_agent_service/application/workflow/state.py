from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from ...domain.contracts import SseEnvelope
from ...domain.errors import ErrorInfo
from ...domain.state import GraphState


class GraphRuntimeContext(TypedDict, total=False):
    trace_id: str
    session_id: str
    turn_id: str
    workflow_version: str
    request_ts: datetime
    user_id: str
    page: str | None
    response_mode: str | None
    topic_hint: str | None
    history_summary: str | None
    client_context: dict[str, Any]


def build_runtime_context(state: GraphState) -> GraphRuntimeContext:
    runtime = state["runtime"]
    return GraphRuntimeContext(
        trace_id=runtime.trace_id,
        session_id=runtime.session_id,
        turn_id=runtime.turn_id,
        workflow_version=runtime.workflow_version,
        request_ts=runtime.request_ts,
        user_id=runtime.user_id,
        page=runtime.page,
        response_mode=runtime.response_mode,
        topic_hint=runtime.topic_hint,
        history_summary=runtime.history_summary,
        client_context=dict(runtime.client_context),
    )


def append_runtime_event(state: GraphState, event_type: str, payload: dict[str, Any]) -> GraphState:
    runtime = state["runtime"]
    event = SseEnvelope(
        event_type=event_type,
        trace_id=runtime.trace_id,
        session_id=runtime.session_id,
        turn_id=runtime.turn_id,
        timestamp=datetime.now(timezone.utc),
        workflow_version=runtime.workflow_version,
        payload=dict(payload),
    )
    events = list(runtime.emitted_events)
    events.append(event)
    state["runtime"] = runtime.model_copy(update={"emitted_events": events})
    state["sse_events"] = list(state.get("sse_events", [])) + [event]
    return state


def append_runtime_error(state: GraphState, error: ErrorInfo) -> GraphState:
    runtime = state["runtime"]
    errors = list(runtime.errors)
    errors.append(error)
    state["runtime"] = runtime.model_copy(update={"errors": errors})
    state["errors"] = list(state.get("errors", [])) + [error]
    return state


def append_stage_timeline_entry(state: GraphState, entry: dict[str, Any]) -> GraphState:
    turn = state["turn"]
    timeline = list(turn.stage_timeline)
    new_timeline = timeline + [dict(entry)]
    state["turn"] = turn.model_copy(update={"stage_timeline": new_timeline})
    state["stage_timeline"] = list(state.get("stage_timeline", [])) + [dict(entry)]
    return state
