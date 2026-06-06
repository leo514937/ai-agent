from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.rag_gate import RagRouteGate
from learning_agent_service.application.router import build_initial_routing_decision
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.domain import (
    AnswerComposeRequest,
    ChatTurnCommand,
    ClarificationCard,
    ClarificationOption,
    EvidenceItem,
    PersistentSessionContext,
    build_initial_state,
)
from learning_agent_service.local_life.response_builder import build_response_bundle
from learning_agent_service.local_life.schemas import EvidenceClaim, LocalLifeSlots, LocationNorm, RankedCandidate
from learning_agent_service.tools.service import AnswerComposer


class Phase0CoreReplayTestCase(unittest.TestCase):
    def _make_state(self, message: str, **persistent_kwargs):
        command = ChatTurnCommand(
            trace_id="trace-core-replay",
            session_id="session-core-replay",
            turn_id="turn-core-replay",
            user_id="user-core-replay",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=PersistentSessionContext(**persistent_kwargs))

    def _adapter(self) -> WorkflowNodeAdapter:
        return WorkflowNodeAdapter(SimpleNamespace(rag_route_gate=RagRouteGate(), answer_composer=AnswerComposer()))

    def test_case_1_coupon_and_environment_replay_is_clean_and_grounded(self) -> None:
        slots = LocalLifeSlots(
            category="粤菜",
            city="北京",
            location=LocationNorm(city="北京"),
        )
        ranked_candidates = [
            RankedCandidate(
                shop_id=1001,
                name="山城一锅",
                matched_requirements=["环境安静"],
                structured_features={
                    "distance_km": 1.2,
                    "avg_price": 148.0,
                    "score": 4.8,
                    "area": "朝阳",
                    "address": "朝阳区示例路1号",
                },
                evidence_features={"quiet": 0.92},
                explainable_reasons=["环境安静", "适合家庭聚餐"],
                vouchers=[{"title": "满100减20", "pay_value": 100, "actual_value": 80}],
                rank_score=0.98,
            )
        ]
        evidence_claims = [
            EvidenceClaim(
                chunk_id="chunk-1",
                shop_id=1001,
                claim="评论摘要",
                support_text="店里环境安静，适合家庭聚餐。",
                source_type="review",
                confidence=0.9,
                metadata={"shop_name": "山城一锅"},
            )
        ]

        bundle = build_response_bundle(
            raw_query="山城一锅这家店有券吗，环境评价怎么样",
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            page="assistant",
            current_topic="山城一锅",
            selected_shop_id=1001,
            route_decision="rag_plus_tool",
            source_mode="java_business",
            degraded_reason=None,
            knowledge_freshness={"snapshot_version": "v1"},
        )

        self.assertIn("券信息", bundle.answer_text)
        self.assertIn("环境评价", bundle.answer_text)
        self.assertIn("满100减20", bundle.answer_text)
        self.assertIn("环境偏安静", bundle.answer_text)
        self.assertNotIn("Tool result", bundle.answer_text)
        self.assertNotIn("shop_detail", bundle.answer_text)
        self.assertNotIn("normalized_output", bundle.answer_text)
        self.assertNotIn("{'", bundle.answer_text)

    def test_case_2_conversation_recap_hits_trace_and_replays_recent_topic(self) -> None:
        state = self._make_state(
            "你记得我们说过什么？",
            history_summary="刚才聊的是山城一锅的券和环境评价。",
            current_topic="山城一锅",
            recent_entities=["山城一锅"],
        )

        loaded = self._adapter().load_context(state)
        trace = loaded["turn"].extra["phase0_trace"]
        self.assertEqual(trace["initial_routing_decision"]["route_candidate"], "conversation_recap")
        self.assertEqual(trace["initial_routing_decision"]["route_reason"], "conversation_recap_request")
        self.assertFalse(trace["initial_routing_decision"]["blocked"])

        request = AnswerComposeRequest(
            raw_query="你记得我们说过什么？",
            requested_output_style=None,
            rag_result=None,
            tool_result=None,
            plan_summary=None,
            memory_injection_plan=None,
            routing_decision=loaded["turn"].routing_decision,
            allow_direct_response=True,
            direct_response_kind="conversation_recap",
            history_summary="刚才聊的是山城一锅的券和环境评价。",
            stream_event_meta={"current_shop": "山城一锅"},
        )
        result = AnswerComposer().compose(request)

        self.assertIn("山城一锅", result.answer_text)
        self.assertIn("券和环境评价", result.answer_text)
        self.assertNotIn("这个问题还不够具体", result.answer_text)

    def test_case_3_initial_clarify_persists_pending_context(self) -> None:
        state = self._make_state("附近有什么推荐菜")

        loaded = self._adapter().load_context(state)

        self.assertEqual(loaded["turn"].routing_decision.required_action, "clarify")
        self.assertIsNotNone(loaded["persistent"].pending_clarification)
        self.assertEqual(loaded["persistent"].clarification_result["original_query"], "附近有什么推荐菜")
        self.assertEqual(loaded["turn"].extra["clarification_result"]["original_query"], "附近有什么推荐菜")
        self.assertEqual(loaded["turn"].extra["pending_clarification"]["question"], loaded["persistent"].pending_clarification.question)
        self.assertEqual(loaded["turn"].extra["pending_clarification"]["ambiguity_type"], "location")

    def test_case_3_beijing_consumes_pending_location_clarification(self) -> None:
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
        state = self._make_state(
            "北京",
            pending_clarification=pending,
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
            },
        )

        loaded = self._adapter().load_context(state)

        self.assertEqual(loaded["turn"].routing_decision.required_action, "rag_retrieval")
        self.assertEqual(loaded["turn"].routing_decision.route_candidate, "local_life")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_query"], "附近有什么推荐菜")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_intent"], "local_life_recommend")
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_route"], "rag_retrieval")
        self.assertNotEqual(loaded["turn"].routing_decision.input_quality.kind, "low_information")
        self.assertIsNone(loaded["turn"].routing_decision.clarification_question)

    def test_case_4_arctic_returns_location_unavailable_and_keeps_pending_context(self) -> None:
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
        state = self._make_state(
            "北极",
            pending_clarification=pending,
            current_city="北京",
            clarification_result={
                "original_query": "附近有什么推荐菜",
                "original_intent": "local_life_recommend",
                "original_route": "rag_retrieval",
            },
        )

        loaded = self._adapter().load_context(state)

        self.assertEqual(loaded["turn"].routing_decision.required_action, "direct_answer")
        self.assertEqual(loaded["turn"].routing_decision.route_candidate, "location_unavailable")
        self.assertEqual(loaded["turn"].routing_decision.route_reason, "unserviceable_location")
        self.assertFalse(loaded["turn"].routing_decision.blocked)
        self.assertIn("unserviceable_location", loaded["turn"].routing_decision.safeguards_triggered)
        self.assertEqual(loaded["turn"].extra["pending_clarification_restore"]["original_query"], "附近有什么推荐菜")
        self.assertIsNone(loaded["turn"].routing_decision.clarification_question)
        self.assertNotEqual(loaded["turn"].routing_decision.input_quality.kind, "low_information")

        answer = AnswerComposer().compose(
            AnswerComposeRequest(
                raw_query="北极",
                requested_output_style=None,
                rag_result=None,
                tool_result=None,
                plan_summary=None,
                memory_injection_plan=None,
                routing_decision=loaded["turn"].routing_decision,
                allow_direct_response=True,
                direct_response_kind="location_unavailable",
                history_summary=None,
                stream_event_meta={"current_shop": None},
            )
        )

        self.assertIn("不太适合本地生活推荐", answer.answer_text)
        self.assertNotIn("这个问题还不够具体", answer.answer_text)

    def test_client_context_shop_name_prevents_ambiguous_reference_block(self) -> None:
        decision = build_initial_routing_decision(
            "山城一锅这家店有券吗，环境评价怎么样",
            PersistentSessionContext(),
            client_context={
                "page": "assistant",
                "shopName": "山城一锅",
            },
        )

        self.assertFalse(decision.blocked)
        self.assertNotEqual(decision.route_candidate, "clarify")
        self.assertNotEqual(decision.route_reason, "ambiguous_reference_without_context")
        self.assertIn("shopName", decision.extra.get("client_context", {}))
        self.assertTrue(bool(decision.extra.get("context_has_anchor")))
        self.assertTrue(bool(decision.extra.get("context_has_candidate_anchor")))


if __name__ == "__main__":
    unittest.main()
