from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.application import routing as routing_module
from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.domain import (
    AnswerComposeRequest,
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
from learning_agent_service.testing.harness import EvaluationHarness, HarnessRunResult, TraceHarnessRecorder
from learning_agent_service.tools.service import AnswerComposer


class Phase4AnswerVerifierTestCase(unittest.TestCase):
    def _build_state(self, *, shop_id: str, tool_shop_id: str) -> dict:
        command = ChatTurnCommand(
            trace_id="trace-phase4",
            session_id="session-phase4",
            turn_id="turn-phase4",
            user_id="user-phase4",
            message="这家店有券吗，环境怎么样",
            page="assistant",
            client_context={},
        )
        state = build_initial_state(
            command,
            persistent=PersistentSessionContext(
                current_city="北京",
                current_location={"area": "朝阳", "lat": 39.9, "lng": 116.4},
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
            },
        )
        pack = EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id="chunk-1",
                    content="店里环境安静，适合家庭聚餐。",
                    score=0.92,
                    document_id="doc-1",
                    chunk_type="review",
                    parent_chunk_id=shop_id,
                    metadata={"shop_id": shop_id, "role": "review", "city": "北京", "category": "火锅"},
                )
            ]
        )
        tool_result = NormalizedToolResult(
            status=ToolExecutionStatus.SUCCESS,
            tool_name="get_coupon_list",
            normalized_output={
                "shop_id": tool_shop_id,
                "shop_name": "示例店",
                "coupons": [{"title": "午市券", "payValue": 20, "actualValue": 50}],
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

    def test_compose_answer_records_phase4_verifier_issues_without_blocking_answer(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state(shop_id="shop-1", tool_shop_id="shop-2")

        updated = adapter.compose_answer(state)
        turn = updated["turn"]
        phase4_trace = turn.extra.get("phase4_trace")

        self.assertIsNotNone(phase4_trace)
        self.assertFalse(phase4_trace["verifier_passed"])
        self.assertIn("cross_entity_stitching", phase4_trace["verifier_issues"])
        self.assertEqual(phase4_trace["suggested_response_mode"], "partial_grounded")
        self.assertTrue(turn.final_answer)
        self.assertIn("环境评价", turn.final_answer)
        self.assertIn("券信息", turn.final_answer)
        self.assertIsNotNone(turn.extra.get("answer_verifier_result"))
        self.assertIsNotNone(updated["runtime"].metrics.get("phase4_trace"))

    def test_compose_answer_marks_aligned_evidence_as_passed(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state(shop_id="shop-1", tool_shop_id="shop-1")

        updated = adapter.compose_answer(state)
        phase4_trace = updated["turn"].extra.get("phase4_trace")

        self.assertIsNotNone(phase4_trace)
        self.assertTrue(phase4_trace["verifier_passed"])
        self.assertEqual(phase4_trace["verifier_issues"], [])
        self.assertEqual(phase4_trace["suggested_response_mode"], "grounded")

    def test_trace_harness_records_phase4_trace(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state(shop_id="shop-1", tool_shop_id="shop-1")

        updated = adapter.compose_answer(state)
        recorded = TraceHarnessRecorder().record(updated, case_id="phase4-case")
        report = EvaluationHarness().summarize(
            [
                HarnessRunResult(
                    case_id="phase4-case",
                    passed=True,
                    actual_trace=recorded,
                    actual_response_mode="grounded",
                    actual_answer=str(updated["turn"].final_answer or ""),
                    failures=[],
                )
            ]
        )

        self.assertIn("phase4_trace", recorded)
        self.assertTrue(recorded["phase4_trace"]["verifier_passed"])
        self.assertEqual(report.metric_summary["verifier_status_distribution"]["passed"], 1)
        self.assertEqual(report.metric_summary["verifier_issue_distribution"], {})

    def test_verifier_can_be_disabled_and_mark_skipped(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state(shop_id="shop-1", tool_shop_id="shop-2")

        with patch.object(
            routing_module,
            "get_settings",
            return_value=SimpleNamespace(enable_answer_verifier=False, answer_verifier_mode="warn_only"),
        ):
            updated = adapter.compose_answer(state)

        phase4_trace = updated["turn"].extra.get("phase4_trace")
        verifier_result = updated["turn"].extra.get("answer_verifier_result")

        self.assertIsNotNone(phase4_trace)
        self.assertTrue(phase4_trace["verifier_passed"])
        self.assertEqual(phase4_trace["answer_verifier_mode"], "skipped")
        self.assertEqual(verifier_result["extra"]["phase4_mode"], "skipped")

    def test_verifier_enforce_mode_recomposes_partial_grounded_answer(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        state = self._build_state(shop_id="shop-1", tool_shop_id="shop-2")
        state["turn"] = state["turn"].model_copy(update={"tool_result": None})

        with patch.object(
            routing_module,
            "get_settings",
            return_value=SimpleNamespace(enable_answer_verifier=True, answer_verifier_mode="enforce"),
        ):
            updated = adapter.compose_answer(state)

        phase4_trace = updated["turn"].extra.get("phase4_trace")
        answer_text = str(updated["turn"].final_answer or "")

        self.assertIsNotNone(phase4_trace)
        self.assertFalse(phase4_trace["verifier_passed"])
        self.assertEqual(phase4_trace["answer_verifier_mode"], "enforce")
        self.assertEqual(phase4_trace["suggested_response_mode"], "partial_grounded")
        self.assertIn("目前只能先给你一个部分判断", answer_text)


if __name__ == "__main__":
    unittest.main()
