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
from ..router import _looks_like_unserviceable_location, _pending_clarification_matches_query
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


class SequentialWorkflowRunner:
    def __init__(
        self,
        services: WorkflowServices,
        workflow_version: str = "learn-agent/v1",
        *,
        runner_kind: str = "sequential",
    ) -> None:
        self.services = services
        self.workflow_version = workflow_version
        self.runner_kind = runner_kind

    def run(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> GraphState:
        initial = build_initial_state(
            command=command,
            workflow_version=self.workflow_version,
            persistent=persistent_context,
        )
        initial = self._annotate_runner_context(initial)
        return self.run_state(initial)

    def run_state(self, state: GraphState) -> GraphState:
        state = clone_graph_state(state)
        state = self._annotate_runner_context(state)
        if self._should_consume_pending_clarification(state):
            state = self._invoke_stage("consume_pending_clarification", self.services.consume_pending_clarification, state)
            if self._is_terminal(state):
                return self._finalize_terminal(state)
            try:
                state = self.services.understand_turn.parse_intent_slots(state)
            except Exception:
                pass
        state = self._invoke_stage("load_context", self.services.load_context, state)
        if self._is_terminal(state):
            return self._finalize_terminal(state)
        if self._should_consume_pending_clarification(state):
            state = self._invoke_stage("consume_pending_clarification", self.services.consume_pending_clarification, state)
            if self._is_terminal(state):
                return self._finalize_terminal(state)
        routing = state["turn"].routing_decision
        if self._is_conversation_recap_route(state):
            state = self._invoke_stage(
                "conversation_recap_direct_response",
                self.services.conversation_recap_direct_response,
                state,
            )
            if self._is_terminal(state):
                return self._finalize_terminal(state)
            state = self._invoke_stage("compose_answer", self.services.compose_answer, state)
            state = self._materialize_pending_clarification_from_answer(state)
            if self._is_terminal(state):
                persistent = state["persistent"]
                if getattr(persistent, "pending_clarification", None) is not None:
                    state = self._invoke_stage("persist_session", self.services.persist_session, state)
                    if self._is_terminal(state):
                        return self._finalize_terminal(state)
                return self._finalize_terminal(state)
            state = self._invoke_stage("persist_session", self.services.persist_session, state)
            if self._is_terminal(state):
                return self._finalize_terminal(state)
            return self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
        if routing is not None and routing.blocked:
            state = self._invoke_stage("compose_answer", self.services.compose_answer, state)
            state = self._materialize_pending_clarification_from_answer(state)
            if self._is_terminal(state):
                persistent = state["persistent"]
                if getattr(persistent, "pending_clarification", None) is not None:
                    state = self._invoke_stage("persist_session", self.services.persist_session, state)
                    if self._is_terminal(state):
                        return self._finalize_terminal(state)
                return self._finalize_terminal(state)
            state = self._invoke_stage("persist_session", self.services.persist_session, state)
            if self._is_terminal(state):
                return self._finalize_terminal(state)
            return self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)

        state = self._invoke_stage(
            "understand_turn",
            lambda current: run_understand_turn(current, self.services.understand_turn),
            state,
        )
        next_stage = route_after_understand(state)
        if next_stage == "emit_final":
            persistent = state["persistent"]
            if getattr(persistent, "pending_clarification", None) is not None:
                state = self._invoke_stage("persist_session", self.services.persist_session, state)
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
            return self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)

        if next_stage == "rag_subgraph":
            state = self._invoke_stage(
                "rag_subgraph",
                lambda current: run_rag_subgraph(current, self.services.rag_subgraph),
                state,
            )
            if self._is_terminal(state):
                return self._finalize_terminal(state)
            next_stage = route_after_rag(state)
            if next_stage == "tool_subgraph":
                state = self._invoke_stage(
                    "tool_subgraph",
                    lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                    state,
                )
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
        elif next_stage == "route_gate":
            state = self._invoke_stage("route_gate", route_gate, state)
            if self._is_terminal(state):
                return self._finalize_terminal(state)
            next_stage = route_decider(state)
            if next_stage == "clarify":
                state = self._invoke_stage("compose_answer", self.services.compose_answer, state)
                state = self._materialize_pending_clarification_from_answer(state)
                if self._is_terminal(state):
                    persistent = state["persistent"]
                    if getattr(persistent, "pending_clarification", None) is not None:
                        state = self._invoke_stage("persist_session", self.services.persist_session, state)
                        if self._is_terminal(state):
                            return self._finalize_terminal(state)
                    return self._finalize_terminal(state)
                state = self._invoke_stage("persist_session", self.services.persist_session, state)
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
                return self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
            if next_stage == "tool":
                state = self._invoke_stage(
                    "tool_subgraph",
                    lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                    state,
                )
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
            elif next_stage == "rag":
                state = self._invoke_stage(
                    "rag_subgraph",
                    lambda current: run_rag_subgraph(current, self.services.rag_subgraph),
                    state,
                )
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
                next_stage = route_after_rag(state)
                if next_stage == "tool_subgraph":
                    state = self._invoke_stage(
                        "tool_subgraph",
                        lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                        state,
                    )
                    if self._is_terminal(state):
                        return self._finalize_terminal(state)
            elif next_stage == "rag_plus_tool":
                state = self._invoke_stage(
                    "rag_subgraph",
                    lambda current: run_rag_subgraph(current, self.services.rag_subgraph),
                    state,
                )
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
                state = self._invoke_stage(
                    "tool_subgraph",
                    lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                    state,
                )
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
            elif next_stage == "recommendation":
                state = self._invoke_stage(
                    "recommendation_subgraph",
                    lambda current: run_recommendation_subgraph(current, self.services.rag_subgraph),
                    state,
                )
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
            elif next_stage == "direct":
                pass
        elif next_stage == "tool_subgraph":
            state = self._invoke_stage(
                "tool_subgraph",
                lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                state,
            )
            if self._is_terminal(state):
                return self._finalize_terminal(state)

        state = self._invoke_stage("compose_answer", self.services.compose_answer, state)
        state = self._materialize_pending_clarification_from_answer(state)
        if self._is_terminal(state):
            persistent = state["persistent"]
            if getattr(persistent, "pending_clarification", None) is not None:
                state = self._invoke_stage("persist_session", self.services.persist_session, state)
                if self._is_terminal(state):
                    return self._finalize_terminal(state)
            return self._finalize_terminal(state)

        state = self._invoke_stage("persist_session", self.services.persist_session, state)
        if self._is_terminal(state):
            return self._finalize_terminal(state)

        return self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)

    def run_stream(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> Iterable[SseEnvelope]:
        state = build_initial_state(
            command=command,
            workflow_version=self.workflow_version,
            persistent=persistent_context,
        )
        state = self._annotate_runner_context(state)
        state = clone_graph_state(state)
        emitted_count = 0

        def drain_emitted_events():
            nonlocal emitted_count
            events = list(state["runtime"].emitted_events)
            for event in events[emitted_count:]:
                yield event
            emitted_count = len(events)

        if self._should_consume_pending_clarification(state):
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "consume_pending_clarification",
                self.services.consume_pending_clarification,
                state,
                heartbeat_stage="consume_pending_clarification",
            )
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            try:
                state = self.services.understand_turn.parse_intent_slots(state)
            except Exception:
                pass
        # 1) load_context
        self._emit_stage_event(state, "load_context_started", "load_context", "started", elapsed_ms=0.0)
        state = yield from self._invoke_stage_with_heartbeat_streaming(
            "load_context",
            self.services.load_context,
            state,
            heartbeat_stage="load_context",
        )
        load_context_elapsed = float(state["runtime"].metrics.get("load_context_elapsed_ms", 0.0) or 0.0)
        self._emit_stage_event(state, "load_context_done", "load_context", "done", elapsed_ms=load_context_elapsed)
        yield from drain_emitted_events()
        if self._is_terminal(state):
            state = self._finalize_terminal(state)
            yield from drain_emitted_events()
            return
        if self._should_consume_pending_clarification(state):
            self._emit_stage_event(
                state,
                "heartbeat",
                "consume_pending_clarification",
                "started",
                elapsed_ms=0.0,
            )
            yield from drain_emitted_events()
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "consume_pending_clarification",
                self.services.consume_pending_clarification,
                state,
                heartbeat_stage="consume_pending_clarification",
            )
            consume_elapsed = float(state["runtime"].metrics.get("consume_pending_clarification_elapsed_ms", 0.0) or 0.0)
            self._emit_stage_event(
                state,
                "heartbeat",
                "consume_pending_clarification",
                "done",
                elapsed_ms=consume_elapsed,
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
        routing = state["turn"].routing_decision
        if self._is_conversation_recap_route(state):
            self._emit_stage_event(
                state,
                "heartbeat",
                "conversation_recap_direct_response",
                "started",
                elapsed_ms=0.0,
            )
            yield from drain_emitted_events()
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "conversation_recap_direct_response",
                self.services.conversation_recap_direct_response,
                state,
                heartbeat_stage="conversation_recap_direct_response",
            )
            recap_elapsed = float(
                state["runtime"].metrics.get("conversation_recap_direct_response_elapsed_ms", 0.0) or 0.0
            )
            self._emit_stage_event(
                state,
                "heartbeat",
                "conversation_recap_direct_response",
                "done",
                elapsed_ms=recap_elapsed,
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            self._emit_stage_event(state, "answer_stream_started", "compose_answer", "started", elapsed_ms=0.0)
            yield from drain_emitted_events()
            gen = self._invoke_stage_streaming("compose_answer", self.services.compose_answer, state)
            while True:
                try:
                    item = next(gen)
                    if isinstance(item, SseEnvelope) and item.event_type == "answer_delta":
                        item = item.model_copy(update={"event_type": "delta"})
                    yield item
                except StopIteration as e:
                    state = e.value
                    break

            yield from drain_emitted_events()
            state = self._materialize_pending_clarification_from_answer(state)
            if self._is_terminal(state):
                persistent = state["persistent"]
                if getattr(persistent, "pending_clarification", None) is not None:
                    state = self._mark_streaming_fast_persist(state)
                    state = yield from self._invoke_stage_with_heartbeat_streaming(
                        "persist_session",
                        self.services.persist_session,
                        state,
                        heartbeat_stage="persist_session",
                    )
                    yield from drain_emitted_events()
                    if self._is_terminal(state):
                        state = self._finalize_terminal(state)
                        yield from drain_emitted_events()
                        return
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return

            state = self._mark_streaming_fast_persist(state)
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "persist_session",
                self.services.persist_session,
                state,
                heartbeat_stage="persist_session",
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return

            state = self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
            yield from drain_emitted_events()
            return
        if routing is not None and routing.blocked:
            self._emit_stage_event(state, "answer_stream_started", "compose_answer", "started", elapsed_ms=0.0)
            yield from drain_emitted_events()
            gen = self._invoke_stage_streaming("compose_answer", self.services.compose_answer, state)
            while True:
                try:
                    item = next(gen)
                    if isinstance(item, SseEnvelope) and item.event_type == "answer_delta":
                        item = item.model_copy(update={"event_type": "delta"})
                    yield item
                except StopIteration as e:
                    state = e.value
                    break
            yield from drain_emitted_events()
            state = self._materialize_pending_clarification_from_answer(state)
            if self._is_terminal(state):
                persistent = state["persistent"]
                if getattr(persistent, "pending_clarification", None) is not None:
                    state = self._mark_streaming_fast_persist(state)
                    state = yield from self._invoke_stage_with_heartbeat_streaming(
                        "persist_session",
                        self.services.persist_session,
                        state,
                        heartbeat_stage="persist_session",
                    )
                    yield from drain_emitted_events()
                    if self._is_terminal(state):
                        state = self._finalize_terminal(state)
                        yield from drain_emitted_events()
                        return
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            state = self._mark_streaming_fast_persist(state)
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "persist_session",
                self.services.persist_session,
                state,
                heartbeat_stage="persist_session",
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            state = self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
            yield from drain_emitted_events()
            return

        # 2) intent_analysis
        self._emit_stage_event(state, "intent_analysis_started", "intent_analysis", "started", elapsed_ms=0.0)
        state = yield from self._invoke_stage_with_heartbeat_streaming(
            "understand_turn",
            lambda current: run_understand_turn(current, self.services.understand_turn),
            state,
            heartbeat_stage="intent_analysis",
        )
        intent_elapsed = float(state["runtime"].metrics.get("intent_analysis_elapsed_ms", 0.0) or 0.0)
        self._emit_stage_event(state, "intent_analysis_done", "intent_analysis", "done", elapsed_ms=intent_elapsed)
        yield from drain_emitted_events()
        next_stage = route_after_understand(state)
        if next_stage == "emit_final":
            persistent = state["persistent"]
            if getattr(persistent, "pending_clarification", None) is not None:
                state = self._mark_streaming_fast_persist(state)
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "persist_session",
                    self.services.persist_session,
                    state,
                    heartbeat_stage="persist_session",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
            state = self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
            yield from drain_emitted_events()
            return

        # 3) 分支阶段
        if next_stage == "route_gate":
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "route_gate",
                route_gate,
                state,
                heartbeat_stage="route_gate",
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            next_stage = route_decider(state)
            if next_stage == "clarify":
                self._emit_stage_event(state, "answer_stream_started", "compose_answer", "started", elapsed_ms=0.0)
                yield from drain_emitted_events()
                gen = self._invoke_stage_streaming("compose_answer", self.services.compose_answer, state)
                while True:
                    try:
                        item = next(gen)
                        if isinstance(item, SseEnvelope) and item.event_type == "answer_delta":
                            item = item.model_copy(update={"event_type": "delta"})
                        yield item
                    except StopIteration as e:
                        state = e.value
                        break
                yield from drain_emitted_events()
                state = self._materialize_pending_clarification_from_answer(state)
                if self._is_terminal(state):
                    persistent = state["persistent"]
                    if getattr(persistent, "pending_clarification", None) is not None:
                        state = self._mark_streaming_fast_persist(state)
                        state = yield from self._invoke_stage_with_heartbeat_streaming(
                            "persist_session",
                            self.services.persist_session,
                            state,
                            heartbeat_stage="persist_session",
                        )
                        yield from drain_emitted_events()
                        if self._is_terminal(state):
                            state = self._finalize_terminal(state)
                            yield from drain_emitted_events()
                            return
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
                state = self._mark_streaming_fast_persist(state)
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "persist_session",
                    self.services.persist_session,
                    state,
                    heartbeat_stage="persist_session",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
                state = self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
                yield from drain_emitted_events()
                return
            if next_stage == "tool":
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "tool_subgraph",
                    lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                    state,
                    heartbeat_stage="tool",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
            elif next_stage == "rag":
                self._emit_stage_event(state, "retrieval_started", "retrieval", "started", elapsed_ms=0.0)
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "rag_subgraph",
                    lambda current: run_rag_subgraph(current, self.services.rag_subgraph),
                    state,
                    heartbeat_stage="retrieval",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
                next_stage = route_after_rag(state)
                if next_stage == "tool_subgraph":
                    state = yield from self._invoke_stage_with_heartbeat_streaming(
                        "tool_subgraph",
                        lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                        state,
                        heartbeat_stage="tool",
                    )
                    yield from drain_emitted_events()
                    if self._is_terminal(state):
                        state = self._finalize_terminal(state)
                        yield from drain_emitted_events()
                        return
            elif next_stage == "rag_plus_tool":
                self._emit_stage_event(state, "retrieval_started", "retrieval", "started", elapsed_ms=0.0)
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "rag_subgraph",
                    lambda current: run_rag_subgraph(current, self.services.rag_subgraph),
                    state,
                    heartbeat_stage="retrieval",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "tool_subgraph",
                    lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                    state,
                    heartbeat_stage="tool",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
            elif next_stage == "recommendation":
                self._emit_stage_event(state, "retrieval_started", "retrieval", "started", elapsed_ms=0.0)
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "recommendation_subgraph",
                    lambda current: run_recommendation_subgraph(current, self.services.rag_subgraph),
                    state,
                    heartbeat_stage="retrieval",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
            elif next_stage == "direct":
                pass
        if next_stage == "rag_subgraph":
            self._emit_stage_event(state, "retrieval_started", "retrieval", "started", elapsed_ms=0.0)
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "rag_subgraph",
                lambda current: run_rag_subgraph(current, self.services.rag_subgraph),
                state,
                heartbeat_stage="retrieval",
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            next_stage = route_after_rag(state)
            if next_stage == "tool_subgraph":
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "tool_subgraph",
                    lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                    state,
                    heartbeat_stage="tool",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
        elif next_stage == "tool_subgraph":
            state = yield from self._invoke_stage_with_heartbeat_streaming(
                "tool_subgraph",
                lambda current: run_tool_subgraph(current, self.services.tool_subgraph),
                state,
                heartbeat_stage="tool",
            )
            yield from drain_emitted_events()
            if self._is_terminal(state):
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return

        # 4) answer stream
        self._emit_stage_event(state, "answer_stream_started", "compose_answer", "started", elapsed_ms=0.0)
        yield from drain_emitted_events()
        gen = self._invoke_stage_streaming("compose_answer", self.services.compose_answer, state)
        while True:
            try:
                item = next(gen)
                if isinstance(item, SseEnvelope) and item.event_type == "answer_delta":
                    item = item.model_copy(update={"event_type": "delta"})
                yield item
            except StopIteration as e:
                state = e.value
                break

        yield from drain_emitted_events()
        state = self._materialize_pending_clarification_from_answer(state)
        if self._is_terminal(state):
            persistent = state["persistent"]
            if getattr(persistent, "pending_clarification", None) is not None:
                state = self._mark_streaming_fast_persist(state)
                state = yield from self._invoke_stage_with_heartbeat_streaming(
                    "persist_session",
                    self.services.persist_session,
                    state,
                    heartbeat_stage="persist_session",
                )
                yield from drain_emitted_events()
                if self._is_terminal(state):
                    state = self._finalize_terminal(state)
                    yield from drain_emitted_events()
                    return
                state = self._finalize_terminal(state)
                yield from drain_emitted_events()
                return
            state = self._mark_streaming_fast_persist(state)

        state = yield from self._invoke_stage_with_heartbeat_streaming(
            "persist_session",
            self.services.persist_session,
            state,
            heartbeat_stage="persist_session",
        )
        yield from drain_emitted_events()
        if self._is_terminal(state):
            state = self._finalize_terminal(state)
            yield from drain_emitted_events()
            return

        state = self._finalize_terminal(state, default_terminal=TerminalEvent.FINAL)
        yield from drain_emitted_events()

    @staticmethod
    def _materialize_pending_clarification_from_answer(state: GraphState) -> GraphState:
        persistent = state["persistent"]
        if getattr(persistent, "pending_clarification", None) is not None:
            return state
        turn = state["turn"]
        answer_text = str(getattr(turn, "final_answer", "") or "").strip()
        if not answer_text:
            return state
        if "?" not in answer_text and "？" not in answer_text:
            return state
        if not any(token in answer_text for token in ("城市", "位置", "附近", "场景", "哪类", "哪里", "哪种")):
            return state

        ambiguity_type = "location" if any(token in answer_text for token in ("城市", "位置", "附近")) else "general"
        clarification_result = {
            "original_query": str(turn.raw_query or "").strip(),
            "original_intent": "local_life_recommend",
            "original_route": "rag_retrieval",
            "question": answer_text,
            "ambiguity_type": ambiguity_type,
        }
        pending_clarification = ClarificationCard(
            card_id=f"{state['runtime'].session_id}:{state['runtime'].turn_id}:clarification",
            question=answer_text,
            options=[],
            ambiguity_type=ambiguity_type,
            source_turn_id=state["runtime"].turn_id,
            expires_at=None,
        )
        state["persistent"] = persistent.model_copy(
            update={
                "clarification_result": clarification_result,
                "pending_clarification": pending_clarification,
            }
        )
        turn_extra = dict(turn.extra)
        turn_extra["clarification_result"] = clarification_result
        turn_extra["pending_clarification"] = pending_clarification.model_dump(mode="json")
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state

    @staticmethod
    def _mark_streaming_fast_persist(state: GraphState) -> GraphState:
        runtime = state["runtime"]
        turn = state["turn"]
        persistent = state["persistent"]
        runtime_context = dict(state.get("runtime_context", {}) or {})
        runtime_context["streaming_fast_persist"] = True
        state["runtime_context"] = runtime_context
        turn_extra = dict(getattr(turn, "extra", {}) or {})
        turn_extra["streaming_fast_persist"] = True
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        persistent_extra = dict(getattr(persistent, "extra", {}) or {})
        persistent_extra["streaming_fast_persist"] = True
        state["persistent"] = persistent.model_copy(update={"extra": persistent_extra})
        runtime_extra = dict(getattr(runtime, "extra", {}) or {})
        runtime_extra["streaming_fast_persist"] = True
        state["runtime"] = runtime.model_copy(update={"extra": runtime_extra})
        return state

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

    def _invoke_stage_with_heartbeat(
        self,
        stage_name: str,
        handler,
        state: GraphState,
        *,
        heartbeat_stage: str,
        heartbeat_interval_ms: int = 800,
    ) -> GraphState:
        result_holder: dict[str, GraphState] = {}
        started_at = time.perf_counter()

        def _run_stage() -> None:
            result_holder["state"] = self._invoke_stage(stage_name, handler, state)

        worker = threading.Thread(target=_run_stage, name=f"workflow-{stage_name}-sync", daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(timeout=max(0.05, heartbeat_interval_ms / 1000.0))
            if worker.is_alive():
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                self._emit_stage_event(
                    state,
                    "heartbeat",
                    heartbeat_stage,
                    "running",
                    elapsed_ms=elapsed_ms,
                )
        worker.join()
        return result_holder.get("state", state)

    def _invoke_stage_with_heartbeat_streaming(
        self,
        stage_name: str,
        handler,
        state: GraphState,
        *,
        heartbeat_stage: str,
        heartbeat_interval_ms: int = 800,
    ):
        result_holder: dict[str, GraphState] = {}
        started_at = time.perf_counter()

        def _run_stage() -> None:
            result_holder["state"] = self._invoke_stage(stage_name, handler, state)

        worker = threading.Thread(target=_run_stage, name=f"workflow-{stage_name}-sync", daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(timeout=max(0.05, heartbeat_interval_ms / 1000.0))
            if not worker.is_alive():
                break
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            runtime = state["runtime"]
            turn = state["turn"]
            routing = getattr(turn, "routing_decision", None)
            payload = {
                "stage": heartbeat_stage,
                "status": "running",
                "elapsed_ms": elapsed_ms,
                "degrade_to": None,
                "error": None,
                "metrics": {},
                "current_stage": getattr(turn, "current_stage", heartbeat_stage),
                "stage_status": getattr(turn, "stage_status", "running"),
                "route_decision": routing.required_action if routing is not None else None,
                "route_reason": routing.route_reason if routing is not None else None,
                "message": None,
                "details": {},
            }
            _LOGGER.info(
                "workflow_stage_event trace_id=%s session_id=%s turn_id=%s stage=%s status=%s elapsed_ms=%.1f degrade_to=%s error=%s",
                runtime.trace_id,
                runtime.session_id,
                runtime.turn_id,
                heartbeat_stage,
                "heartbeat",
                elapsed_ms,
                None,
                "",
            )
            yield SseEnvelope(
                event_type="heartbeat",
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                timestamp=datetime.now(timezone.utc),
                workflow_version=runtime.workflow_version,
                payload=payload,
            )
        worker.join()
        return result_holder.get("state", state)

    def _invoke_stage(self, stage_name: str, handler, state: GraphState) -> GraphState:
        metric_stage = {
            "understand_turn": "intent_analysis",
            "rag_subgraph": "retrieval",
        }.get(stage_name, stage_name)
        started_at = time.perf_counter()
        try:
            result = handler(state)
            if type(result).__name__ == "Command" or (hasattr(result, "update") and not isinstance(result, dict)):
                cmd = result
                result = clone_graph_state(state)
                if isinstance(cmd.update, dict):
                    result.update(cmd.update)
        except Exception as exc:  # pragma: no cover - defensive safeguard
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            runtime = state["runtime"]
            _LOGGER.exception(
                "workflow_stage_event trace_id=%s session_id=%s turn_id=%s stage=%s status=failed elapsed_ms=%.1f error=%s",
                runtime.trace_id,
                runtime.session_id,
                runtime.turn_id,
                metric_stage,
                elapsed_ms,
                str(exc),
            )
            return self._record_unexpected_error(state, stage_name, exc)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        runtime = result["runtime"]
        metrics = dict(runtime.metrics)
        stage_timings = dict(metrics.get("stage_elapsed_ms", {}) or {})
        stage_timings[metric_stage] = round(elapsed_ms, 3)
        metrics["stage_elapsed_ms"] = stage_timings
        metrics[f"{metric_stage}_elapsed_ms"] = round(elapsed_ms, 3)
        if stage_name == "understand_turn":
            metrics["understand_bundle_ms"] = round(elapsed_ms, 3)
        elif stage_name == "rag_subgraph":
            metrics["retrieval_bundle_ms"] = round(elapsed_ms, 3)
        result["runtime"] = runtime.model_copy(update={"metrics": metrics})
        phase5_trace = dict(metrics.get(_PHASE5_TRACE_KEY, {}) or {})
        nodes_visited = list(phase5_trace.get("nodes_visited") or [])
        if metric_stage not in nodes_visited:
            nodes_visited.append(metric_stage)
        result = _update_phase5_trace(result, nodes_visited=nodes_visited)
        _LOGGER.info(
            "workflow_stage_event trace_id=%s session_id=%s turn_id=%s stage=%s status=done elapsed_ms=%.1f degrade_to=%s error=",
            runtime.trace_id,
            runtime.session_id,
            runtime.turn_id,
            metric_stage,
            elapsed_ms,
            runtime.degrade_to,
        )
        return result

    def _invoke_stage_streaming(self, stage_name: str, handler, state: GraphState):
        event_queue: queue.Queue[object] = queue.Queue()
        runtime = state["runtime"]
        runtime_context = dict(state.get("runtime_context", {}) or {})
        runtime_context["stream_event_sink"] = event_queue
        state["runtime_context"] = runtime_context
        runtime_extra = dict(getattr(runtime, "extra", {}) or {})
        runtime_extra["stream_event_sink"] = event_queue
        state["runtime"] = runtime.model_copy(update={"extra": runtime_extra})
        started_at = time.perf_counter()

        result_holder: dict[str, GraphState] = {}

        def _run_stage() -> None:
            try:
                result_holder["state"] = self._invoke_stage(stage_name, handler, state)
            finally:
                event_queue.put(_STREAM_STOP)

        worker = threading.Thread(target=_run_stage, name=f"workflow-{stage_name}-stream", daemon=True)
        worker.start()

        while True:
            try:
                item = event_queue.get(timeout=0.8)
            except queue.Empty:
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                self._emit_stage_event(state, "heartbeat", stage_name, "running", elapsed_ms=elapsed_ms)
                continue
            if item is _STREAM_STOP:
                break
            if isinstance(item, SseEnvelope):
                if item.event_type == "answer_delta":
                    item = item.model_copy(update={"event_type": "delta"})
                yield item

        worker.join()
        state = result_holder.get("state", state)
        runtime_context = dict(state.get("runtime_context", {}) or {})
        runtime_context.pop("stream_event_sink", None)
        state["runtime_context"] = runtime_context
        runtime = state["runtime"]
        runtime_extra = dict(getattr(runtime, "extra", {}) or {})
        runtime_extra.pop("stream_event_sink", None)
        state["runtime"] = runtime.model_copy(update={"extra": runtime_extra})
        return state

    @staticmethod
    def _should_consume_pending_clarification(state: GraphState) -> bool:
        persistent = state["persistent"]
        turn = state["turn"]
        pending = getattr(persistent, "pending_clarification", None)
        if pending is None:
            pending_payload = dict(getattr(turn, "extra", {}) or {}).get("pending_clarification")
            if isinstance(pending_payload, Mapping):
                try:
                    pending = ClarificationCard.model_validate(dict(pending_payload))
                except Exception:
                    pending = None
        if pending is None:
            return False
        raw_query = str(state["turn"].raw_query or "").strip()
        if not raw_query or _looks_like_unserviceable_location(raw_query):
            return False
        if getattr(persistent, "pending_clarification", None) is not pending:
            persistent = persistent.model_copy(update={"pending_clarification": pending})
        return _pending_clarification_matches_query(raw_query, persistent)

    @staticmethod
    def _is_conversation_recap_route(state: GraphState) -> bool:
        routing = state["turn"].routing_decision
        if routing is None:
            return False
        route_candidate = str(routing.route_candidate).strip().lower()
        return route_candidate in {"conversation_recap", "continue_previous_topic"}

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
