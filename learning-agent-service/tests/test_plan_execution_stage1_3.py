from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.builder import route_after_understand
from learning_agent_service.domain import ChatTurnCommand, PlanExecutionSummary, PlanStep, StepResult, build_initial_state


class PlanExecutionStageTestCase(unittest.TestCase):
    def _build_state(self):
        return build_initial_state(
            ChatTurnCommand(
                trace_id="trace-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                message="Please help me with a complex task.",
            )
        )

    def test_new_plan_models_can_serialize(self) -> None:
        step = PlanStep(
            step_id="step-1",
            goal="analyze need",
            expected_output="one short summary",
            allowed_tools=["search_restaurants"],
            risk_level="medium",
            requires_approval=True,
        )
        result = StepResult(
            step_id="step-1",
            status="need_approval",
            tools_used=["search_restaurants"],
            observations=["manual approval required"],
            result={"summary": "pending"},
            error=None,
            next_action="wait_for_approval",
        )
        summary = PlanExecutionSummary(
            status="need_approval",
            completed_steps=0,
            total_steps=1,
            key_findings=["manual approval required"],
            final_decision="wait_for_approval",
        )

        self.assertEqual(step.model_dump(mode="json")["goal"], "analyze need")
        self.assertEqual(result.model_dump(mode="json")["status"], "need_approval")
        self.assertEqual(summary.model_dump(mode="json")["total_steps"], 1)

    def test_initial_state_exposes_plan_execution_defaults(self) -> None:
        state = self._build_state()
        turn = state["turn"]

        self.assertEqual(turn.task_complexity, "simple")
        self.assertEqual(turn.execution_mode, "auto")
        self.assertEqual(turn.risk_level, "low")
        self.assertEqual(turn.plan, [])
        self.assertEqual(turn.step_results, [])
        self.assertFalse(turn.need_human_approval)
        self.assertEqual(turn.approval_request, {})
        self.assertIsNone(turn.final_task_summary)

    def test_route_after_understand_routes_complex_task_to_route_gate(self) -> None:
        state = self._build_state()
        state["turn"] = state["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "need_human_approval": True,
            }
        )

        self.assertEqual(route_after_understand(state), "route_gate")


if __name__ == "__main__":
    unittest.main()
