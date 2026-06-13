from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from ...domain.contracts import (
    ChatTurnCommand,
    ClarificationCard,
    PersistentSessionContext,
    SseEnvelope,
)
from ...domain.errors import TerminalEvent, WorkflowErrorCode, build_error
from ...domain.state import GraphState, build_initial_state, clone_graph_state
from ..routing_primitives import _looks_like_unserviceable_location, _pending_clarification_matches_query
from .state import append_runtime_error as _append_state_runtime_error
from .state import append_runtime_event as _append_state_runtime_event
from .state import append_stage_timeline_entry as _append_stage_timeline_entry
from .services import WorkflowServices
from .subgraphs import (
    route_after_rag,
    route_after_understand,
    route_decider,
    route_gate,
    run_rag_subgraph,
    run_recommendation_subgraph,
    run_tool_subgraph,
    run_understand_turn,
)

_LOGGER = logging.getLogger(__name__)
_STREAM_STOP = object()
_PHASE5_TRACE_KEY = "phase5_trace"


def _update_phase5_trace(state: GraphState, **updates: Any) -> GraphState:
    turn = state["turn"]
    runtime = state["runtime"]

    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase5_trace = dict(turn_extra.get(_PHASE5_TRACE_KEY, {}) or {})
    phase5_trace.update(updates)
    turn_extra[_PHASE5_TRACE_KEY] = phase5_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase5_trace = dict(runtime_metrics.get(_PHASE5_TRACE_KEY, {}) or {})
    runtime_phase5_trace.update(updates)
    runtime_metrics[_PHASE5_TRACE_KEY] = runtime_phase5_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


class WorkflowRunner(Protocol):
    def run(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> GraphState:
        ...

    def run_stream(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> Iterable[SseEnvelope]:
        ...


class BaseWorkflowRunner:
    def __init__(
        self,
        services: WorkflowServices,
        workflow_version: str = "learn-agent/v1",
        *,
        runner_kind: str = "base",
    ) -> None:
        self.services = services
        self.workflow_version = workflow_version
        self.runner_kind = runner_kind


    def _annotate_runner_context(self, state: GraphState) -> GraphState:
        state = _update_phase5_trace(
            state,
            runner_kind=self.runner_kind,
            runner_backend="sequential",
            graph_runtime="legacy",
            runner_class=self.__class__.__name__,
            compare_ready=True,
        )
        runtime_context = dict(state.get("runtime_context", {}) or {})
        runtime_context.update(
            {
                "runner_kind": self.runner_kind,
                "runner_backend": "sequential",
                "graph_runtime": "legacy",
                "runner_class": self.__class__.__name__,
                "compare_ready": True,
            }
        )
        state["runtime_context"] = runtime_context
        return state

    def _emit_stage_event(
        self,
        state: GraphState,
        event_type: str,
        stage: str,
        status: str,
        *,
        elapsed_ms: float | None = None,
        degrade_to: str | None = None,
        error: str | None = None,
    ) -> None:
        runtime = state["runtime"]
        turn = state["turn"]
        routing = getattr(turn, "routing_decision", None)
        payload = {
            "stage": stage,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "degrade_to": degrade_to,
            "error": error,
            "metrics": {},
            "current_stage": getattr(turn, "current_stage", stage),
            "stage_status": getattr(turn, "stage_status", status),
            "route_decision": routing.required_action if routing is not None else None,
            "route_reason": routing.route_reason if routing is not None else None,
            "message": None,
            "details": {},
        }
        _append_state_runtime_event(state, event_type, payload)
        _append_stage_timeline_entry(
            state,
            {
                "stage": stage,
                "status": status,
                "route_decision": payload["route_decision"],
                "route_reason": payload["route_reason"],
                "detail": {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        _LOGGER.info(
            "workflow_stage_event trace_id=%s session_id=%s turn_id=%s stage=%s status=%s elapsed_ms=%s degrade_to=%s error=%s",
            runtime.trace_id,
            runtime.session_id,
            runtime.turn_id,
            stage,
            status,
            elapsed_ms,
            degrade_to,
            error or "",
        )

    def _invoke_stage(self, stage_name: str, func: Any, state: GraphState) -> GraphState:
        started_at = time.perf_counter()
        try:
            state = func(state)
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            self._emit_stage_event(state, "workflow_stage_event", stage_name, "ok", elapsed_ms=elapsed_ms)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            self._emit_stage_event(state, "workflow_stage_event", stage_name, "error", error=str(exc), elapsed_ms=elapsed_ms)
            state = self._record_unexpected_error(state, stage_name, exc)
        return state

    def _record_unexpected_error(self, state: GraphState, stage_name: str, exc: Exception) -> GraphState:
        runtime = state["runtime"]
        error = build_error(
            WorkflowErrorCode.INTERNAL_ERROR,
            stage=stage_name,
            message=str(exc),
            is_terminal=True,
        )
        state = _append_state_runtime_error(state, error)
        state["runtime"] = state["runtime"].model_copy(update={"terminal_event": TerminalEvent.ERROR})
        return state

    @staticmethod
    def _is_terminal(state: GraphState) -> bool:
        return state["runtime"].terminal_event == TerminalEvent.ERROR

    def _finalize_terminal(
        self,
        state: GraphState,
        default_terminal: TerminalEvent | None = None,
    ) -> GraphState:
        runtime = state["runtime"]
        if runtime.terminal_event is None and default_terminal is not None:
            state["runtime"] = runtime.model_copy(update={"terminal_event": default_terminal})

        state = self._invoke_stage("emit_final", self.services.emit_final, state)
        runtime = state["runtime"]
        if runtime.terminal_event is None:
            state["runtime"] = runtime.model_copy(update={"terminal_event": default_terminal or TerminalEvent.FINAL})
        return state
