from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router import (
    apply_fast_decision_to_routing,
    build_clarification_question,
    build_evidence_quality,
    build_initial_routing_decision,
    can_enter_retrieval,
    can_enter_tool,
)
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.application.workflow.subgraphs import route_after_rag, route_after_understand
from learning_agent_service.application.workflow.runner import SequentialWorkflowRunner
from learning_agent_service.application.workflow.services import (
    RagSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
    WorkflowServices,
)
from learning_agent_service.domain import (
    ChatTurnCommand,
    AnswerComposeRequest,
    EvidenceItem,
    EvidencePack,
    EvidenceQualityDecision,
    FastDecision,
    IntentType,
    PersistentSessionContext,
    RagResult,
    RagStatus,
    RetrievalPlan,
    build_initial_state,
)
from learning_agent_service.domain.enums import TurnDecision
from learning_agent_service.rag.heuristics import HeuristicModelGateway
from learning_agent_service.tools.service import AnswerComposer


class _FakeMemoryService:
    def __init__(self) -> None:
        self.calls = 0

    def persist_session(self, command):
        self.calls += 1
        return type(
            "PersistResult",
            (),
            {
                "updated_context": command.persistent,
                "memory_updates": type("MemoryUpdates", (), {"model_dump": lambda self, **kwargs: {}})(),
            },
        )()


class _FakeContainer:
    def __init__(self) -> None:
        self.answer_composer = AnswerComposer()
        self.memory_service = _FakeMemoryService()
        self.rag_route_gate = None
        self.model_gateway = None
        self.rag_orchestrator = None


