from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router.phase0_quality import build_initial_routing_decision
from learning_agent_service.application.router.phase2_slots import build_evidence_quality
from learning_agent_service.application.router.phase5_retrieval import ensure_retrieval_plan
from learning_agent_service.domain import (
    ChatTurnCommand,
    EvidenceItem,
    EvidencePack,
    PersistentSessionContext,
    build_initial_state,
)


class Phase1RoutingTestCase(unittest.TestCase):
    def _make_state(self, message: str, **persistent_kwargs):
        command = ChatTurnCommand(
            trace_id="trace-phase1",
            session_id="session-phase1",
            turn_id="turn-phase1",
            user_id="user-phase1",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=PersistentSessionContext(**persistent_kwargs))

    def test_route_review_upgrades_nearby_recommendations_when_location_context_exists(self) -> None:
        routing = build_initial_routing_decision(
            "附近有没有适合约会、现在营业、最好有券的火锅？",
            PersistentSessionContext(current_city="上海"),
        )

        self.assertEqual(routing.required_action, "rag_plus_tool")
        review = routing.extra["route_review_decision"]
        self.assertTrue(review["changed"])
        self.assertEqual(review["recommended_action"], "rag_plus_tool")

        constraints = routing.extra["required_facets_source_constraints"]
        self.assertEqual(constraints["scene_fit"], "static_rag")
        self.assertEqual(constraints["recommendation_reason"], "mixed")
        self.assertEqual(constraints["shop_detail"], "static_rag")
        self.assertEqual(constraints["open_status"], "dynamic_tool")
        self.assertEqual(constraints["coupon"], "dynamic_tool")
        self.assertEqual(constraints["distance_eta"], "dynamic_tool")

        state = self._make_state("附近有没有适合约会、现在营业、最好有券的火锅？", current_city="上海")
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing})
        state = ensure_retrieval_plan(state)

        retrieval_plan = state["turn"].retrieval_plan
        self.assertIsNotNone(retrieval_plan)
        self.assertIn("required_facets_source_constraints", retrieval_plan.extra)
        self.assertEqual(retrieval_plan.extra["required_facets_source_constraints"]["scene_fit"], "static_rag")
        self.assertEqual(retrieval_plan.extra["required_facets_source_constraints"]["coupon"], "dynamic_tool")

    def test_route_review_keeps_status_queries_on_tool_call(self) -> None:
        routing = build_initial_routing_decision(
            "湖畔私房菜现在营业吗",
            PersistentSessionContext(current_topic="湖畔私房菜"),
        )

        self.assertEqual(routing.required_action, "tool_call")
        facets = {facet["name"] for facet in routing.extra["required_facets"]}
        self.assertIn("open_status", facets)
        self.assertNotIn("scene_fit", facets)
        self.assertNotIn("shop_detail", facets)
        self.assertEqual(routing.extra["required_facets_source_constraints"]["open_status"], "dynamic_tool")

    def test_route_review_treats_conversation_recap_as_direct_answer(self) -> None:
        routing = build_initial_routing_decision(
            "你记得我们说过什么吗",
            PersistentSessionContext(history_summary="刚才在聊湖畔私房菜和优惠券"),
        )

        self.assertEqual(routing.required_action, "direct_answer")
        self.assertEqual(routing.route_candidate, "conversation_recap")
        self.assertEqual(routing.intent.name, "conversation_recap")

    def test_current_shop_keeps_shop_follow_up_on_track(self) -> None:
        routing = build_initial_routing_decision(
            "这家店推荐菜",
            PersistentSessionContext(
                current_shop="山城一锅",
                selected_shop_name="山城一锅",
                selected_shop_id=1001,
                recent_entities=["山城一锅"],
            ),
        )

        self.assertEqual(routing.required_action, "rag_retrieval")
        self.assertEqual(routing.route_candidate, "follow_up_reference")
        self.assertFalse(routing.blocked)
        self.assertIn("山城一锅", routing.resolved_references)
        self.assertNotEqual(routing.route_reason, "low_information")
        self.assertNotEqual(routing.required_action, "clarify")

    def test_nearby_recommendation_with_current_shop_asks_human_clarification(self) -> None:
        routing = build_initial_routing_decision(
            "附近有什么推荐菜",
            PersistentSessionContext(
                current_shop="山城一锅",
                selected_shop_name="山城一锅",
                selected_shop_id=1001,
                current_city="北京",
            ),
        )

        self.assertEqual(routing.required_action, "clarify")
        self.assertTrue(routing.blocked)
        self.assertEqual(routing.route_candidate, "clarify")
        self.assertIn("这家店", routing.clarification_question or "")
        self.assertIn("当前位置附近", routing.clarification_question or "")

    def test_route_review_marks_unserviceable_location_for_direct_answer(self) -> None:
        routing = build_initial_routing_decision("北极", PersistentSessionContext(current_city="北京"))

        self.assertEqual(routing.required_action, "direct_answer")
        self.assertEqual(routing.route_candidate, "location_unavailable")
        self.assertEqual(routing.intent.name, "location_unavailable")

    def test_min_entity_consistency_flags_cross_shop_mixture(self) -> None:
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-a-review",
                    content="A店评价很好，环境安静。",
                    score=0.99,
                    document_id="doc-a",
                    chunk_type="review",
                    parent_chunk_id="parent-a",
                    metadata={"shop_id": "A", "shop_name": "A店", "role": "review"},
                ),
                EvidenceItem(
                    chunk_id="chunk-b-coupon",
                    content="B店券还能用，优惠力度不错。",
                    score=0.90,
                    document_id="doc-b",
                    chunk_type="coupon",
                    parent_chunk_id="parent-b",
                    metadata={"shop_id": "B", "shop_name": "B店", "role": "coupon"},
                ),
                EvidenceItem(
                    chunk_id="chunk-c-status",
                    content="C店现在营业中。",
                    score=0.80,
                    document_id="doc-c",
                    chunk_type="status",
                    parent_chunk_id="parent-c",
                    metadata={"shop_id": "C", "shop_name": "C店", "role": "business_evidence"},
                ),
            ]
        )

        quality = build_evidence_quality(
            pack,
            intent_name="local_life_recommend",
            context={
                "query_text": "A店怎么样？",
                "shop_id": "A",
                "shop_name": "A店",
                "tool_result_present": True,
                "has_tool_result": True,
                "tool_result_payload": {"shop_id": "B", "shop_name": "B店"},
            },
        )

        self.assertFalse(quality.is_valid)
        self.assertEqual(quality.reason, "multi_shop_evidence")
        self.assertEqual(quality.response_mode, "no_answer")
        self.assertIn("entity_consistency_minimal", quality.details)
        self.assertTrue(quality.details["entity_consistency_minimal"]["cross_entity_risk"])
        self.assertEqual(quality.details["entity_consistency_minimal"]["mismatch_reason"], "multi_shop_evidence")


if __name__ == "__main__":
    unittest.main()
