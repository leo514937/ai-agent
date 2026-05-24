from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.builder import route_after_understand
from learning_agent_service.application.workflow.services import PlanExecuteSubgraphServices
from learning_agent_service.application.workflow.subgraphs import run_plan_execute_subgraph
from learning_agent_service.domain import (
    ChatTurnCommand,
    PlanExecutionSummary,
    PlanStep,
    StepResult,
    build_initial_state,
)


class PlanExecutionStageTestCase(unittest.TestCase):
    def _build_state(self):
        return build_initial_state(
            ChatTurnCommand(
                trace_id="trace-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                message="请帮我做一个复杂任务",
            )
        )

    def test_new_plan_models_can_serialize(self) -> None:
        step = PlanStep(
            step_id="step-1",
            goal="分析需求",
            expected_output="输出一段摘要",
            allowed_tools=["search_restaurants"],
            risk_level="medium",
            requires_approval=True,
        )
        result = StepResult(
            step_id="step-1",
            status="need_approval",
            tools_used=["search_restaurants"],
            observations=["需要人工确认"],
            result={"summary": "pending"},
            error=None,
            next_action="等待审批",
        )
        summary = PlanExecutionSummary(
            status="need_approval",
            completed_steps=0,
            total_steps=1,
            key_findings=["需要人工确认"],
            final_decision="等待审批",
        )

        self.assertEqual(step.model_dump(mode="json")["goal"], "分析需求")
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

    def test_route_after_understand_prefers_plan_execute_for_complex_task(self) -> None:
        state = self._build_state()
        state["turn"] = state["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "plan": [
                    PlanStep(
                        step_id="step-1",
                        goal="先整理复杂任务的拆解",
                        requires_approval=True,
                    )
                ],
                "need_human_approval": True,
            }
        )

        self.assertEqual(route_after_understand(state), "plan_execute_subgraph")

        updated = run_plan_execute_subgraph(state, PlanExecuteSubgraphServices())
        self.assertIsNotNone(updated["turn"].current_step)
        self.assertEqual(updated["turn"].current_step.step_id, "step-1")
        self.assertIsNotNone(updated["turn"].final_task_summary)
        self.assertEqual(updated["turn"].final_task_summary.status, "need_approval")


if __name__ == "__main__":
    unittest.main()
