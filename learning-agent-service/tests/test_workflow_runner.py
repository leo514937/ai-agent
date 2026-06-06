from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.router import build_initial_routing_decision
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.application.workflow.runner import SequentialWorkflowRunner
from learning_agent_service.application.workflow.services import (
    UnderstandTurnServices,
    WorkflowServices,
)
from learning_agent_service.domain import ChatTurnCommand, ClarificationCard, ClarificationOption, PersistentSessionContext, build_initial_state


class _UnderstandTurnService:
    def parse_intent_slots(self, state):
        pending = ClarificationCard(
            card_id="session:test:clarification",
            question="你现在在哪个城市或位置附近？",
            options=[
                ClarificationOption(
                    id="opt-1",
                    label="北京",
                    value="北京",
                    description="北京",
                )
            ],
            ambiguity_type="location",
            source_turn_id=state["runtime"].turn_id,
            expires_at=None,
        )
        routing = build_initial_routing_decision(
            state["turn"].raw_query,
            state["persistent"],
            client_context=state["runtime"].client_context,
        ).model_copy(
            update={
                "required_action": "clarify",
                "blocked": False,
                "clarification_question": pending.question,
                "route_candidate": "local_life",
                "route_reason": "test_clarify",
            }
        )
        turn_extra = dict(state["turn"].extra)
        turn_extra["clarification_result"] = {
            "original_query": "附近有什么推荐菜",
            "original_intent": "local_life_recommend",
            "original_route": "rag_retrieval",
            "question": pending.question,
            "ambiguity_type": "location",
        }
        turn_extra["pending_clarification"] = pending.model_dump(mode="json")
        state["persistent"] = state["persistent"].model_copy(
            update={
                "clarification_result": turn_extra["clarification_result"],
                "pending_clarification": pending,
            }
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": turn_extra})
        return state

    def resolve_reference(self, state):
        return state

    def ambiguity_check(self, state):
        return state

    def rag_gate(self, state):
        return state

    def compose_answer(self, state):
        raise AssertionError("compose_answer should not be called when pending clarification exists")


class _ClarifyPersistServices:
    def __init__(self) -> None:
        self.persist_calls = 0
        self.understand_turn = _UnderstandTurnService()

    def load_context(self, state):
        return state

    def compose_answer(self, state):
        return state

    def persist_session(self, state):
        self.persist_calls += 1
        return state

    def emit_final(self, state):
        return state


class WorkflowRunnerClarifyPersistTestCase(unittest.TestCase):
    def test_streaming_fast_persist_flag_survives_all_state_layers(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-fast-persist",
            session_id="session-fast-persist",
            turn_id="turn-fast-persist",
            user_id="user-fast-persist",
            message="附近有什么推荐菜",
            page="assistant",
        )
        state = build_initial_state(command, persistent=PersistentSessionContext())

        updated = SequentialWorkflowRunner._mark_streaming_fast_persist(state)

        self.assertTrue(updated["runtime"].extra.get("streaming_fast_persist"))
        self.assertTrue(updated["turn"].extra.get("streaming_fast_persist"))
        self.assertTrue(updated["persistent"].extra.get("streaming_fast_persist"))

    def test_emit_final_after_clarify_still_persists_pending_context(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-runner-clarify",
            session_id="session-runner-clarify",
            turn_id="turn-runner-clarify",
            user_id="user-runner-clarify",
            message="附近有什么推荐菜",
            page="assistant",
            client_context={},
        )
        state = build_initial_state(command, persistent=PersistentSessionContext())
        services = _ClarifyPersistServices()
        runner = SequentialWorkflowRunner(services)

        result = runner.run_state(state)

        self.assertEqual(services.persist_calls, 1)
        self.assertIsNotNone(result["persistent"].pending_clarification)
        self.assertEqual(result["persistent"].pending_clarification.question, "你现在在哪个城市或位置附近？")


class WorkflowRunnerPendingClarificationTestCase(unittest.TestCase):
    def _build_services(self, adapter: WorkflowNodeAdapter, understand_services: UnderstandTurnServices) -> WorkflowServices:
        return WorkflowServices(
            load_context=adapter.load_context,
            consume_pending_clarification=adapter.consume_pending_clarification,
            conversation_recap_direct_response=adapter.conversation_recap_direct_response,
            understand_turn=understand_services,
            compose_answer=adapter.compose_answer,
            persist_session=adapter.persist_session,
            emit_final=adapter.emit_final,
        )

    def test_pending_clarification_is_consumed_before_understand_turn(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-runner-pending",
            session_id="session-runner-pending",
            turn_id="turn-runner-pending",
            user_id="user-runner-pending",
            message="北京",
            page="assistant",
        )
        pending = ClarificationCard(
            card_id="session-runner-pending:clarification",
            question="你现在在哪个城市或位置附近？",
            options=[
                ClarificationOption(
                    id="opt-1",
                    label="北京",
                    value="北京",
                    description="北京",
                )
            ],
            ambiguity_type="location",
            source_turn_id="turn-origin",
            expires_at=None,
        )
        persistent = PersistentSessionContext(
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
                "question": pending.question,
                "ambiguity_type": "location",
            },
            pending_clarification=pending,
        )
        state = build_initial_state(command, persistent=persistent)
        adapter = WorkflowNodeAdapter(SimpleNamespace(answer_composer=SimpleNamespace(compose=lambda request: SimpleNamespace(answer_text=f"answer:{request.raw_query}", confidence=0.9))))
        seen: dict[str, object] = {}

        def parse_intent_slots(current_state):
            seen["raw_query"] = current_state["turn"].raw_query
            seen["pending"] = current_state["persistent"].pending_clarification
            seen["city"] = current_state["persistent"].current_city
            self.assertEqual(current_state["turn"].raw_query, "附近有什么推荐菜")
            self.assertIsNone(current_state["persistent"].pending_clarification)
            self.assertEqual(current_state["persistent"].current_city, "北京")
            return current_state

        understand_services = UnderstandTurnServices(
            parse_intent_slots=parse_intent_slots,
            resolve_reference=lambda current_state: current_state,
            ambiguity_check=lambda current_state: current_state,
            rag_gate=lambda current_state: current_state,
            rewrite_query=lambda current_state: current_state,
        )
        runner = SequentialWorkflowRunner(self._build_services(adapter, understand_services))

        result = runner.run_state(state)

        self.assertEqual(seen["raw_query"], "附近有什么推荐菜")
        self.assertIsNone(seen["pending"])
        self.assertEqual(seen["city"], "北京")
        self.assertIsNone(result["persistent"].pending_clarification)
        self.assertTrue(result["persistent"].clarification_result.get("consumed"))
        self.assertEqual(result["persistent"].clarification_result.get("follow_up_query"), "北京")
        self.assertEqual(result["persistent"].clarification_result.get("resolved_city"), "北京")
        self.assertEqual(result["persistent"].current_city, "北京")
        self.assertEqual(result["turn"].raw_query, "附近有什么推荐菜")
        self.assertEqual(result["turn"].extra.get("clarification_response"), "北京")

    def test_conversation_recap_skips_understand_turn(self) -> None:
        command = ChatTurnCommand(
            trace_id="trace-runner-recap",
            session_id="session-runner-recap",
            turn_id="turn-runner-recap",
            user_id="user-runner-recap",
            message="你记得我们说过什么吗",
            page="assistant",
        )
        persistent = PersistentSessionContext(
            current_topic="山城一锅",
            history_summary="我们聊过山城一锅的券和环境评价。",
            recent_entities=["山城一锅"],
            current_shop="山城一锅",
            selected_shop_name="山城一锅",
        )
        state = build_initial_state(command, persistent=persistent)
        adapter = WorkflowNodeAdapter(SimpleNamespace(answer_composer=SimpleNamespace(compose=lambda request: SimpleNamespace(answer_text=f"recap:{request.raw_query}", confidence=0.95))))
        understand_called = {"value": False}

        def parse_intent_slots(current_state):
            understand_called["value"] = True
            raise AssertionError("conversation_recap should skip understand_turn")

        understand_services = UnderstandTurnServices(
            parse_intent_slots=parse_intent_slots,
            resolve_reference=lambda current_state: current_state,
            ambiguity_check=lambda current_state: current_state,
            rag_gate=lambda current_state: current_state,
            rewrite_query=lambda current_state: current_state,
        )
        runner = SequentialWorkflowRunner(self._build_services(adapter, understand_services))

        result = runner.run_state(state)

        self.assertFalse(understand_called["value"])
        self.assertEqual(result["turn"].extra.get("conversation_recap"), True)
        self.assertEqual(result["turn"].final_answer, "recap:你记得我们说过什么吗")


if __name__ == "__main__":
    unittest.main()