class RoutingDecisionMatrixTestCase(unittest.TestCase):
    def _make_context(self, **kwargs) -> PersistentSessionContext:
        return PersistentSessionContext(**kwargs)

    def _build_state(self, message: str, **persistent_kwargs):
        command = ChatTurnCommand(
            trace_id="trace-routing",
            session_id="session-routing",
            turn_id="turn-routing",
            user_id="user-routing",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=self._make_context(**persistent_kwargs))

    def test_invalid_inputs_do_not_enter_understanding_or_retrieval(self) -> None:
        cases = [
            ("", "empty_input", "reject"),
            ("，", "pure_punctuation", "reject"),
            ("???", "pure_punctuation", "reject"),
            ("cccccccccccc", "repeated_noise", "reject"),
        ]
        for raw_query, expected_kind, expected_action in cases:
            with self.subTest(raw_query=raw_query):
                routing = build_initial_routing_decision(raw_query, self._make_context())
                self.assertEqual(routing.input_quality.kind, expected_kind)
                self.assertEqual(routing.required_action, expected_action)
                self.assertTrue(routing.blocked)
                self.assertFalse(routing.should_retrieve)
                self.assertFalse(routing.should_call_tool)
                self.assertFalse(routing.should_persist_memory)
                self.assertFalse(routing.should_vectorize_memory)

    def test_low_information_without_context_clarifies(self) -> None:
        routing = build_initial_routing_decision("嗯", self._make_context())
        self.assertEqual(routing.input_quality.kind, "low_information")
        self.assertEqual(routing.required_action, "clarify")
        self.assertTrue(routing.blocked)
        self.assertFalse(routing.should_retrieve)

    def test_then_with_context_routes_to_follow_up_reference(self) -> None:
        routing = build_initial_routing_decision(
            "然后",
            self._make_context(current_topic="湖畔私房菜", last_candidates=[{"shop_id": 1, "name": "湖畔私房菜"}]),
        )
        self.assertFalse(routing.blocked)
        self.assertEqual(routing.required_action, "rag_retrieval")
        self.assertEqual(routing.intent.name, "follow_up_reference")
        self.assertTrue(routing.should_retrieve)
        self.assertTrue(routing.should_rewrite_query)

    def test_ambiguous_reference_without_context_clarifies(self) -> None:
        routing = build_initial_routing_decision("这个呢", self._make_context())
        self.assertEqual(routing.required_action, "clarify")
        self.assertTrue(routing.blocked)
        self.assertFalse(routing.should_retrieve)

    def test_ambiguous_reference_with_last_candidates_resolves(self) -> None:
        routing = build_initial_routing_decision(
            "第二个有没有停车",
            self._make_context(last_candidates=[{"shop_id": 11, "name": "第一家"}, {"shop_id": 22, "name": "第二家"}]),
        )
        self.assertFalse(routing.blocked)
        self.assertEqual(routing.intent.name, "follow_up_reference")
        self.assertTrue(routing.should_retrieve)
        self.assertTrue(routing.resolved_references or routing.route_candidate == "follow_up_reference")

    def test_incomplete_recommendation_without_context_clarifies(self) -> None:
        routing = build_initial_routing_decision("附近有什么推荐", self._make_context())
        self.assertEqual(routing.required_action, "clarify")
        self.assertTrue(routing.blocked)
        self.assertFalse(routing.should_retrieve)
        self.assertIn("city", routing.missing_slots)

    def test_nearby_recommendation_with_city_in_query_does_not_clarify(self) -> None:
        routing = build_initial_routing_decision("上海附近有什么推荐菜", self._make_context())
        self.assertEqual(routing.domain, "local_life")
        self.assertEqual(routing.intent.name, "local_life_recommend")
        self.assertIn(routing.required_action, {"rag_retrieval", "rag_plus_tool"})
        self.assertFalse(routing.blocked)
        self.assertTrue(routing.should_retrieve)
        self.assertIn(routing.route_candidate, {"local_life.nearby_recommend", "nearby_recommend", "semantic_fallback"})
        self.assertFalse("location" in routing.missing_slots)
        self.assertIsNone(routing.clarification_question)

    def test_incomplete_recommendation_with_context_goes_forward(self) -> None:
        routing = build_initial_routing_decision(
            "附近有什么推荐",
            self._make_context(current_city="北京", current_location={"lat": 39.9, "lng": 116.4}),
        )
        self.assertFalse(routing.blocked)
        self.assertEqual(routing.intent.name, "local_life_recommend")
        self.assertTrue(routing.should_retrieve)

    def test_local_life_recommendation_keeps_retrieval_path_open(self) -> None:
        routing = build_initial_routing_decision(
            "朝阳公园附近适合带父母吃饭的安静餐厅",
            self._make_context(current_city="北京", current_location={"lat": 39.9, "lng": 116.4}),
        )
        self.assertFalse(routing.blocked)
        self.assertTrue(routing.should_retrieve)
        self.assertNotEqual(routing.required_action, "clarify")

    def test_merchant_detail_query_keeps_understanding_path(self) -> None:
        routing = build_initial_routing_decision("湖畔私房菜适合带父母吗", self._make_context(current_topic="湖畔私房菜"))
        self.assertFalse(routing.blocked)
        self.assertTrue(routing.should_retrieve)
        self.assertNotEqual(routing.required_action, "clarify")

    def test_package_question_can_switch_to_tool_call_after_classification(self) -> None:
        routing = build_initial_routing_decision("这个套餐现在还能用吗", self._make_context(current_topic="湖畔私房菜"))
        routed = apply_fast_decision_to_routing(
            routing,
            FastDecision(
                intent=IntentType.RECOMMEND,
                needs_rag=False,
                needs_tool=True,
                needs_clarify=False,
                needs_query_rewrite=False,
                confidence=0.83,
                key_slots={"tool_name": "check_coupon"},
                extra={"route_candidate": "tool_then_rag"},
            ),
        )
        self.assertEqual(routed.required_action, "tool_call")
        self.assertTrue(routed.should_call_tool)
        self.assertFalse(routed.should_retrieve)

    def test_heuristic_package_status_query_routes_to_tool_call(self) -> None:
        container = _FakeContainer()
        container.model_gateway = HeuristicModelGateway()
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("这个套餐现在还能用吗", current_topic="湖畔私房菜")

        state = adapter.parse_intent_slots(state)

        routing = state["turn"].routing_decision
        self.assertIsNotNone(routing)
        self.assertEqual(routing.required_action, "tool_call")
        self.assertTrue(routing.should_call_tool)
        self.assertFalse(routing.should_retrieve)
        self.assertIsNone(state["turn"].retrieval_plan)
        self.assertEqual(route_after_understand(state), "tool_subgraph")

    def test_heuristic_package_status_query_without_context_clarifies(self) -> None:
        routing = build_initial_routing_decision("这个套餐现在还能用吗", self._make_context())
        self.assertEqual(routing.required_action, "clarify")
        self.assertTrue(routing.blocked)
        self.assertFalse(routing.should_call_tool)
        self.assertIn("voucher_id", routing.missing_slots or ["voucher_id"])

    def test_heuristic_business_status_query_routes_to_tool_call(self) -> None:
        container = _FakeContainer()
        container.model_gateway = HeuristicModelGateway()
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("湖畔私房菜现在营业吗", current_topic="湖畔私房菜")

        state = adapter.parse_intent_slots(state)

        routing = state["turn"].routing_decision
        self.assertIsNotNone(routing)
        self.assertEqual(routing.required_action, "tool_call")
        self.assertTrue(routing.should_call_tool)
        self.assertFalse(routing.should_retrieve)
        self.assertEqual(route_after_understand(state), "tool_subgraph")

    def test_heuristic_detail_query_routes_to_rag_and_builds_plan(self) -> None:
        container = _FakeContainer()
        container.model_gateway = HeuristicModelGateway()
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("湖畔私房菜适合带父母吗", current_topic="湖畔私房菜")

        state = adapter.parse_intent_slots(state)

        routing = state["turn"].routing_decision
        self.assertIsNotNone(routing)
        self.assertEqual(routing.required_action, "rag_retrieval")
        self.assertTrue(routing.should_retrieve)
        self.assertIsNotNone(state["turn"].retrieval_plan)
        self.assertEqual(route_after_understand(state), "rag_subgraph")

    def test_shop_detail_is_not_exposed_as_user_clarification_slot(self) -> None:
        self.assertEqual(
            build_clarification_question(
                clarification_slot="shop_detail",
                query_text="山城一锅这家店有券吗，环境评价怎么样",
            ),
            "你是想看哪家店的详情，还是想重新选一家店？",
        )

    def test_coupon_and_environment_query_routes_to_rag_plus_tool(self) -> None:
        container = _FakeContainer()
        container.model_gateway = HeuristicModelGateway()
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("卷卷烤肉有券吗，环境怎么样", current_topic="卷卷烤肉")

        state = adapter.parse_intent_slots(state)

        routing = state["turn"].routing_decision
        self.assertIsNotNone(routing)
        self.assertEqual(routing.required_action, "rag_plus_tool")
        self.assertTrue(routing.should_retrieve)
        self.assertTrue(routing.should_call_tool)
        self.assertIn("package_description", routing.preferred_chunk_roles)
        self.assertTrue(
            any(role in routing.preferred_chunk_roles for role in ("merchant_scene_fit", "merchant_review_summary"))
        )
        self.assertEqual(route_after_understand(state), "rag_subgraph")

        state = state.copy()
        state["turn"] = state["turn"].model_copy(
            update={
                "retrieval_plan": RetrievalPlan(
                    semantic_query="卷卷烤肉有券吗 环境怎么样",
                    keyword_query="卷卷烤肉 券 环境 评价",
                )
            }
        )
        self.assertEqual(route_after_rag(state), "tool_subgraph")

    def test_retrieval_plan_can_be_synthesized_when_missing(self) -> None:
        state = self._build_state("湖畔私房菜适合带父母吗", current_topic="湖畔私房菜")
        routing = build_initial_routing_decision("湖畔私房菜适合带父母吗", self._make_context(current_topic="湖畔私房菜"))
        routing = routing.model_copy(update={"required_action": "rag_retrieval", "should_retrieve": True})
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "retrieval_plan": None})

        eligibility = can_enter_retrieval(state)

        self.assertTrue(eligibility.allowed)
        self.assertIsNotNone(state["turn"].retrieval_plan)
        self.assertTrue(state["turn"].retrieval_plan.semantic_query)
        self.assertIn("merchant_scene_fit", state["turn"].retrieval_plan.preferred_chunk_types)

    def test_tool_plan_can_be_synthesized_when_missing(self) -> None:
        state = self._build_state("湖畔私房菜现在营业吗", current_topic="湖畔私房菜")
        routing = build_initial_routing_decision("湖畔私房菜现在营业吗", self._make_context(current_topic="湖畔私房菜"))
        routing = routing.model_copy(update={"required_action": "tool_call", "should_call_tool": True})
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "tool_plan": None})

        eligibility = can_enter_tool(state)

        self.assertTrue(eligibility.allowed)
        self.assertIsNotNone(state["turn"].tool_plan)
        self.assertTrue(state["turn"].tool_plan.should_execute)
        self.assertTrue(state["turn"].tool_plan.tool_name)

    def test_greeting_and_profile_are_direct_answers(self) -> None:
        greeting = build_initial_routing_decision("你好", self._make_context())
        profile = build_initial_routing_decision("你是谁", self._make_context())
        self.assertEqual(greeting.required_action, "direct_answer")
        self.assertFalse(greeting.blocked)
        self.assertEqual(profile.required_action, "direct_answer")
        self.assertFalse(profile.blocked)
        self.assertIn(profile.intent.name, {"chit_chat", "direct_answer"})

    def test_memory_update_routes_to_memory_only(self) -> None:
        routing = build_initial_routing_decision("我以后不吃辣", self._make_context())
        self.assertEqual(routing.required_action, "memory_update")
        self.assertFalse(routing.blocked)
        self.assertTrue(routing.should_persist_memory)
        self.assertFalse(routing.should_retrieve)

    def test_legacy_route_decision_cannot_override_routing_decision(self) -> None:
        state = self._build_state("湖畔私房菜适合带父母吗", current_topic="湖畔私房菜")
        routing = build_initial_routing_decision("湖畔私房菜适合带父母吗", self._make_context(current_topic="湖畔私房菜"))
        routing = routing.model_copy(update={"required_action": "clarify", "should_retrieve": False})
        state["turn"] = state["turn"].model_copy(
            update={
                "decision": TurnDecision.RETRIEVE_THEN_ANSWER,
                "route_decision": "retrieve_then_answer",
                "routing_decision": routing,
                "extra": {
                    **dict(state["turn"].extra),
                    "route_decision": "retrieve_then_answer",
                    "direct_response_kind": "answer",
                },
            }
        )

        self.assertEqual(route_after_understand(state), "compose_answer")

    def test_legacy_direct_response_kind_cannot_override_clarify(self) -> None:
        state = self._build_state("这个呢", current_topic="湖畔私房菜")
        routing = build_initial_routing_decision("这个呢", self._make_context(current_topic="湖畔私房菜"))
        routing = routing.model_copy(update={"required_action": "clarify", "blocked": True, "should_retrieve": False})
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": routing,
                "extra": {
                    **dict(state["turn"].extra),
                    "route_decision": "direct_answer",
                    "direct_response_kind": "answer",
                },
            }
        )

        self.assertEqual(route_after_understand(state), "compose_answer")

    def test_tool_only_routes_without_rag(self) -> None:
        state = self._build_state("这个套餐现在还能用吗", current_topic="湖畔私房菜")
        routing = build_initial_routing_decision("这个套餐现在还能用吗", self._make_context(current_topic="湖畔私房菜"))
        routing = apply_fast_decision_to_routing(
            routing,
            FastDecision(
                intent=IntentType.RECOMMEND,
                needs_rag=False,
                needs_tool=True,
                needs_clarify=False,
                needs_query_rewrite=False,
                confidence=0.91,
                extra={"route_candidate": "tool_only"},
            ),
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing})

        self.assertEqual(route_after_understand(state), "tool_subgraph")
        self.assertFalse(routing.should_retrieve)
        self.assertEqual(route_after_rag(state), "compose_answer")

    def test_rag_only_routes_to_rag_subgraph(self) -> None:
        state = self._build_state("湖畔私房菜适合带父母吗", current_topic="湖畔私房菜")
        routing = build_initial_routing_decision("湖畔私房菜适合带父母吗", self._make_context(current_topic="湖畔私房菜"))
        routing = apply_fast_decision_to_routing(
            routing,
            FastDecision(
                intent=IntentType.RECOMMEND,
                needs_rag=True,
                needs_tool=False,
                needs_clarify=False,
                needs_query_rewrite=False,
                confidence=0.93,
                extra={"route_candidate": "knowledge"},
            ),
        )
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": routing,
                "retrieval_plan": RetrievalPlan(semantic_query="湖畔私房菜适合带父母吗", keyword_query="湖畔私房菜"),
            }
        )

        self.assertEqual(route_after_understand(state), "rag_subgraph")
        self.assertEqual(route_after_rag(state), "compose_answer")

    def test_session_only_constraint_does_not_promote_long_term_memory(self) -> None:
        routing = build_initial_routing_decision("今天不想吃辣", self._make_context())
        self.assertFalse(routing.should_persist_memory)
        self.assertFalse(routing.should_vectorize_memory)
        self.assertFalse(routing.should_retrieve)

    def test_llm_router_fallback_handles_semantic_local_life_query(self) -> None:
        routing = build_initial_routing_decision(
            "爸妈来了，附近有没有稳一点的地方？",
            self._make_context(),
        )
        self.assertEqual(routing.domain, "local_life")
        self.assertEqual(routing.intent.name, "local_life_recommend")
        self.assertEqual(routing.required_action, "clarify")
        self.assertIn("location", routing.missing_slots)

    def test_llm_router_fallback_handles_nearby_query_with_location(self) -> None:
        routing = build_initial_routing_decision(
            "爸妈来了，附近有没有稳一点的地方？",
            self._make_context(current_city="北京", current_location={"lat": 39.9, "lng": 116.4}),
        )
        self.assertEqual(routing.domain, "local_life")
        self.assertEqual(routing.intent.name, "local_life_recommend")
        self.assertIn(routing.required_action, {"rag_retrieval", "rag_plus_tool"})
        self.assertTrue(routing.should_retrieve)

    def test_answer_composer_honors_no_answer_evidence_gate(self) -> None:
        called = []

        def _llm_answerer(_request):
            called.append("llm")
            return {"answer": "不应该被调用"}

        composer = AnswerComposer(llm_answerer=_llm_answerer)
        request = AnswerComposeRequest(
            raw_query="湖畔私房菜适合带父母吗",
            requested_output_style=None,
            rag_result=RagResult(status=RagStatus.EMPTY, evidence_pack=EvidencePack(items=[]), evidence_status="EMPTY"),
            tool_result=None,
            plan_summary=None,
            memory_injection_plan=None,
            evidence_quality=EvidenceQualityDecision(
                evidence_count=0,
                top_score=0.0,
                score_gap=0.0,
                topic_consistency=0.0,
                entity_consistency=0.0,
                city_area_category_consistency=False,
                required_roles_covered=False,
                citation_available=False,
                stale_evidence=False,
                response_mode="no_answer",
                is_valid=False,
                reason="no_evidence",
                fallback_reason="empty_pack",
            ),
            final_response_mode="no_answer",
            allow_direct_response=False,
            direct_response_kind=None,
        )

        result = composer.compose(request)

        self.assertEqual(called, [])
        self.assertIn("RAG_NO_ANSWER", result.answer_text)

    def test_answer_composer_uses_clarification_question_when_available(self) -> None:
        routing = build_initial_routing_decision("附近有什么推荐", self._make_context())
        composer = AnswerComposer()
        request = AnswerComposeRequest(
            raw_query="附近有什么推荐",
            requested_output_style=None,
            rag_result=None,
            tool_result=None,
            plan_summary=None,
            memory_injection_plan=None,
            routing_decision=routing,
            allow_direct_response=True,
            direct_response_kind="low_info",
        )

        result = composer.compose(request)

        self.assertIsNotNone(routing.clarification_question)
        self.assertIn(str(routing.clarification_question), result.answer_text)
        self.assertNotIn("这个问题还不够具体", result.answer_text)

    def test_punctuation_input_skips_retrieval_sse_events(self) -> None:
        container = _FakeContainer()
        adapter = WorkflowNodeAdapter(container)
        services = WorkflowServices(
            load_context=adapter.load_context,
            understand_turn=UnderstandTurnServices(
                parse_intent_slots=lambda state: state,
                resolve_reference=lambda state: state,
                ambiguity_check=lambda state: state,
                rag_gate=lambda state: state,
                rewrite_query=lambda state: state,
            ),
            rag_subgraph=RagSubgraphServices(),
            tool_subgraph=ToolSubgraphServices(),
            compose_answer=adapter.compose_answer,
            persist_session=adapter.persist_session,
            emit_final=adapter.emit_final,
        )
        runner = SequentialWorkflowRunner(services=services)
        command = ChatTurnCommand(
            trace_id="trace-punct",
            session_id="session-punct",
            turn_id="turn-punct",
            user_id="user-punct",
            message="，",
            page="assistant",
            client_context={},
        )

        events = list(runner.run_stream(command, persistent_context=self._make_context()))
        event_types = [event.event_type for event in events]
        self.assertNotIn("retrieval_started", event_types)
        self.assertNotIn("embedding_started", event_types)
        self.assertNotIn("qdrant_search_started", event_types)
        self.assertNotIn("rerank_started", event_types)
        self.assertIn("answer_stream_started", event_types)

    def test_general_question_stays_out_of_local_life_route(self) -> None:
        routing = build_initial_routing_decision("帮我写一段 Python 排序代码", self._make_context())
        self.assertFalse(routing.blocked)
        self.assertNotEqual(routing.route_candidate, "local_life_recommend")
        self.assertNotEqual(routing.intent.name, "local_life_recommend")

    def test_weather_question_stays_out_of_local_life_route(self) -> None:
        routing = build_initial_routing_decision("明天天气怎么样", self._make_context())
        self.assertFalse(routing.blocked)
        self.assertNotEqual(routing.route_candidate, "local_life_recommend")

    def test_low_evidence_pack_is_downgraded(self) -> None:
        pack = EvidencePack(
            items=[
                EvidenceItem(chunk_id="a", content="证据一", score=0.21, document_id="d1", chunk_type="qa"),
                EvidenceItem(chunk_id="b", content="证据二", score=0.23, document_id="d2", chunk_type="qa"),
            ]
        )
        quality = build_evidence_quality(pack, intent_name="qa_general")
        self.assertFalse(quality.is_valid)
        self.assertEqual(quality.reason, "low_top_score")
        self.assertFalse(quality.citation_available)

    def test_stream_skips_intent_analysis_for_invalid_input(self) -> None:
        container = _FakeContainer()
        adapter = WorkflowNodeAdapter(container)
        called = []

        def _should_not_run(_state):
            called.append("understand")
            raise AssertionError("understand_turn should not run for invalid input")

        services = WorkflowServices(
            load_context=adapter.load_context,
            understand_turn=UnderstandTurnServices(
                parse_intent_slots=_should_not_run,
                resolve_reference=_should_not_run,
                ambiguity_check=_should_not_run,
                rag_gate=_should_not_run,
                rewrite_query=_should_not_run,
            ),
            rag_subgraph=RagSubgraphServices(),
            tool_subgraph=ToolSubgraphServices(),
            compose_answer=adapter.compose_answer,
            persist_session=adapter.persist_session,
            emit_final=adapter.emit_final,
        )
        runner = SequentialWorkflowRunner(services=services)
        command = ChatTurnCommand(
            trace_id="trace-matrix",
            session_id="session-matrix",
            turn_id="turn-matrix",
            user_id="user-matrix",
            message="，",
            page="assistant",
            client_context={},
        )

        events = list(runner.run_stream(command, persistent_context=self._make_context()))
        event_types = [event.event_type for event in events]
        self.assertNotIn("intent_analysis_started", event_types)
        self.assertNotIn("retrieval_started", event_types)
        self.assertIn("answer_stream_started", event_types)
        self.assertTrue(event_types[-1] == "final")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
