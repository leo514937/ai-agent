from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

try:
    from learning_agent_service.application.workflow.builder import LANGGRAPH_AVAILABLE, create_workflow_runner
except Exception:  # pragma: no cover - optional dependency or import error
    LANGGRAPH_AVAILABLE = False
    create_workflow_runner = None  # type: ignore[assignment]

from learning_agent_service.application.workflow.services import WorkflowServices
from learning_agent_service.domain import (
    ChatTurnCommand,
    PersistentSessionContext,
    RoutingDecision,
    build_initial_state,
)
from learning_agent_service.testing.harness import (
    HarnessRunResult,
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
            message="缁欐垜涓€涓畝鐭洖绛?",
            page="assistant",
            client_context={},
        )

    def _run_and_record(self, runner, case_id: str):
        state = runner.run_state(
            build_initial_state(self._build_command(), persistent=PersistentSessionContext())
        )
        recorded = TraceHarnessRecorder().record(state, case_id=case_id)
        return HarnessRunResult(
            case_id=case_id,
            passed=True,
            actual_trace=recorded,
            actual_response_mode=str(recorded.get("phase0_trace", {}).get("final_response_mode") or "direct_answer"),
            actual_answer=str(state["turn"].final_answer or ""),
            failures=[],
        )

    def test_runner_trace_records_langgraph_runner_kind(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        services = self._build_services()
        runner = create_workflow_runner(services, prefer_langgraph=False, workflow_version="phase5/v1")

        result = self._run_and_record(runner, "langgraph-case")

        self.assertEqual(result.actual_trace["phase5_trace"]["runner_kind"], "langgraph")
        self.assertEqual(result.actual_trace["phase5_trace"]["runner_backend"], "langgraph")
        self.assertTrue(result.actual_trace["phase5_trace"]["compare_ready"])

    def test_runner_factory_ignores_legacy_preference_flag(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        services = self._build_services()
        baseline_runner = create_workflow_runner(services, prefer_langgraph=True, workflow_version="phase5/v1")
        langgraph_runner = create_workflow_runner(services, prefer_langgraph=True, workflow_version="phase5/v1")
        self.assertEqual(type(baseline_runner), type(langgraph_runner))
        self.assertEqual(baseline_runner.runner_kind, "langgraph")
        self.assertEqual(langgraph_runner.runner_kind, "langgraph")


if __name__ == "__main__":
    unittest.main()
