from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

try:
    from learning_agent_service.application.workflow.builder import LANGGRAPH_AVAILABLE, create_workflow_runner
except Exception:  # pragma: no cover - optional dependency or import error
    LANGGRAPH_AVAILABLE = False
    create_workflow_runner = None  # type: ignore[assignment]

from learning_agent_service.application.workflow.services import WorkflowServices
from learning_agent_service.application.workflow.subgraphs import route_after_understand
from learning_agent_service.domain import (
    ChatTurnCommand,
    PersistentSessionContext,
    RoutingDecision,
    build_initial_state,
)
from learning_agent_service.testing.harness import (
    EvaluationHarness,
    HarnessCase,
    HarnessRunResult,
    ReplayHarness,
    TraceHarnessRecorder,
)


class Phase5RunnerCompareTestCase(unittest.TestCase):
    def _build_services(self) -> WorkflowServices:
        def load_context(state):
            state["turn"] = state["turn"].model_copy(
                update={
                    "routing_decision": RoutingDecision(
                        required_action="direct_answer",
                        should_retrieve=False,
                        should_call_tool=False,
                        route_reason="phase5_direct_answer",
                    ),
                    "extra": dict(state["turn"].extra),
                }
            )
            return state

        def compose_answer(state):
            state["turn"] = state["turn"].model_copy(
                update={
                    "final_answer": "phase5 answer",
                    "extra": dict(state["turn"].extra),
                }
            )
            return state

        def persist_session(state):
            state["runtime"] = state["runtime"].model_copy(update={"extra": dict(state["runtime"].extra)})
            return state

        def emit_final(state):
            state["runtime"] = state["runtime"].model_copy(update={"extra": dict(state["runtime"].extra)})
            return state

        return WorkflowServices(
            load_context=load_context,
            compose_answer=compose_answer,
            persist_session=persist_session,
            emit_final=emit_final,
        )

    def _build_command(self) -> ChatTurnCommand:
        return ChatTurnCommand(
            trace_id="trace-phase5",
            session_id="session-phase5",
            turn_id="turn-phase5",
            user_id="user-phase5",
            message="给我一个简短回答",
            page="assistant",
            client_context={},
        )

    def _run_and_record(self, runner, case_id: str):
        state = runner.run(self._build_command(), persistent_context=PersistentSessionContext())
        recorded = TraceHarnessRecorder().record(state, case_id=case_id)
        return HarnessRunResult(
            case_id=case_id,
            passed=True,
            actual_trace=recorded,
            actual_response_mode=str(recorded.get("phase0_trace", {}).get("final_response_mode") or "direct_answer"),
            actual_answer=str(state["turn"].final_answer or ""),
            failures=[],
        )

    def test_runner_trace_records_runner_kind(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        services = self._build_services()
        sequential_runner = create_workflow_runner(services, prefer_langgraph=False, workflow_version="phase5/v1")

        result = self._run_and_record(sequential_runner, "sequential-case")

        self.assertEqual(result.actual_trace["phase5_trace"]["runner_kind"], "sequential")
        self.assertEqual(result.actual_trace["phase5_trace"]["runner_backend"], "sequential")
        self.assertTrue(result.actual_trace["phase5_trace"]["compare_ready"])

    def test_runner_compare_reports_path_difference(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        services = self._build_services()
        sequential_runner = create_workflow_runner(services, prefer_langgraph=False, workflow_version="phase5/v1")
        langgraph_runner = create_workflow_runner(services, prefer_langgraph=True, workflow_version="phase5/v1")
        case = HarnessCase(case_id="phase5-case", query="给我一个简短回答")

        replay = ReplayHarness()
        comparison = replay.compare_case(
            case,
            lambda _case: self._run_and_record(sequential_runner, "baseline"),
            lambda _case: self._run_and_record(langgraph_runner, "candidate"),
            comparison_fields=("phase5_trace", "phase0_trace", "phase3_trace", "phase4_trace", "actual_response_mode", "actual_answer"),
        )
        report = EvaluationHarness().summarize_comparisons([comparison])

        self.assertTrue(comparison.passed)
        self.assertIn("phase5_trace", comparison.differences)
        self.assertEqual(comparison.baseline.actual_trace["phase5_trace"]["runner_kind"], "sequential")
        self.assertEqual(comparison.candidate.actual_trace["phase5_trace"]["runner_kind"], "langgraph")
        self.assertEqual(report.changed_cases, 1)
        self.assertEqual(report.case_status_counts["changed"], 1)


if __name__ == "__main__":
    unittest.main()
