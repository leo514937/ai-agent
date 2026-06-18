from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters.helpers import ensure_task_plan
from learning_agent_service.application.workflow.subgraphs import route_after_understand
from learning_agent_service.domain import (
    ChatTurnCommand,
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
    build_initial_state,
)
from learning_agent_service.testing import EvaluationHarness, HarnessCase, ReplayHarness, TraceHarnessRecorder


class Phase3ReplayCompareTestCase(unittest.TestCase):
    def _build_case(self) -> HarnessCase:
        return HarnessCase(
            case_id="phase3-replay-case",
            query="推荐一家适合约会、现在营业、最好有券的火锅店",
            session_context={
                "current_city": "北京",
                "current_location": {"area": "朝阳", "lat": 39.9, "lng": 116.4},
            },
        )

    def _build_state(self, case: HarnessCase):
        command = ChatTurnCommand(
            trace_id=f"trace-{case.case_id}",
            session_id=f"session-{case.case_id}",
            turn_id=f"turn-{case.case_id}",
            user_id=f"user-{case.case_id}",
            message=case.query,
            page="assistant",
            client_context={},
        )
        persistent = PersistentSessionContext(**case.session_context)
        state = build_initial_state(command, persistent=persistent)
        routing = RoutingDecision(
            required_action="rag_plus_tool",
            should_retrieve=True,
            should_call_tool=True,
            route_candidate="local_life.combo",
            intent=IntentRoutingDecision(name="local_life_recommend", confidence=0.97),
            extra={
                "required_facets": [
                    {"name": "scene_fit", "data_source": "static_rag"},
                    {"name": "recommendation_reason", "data_source": "static_rag"},
                    {"name": "open_status", "data_source": "dynamic_tool"},
                    {"name": "coupon", "data_source": "dynamic_tool"},
                ],
                "optional_facets": [
                    {"name": "location", "data_source": "slot"},
                ],
            },
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})
        return state

    def _build_simple_state(self, case: HarnessCase):
        command = ChatTurnCommand(
            trace_id=f"trace-{case.case_id}",
            session_id=f"session-{case.case_id}",
            turn_id=f"turn-{case.case_id}",
            user_id=f"user-{case.case_id}",
            message=case.query,
            page="assistant",
            client_context={},
        )
        state = build_initial_state(command, persistent=PersistentSessionContext(**case.session_context))
        routing = RoutingDecision(
            required_action="direct_answer",
            should_retrieve=False,
            should_call_tool=False,
            route_candidate="greeting",
            intent=IntentRoutingDecision(name="chit_chat", confidence=0.99),
            extra={},
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})
        return state

    def test_replay_compare_highlights_task_plan_trace_diff(self) -> None:
        case = self._build_case()
        recorder = TraceHarnessRecorder()
        replay = ReplayHarness()

        def baseline_executor(_case: HarnessCase):
            state = self._build_state(_case)
            snapshot = recorder.record(state, case_id=_case.case_id)
            return {
                "case_id": _case.case_id,
                "passed": True,
                "actual_trace": snapshot,
                "actual_response_mode": "unknown",
                "actual_answer": "",
                "failures": [],
            }

        def candidate_executor(_case: HarnessCase):
            state = self._build_state(_case)
            state = ensure_task_plan(state)
            snapshot = recorder.record(state, case_id=_case.case_id)
            return {
                "case_id": _case.case_id,
                "passed": True,
                "actual_trace": snapshot,
                "actual_response_mode": "unknown",
                "actual_answer": "",
                "failures": [],
            }

        comparison = replay.compare_case(case, baseline_executor, candidate_executor)

        self.assertTrue(comparison.passed)
        self.assertIn("phase3_trace", comparison.differences)
        baseline_phase3 = comparison.baseline.actual_trace.get("phase3_trace", {})
        candidate_phase3 = comparison.candidate.actual_trace.get("phase3_trace", {})
        self.assertEqual(baseline_phase3.get("task_plan_status"), None)
        self.assertEqual(candidate_phase3.get("task_plan_status"), "synthesized")

    def test_replay_compare_batch_reports_changed_and_unchanged_cases(self) -> None:
        replay = ReplayHarness()
        evaluation = EvaluationHarness()
        recorder = TraceHarnessRecorder()
        cases = [
            self._build_case(),
            HarnessCase(
                case_id="phase3-simple-case",
                query="你好",
                session_context={},
            ),
        ]

        def baseline_executor(case: HarnessCase):
            state = self._build_state(case) if case.case_id == "phase3-replay-case" else self._build_simple_state(case)
            snapshot = recorder.record(state, case_id=case.case_id)
            return {
                "case_id": case.case_id,
                "passed": True,
                "actual_trace": snapshot,
                "actual_response_mode": "unknown",
                "actual_answer": "",
                "failures": [],
            }

        def candidate_executor(case: HarnessCase):
            state = self._build_state(case) if case.case_id == "phase3-replay-case" else self._build_simple_state(case)
            if case.case_id == "phase3-replay-case":
                state = ensure_task_plan(state)
            snapshot = recorder.record(state, case_id=case.case_id)
            return {
                "case_id": case.case_id,
                "passed": True,
                "actual_trace": snapshot,
                "actual_response_mode": "unknown",
                "actual_answer": "",
                "failures": [],
            }

        comparisons = replay.compare_many(cases, baseline_executor, candidate_executor)
        report = evaluation.summarize_comparisons(comparisons)

        self.assertEqual(report.total_cases, 2)
        self.assertEqual(report.changed_cases, 1)
        self.assertEqual(report.unchanged_cases, 1)
        self.assertEqual(report.changed_field_counts.get("phase3_trace"), 1)
        self.assertEqual(report.case_status_counts.get("changed"), 1)
        self.assertEqual(report.case_status_counts.get("unchanged"), 1)
        self.assertEqual(len([item for item in comparisons if item.passed]), 1)


if __name__ == "__main__":
    unittest.main()
