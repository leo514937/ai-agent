from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters.helpers import build_initial_routing_decision
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.domain import (
    ChatTurnCommand,
    EvidenceItem,
    EvidencePack,
    EvidenceQualityDecision,
    IntentRoutingDecision,
    NormalizedToolResult,
    PersistentSessionContext,
    RagResult,
    RagStatus,
    RoutingDecision,
    ToolExecutionStatus,
    build_initial_state,
)
from learning_agent_service.tools.service import AnswerComposer


class P15Day4StandardPathContractReviewTestCase(unittest.TestCase):
    def _build_state(self) -> dict:
        command = ChatTurnCommand(
            trace_id="trace-p15-day4",
            session_id="session-p15-day4",
            turn_id="turn-p15-day4",
            user_id="user-p15-day4",
            message="这家店推荐理由和环境怎么样，顺便看下有没有券",
            page="assistant",
            client_context={},
        )
        state = build_initial_state(
            command,
            persistent=PersistentSessionContext(
                current_city="北京",
                current_shop="测试店",
                selected_shop_name="测试店",
                selected_shop_id=11,
            ),
        )
        routing = RoutingDecision(
            required_action="rag_plus_tool",
            should_retrieve=True,
            should_call_tool=True,
            route_candidate="local_life.combo",
            intent=IntentRoutingDecision(name="local_life_recommend", confidence=0.97),
            extra={
                "required_facets": [
                    {"name": "scene_fit", "data_source": "static_rag"},
                    {"name": "recommendation_reason", "data_source": "mixed"},
                    {"name": "coupon", "data_source": "dynamic_tool"},
                ],
                "optional_facets": [
                    {"name": "distance_eta", "data_source": "dynamic_tool"},
                ],
                "scope_kind": "single_shop",
                "answer_style": "facet_multi",
            },
        )
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-1",
                    content="测试店环境不错，适合朋友聚餐。",
                    score=0.96,
                    document_id="doc-1",
                    chunk_type="review",
                    parent_chunk_id="11",
                    metadata={"shop_id": "11", "role": "review", "city": "北京"},
                ),
                EvidenceItem(
                    chunk_id="chunk-2",
                    content="测试店门店介绍中提到推荐理由是安静和出餐快。",
                    score=0.91,
                    document_id="doc-2",
                    chunk_type="profile",
                    parent_chunk_id="11",
                    metadata={"shop_id": "11", "role": "merchant_profile", "city": "北京"},
                ),
            ]
        )
        tool_result = NormalizedToolResult(
            status=ToolExecutionStatus.SUCCESS,
            tool_name="get_coupon_list",
            normalized_output={
                "shop_id": 11,
                "shop_name": "测试店",
                "coupons": [{"title": "满减券", "payValue": 20, "actualValue": 50}],
            },
            used_tools=["get_coupon_list"],
            extra={"grounding_source": "business_evidence"},
        )
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": routing,
                "rag_result": RagResult(status=RagStatus.OK, evidence_pack=pack, evidence_status="OK"),
                "tool_result": tool_result,
                "evidence_quality": EvidenceQualityDecision(
                    response_mode="grounded",
                    is_valid=True,
                    reason="",
                    covered_facets=["scene_fit", "recommendation_reason", "coupon"],
                    missing_facets=[],
                    tool_candidates=["get_coupon_list"],
                ),
            }
        )
        return state

    def test_simple_path_keeps_rule_review_trace(self) -> None:
        routing = build_initial_routing_decision("谢谢", PersistentSessionContext())
        route_review = routing.extra.get("route_review_decision") or {}

        self.assertEqual(routing.execution_mode, "simple")
        self.assertTrue(route_review.get("reviewed"))
        self.assertIn("current_action", route_review)
        self.assertIn("recommended_action", route_review)
        self.assertEqual(route_review.get("changed"), False)

    def test_standard_path_builds_source_contract_and_contract_review(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state()

        updated = adapter.compose_answer(state)
        turn = updated["turn"]
        answer_contract = turn.extra["answer_contract"]
        source_contract = turn.source_contract
        review_report = turn.review_report
        route_review = turn.extra.get("route_review_decision") or {}

        self.assertEqual(answer_contract["answer_style"], "facet_multi")
        self.assertEqual(answer_contract["facet_source_expectations"]["recommendation_reason"]["data_source"], "mixed")
        self.assertEqual(source_contract.facet_source_map["scene_fit"]["data_source"], "static_rag")
        self.assertEqual(source_contract.facet_source_map["recommendation_reason"]["data_source"], "mixed")
        self.assertEqual(source_contract.facet_source_map["coupon"]["data_source"], "dynamic_tool")
        self.assertIn(review_report.decision, {"pass", "repair_answer", "retry_rag", "retry_tool", "degrade"})
        self.assertNotEqual(review_report.decision, "replan")
        self.assertIsNotNone(route_review)
        self.assertEqual(review_report.extra.get("phase4_mode"), answer_contract.get("extra", {}).get("phase4_mode"))
        self.assertIn("source_contract", turn.extra)
        self.assertIn("review_report", turn.extra)
        self.assertIn("answer_contract", turn.extra)
        self.assertIn("answer_verifier_result", turn.extra)


if __name__ == "__main__":
    unittest.main()
