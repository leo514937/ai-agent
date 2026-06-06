from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.domain import (
    AnswerContract,
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
    SemanticParseResult,
    SourceContract,
    LoopCounter,
    ReviewReport,
    ToolExecutionStatus,
    build_initial_state,
)
from learning_agent_service.tools.service import AnswerComposer


class CompatibilityFirstDay1TestCase(unittest.TestCase):
    def _build_state(self) -> dict:
        command = ChatTurnCommand(
            trace_id="trace-p15-day1",
            session_id="session-p15-day1",
            turn_id="turn-p15-day1",
            user_id="user-p15-day1",
            message="这家店有券吗，环境怎么样",
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
                    {"name": "coupon", "data_source": "dynamic_tool"},
                ],
                "optional_facets": [
                    {"name": "location", "data_source": "slot"},
                ],
                "scope_kind": "single_shop",
                "answer_style": "single_shop_review",
                "facet_source_expectations": {"scene_fit": {"data_source": "static_rag"}},
            },
        )
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-1",
                    content="测试店环境不错，适合家庭聚餐。",
                    score=0.95,
                    document_id="doc-1",
                    chunk_type="review",
                    parent_chunk_id="11",
                    metadata={"shop_id": "11", "role": "review", "city": "北京"},
                )
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
                    covered_facets=["scene_fit", "coupon"],
                    missing_facets=[],
                    tool_candidates=["get_coupon_list"],
                ),
            }
        )
        return state

    def test_compose_answer_writes_compatibility_shadow_fields_without_changing_answer(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state()

        updated = adapter.compose_answer(state)
        turn = updated["turn"]
        extra = turn.extra

        self.assertTrue(turn.final_answer)
        self.assertIsInstance(turn.semantic_parse_result, SemanticParseResult)
        self.assertIsInstance(turn.source_contract, SourceContract)
        self.assertIsInstance(turn.review_report, ReviewReport)
        self.assertIsInstance(turn.loop_counter, LoopCounter)

        self.assertIn("semantic_parse_result", extra)
        self.assertIn("source_contract", extra)
        self.assertIn("review_report", extra)
        self.assertIn("loop_counter", extra)
        self.assertIn("answer_contract", extra)
        self.assertIn("answer_verifier_result", extra)

        self.assertEqual(extra["semantic_parse_result"]["primary_intent"], "local_life_recommend")
        self.assertEqual(extra["source_contract"]["target_shop_id"], 11)
        self.assertEqual(extra["review_report"]["decision"], "pass")
        self.assertEqual(extra["loop_counter"]["retry_rag"], 0)
        self.assertEqual(extra["loop_counter"]["retry_tool"], 0)
        self.assertEqual(extra["loop_counter"]["replan"], 0)

        self.assertEqual(extra["answer_contract"]["selected_entity"], "11")
        self.assertEqual(extra["answer_verifier_result"]["passed"], True)
        self.assertIsInstance(extra["answer_contract"], dict)
        self.assertIsInstance(extra["answer_verifier_result"], dict)


if __name__ == "__main__":
    unittest.main()
