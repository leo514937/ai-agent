from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.application.routing import ensure_retrieval_plan, ensure_tool_plan
from learning_agent_service.domain import (
    ChatTurnCommand,
    EvidencePack,
    EvidenceQualityDecision,
    PersistentSessionContext,
    RagResult,
    RagStatus,
    build_initial_state,
)
from learning_agent_service.rag.heuristics import HeuristicModelGateway
from learning_agent_service.testing import (
    EvaluationHarness,
    GoldenEvidencePack,
    HarnessCase,
    HarnessRunResult,
    RagGoldenEvidenceHarness,
    ReplayHarness,
    ToolMockHarness,
    ToolMockResult,
    TraceHarnessRecorder,
    extract_phase0_trace,
)
from learning_agent_service.tools.service import AnswerComposer


class _Phase0Container(SimpleNamespace):
    pass


class Phase0TraceHarnessTestCase(unittest.TestCase):
    def _build_state(self, message: str, **persistent_kwargs):
        command = ChatTurnCommand(
            trace_id="trace-phase0",
            session_id="session-phase0",
            turn_id="turn-phase0",
            user_id="user-phase0",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=PersistentSessionContext(**persistent_kwargs))

    def test_load_context_records_phase0_trace_baseline(self) -> None:
        container = _Phase0Container(
            model_gateway=HeuristicModelGateway(),
            answer_composer=AnswerComposer(),
            rag_orchestrator=None,
            tool_planner=None,
            tool_executor=None,
            tool_result_normalizer=None,
            memory_service=None,
        )
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("附近有什么推荐")

        state = adapter.load_context(state)
        trace = extract_phase0_trace(state)
        snapshot = TraceHarnessRecorder().record(state, case_id="case-1")

        self.assertEqual(trace["harness_mode"], "off")
        self.assertIsNotNone(trace["initial_routing_decision"])
        self.assertEqual(trace["initial_routing_decision"]["required_action"], "clarify")
        self.assertEqual(trace["retrieval_plan_status"], "not_attempted")
        self.assertEqual(trace["tool_plan_status"], "not_attempted")
        self.assertEqual(state["turn"].extra["phase0_trace"]["initial_required_action"], "clarify")
        self.assertEqual(snapshot["initial_routing_decision"]["required_action"], "clarify")

    def test_phase0_trace_records_plan_failures_and_final_response_mode(self) -> None:
        container = _Phase0Container(
            model_gateway=HeuristicModelGateway(),
            answer_composer=AnswerComposer(),
            rag_orchestrator=None,
            tool_planner=None,
            tool_executor=None,
            tool_result_normalizer=None,
            memory_service=None,
        )
        adapter = WorkflowNodeAdapter(container)
        state = self._build_state("附近有什么推荐")
        state = adapter.load_context(state)

        state = ensure_retrieval_plan(state)
        state = ensure_tool_plan(state)
        trace = extract_phase0_trace(state)
        self.assertEqual(trace["retrieval_plan_status"], "skipped")
        self.assertTrue(trace["retrieval_plan_failure_reason"])
        self.assertEqual(trace["tool_plan_status"], "skipped")
        self.assertTrue(trace["tool_plan_failure_reason"])

        routing = state["turn"].routing_decision.model_copy(
            update={
                "required_action": "rag_retrieval",
                "blocked": False,
                "should_retrieve": True,
                "should_call_tool": False,
            }
        )
        state["turn"] = state["turn"].model_copy(
            update={
                "routing_decision": routing,
                "rag_result": RagResult(
                    status=RagStatus.EMPTY,
                    evidence_pack=EvidencePack(items=[]),
                    evidence_status="EMPTY",
                ),
                "evidence_quality": EvidenceQualityDecision(
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
            }
        )
        state = adapter.compose_answer(state)
        trace = extract_phase0_trace(state)

        self.assertEqual(trace["final_response_mode"], "no_answer")
        self.assertEqual(trace["response_origin"], "rag")
        self.assertIn("RAG_NO_ANSWER", state["turn"].final_answer)

    def test_replay_tool_mock_and_evaluation_skeleton_work_together(self) -> None:
        tool_harness = ToolMockHarness()
        tool_harness.register(
            ToolMockResult(
                tool_name="check_open_status",
                status="success",
                payload={"open_status": "营业中"},
            )
        )
        rag_harness = RagGoldenEvidenceHarness()
        rag_harness.register(
            GoldenEvidencePack(
                case_id="case-1",
                evidence_items=[{"content": "这里环境安静"}],
                covered_facets=["scene_fit"],
                missing_facets=["coupon"],
                entity_keys={"shop_id": 1001},
            )
        )

        case = HarnessCase(
            case_id="case-1",
            query="这家店现在营业吗",
            expected_response_mode="grounded",
        )
        replay = ReplayHarness()

        results = replay.run_many(
            [case],
            lambda item: HarnessRunResult(
                case_id=item.case_id,
                passed=True,
                actual_trace={
                    "phase0_trace": {
                        "harness_mode": "replay",
                        "initial_routing_decision": {"required_action": "tool_call"},
                        "evidence_quality": {"response_mode": item.expected_response_mode},
                        "final_response_mode": item.expected_response_mode,
                        "response_origin": "tool",
                    }
                },
                actual_response_mode=item.expected_response_mode or "grounded",
                actual_answer="店铺当前营业中",
                failures=[],
            ),
        )

        report = EvaluationHarness().summarize(results)
        recorded_tool = tool_harness.resolve("check_open_status")
        recorded_pack = rag_harness.resolve("case-1")

        self.assertEqual(recorded_tool.payload["open_status"], "营业中")
        self.assertEqual(recorded_pack.covered_facets, ["scene_fit"])
        self.assertEqual(report.total_cases, 1)
        self.assertEqual(report.passed_cases, 1)
        self.assertEqual(report.failed_cases, 0)
        self.assertEqual(report.metric_summary["response_origin_distribution"]["tool"], 1)
        self.assertEqual(report.metric_summary["missing_trace_fields"].get("initial_routing_decision", 0), 0)


if __name__ == "__main__":
    unittest.main()
