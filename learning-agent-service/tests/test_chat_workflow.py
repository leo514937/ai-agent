from __future__ import annotations

import unittest
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import _bootstrap  # noqa: F401

from learning_agent_service.application.use_cases.chat_workflow import ChatWorkflowService
from learning_agent_service.application.service import WorkflowLearningAgentService
from learning_agent_service.application.dependencies import OpenAIBackedModelGateway
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, SseEnvelope, TurnUnderstandingRequest
from learning_agent_service.domain.errors import TerminalEvent, WorkflowErrorCode, build_error
from learning_agent_service.domain.enums import IntentType, TurnDecision
from learning_agent_service.domain.state import build_initial_state
from learning_agent_service.rag.heuristics import HeuristicModelGateway


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls = []

    def run_stream(self, *, command, persistent_context):
        self.calls.append((command, persistent_context))
        return ["runner-event"]


class _RecordingSubgraph:
    def __init__(self) -> None:
        self.called = False

    def run_stream(self, *, command, persistent_context):
        self.called = True
        return ["subgraph-event"]


class ChatWorkflowServiceTestCase(unittest.TestCase):
    def test_run_uses_workflow_runner_as_default_entry(self) -> None:
        store = SimpleNamespace(load=MagicMock(return_value=PersistentSessionContext(current_topic="火锅")))
        service = ChatWorkflowService.__new__(ChatWorkflowService)
        service._container = SimpleNamespace(session_context_store=store)
        service._workflow_runner = _RecordingRunner()
        service._workflow = _RecordingSubgraph()

        command = ChatTurnCommand(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            message="解释一下 Python 的列表推导式",
        )

        events = list(service.run(command))

        self.assertEqual(events, ["runner-event"])
        self.assertEqual(len(service._workflow_runner.calls), 1)
        self.assertFalse(service._workflow.called)
        self.assertEqual(service._workflow_runner.calls[0][1].current_topic, "火锅")

    def test_run_uses_local_life_subgraph_for_local_life_turn(self) -> None:
        store = SimpleNamespace(load=MagicMock(return_value=PersistentSessionContext(current_topic="火锅")))
        service = ChatWorkflowService.__new__(ChatWorkflowService)
        service._container = SimpleNamespace(session_context_store=store)
        service._workflow_runner = _RecordingRunner()
        service._workflow = _RecordingSubgraph()

        command = ChatTurnCommand(
            trace_id="trace-2",
            session_id="session-2",
            turn_id="turn-2",
            user_id="user-2",
            message="海底捞火锅(水晶城购物中心店）怎么样？",
            page="assistant",
        )

        events = list(service.run(command))

        self.assertEqual(events, ["subgraph-event"])
        self.assertEqual(len(service._workflow_runner.calls), 0)
        self.assertTrue(service._workflow.called)
        self.assertEqual(service._workflow.called, True)


class _RecordingChatUseCase:
    def __init__(self) -> None:
        self.calls = []

    def run(self, *, command, persistent_context):
        self.calls.append((command, persistent_context))
        return [
            SseEnvelope(
                event_type="final",
                trace_id=command.trace_id,
                session_id=command.session_id,
                turn_id=command.turn_id,
                timestamp=datetime.now(timezone.utc),
                workflow_version="test-workflow",
                payload={"answer_text": "subgraph-final"},
            )
        ]


class WorkflowLearningAgentServiceTestCase(unittest.TestCase):
    def test_chat_stream_for_local_life_turn_uses_chat_use_case(self) -> None:
        store = SimpleNamespace(load=MagicMock(return_value=PersistentSessionContext(current_topic="火锅")))
        container = SimpleNamespace(
            settings=SimpleNamespace(workflow_version="test-workflow"),
            session_context_store=store,
            memory_service=SimpleNamespace(),
        )
        service = WorkflowLearningAgentService.__new__(WorkflowLearningAgentService)
        service.container = container
        recording_use_case = _RecordingChatUseCase()
        service.chat_use_case = recording_use_case
        service.session_query_use_case = SimpleNamespace(get=lambda session_id: PersistentSessionContext())

        request = SimpleNamespace(
            trace_id="trace-api-1",
            session_id="session-api-1",
            turn_id="turn-api-1",
            user_id="user-api-1",
            message="海底捞火锅(水晶城购物中心店）怎么样？",
            page="assistant",
            response_mode=None,
            topic_hint=None,
            history_summary=None,
            client_context={},
        )

        events = list(service.run_stream(request))

        self.assertEqual(events[0].event_type, "ack")
        self.assertEqual(events[-1].event_type, "final")
        self.assertEqual(events[-1].payload["answer_text"], "subgraph-final")
        self.assertEqual(len(recording_use_case.calls), 1)
        self.assertEqual(recording_use_case.calls[0][0].message, request.message)
        self.assertEqual(recording_use_case.calls[0][1].current_topic, "火锅")


