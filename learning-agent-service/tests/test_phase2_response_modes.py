from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.application.router.phase2_slots import build_clarification_question, build_evidence_quality
from learning_agent_service.domain import (
    AnswerComposeRequest,
    ChatTurnCommand,
    EvidenceItem,
    EvidencePack,
    EvidenceQualityDecision,
    PersistentSessionContext,
    RagResult,
    RagStatus,
    RoutingDecision,
    build_initial_state,
)
from learning_agent_service.tools.service import AnswerComposer


class Phase2ResponseModesTestCase(unittest.TestCase):
    def test_partial_grounded_when_core_facet_is_covered_but_dynamic_facets_are_missing(self) -> None:
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-1",
                    content="店里环境安静，适合家庭聚餐。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="review",
                    parent_chunk_id="shop-1",
                    metadata={"shop_id": "shop-1", "role": "review", "city": "北京", "category": "火锅"},
                )
            ]
        )

        quality = build_evidence_quality(
            pack,
            intent_name="local_life_recommend",
            context={
                "query_text": "这家店适合带父母吗",
                "shop_id": "shop-1",
                "shop_name": "示例店",
                "required_facets": [
                    {"name": "scene_fit", "missing_policy": "partial_grounded", "data_source": "static_rag"},
                    {"name": "coupon", "missing_policy": "partial_grounded", "data_source": "dynamic_tool"},
                ],
                "tool_result_present": False,
                "has_tool_result": False,
            },
        )

        self.assertEqual(quality.response_mode, "partial_grounded")
        self.assertFalse(quality.is_valid)
        self.assertIn("scene_fit", quality.details.get("covered_facets", []))
        self.assertIn("coupon", quality.details.get("missing_facets", []))

    def test_ask_clarification_when_key_slot_is_missing(self) -> None:
        quality = build_evidence_quality(
            None,
            intent_name="local_life_recommend",
            context={
                "query_text": "附近有什么推荐",
                "missing_slots": ["location"],
                "clarification_slot": "location",
                "required_facets": [
                    {"name": "location", "missing_policy": "ask_clarification", "data_source": "client_context"}
                ],
            },
        )

        self.assertEqual(quality.response_mode, "ask_clarification")
        self.assertIn("location", quality.missing_slots)
        self.assertEqual(quality.clarification_slot, "location")

    def test_answer_composer_uses_slot_specific_clarification(self) -> None:
        composer = AnswerComposer()
        request = AnswerComposeRequest(
            raw_query="附近有什么推荐",
            requested_output_style=None,
            rag_result=None,
            tool_result=None,
            plan_summary=None,
            memory_injection_plan=None,
            routing_decision=RoutingDecision(
                required_action="clarify",
                missing_slots=["location"],
                clarification_question=None,
            ),
            evidence_quality=EvidenceQualityDecision(response_mode="ask_clarification"),
            final_response_mode="ask_clarification",
            allow_direct_response=True,
            direct_response_kind="low_info",
        )

        result = composer.compose(request)

        self.assertIn("城市或商圈", result.answer_text)
        self.assertNotIn("我还差一点信息", result.answer_text)

    def test_build_clarification_question_hides_internal_shop_detail_slot(self) -> None:
        question = build_clarification_question(["shop_detail"], clarification_slot="shop_detail")

        self.assertIsNotNone(question)
        self.assertIn("哪家店", question or "")
        self.assertIn("详情", question or "")
        self.assertNotIn("shop_detail", question or "")

    def test_answer_composer_preserves_rag_result_on_partial_grounded_tool_failure(self) -> None:
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-1",
                    content="店里环境安静，适合家庭聚餐。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="review",
                    parent_chunk_id="shop-1",
                    metadata={"shop_id": "shop-1", "role": "review", "city": "北京", "category": "火锅"},
                )
            ]
        )
        quality = EvidenceQualityDecision(
            response_mode="partial_grounded",
            is_valid=False,
            reason="too_few_evidence",
            fallback_reason="insufficient_count",
        )
        composer = AnswerComposer()
        request = AnswerComposeRequest(
            raw_query="这家店适合带父母吗",
            requested_output_style=None,
            rag_result=RagResult(status=RagStatus.OK, evidence_pack=pack, evidence_status="OK"),
            tool_result=None,
            plan_summary=None,
            memory_injection_plan=None,
            routing_decision=RoutingDecision(required_action="rag_plus_tool", should_retrieve=True, should_call_tool=True),
            evidence_quality=quality,
            final_response_mode="partial_grounded",
            allow_direct_response=False,
            direct_response_kind=None,
        )

        result = composer.compose(request)

        self.assertIn("部分判断", result.answer_text)
        self.assertIn("环境安静", result.answer_text)
        self.assertNotIn("RAG_NO_ANSWER", result.answer_text)

    def test_phase2_trace_records_rag_plus_tool_failure_reasons(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        command = ChatTurnCommand(
            trace_id="trace-phase2",
            session_id="session-phase2",
            turn_id="turn-phase2",
            user_id="user-phase2",
            message="这家店有券吗，环境怎么样",
            page="assistant",
            client_context={},
        )
        state = build_initial_state(command, persistent=PersistentSessionContext())
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-1",
                    content="店里环境安静，适合家庭聚餐。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="review",
                    parent_chunk_id="shop-1",
                    metadata={"shop_id": "shop-1", "role": "review", "city": "北京", "category": "火锅"},
                )
            ]
        )
        routing = RoutingDecision(
            required_action="rag_plus_tool",
            should_retrieve=False,
            should_call_tool=False,
            missing_slots=["shop_id"],
            tool_candidates=["get_coupon_list"],
            route_reason="rag_plus_tool_test",
        )
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": routing,
                "retrieval_plan": None,
                "tool_plan": None,
                "rag_result": RagResult(status=RagStatus.OK, evidence_pack=pack, evidence_status="OK"),
                "evidence_quality": EvidenceQualityDecision(
                    response_mode="partial_grounded",
                    is_valid=False,
                    reason="too_few_evidence",
                    fallback_reason="insufficient_count",
                    missing_slots=["shop_id"],
                    clarification_slot="shop_id",
                    covered_facets=["scene_fit"],
                    missing_facets=["coupon"],
                    tool_candidates=["get_coupon_list"],
                ),
            }
        )

        updated = adapter.compose_answer(state)
        phase2_trace = updated["turn"].extra.get("phase2_trace")

        self.assertIsNotNone(phase2_trace)
        self.assertEqual(phase2_trace["response_mode"], "partial_grounded")
        self.assertTrue(phase2_trace["rag_plus_tool_failed"])
        self.assertEqual(phase2_trace["rag_plus_tool_failure_reason"], "retrieval_plan_missing")
        self.assertIn("retrieval_plan_missing", phase2_trace["rag_plus_tool_failure_reasons"])
        self.assertIn("tool_plan_missing", phase2_trace["rag_plus_tool_failure_reasons"])
        self.assertIn("tool_slot_missing", phase2_trace["rag_plus_tool_failure_reasons"])
        self.assertIn("tool_not_allowed", phase2_trace["rag_plus_tool_failure_reasons"])
        self.assertEqual(phase2_trace["missing_slots"], ["shop_id"])
        self.assertEqual(phase2_trace["clarification_slot"], "shop_id")
        self.assertEqual(phase2_trace["tool_candidates"], ["get_coupon_list"])
        self.assertGreaterEqual(phase2_trace["evidence_after_gate_count"], 1)
        runtime_phase2_trace = updated["runtime"].metrics.get("phase2_trace")
        self.assertIsNotNone(runtime_phase2_trace)
        self.assertEqual(runtime_phase2_trace["rag_plus_tool_failure_reason"], "retrieval_plan_missing")
        self.assertIn("tool_not_allowed", runtime_phase2_trace["rag_plus_tool_failure_reasons"])


if __name__ == "__main__":
    unittest.main()
