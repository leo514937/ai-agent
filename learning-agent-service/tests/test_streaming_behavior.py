from __future__ import annotations

import unittest
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.api.contracts import ChatStreamRequest, EventType, FinalPayload, SseEnvelope as ApiSseEnvelope
from learning_agent_service.application.service import WorkflowLearningAgentService
from learning_agent_service.application.workflow.runner import SequentialWorkflowRunner
from learning_agent_service.domain.contracts import AnswerComposeRequest, ChatTurnCommand, PersistentSessionContext, RagResult, SseEnvelope
from learning_agent_service.domain.enums import RagStatus
from learning_agent_service.application.workflow.services import (
    RagSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
    WorkflowServices,
)
from learning_agent_service.tools.service import AnswerComposer


class _TrackingSessionStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def load(self, session_id: str, user_id: str):
        self.calls.append((session_id, user_id))
        return PersistentSessionContext()


class _TrackingChatUseCase:
    def __init__(self) -> None:
        self.started = False
        self.calls: list[tuple[ChatTurnCommand, object]] = []

    def run(self, *, command: ChatTurnCommand, persistent_context=None):
        self.started = True
        self.calls.append((command, persistent_context))
        yield ApiSseEnvelope(
            event_type=EventType.FINAL.value,
            trace_id=command.trace_id,
            session_id=command.session_id,
            turn_id=command.turn_id,
            timestamp=datetime.now(timezone.utc),
            workflow_version="test/v1",
            payload=FinalPayload(
                answer_text="ok",
                citations=[],
                mode="remote",
                source="learning-agent-service",
                page=command.page,
            ).model_dump(mode="json"),
        )


class _FakeWorkflowServices:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.understand_turn = UnderstandTurnServices(
            parse_intent_slots=lambda state: self._append(state, "parse_intent_slots", EventType.RETRIEVAL_RESULT.value),
            resolve_reference=lambda state: self._append(state, "resolve_reference", EventType.RETRIEVAL_RESULT.value),
            ambiguity_check=lambda state: self._append(state, "ambiguity_check", EventType.RETRIEVAL_RESULT.value),
            rag_gate=lambda state: self._append(state, "rag_gate", EventType.RETRIEVAL_RESULT.value),
            rewrite_query=lambda state: self._append(state, "rewrite_query", EventType.RETRIEVAL_RESULT.value),
        )
        self.rag_subgraph = RagSubgraphServices(
            hybrid_retrieve=lambda state: self._append(state, "hybrid_retrieve", EventType.RETRIEVAL_RESULT.value),
            evaluate_evidence=lambda state: self._append(state, "evaluate_evidence", EventType.RETRIEVAL_RESULT.value),
            citation_builder=lambda state: self._append(state, "citation_builder", EventType.RETRIEVAL_RESULT.value),
        )
        self.tool_subgraph = ToolSubgraphServices(
            tool_planner=lambda state: self._append(state, "tool_planner", EventType.TOOL_RESULT.value),
            tool_executor=lambda state: self._append(state, "tool_executor", EventType.TOOL_RESULT.value),
            tool_result_normalizer=lambda state: self._append(state, "tool_result_normalizer", EventType.TOOL_RESULT.value),
        )

    def _append(self, state, stage: str, event_type: str) -> object:
        self.calls.append(stage)
        runtime = state["runtime"]
        events = list(runtime.emitted_events)
        events.append(
            SseEnvelope(
                event_type=event_type,
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                timestamp=datetime.now(timezone.utc),
                workflow_version=runtime.workflow_version,
                payload={"stage": stage},
            )
        )
        state["runtime"] = runtime.model_copy(update={"emitted_events": events})
        return state

    def load_context(self, state):
        return self._append(state, "load_context", EventType.RETRIEVAL_STARTED.value)

    def understand_turn(self, state):
        return self._append(state, "understand_turn", EventType.RETRIEVAL_RESULT.value)

    def rag_subgraph(self, state):
        return self._append(state, "rag_subgraph", EventType.RETRIEVAL_RESULT.value)

    def tool_subgraph(self, state):
        return self._append(state, "tool_subgraph", EventType.TOOL_RESULT.value)

    def compose_answer(self, state):
        runtime = state["runtime"]
        stream_sink = runtime.extra.get("stream_event_sink")
        if stream_sink is not None:
            stream_sink.put(
                SseEnvelope(
                    event_type=EventType.DELTA.value,
                    trace_id=runtime.trace_id,
                    session_id=runtime.session_id,
                    turn_id=runtime.turn_id,
                    timestamp=datetime.now(timezone.utc),
                    workflow_version=runtime.workflow_version,
                    payload={
                        "delta": "正在生成回答",
                        "answer_text": "正在生成回答",
                        "current_stage": "compose",
                        "stage_status": "streaming",
                    },
                )
            )
        turn = state["turn"]
        state["turn"] = turn.model_copy(update={"final_answer": "最终答案"})
        return self._append(state, "compose_answer", EventType.FINAL.value)

    def persist_session(self, state):
        return self._append(state, "persist_session", EventType.FINAL.value)

    def emit_final(self, state):
        return self._append(state, "emit_final", EventType.FINAL.value)