class DomainModelDefaultsTestCase(unittest.TestCase):
    def test_chat_turn_command_and_session_context_allow_empty_defaults(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            message="推荐北京望京附近适合带爸妈吃饭、安静、有停车、人均150以内的家常菜",
        )
        persistent = PersistentSessionContext()

        self.assertIsNone(command.page)
        self.assertIsNone(command.response_mode)
        self.assertIsNone(command.topic_hint)
        self.assertIsNone(command.history_summary)
        self.assertEqual(command.client_context, {})

        self.assertIsNone(persistent.current_topic)
        self.assertEqual(persistent.recent_entities, [])
        self.assertEqual(persistent.clarification_result, {})
        self.assertEqual(persistent.user_preferences, {})
        self.assertIsNone(persistent.last_retrieval_topic)
        self.assertIsNone(persistent.history_summary)
        self.assertEqual(persistent.open_questions, [])
        self.assertEqual(persistent.confirmed_facts, [])
        self.assertEqual(persistent.next_steps, [])
        self.assertEqual(persistent.summary_version, 0)
        self.assertIsNone(persistent.summary_updated_at)
        self.assertIsNone(persistent.pending_clarification)
        self.assertIsNone(persistent.current_city)
        self.assertEqual(persistent.current_location, {})
        self.assertEqual(persistent.current_constraints, {})
        self.assertEqual(persistent.last_candidates, [])
        self.assertIsNone(persistent.selected_shop_id)
        self.assertIsNone(persistent.selected_shop_name)
        self.assertEqual(persistent.local_life_preferences, [])
        self.assertEqual(persistent.local_life_avoid, [])
        self.assertIsNone(persistent.current_scene)
        self.assertIsNone(persistent.current_action)
        self.assertIsNone(persistent.page)
        self.assertIsNone(persistent.route_decision)
        self.assertIsNone(persistent.route_reason)
        self.assertIsNone(persistent.current_stage)
        self.assertIsNone(persistent.stage_status)
        self.assertEqual(persistent.stage_timeline, [])
        self.assertEqual(persistent.extra, {})

    def test_build_initial_state_supports_minimal_command(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-2",
            session_id="session-2",
            turn_id="turn-2",
            user_id="user-2",
            message="bj",
        )
        state = build_initial_state(command, persistent=PersistentSessionContext())

        self.assertEqual(state["turn"].raw_query, "bj")
        self.assertEqual(state["turn"].short_term_window[0]["content"], "bj")
        self.assertEqual(state["turn"].decision, TurnDecision.DIRECT_ANSWER)
        self.assertIsNone(state["turn"].intent)
        self.assertEqual(state["persistent"].current_topic, None)
        self.assertEqual(state["runtime"].session_id, "session-2")

    def test_emit_final_uses_error_payload_when_terminal_event_is_error(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-3",
            session_id="session-3",
            turn_id="turn-3",
            user_id="user-3",
            message="bj",
        )
        state = build_initial_state(command, persistent=PersistentSessionContext())
        state["runtime"] = state["runtime"].model_copy(
            update={
                "terminal_event": TerminalEvent.ERROR,
                "errors": [
                    build_error(
                        WorkflowErrorCode.INTERNAL_ERROR,
                        stage="emit_final",
                        message="boom",
                        retryable=False,
                    )
                ],
            }
        )
        state["turn"] = state["turn"].model_copy(update={"current_stage": "emit_final", "stage_status": "failed"})

        updated = WorkflowNodeAdapter(SimpleNamespace()).emit_final(state)
        envelope = updated["runtime"].emitted_events[-1]

        self.assertEqual(envelope.event_type, "error")
        self.assertEqual(envelope.payload["code"], WorkflowErrorCode.INTERNAL_ERROR.value)
        self.assertEqual(envelope.payload["message"], "boom")
        self.assertNotIn("answer_text", envelope.payload)


class HeuristicModelGatewayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = HeuristicModelGateway()
        self.persistent = PersistentSessionContext()

    def test_coupon_query_maps_to_local_life_tool_turn(self) -> None:
        result = self.gateway.classify_turn(
            TurnUnderstandingRequest(
                command=ChatTurnCommand(
                    trace_id="trace-1",
                    session_id="session-1",
                    turn_id="turn-1",
                    user_id="user-1",
                    message="帮我看看这家店的优惠券",
                    topic_hint="示例粤菜馆",
                    client_context={"shopName": "示例粤菜馆"},
                ),
                persistent=self.persistent,
            )
        )

        self.assertTrue(result.needs_tool)
        self.assertTrue(result.needs_rag)
        self.assertEqual(result.intent, IntentType.FOLLOW_UP)
        self.assertEqual(result.key_slots["domain"], "local_life")
        self.assertEqual(result.key_slots["local_life_intent"], "coupon")
        self.assertEqual(result.key_slots["shop_name"], "示例粤菜馆")

    def test_booking_query_maps_to_local_life_tool_turn(self) -> None:
        result = self.gateway.classify_turn(
            TurnUnderstandingRequest(
                command=ChatTurnCommand(
                    trace_id="trace-1",
                    session_id="session-1",
                    turn_id="turn-1",
                    user_id="user-1",
                    message="帮我订今晚七点两个人的位置",
                    client_context={"shopName": "示例粤菜馆", "shopId": 1001},
                ),
                persistent=self.persistent,
            )
        )

        self.assertTrue(result.needs_tool)
        self.assertTrue(result.needs_rag)
        self.assertEqual(result.key_slots["local_life_intent"], "booking")
        self.assertEqual(result.key_slots["shop_id"], 1001)

    def test_general_knowledge_query_keeps_non_local_life_route(self) -> None:
        result = self.gateway.classify_turn(
            TurnUnderstandingRequest(
                command=ChatTurnCommand(
                    trace_id="trace-1",
                    session_id="session-1",
                    turn_id="turn-1",
                    user_id="user-1",
                    message="解释一下 Spring AOP 的原理",
                ),
                persistent=self.persistent,
            )
        )

        self.assertEqual(result.intent, IntentType.EXPLAIN)
        self.assertTrue(result.needs_rag)
        self.assertFalse(result.needs_tool)
        self.assertNotIn("local_life_intent", result.key_slots)


