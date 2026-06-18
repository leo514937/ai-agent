from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.application.workflow.adapters.helpers import build_clarification_question, build_evidence_quality
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
    NormalizedToolResult,
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

    def test_compose_answer_marks_complete_shop_evidence_as_grounded_strict(self) -> None:
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": AnswerComposer()})())
        command = ChatTurnCommand(
            trace_id="trace-grounded-strict",
            session_id="session-grounded-strict",
            turn_id="turn-grounded-strict",
            user_id="user-grounded-strict",
            message="某某家常菜现在营业吗",
        )
        state = build_initial_state(command, persistent=PersistentSessionContext(current_shop="某某家常菜"))
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": RoutingDecision(
                    required_action="tool_call",
                    should_call_tool=True,
                    route_candidate="tool",
                    route_reason="open_status_lookup",
                ),
                "evidence_quality": EvidenceQualityDecision(response_mode="grounded", is_valid=True),
                "tool_result": NormalizedToolResult(
                    status="success",
                    tool_name="check_open_status",
                    normalized_output={
                        "data": {
                            "shop_id": 1001,
                            "shop_name": "某某家常菜",
                            "open_status": "open",
                            "open_hours": "10:00-22:00",
                        }
                    },
                    extra={},
                ),
                "extra": {
                    **dict(state["turn"].extra),
                    "current_shop": "某某家常菜",
                    "ranked_candidates": [
                        {
                            "shop_id": 1001,
                            "name": "某某家常菜",
                            "score": 4.8,
                            "distance_km": 1.2,
                            "avg_price": 68,
                        }
                    ],
                },
            }
        )

        updated = adapter.compose_answer(state)

        self.assertEqual(updated["turn"].extra.get("final_response_mode"), "grounded_strict")
        self.assertIn("现在营业中", updated["turn"].final_answer)
        self.assertNotIn("评分", updated["turn"].final_answer)

        final_state = adapter.emit_final(updated)
        final_event = final_state["runtime"].emitted_events[-1]
        self.assertEqual(final_event.event_type, "final")
        self.assertEqual(final_event.payload["answer_text"], updated["turn"].final_answer)
        self.assertNotIn("评分", final_event.payload["answer_text"])

    def test_compose_answer_does_not_reenter_composer_for_grounded_strict_verifier_failure(self) -> None:
        from unittest.mock import patch

        from learning_agent_service.domain import AnswerComposeResult, AnswerContract, EntityJoinResult

        class _FakeComposer:
            def __init__(self) -> None:
                self.calls = 0

            def compose(self, request):  # noqa: ANN001 - adapter contract is dynamic here
                self.calls += 1
                return AnswerComposeResult(answer_text="某某家常菜现在营业中。", confidence=0.9)

            def _compose_clarify_response(self, request, routing):  # noqa: ANN001 - test double
                return "请告诉我更具体的店名。"

            def _compose_no_answer(self, request, evidence_quality):  # noqa: ANN001 - test double
                return "暂时没有找到足够可靠的依据。"

            def _compose_partial_grounded_answer(self, request):  # noqa: ANN001 - test double
                return "部分判断：某某家常菜现在营业中。"

        class _ReviewReport:
            def model_dump(self, mode="json"):  # noqa: ANN001 - test double
                return {}

        class _VerifierResult:
            passed = False
            suggested_response_mode = "ask_clarification"
            extra = {"phase4_mode": "enforce"}
            issues = []
            repair_hint = None

            def model_dump(self, mode="json"):  # noqa: ANN001 - test double
                return {
                    "passed": self.passed,
                    "suggested_response_mode": self.suggested_response_mode,
                    "extra": self.extra,
                    "issues": self.issues,
                    "repair_hint": self.repair_hint,
                }

        fake_composer = _FakeComposer()
        adapter = WorkflowNodeAdapter(type("Container", (), {"answer_composer": fake_composer})())
        command = ChatTurnCommand(
            trace_id="trace-grounded-strict-enforce",
            session_id="session-grounded-strict-enforce",
            turn_id="turn-grounded-strict-enforce",
            user_id="user-grounded-strict-enforce",
            message="某某家常菜现在营业吗",
        )
        state = build_initial_state(command, persistent=PersistentSessionContext(current_shop="某某家常菜"))
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": RoutingDecision(
                    required_action="tool_call",
                    should_call_tool=True,
                    route_candidate="tool",
                    route_reason="open_status_lookup",
                ),
                "evidence_quality": EvidenceQualityDecision(response_mode="grounded", is_valid=True),
                "tool_result": NormalizedToolResult(
                    status="success",
                    tool_name="check_open_status",
                    normalized_output={
                        "data": {
                            "shop_id": 1001,
                            "shop_name": "某某家常菜",
                            "open_status": "open",
                            "open_hours": "10:00-22:00",
                        }
                    },
                    extra={},
                ),
                "extra": {
                    **dict(state["turn"].extra),
                    "current_shop": "某某家常菜",
                    "ranked_candidates": [
                        {
                            "shop_id": 1001,
                            "name": "某某家常菜",
                            "score": 4.8,
                            "distance_km": 1.2,
                            "avg_price": 68,
                        }
                    ],
                },
            }
        )

        with patch(
            "learning_agent_service.application.workflow.adapters.stages_back_core._build_answer_contract",
            return_value=AnswerContract(
                allowed_facets=["open_status"],
                optional_facets=[],
                forbidden_facets=[],
                required_facets=[],
                evidence_requirements={},
                tool_requirements={},
                forbidden_without_evidence=[],
                candidate_entities=["某某家常菜"],
                selected_entity="某某家常菜",
                missing_slots=[],
                clarification_slot=None,
                answer_style="open_status_only",
                scope_kind="single_shop",
                facet_source_expectations={},
                extra={},
            ),
        ), patch(
            "learning_agent_service.application.workflow.adapters.stages_back_core._build_entity_join_result",
            return_value=EntityJoinResult(selected_entity="某某家常菜"),
        ), patch(
            "learning_agent_service.application.workflow.adapters.stages_back_core._build_answer_verifier_result",
            return_value=_VerifierResult(),
        ), patch(
            "learning_agent_service.application.workflow.adapters.stages_back_core._build_review_report",
            return_value=_ReviewReport(),
        ):
            updated = adapter.compose_answer(state)

        self.assertEqual(fake_composer.calls, 1)
        self.assertEqual(updated["turn"].extra.get("final_response_mode"), "ask_clarification")
        self.assertIn("营业", updated["turn"].final_answer)

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
