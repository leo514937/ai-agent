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
    ClarificationCard,
    ClarificationOption,
    PersistentSessionContext,
    ReferenceResolutionResult,
    RetrievalPlan,
    ToolSelection,
    TurnUnderstandingResult,
    build_initial_state,
)
from learning_agent_service.domain.enums import IntentType, OutputStyle, TurnDecision
from learning_agent_service.infrastructure.repositories.in_memory import InMemorySessionContextStore
from learning_agent_service.rag.rewrite import QueryRewriteContext, QueryRewriteService


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

    def test_load_context_resumes_pending_location_clarification_follow_up(self) -> None:
        pending = ClarificationCard(
            card_id="clarify-1",
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
            source_turn_id="turn-old",
            expires_at=None,
        )
        container = SimpleNamespace(rag_route_gate=RagRouteGate())
        adapter = WorkflowNodeAdapter(container)

        state = self._build_state("北京", pending_clarification=pending)
        loaded = adapter.load_context(state)

        self.assertEqual(loaded["turn"].routing_decision.required_action, "rag_retrieval")
        self.assertTrue(loaded["turn"].routing_decision.should_retrieve)
        self.assertEqual(loaded["turn"].extra["rag_gate"]["precheck_vote"], "allow")
        self.assertEqual(loaded["turn"].extra["rag_gate"]["precheck_reason"], "pending_clarification")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_query"], "你现在在哪个城市或位置附近？")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_intent"], "local_life_recommend")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_route"], "rag_retrieval")

    def test_load_context_restores_pending_location_clarification_from_result_only(self) -> None:
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

        state = self._build_state(
            "北京",
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
                "question": "你现在在哪个城市或位置附近？",
                "ambiguity_type": "location",
            },
        )

        loaded = adapter.load_context(state)

        self.assertIsNotNone(loaded["persistent"].pending_clarification)
        self.assertEqual(loaded["persistent"].pending_clarification.question, "你现在在哪个城市或位置附近？")
        self.assertEqual(loaded["turn"].routing_decision.required_action, "rag_retrieval")
        self.assertEqual(loaded["turn"].extra["pending_clarification"]["question"], "你现在在哪个城市或位置附近？")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_query"], "附近有什么推荐菜")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_intent"], "local_life_recommend")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_route"], "rag_retrieval")

    def test_beijing_pending_clarification_consumes_before_low_information_gate(self) -> None:
        pending = ClarificationCard(
            card_id="clarify-2",
            question="你现在在哪个城市或位置附近？",
            options=[
                ClarificationOption(
                    id="opt-2",
                    label="北京",
                    value="北京",
                    description="北京",
                )
            ],
            ambiguity_type="location",
            source_turn_id="turn-old",
            expires_at=None,
        )
        adapter = WorkflowNodeAdapter(SimpleNamespace(rag_route_gate=RagRouteGate()))

        state = self._build_state("北京", pending_clarification=pending)
        loaded = adapter.load_context(state)

        self.assertEqual(loaded["turn"].routing_decision.required_action, "rag_retrieval")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_query"], "你现在在哪个城市或位置附近？")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_intent"], "local_life_recommend")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_route"], "rag_retrieval")
        self.assertTrue(loaded["turn"].extra["rag_gate"]["precheck_vote"], "allow")

    def test_parse_intent_slots_preserves_restored_pending_location_follow_up(self) -> None:
        model_gateway = SimpleNamespace(classify_turn=MagicMock())
        adapter = WorkflowNodeAdapter(
            SimpleNamespace(
                model_gateway=model_gateway,
                rag_route_gate=RagRouteGate(),
            )
        )

        state = self._build_state(
            "北京",
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
                "question": "你现在在哪个城市或位置附近？",
                "ambiguity_type": "location",
            },
        )

        loaded = adapter.load_context(state)
        parsed = adapter.parse_intent_slots(loaded)

        self.assertFalse(model_gateway.classify_turn.called)
        self.assertEqual(parsed["turn"].routing_decision.required_action, "rag_retrieval")
        self.assertTrue(parsed["turn"].extra["cached_rag_gate_vote"]["allowed"])
        self.assertEqual(parsed["turn"].extra["pending_clarification_restore"]["original_query"], "附近有什么推荐菜")
        self.assertIsNotNone(parsed["persistent"].pending_clarification)

    def test_rewrite_query_preserves_follow_up_query_and_restores_original_topic(self) -> None:
        captured: dict[str, object] = {}

        class _RagOrchestrator:
            def rewrite_query(self, request):  # noqa: ANN001
                captured["request"] = request
                return RetrievalPlan(
                    semantic_query=request.current_topic or request.raw_query,
                    keyword_query=request.current_topic or request.raw_query,
                )

        model_gateway = SimpleNamespace(classify_turn=MagicMock())
        adapter = WorkflowNodeAdapter(
            SimpleNamespace(
                model_gateway=model_gateway,
                rag_orchestrator=_RagOrchestrator(),
                rag_route_gate=RagRouteGate(),
            )
        )

        state = self._build_state(
            "北京",
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
                "question": "你现在在哪个城市或位置附近？",
                "ambiguity_type": "location",
            },
        )

        loaded = adapter.load_context(state)
        parsed = adapter.parse_intent_slots(loaded)
        rewritten = adapter.rewrite_query(parsed)

        self.assertFalse(model_gateway.classify_turn.called)
        self.assertEqual(parsed["persistent"].current_topic, "附近有什么推荐菜")
        self.assertEqual(parsed["persistent"].last_retrieval_topic, "附近有什么推荐菜")
        self.assertEqual(captured["request"].raw_query, "北京")
        self.assertEqual(captured["request"].current_topic, "附近有什么推荐菜")
        self.assertEqual(rewritten["turn"].retrieval_plan.semantic_query, "附近有什么推荐菜")

    def test_rewrite_query_restores_topic_hint_from_pending_clarification_restore_when_current_topic_is_blank(self) -> None:
        captured: dict[str, object] = {}

        class _RagOrchestrator:
            def rewrite_query(self, request):  # noqa: ANN001
                captured["request"] = request
                combined = f"{request.current_topic or ''} {request.raw_query or ''}".strip()
                return RetrievalPlan(
                    semantic_query=combined,
                    keyword_query=combined,
                )

        model_gateway = SimpleNamespace(classify_turn=MagicMock())
        adapter = WorkflowNodeAdapter(
            SimpleNamespace(
                model_gateway=model_gateway,
                rag_orchestrator=_RagOrchestrator(),
                rag_route_gate=RagRouteGate(),
            )
        )

        state = self._build_state(
            "北京",
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
                "question": "你现在在哪个城市或位置附近？",
                "ambiguity_type": "location",
            },
        )

        loaded = adapter.load_context(state)
        loaded["persistent"] = loaded["persistent"].model_copy(update={"current_topic": "", "last_retrieval_topic": ""})
        rewritten = adapter.rewrite_query(loaded)

        self.assertFalse(model_gateway.classify_turn.called)
        self.assertEqual(captured["request"].raw_query, "北京")
        self.assertEqual(captured["request"].current_topic, "附近有什么推荐菜")
        self.assertEqual(captured["request"].topic_hint, "附近有什么推荐菜")
        self.assertEqual(rewritten["turn"].retrieval_plan.semantic_query, "附近有什么推荐菜 北京")

    def test_persist_session_preserves_clarification_state_from_turn_payload(self) -> None:
        captured: dict[str, object] = {}

        def persist_session(command):  # noqa: ANN001
            captured["command"] = command
            return SimpleNamespace(updated_context=command.persistent, memory_updates={})

        container = SimpleNamespace(memory_service=SimpleNamespace(persist_session=persist_session))
        adapter = WorkflowNodeAdapter(container)

        pending = ClarificationCard(
            card_id="clarify-3",
            question="你现在在哪个城市或位置附近？",
            options=[
                ClarificationOption(
                    id="opt-3",
                    label="北京",
                    value="北京",
                    description="北京",
                )
            ],
            ambiguity_type="location",
            source_turn_id="turn-old",
            expires_at=None,
        )
        state = self._build_state("北京")
        state["persistent"] = PersistentSessionContext()
        state["turn"] = state["turn"].model_copy(
            update={
                "clarification_card": pending,
                "extra": {
                    "clarification_result": {
                        "original_query": "附近有什么推荐菜",
                        "original_intent": "local_life_recommend",
                        "original_route": "rag_retrieval",
                        "question": "你现在在哪个城市或位置附近？",
                        "ambiguity_type": "location",
                    },
                    "pending_clarification": pending.model_dump(mode="json"),
                    "pending_clarification_restore": {
                        "original_query": "附近有什么推荐菜",
                        "original_intent": "local_life_recommend",
                        "original_route": "rag_retrieval",
                    },
                },
            }
        )

        updated = adapter.persist_session(state)
        command = captured["command"]

        self.assertEqual(command.persistent.current_topic, "附近有什么推荐菜")
        self.assertEqual(command.persistent.last_retrieval_topic, "附近有什么推荐菜")
        self.assertIsNotNone(command.persistent.pending_clarification)
        self.assertEqual(command.persistent.clarification_result["original_query"], "附近有什么推荐菜")
        self.assertEqual(updated["persistent"].current_topic, "附近有什么推荐菜")

    def test_persist_session_reconstructs_clarification_state_from_routing_restore(self) -> None:
        captured: dict[str, object] = {}

        def persist_session(command):  # noqa: ANN001
            captured["command"] = command
            return SimpleNamespace(updated_context=command.persistent, memory_updates={})

        container = SimpleNamespace(memory_service=SimpleNamespace(persist_session=persist_session))
        adapter = WorkflowNodeAdapter(container)

        routing = build_initial_routing_decision("北京", PersistentSessionContext()).model_copy(
            update={
                "required_action": "clarify",
                "clarification_question": "你现在在哪个城市或位置附近？",
                "route_reason": "pending_clarification_location",
                "extra": {
                    "pending_clarification_restore": {
                        "original_query": "附近有什么推荐菜",
                        "original_intent": "local_life_recommend",
                        "original_route": "rag_retrieval",
                        "question": "你现在在哪个城市或位置附近？",
                        "ambiguity_type": "location",
                    }
                },
            }
        )
        state = self._build_state("北京")
        state["persistent"] = PersistentSessionContext()
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})

        updated = adapter.persist_session(state)
        command = captured["command"]

        self.assertEqual(command.persistent.current_topic, "附近有什么推荐菜")
        self.assertEqual(command.persistent.last_retrieval_topic, "附近有什么推荐菜")
        self.assertIsNotNone(command.persistent.pending_clarification)
        self.assertEqual(command.persistent.pending_clarification.question, "你现在在哪个城市或位置附近？")
        self.assertEqual(updated["persistent"].current_topic, "附近有什么推荐菜")

    def test_query_rewriter_combines_follow_up_location_with_restored_topic(self) -> None:
        service = QueryRewriteService()

        plan = service.build_plan(
            QueryRewriteContext(
                raw_query="北京",
                session_topic="附近有什么推荐菜",
            )
        )

        self.assertIn("附近有什么推荐菜", plan.semantic_query)
        self.assertIn("北京", plan.semantic_query)
        self.assertIn("北京", plan.keyword_query)

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

    def test_conversation_recap_has_priority_over_low_information(self) -> None:
        routing = build_initial_routing_decision(
            "你记得我们说过什么吗",
            PersistentSessionContext(
                history_summary="刚才聊的是山城一锅的券和环境评价。",
                current_topic="山城一锅",
                recent_entities=["山城一锅"],
            ),
        )

        self.assertEqual(routing.required_action, "direct_answer")
        self.assertEqual(routing.route_candidate, "conversation_recap")
        self.assertEqual(routing.route_reason, "conversation_recap_request")
        self.assertFalse(routing.blocked)
        self.assertIsNone(routing.clarification_question)

    def test_arctic_unserviceable_location_returns_location_unavailable_direct_response(self) -> None:
        routing = build_initial_routing_decision(
            "附近有什么推荐菜，北极",
            PersistentSessionContext(current_city="北京"),
        )

        self.assertEqual(routing.required_action, "direct_answer")
        self.assertEqual(routing.route_candidate, "location_unavailable")
        self.assertEqual(routing.route_reason, "unserviceable_location")
        self.assertFalse(routing.blocked)
        self.assertIn("unserviceable_location", routing.safeguards_triggered)

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