class StreamingBehaviorTestCase(unittest.TestCase):
    def test_service_emits_ack_before_loading_session_or_workflow(self) -> None:
        session_store = _TrackingSessionStore()
        chat_use_case = _TrackingChatUseCase()
        container = SimpleNamespace(
            settings=SimpleNamespace(workflow_version="test/v1"),
            memory_service=SimpleNamespace(load_any=lambda session_id: PersistentSessionContext()),
            session_context_store=session_store,
        )
        service = WorkflowLearningAgentService(container)
        service.chat_use_case = chat_use_case

        stream = service.run_stream(
            ChatStreamRequest(
                user_id="user-1",
                session_id="session-1",
                trace_id="trace-1",
                turn_id="turn-1",
                message="你好",
                page="assistant",
            )
        )

        first = next(stream)
        self.assertEqual(first.event_type, EventType.ACK.value)
        self.assertEqual(session_store.calls, [])
        self.assertFalse(chat_use_case.started)

        second = next(stream)
        self.assertEqual(second.event_type, EventType.FINAL.value)
        self.assertEqual(session_store.calls, [("session-1", "user-1")])
        self.assertTrue(chat_use_case.started)

    def test_runner_stream_yields_before_completion_of_all_stages(self) -> None:
        services = _FakeWorkflowServices()
        runner = SequentialWorkflowRunner(services=services, workflow_version="test/v1")
        command = ChatTurnCommand(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            message="你好",
            page="assistant",
        )

        with patch(
            "learning_agent_service.application.workflow.runner.route_after_understand",
            return_value="emit_final",
        ):
            stream = runner.run_stream(command=command, persistent_context=PersistentSessionContext())

            # First event: load_context_started
            first = next(stream)
            self.assertEqual(first.event_type, EventType.LOAD_CONTEXT_STARTED.value)
            self.assertEqual(first.payload["stage"], "load_context")

            # Second event: retrieval_started emitted inside mocked load_context
            second = next(stream)
            self.assertEqual(second.event_type, EventType.RETRIEVAL_STARTED.value)

            # Third event: load_context_done
            third = next(stream)
            self.assertEqual(third.event_type, EventType.LOAD_CONTEXT_DONE.value)
            self.assertEqual(services.calls, ["load_context"])

            remaining = list(stream)

        self.assertTrue(any(event.event_type == EventType.FINAL.value for event in remaining))
        self.assertIn("parse_intent_slots", services.calls)
        self.assertIn("emit_final", services.calls)

    def test_runner_stream_emits_answer_delta_before_final(self) -> None:
        services = _FakeWorkflowServices()
        runner = SequentialWorkflowRunner(services=services, workflow_version="test/v1")
        command = ChatTurnCommand(
            trace_id="trace-2",
            session_id="session-2",
            turn_id="turn-2",
            user_id="user-2",
            message="你好",
            page="assistant",
        )

        with patch(
            "learning_agent_service.application.workflow.runner.route_after_understand",
            return_value="rag_subgraph",
        ), patch(
            "learning_agent_service.application.workflow.runner.route_after_rag",
            return_value="compose_answer",
        ):
            stream = runner.run_stream(command=command, persistent_context=PersistentSessionContext())
            event_types = [event.event_type for event in stream]

        self.assertIn(EventType.DELTA.value, event_types)
        self.assertIn(EventType.FINAL.value, event_types)
        self.assertLess(
            event_types.index(EventType.DELTA.value),
            event_types.index(EventType.FINAL.value),
        )

    def test_runner_records_stage_timing_metrics_for_bundles(self) -> None:
        services = _FakeWorkflowServices()
        runner = SequentialWorkflowRunner(services=services, workflow_version="test/v1")
        command = ChatTurnCommand(
            trace_id="trace-3",
            session_id="session-3",
            turn_id="turn-3",
            user_id="user-3",
            message="解释一下 RAG",
            page="assistant",
        )

        with patch(
            "learning_agent_service.application.workflow.runner.route_after_understand",
            return_value="rag_subgraph",
        ), patch(
            "learning_agent_service.application.workflow.runner.route_after_rag",
            return_value="emit_final",
        ):
            state = runner.run(command=command, persistent_context=PersistentSessionContext())

        metrics = state["runtime"].metrics
        self.assertIn("stage_elapsed_ms", metrics)
        self.assertIn("intent_analysis_elapsed_ms", metrics)
        self.assertIn("retrieval_elapsed_ms", metrics)
        self.assertIn("understand_bundle_ms", metrics)
        self.assertIn("retrieval_bundle_ms", metrics)
        self.assertIn("compose_answer_elapsed_ms", metrics)

    def test_fallback_answer_composer_streams_contextual_answer_deltas(self) -> None:
        events: list[SseEnvelope] = []
        composer = AnswerComposer()
        request = AnswerComposeRequest(
            raw_query="解释一下 Spring AOP 的原理",
            requested_output_style=None,
            rag_result=RagResult(
                status=RagStatus.EMPTY,
                evidence_pack=None,
                citations=[],
                evidence_status="EMPTY",
            ),
            tool_result=None,
            plan_summary=None,
            memory_injection_plan=None,
            stream_event_sink=events.append,
            stream_event_meta={
                "trace_id": "trace-3",
                "session_id": "session-3",
                "turn_id": "turn-3",
                "workflow_version": "test/v1",
                "current_stage": "compose",
                "stage_status": "streaming",
            },
        )

        result = composer.compose(request)

        self.assertIn("Spring AOP", result.answer_text)
        self.assertGreater(len(events), 0)
        self.assertTrue(all(event.event_type == "delta" for event in events))
        self.assertEqual(events[-1].payload["answer_text"], result.answer_text)

    def test_sse_event_sequence_matches_stage_protocol(self) -> None:
        def _noop(state):
            return state

        def _compose(state):
            runtime = state["runtime"]
            stream_sink = runtime.extra.get("stream_event_sink")
            if stream_sink is not None:
                stream_sink.put(
                    SseEnvelope(
                        event_type="delta",
                        trace_id=runtime.trace_id,
                        session_id=runtime.session_id,
                        turn_id=runtime.turn_id,
                        timestamp=datetime.now(timezone.utc),
                        workflow_version=runtime.workflow_version,
                        payload={"delta": "答", "answer_text": "答"},
                    )
                )
            turn = state["turn"]
            state["turn"] = turn.model_copy(update={"final_answer": "答案"})
            return state

        def _emit_final(state):
            runtime = state["runtime"]
            events = list(runtime.emitted_events)
            events.append(
                SseEnvelope(
                    event_type=EventType.FINAL.value,
                    trace_id=runtime.trace_id,
                    session_id=runtime.session_id,
                    turn_id=runtime.turn_id,
                    timestamp=datetime.now(timezone.utc),
                    workflow_version=runtime.workflow_version,
                    payload={"answer_text": "答案", "citations": []},
                )
            )
            state["runtime"] = runtime.model_copy(update={"emitted_events": events})
            return state

        services = WorkflowServices(
            load_context=_noop,
            understand_turn=UnderstandTurnServices(
                parse_intent_slots=_noop,
                resolve_reference=_noop,
                ambiguity_check=_noop,
                rag_gate=_noop,
                rewrite_query=_noop,
            ),
            rag_subgraph=RagSubgraphServices(
                hybrid_retrieve=_noop,
                evaluate_evidence=_noop,
                citation_builder=_noop,
            ),
            tool_subgraph=ToolSubgraphServices(),
            compose_answer=_compose,
            persist_session=_noop,
            emit_final=_emit_final,
        )
        runner = SequentialWorkflowRunner(services=services, workflow_version="test/v1")
        command = ChatTurnCommand(
            trace_id="trace-order",
            session_id="session-order",
            turn_id="turn-order",
            user_id="user-order",
            message="推荐附近吃饭",
            page="assistant",
        )

        with patch(
            "learning_agent_service.application.workflow.runner.route_after_understand",
            return_value="rag_subgraph",
        ), patch(
            "learning_agent_service.application.workflow.runner.route_after_rag",
            return_value="compose_answer",
        ):
            events = list(runner.run_stream(command=command, persistent_context=PersistentSessionContext()))

        event_types = [event.event_type for event in events]
        expected_sequence = [
            "load_context_started",
            "load_context_done",
            "intent_analysis_started",
            "intent_analysis_done",
            "retrieval_started",
            "answer_stream_started",
            "delta",
            "final",
        ]
        positions = [event_types.index(item) for item in expected_sequence]
        self.assertEqual(positions, sorted(positions))

    def test_long_stage_emits_heartbeat(self) -> None:
        def _slow_load_context(state):
            time.sleep(0.95)
            return state

        def _emit_final(state):
            runtime = state["runtime"]
            events = list(runtime.emitted_events)
            events.append(
                SseEnvelope(
                    event_type=EventType.FINAL.value,
                    trace_id=runtime.trace_id,
                    session_id=runtime.session_id,
                    turn_id=runtime.turn_id,
                    timestamp=datetime.now(timezone.utc),
                    workflow_version=runtime.workflow_version,
                    payload={"answer_text": "ok", "citations": []},
                )
            )
            state["runtime"] = runtime.model_copy(update={"emitted_events": events})
            return state

        def _compose_noop(state):
            turn = state["turn"]
            state["turn"] = turn.model_copy(update={"final_answer": "ok"})
            return state

        services = WorkflowServices(
            load_context=_slow_load_context,
            understand_turn=UnderstandTurnServices(),
            rag_subgraph=RagSubgraphServices(),
            tool_subgraph=ToolSubgraphServices(),
            compose_answer=_compose_noop,
            persist_session=lambda state: state,
            emit_final=_emit_final,
        )
        runner = SequentialWorkflowRunner(services=services, workflow_version="test/v1")
        command = ChatTurnCommand(
            trace_id="trace-heartbeat",
            session_id="session-heartbeat",
            turn_id="turn-heartbeat",
            user_id="user-heartbeat",
            message="你好",
            page="assistant",
        )

        with patch(
            "learning_agent_service.application.workflow.runner.route_after_understand",
            return_value="emit_final",
        ):
            events = list(runner.run_stream(command=command, persistent_context=PersistentSessionContext()))

        event_types = [event.event_type for event in events]
        self.assertIn("heartbeat", event_types)


if __name__ == "__main__":
    unittest.main()