class OpenAIBackedModelGatewayTestCase(unittest.TestCase):
    def test_simple_greeting_hits_heuristic_without_calling_llm(self) -> None:
        responses = SimpleNamespace(create=MagicMock(side_effect=RuntimeError("should not call llm")))
        runtime = SimpleNamespace(client=SimpleNamespace(responses=responses), default_model="test-model")
        gateway = OpenAIBackedModelGateway(runtime=runtime, fallback=HeuristicModelGateway())

        result = gateway.classify_turn(
            TurnUnderstandingRequest(
                command=ChatTurnCommand(
                    trace_id="trace-greet",
                    session_id="session-greet",
                    turn_id="turn-greet",
                    user_id="user-greet",
                    message="你好呀",
                ),
                persistent=PersistentSessionContext(),
            )
        )

        self.assertFalse(result.needs_rag)
        self.assertFalse(result.needs_tool)
        responses.create.assert_not_called()

    def test_nearby_recommendation_hits_heuristic_gate(self) -> None:
        responses = SimpleNamespace(create=MagicMock(side_effect=RuntimeError("should not call llm")))
        runtime = SimpleNamespace(client=SimpleNamespace(responses=responses), default_model="test-model")
        gateway = OpenAIBackedModelGateway(runtime=runtime, fallback=HeuristicModelGateway())

        result = gateway.classify_turn(
            TurnUnderstandingRequest(
                command=ChatTurnCommand(
                    trace_id="trace-nearby",
                    session_id="session-nearby",
                    turn_id="turn-nearby",
                    user_id="user-nearby",
                    message="附近有什么适合晚餐的店推荐？",
                ),
                persistent=PersistentSessionContext(),
            )
        )

        self.assertEqual(result.intent, IntentType.RECOMMEND)
        self.assertTrue(result.needs_rag)
        responses.create.assert_not_called()

    def test_llm_classify_timeout_fallback(self) -> None:
        runtime = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=MagicMock())), default_model="test-model")
        gateway = OpenAIBackedModelGateway(runtime=runtime, fallback=HeuristicModelGateway())

        def _slow(_command):
            import time
            time.sleep(1.5)
            return gateway.fallback.classify_turn(
                TurnUnderstandingRequest(
                    command=ChatTurnCommand(
                        trace_id="trace-timeout",
                        session_id="session-timeout",
                        turn_id="turn-timeout",
                        user_id="user-timeout",
                        message="解释一下 RAG",
                    ),
                    persistent=PersistentSessionContext(),
                )
            )

        gateway._classify_with_openai = _slow  # type: ignore[method-assign]
        result = gateway.classify_turn(
            TurnUnderstandingRequest(
                command=ChatTurnCommand(
                    trace_id="trace-timeout",
                    session_id="session-timeout",
                    turn_id="turn-timeout",
                    user_id="user-timeout",
                    message="解释一下 RAG",
                ),
                persistent=PersistentSessionContext(),
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(gateway.last_degrade_to, "classify_timeout_fallback")

    def test_classify_turn_accepts_string_response_mode(self) -> None:
        payload = {
            "intent": "recommend",
            "needs_rag": True,
            "needs_tool": True,
            "needs_clarify": False,
            "needs_query_rewrite": False,
            "confidence": 0.91,
            "key_slots": {
                "domain": "local_life",
                "local_life_intent": "recommend",
                "tool_name": "search_restaurants",
                "city": "北京",
                "category": "火锅",
                "scene": "family_dinner",
            },
        }
        response = SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))
        responses = SimpleNamespace(create=MagicMock(return_value=response))
        runtime = SimpleNamespace(client=SimpleNamespace(responses=responses), default_model="test-model")
        gateway = OpenAIBackedModelGateway(runtime=runtime, fallback=HeuristicModelGateway())

        command = ChatTurnCommand(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            message="附近有什么火锅",
            response_mode="default",
        )

        result = gateway._classify_with_openai(command)
        call_kwargs = responses.create.call_args.kwargs
        system_text = call_kwargs["input"][0]["content"][0]["text"]
        prompt_text = call_kwargs["input"][1]["content"][0]["text"]
        prompt = json.loads(prompt_text)

        self.assertEqual(prompt["response_mode"], "default")
        self.assertIn("needs_rag", system_text)
        self.assertIn("needs_tool", system_text)
        self.assertEqual(result.intent, IntentType.RECOMMEND)
        self.assertTrue(result.needs_rag)
        self.assertTrue(result.needs_tool)
        self.assertEqual(result.key_slots["tool_name"], "search_restaurants")
        self.assertEqual(result.key_slots["category"], "火锅")

    def test_classify_turn_keeps_openai_result_over_heuristic_fallback(self) -> None:
        payload = {
            "intent": "explain",
            "needs_rag": False,
            "needs_tool": False,
            "needs_clarify": False,
            "needs_query_rewrite": False,
            "confidence": 0.96,
            "key_slots": {},
        }
        response = SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))
        responses = SimpleNamespace(create=MagicMock(return_value=response))
        runtime = SimpleNamespace(client=SimpleNamespace(responses=responses), default_model="test-model")
        gateway = OpenAIBackedModelGateway(runtime=runtime, fallback=HeuristicModelGateway())

        command = ChatTurnCommand(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            message="解释一下 Spring AOP 的原理",
            response_mode="default",
        )

        result = gateway.classify_turn(
            TurnUnderstandingRequest(
                command=command,
                persistent=PersistentSessionContext(),
            )
        )

        self.assertEqual(result.intent, IntentType.EXPLAIN)
        self.assertFalse(result.needs_rag)
        self.assertFalse(result.needs_tool)


class WorkflowNodeAdapterTestCase(unittest.TestCase):
    def test_query_rewrite_timeout_falls_back_to_raw_query(self) -> None:
        class _SlowRag:
            def rewrite_query(self, request):  # noqa: ANN001
                import time
                time.sleep(1.2)
                raise RuntimeError("timeout")

            def warmup_raw_query_embedding(self, raw_query: str):
                return {"cache_hit": True, "latency_ms": 3.0}

        command = ChatTurnCommand(
            trace_id="trace-rewrite-timeout",
            session_id="session-rewrite-timeout",
            turn_id="turn-rewrite-timeout",
            user_id="user-rewrite-timeout",
            message="这家店怎么样",
        )
        state = build_initial_state(command, persistent=PersistentSessionContext())
        turn = state["turn"].model_copy(
            update={
                "intent": IntentType.FOLLOW_UP,
                "intent_confidence": 0.3,
                "extra": {"needs_query_rewrite": True},
            }
        )
        state["turn"] = turn
        adapter = WorkflowNodeAdapter(SimpleNamespace(rag_orchestrator=_SlowRag()))

        next_state = adapter.rewrite_query(state)
        plan = next_state["turn"].retrieval_plan
        self.assertIsNotNone(plan)
        self.assertEqual(plan.semantic_query, "这家店怎么样")
        self.assertEqual(plan.keyword_query, "这家店怎么样")
        self.assertIn("query_rewrite_timeout_raw_query", next_state["runtime"].metrics.get("degrade_to_list", []))


if __name__ == "__main__":
    unittest.main()
