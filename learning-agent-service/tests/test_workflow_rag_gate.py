from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import _bootstrap  # noqa: F401

from learning_agent_service.application.rag_gate import RagRouteGate
from learning_agent_service.application.routing import build_initial_routing_decision
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.application.workflow.services import ToolSubgraphServices, UnderstandTurnServices
from learning_agent_service.application.workflow.subgraphs import route_after_understand, run_tool_subgraph, run_understand_turn
from learning_agent_service.domain import (
    ChatTurnCommand,
    PersistentSessionContext,
    ReferenceResolutionResult,
    RetrievalPlan,
    ToolSelection,
    TurnUnderstandingResult,
    build_initial_state,
)
from learning_agent_service.domain.enums import IntentType, OutputStyle, TurnDecision
from learning_agent_service.infrastructure.repositories.in_memory import InMemorySessionContextStore


class WorkflowRagGateTestCase(unittest.TestCase):
    def _build_state(self, message: str = "你好", **persistent_kwargs):
        return build_initial_state(
            ChatTurnCommand(
                trace_id="trace-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                message=message,
            ),
            persistent=PersistentSessionContext(**persistent_kwargs),
        )

    def test_load_context_skips_memory_retrieval_for_greeting(self) -> None:
        session_store = SimpleNamespace(load=MagicMock(return_value=PersistentSessionContext()))
        memory_orchestrator = SimpleNamespace(
            retrieve_for_state=MagicMock(),
            build_injection_plan=MagicMock(),
            attach_to_state=MagicMock(side_effect=lambda state, *_: state),
        )
        container = SimpleNamespace(
            session_context_store=session_store,
            memory_orchestrator=memory_orchestrator,
            rag_route_gate=RagRouteGate(),
        )
        adapter = WorkflowNodeAdapter(container)

        state = self._build_state("你好")
        loaded = adapter.load_context(state)

        self.assertFalse(memory_orchestrator.retrieve_for_state.called)
        self.assertEqual(loaded["runtime"].metrics["memory_retrieval_skipped"], True)
        self.assertEqual(loaded["turn"].routing_decision.required_action, "direct_answer")
        self.assertNotIn("rag_gate", loaded["turn"].extra)

    def test_load_context_skips_memory_retrieval_for_profile_query(self) -> None:
        session_store = SimpleNamespace(load=MagicMock(return_value=PersistentSessionContext()))
        memory_orchestrator = SimpleNamespace(
            retrieve_for_state=MagicMock(),
            build_injection_plan=MagicMock(),
            attach_to_state=MagicMock(side_effect=lambda state, *_: state),
        )
        container = SimpleNamespace(
            session_context_store=session_store,
            memory_orchestrator=memory_orchestrator,
            rag_route_gate=RagRouteGate(),
        )
        adapter = WorkflowNodeAdapter(container)

        state = self._build_state("你有什么功能")
        loaded = adapter.load_context(state)

        self.assertFalse(memory_orchestrator.retrieve_for_state.called)
        self.assertEqual(loaded["runtime"].metrics["memory_retrieval_skipped"], True)
        self.assertEqual(loaded["turn"].routing_decision.required_action, "direct_answer")
        self.assertNotIn("rag_gate", loaded["turn"].extra)

    def test_run_understand_turn_skips_rewrite_when_gate_denies(self) -> None:
        rewrite_query = MagicMock()
        adapter = WorkflowNodeAdapter(SimpleNamespace(rag_route_gate=RagRouteGate()))

        def parse_intent_slots(state):
            turn = state["turn"]
            state["turn"] = turn.model_copy(
                update={
                    "decision": TurnDecision.RETRIEVE_THEN_ANSWER,
                    "intent": IntentType.EXPLAIN,
                    "intent_confidence": 0.84,
                }
            )
            return state

        def rag_gate(state):
            turn = state["turn"]
            state["turn"] = turn.model_copy(
                update={
                    "extra": {
                        **dict(turn.extra),
                        "rag_gate": {
                            "allowed": False,
                            "reason": "greeting",
                            "response_kind": "greeting",
                            "final_vote": "deny",
                        },
                    }
                }
            )
            return state

        services = UnderstandTurnServices(
            parse_intent_slots=parse_intent_slots,
            resolve_reference=lambda state: state,
            ambiguity_check=lambda state: state,
            rag_gate=adapter.rag_gate,
            rewrite_query=rewrite_query,
        )

        state = self._build_state("你好")
        state["turn"] = state["turn"].model_copy(
            update={
                "retrieval_plan": RetrievalPlan(semantic_query="Spring AOP", keyword_query="Spring AOP"),
            }
        )

        updated = run_understand_turn(state, services)

        self.assertFalse(rewrite_query.called)
        self.assertEqual(updated["turn"].extra["rag_gate"]["allowed"], False)
        self.assertEqual(updated["turn"].decision, TurnDecision.RETRIEVE_THEN_ANSWER)
        self.assertTrue(updated["turn"].routing_decision.blocked)
        self.assertEqual(route_after_understand(updated), "compose_answer")

    def test_cached_understanding_bundle_skips_followup_llm_paths(self) -> None:
        model_gateway = SimpleNamespace(
            classify_turn=MagicMock(
                return_value=TurnUnderstandingResult(
                    decision=TurnDecision.RETRIEVE_THEN_ANSWER,
                    intent=IntentType.COMPARE,
                    intent_confidence=0.91,
                    requested_output_style=OutputStyle.COMPARISON,
                    reference_resolution=ReferenceResolutionResult(
                        resolved=True,
                        confidence=0.88,
                        resolved_entity="shop-42",
                        candidate_entities=["shop-42"],
                    ),
                    retrieval_plan=RetrievalPlan(
                        semantic_query="上海两家烤肉店对比",
                        keyword_query="烤肉 对比",
                    ),
                    slots={"shop_name": "烤肉店"},
                    extra={
                        "route_candidate": "knowledge",
                        "rag_gate": {
                            "allowed": True,
                            "reason": "cached_understanding",
                            "confidence": 0.91,
                            "response_kind": "fallback",
                            "precheck_skip_memory": False,
                            "final_vote": "allow",
                            "metadata": {"source": "understanding_bundle"},
                        },
                    },
                )
            )
        )
        resolve_reference = MagicMock(return_value=ReferenceResolutionResult(resolved=True, confidence=0.88, resolved_entity="shop-42"))
        rag_gate_decide = MagicMock(return_value=None)
        rewrite_query = MagicMock(return_value=RetrievalPlan(semantic_query="fallback", keyword_query="fallback"))
        container = SimpleNamespace(
            model_gateway=model_gateway,
            rag_orchestrator=SimpleNamespace(
                resolve_reference=resolve_reference,
                rewrite_query=rewrite_query,
            ),
            rag_route_gate=SimpleNamespace(decide=rag_gate_decide),
        )
        adapter = WorkflowNodeAdapter(container)

        state = self._build_state("这家和那家哪个好", current_topic="shop-42")
        state = adapter.parse_intent_slots(state)
        state = adapter.resolve_reference(state)
        state = adapter.rag_gate(state)
        state = adapter.rewrite_query(state)

        self.assertFalse(resolve_reference.called)
        self.assertFalse(rag_gate_decide.called)
        self.assertFalse(rewrite_query.called)
        self.assertIsNotNone(state["turn"].reference_resolution)
        self.assertIsNotNone(state["turn"].retrieval_plan)
        self.assertEqual(state["turn"].extra["rag_gate"]["allowed"], True)

    def test_rag_gate_keeps_low_information_turn_on_text_reply_path(self) -> None:
        session_store = InMemorySessionContextStore()
        container = SimpleNamespace(rag_route_gate=RagRouteGate(), session_context_store=session_store)
        adapter = WorkflowNodeAdapter(container)

        state = self._build_state("推荐")
        updated = adapter.rag_gate(state)

        self.assertEqual(updated["turn"].decision, TurnDecision.DIRECT_ANSWER)
        self.assertIsNone(updated["turn"].clarification_card)
        self.assertEqual(updated["runtime"].metrics.get("clarification_cards_total", 0), 0)
        self.assertEqual(updated["turn"].extra["rag_gate"]["clarification_response_kind"], "low_info")
        self.assertEqual(updated["turn"].extra["clarification_signal"]["kind"], "low_info")
        persisted = session_store.load("session-1", "user-1")
        self.assertIsNone(persisted.pending_clarification)

    def test_compose_answer_uses_profile_direct_response_when_routed(self) -> None:
        captured = {}

        class _Composer:
            def compose(self, request):
                captured["request"] = request
                return SimpleNamespace(answer_text="我可以帮你做很多事情。", confidence=0.91)

        container = SimpleNamespace(answer_composer=_Composer())
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("你有什么功能")
        routing = build_initial_routing_decision("你有什么功能", PersistentSessionContext()).model_copy(
            update={
                "required_action": "direct_answer",
                "route_candidate": "profile",
                "route_reason": "profile",
            }
        )
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": routing,
                "extra": {
                    "direct_response_kind": "profile",
                    "route_candidate": "profile",
                    "rag_gate": {"response_kind": "profile", "allowed": True},
                }
            }
        )

        updated = adapter.compose_answer(state)

        request = captured["request"]
        self.assertTrue(request.allow_direct_response)
        self.assertEqual(request.direct_response_kind, "profile")
        self.assertEqual(request.stream_event_meta["route_candidate"], "profile")
        self.assertEqual(request.stream_event_meta["direct_response_kind"], "profile")
        self.assertEqual(updated["turn"].final_answer, "我可以帮你做很多事情。")

    def test_run_tool_subgraph_records_no_tool_mapping_state(self) -> None:
        services = ToolSubgraphServices(
            tool_planner=lambda state: state,
            tool_executor=lambda state: state,
            tool_result_normalizer=lambda state: state,
        )
        state = self._build_state("推荐一家适合带爸妈吃饭的餐厅")
        state["turn"] = state["turn"].model_copy(
            update={
                "decision": TurnDecision.TOOL_THEN_ANSWER,
                "intent": IntentType.RECOMMEND,
                "tool_plan": ToolSelection(
                    tool_name=None,
                    should_execute=False,
                    reason="no_tool_mapping",
                    extra={"planning_state": "no_tool_mapping"},
                ),
            }
        )

        updated = run_tool_subgraph(state, services)

        timeline = updated["turn"].stage_timeline
        self.assertEqual(timeline[-1]["stage"], "tool")
        self.assertEqual(timeline[-1]["status"], "completed")
        self.assertEqual(timeline[-1]["detail"]["tool_plan_state"], "no_tool_mapping")
        self.assertEqual(timeline[-1]["detail"]["should_execute"], False)
        self.assertEqual(timeline[-1]["detail"]["tool_name"], None)


if __name__ == "__main__":
    unittest.main()
