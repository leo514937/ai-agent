from __future__ import annotations

from types import SimpleNamespace
import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.plan_execute import ReactStepExecutor
from learning_agent_service.application.workflow.services import PlanExecuteSubgraphServices
from learning_agent_service.application.workflow.state import append_runtime_event
from learning_agent_service.application.workflow.subgraphs import route_gate, run_plan_execute_subgraph
from learning_agent_service.domain import (
    ChatTurnCommand,
    IntentRoutingDecision,
    PersistentSessionContext,
    PlanStep,
    RoutingDecision,
    build_initial_state,
)


class P15Day5ComplexPathConvergenceTestCase(unittest.TestCase):
    def _build_state(self, message: str = "请帮我做一个复杂任务") -> dict:
        command = ChatTurnCommand(
            trace_id="trace-p15-day5",
            session_id="session-p15-day5",
            turn_id="turn-p15-day5",
            user_id="user-p15-day5",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=PersistentSessionContext(current_city="北京"))

    def _build_plan_services(self) -> PlanExecuteSubgraphServices:
        executor = ReactStepExecutor(
            container=SimpleNamespace(),
            append_event=append_runtime_event,
        )
        return PlanExecuteSubgraphServices(
            plan_planner=executor.plan_planner,
            plan_validator=executor.plan_validator,
            step_executor=executor.step_executor,
            progress_checker=executor.progress_checker,
            plan_reviewer=executor.plan_reviewer,
            human_approval_stub=executor.human_approval_stub,
            replanner=executor.replanner,
        )

    def test_complex_route_gate_normalizes_execution_mode_for_plan_execute(self) -> None:
        state = self._build_state()
        routing = RoutingDecision(
            required_action="rag_plus_tool",
            should_retrieve=True,
            should_call_tool=True,
            route_candidate="local_life.combo",
            intent=IntentRoutingDecision(name="local_life_recommend", confidence=0.96),
            execution_mode="complex",
            extra={
                "required_facets": [
                    {"name": "scene_fit", "data_source": "static_rag"},
                    {"name": "coupon", "data_source": "dynamic_tool"},
                ],
                "recommendation_mode": True,
            },
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})

        command = route_gate(state)
        updated_state = command.update

        self.assertEqual(command.goto, "plan_execute_subgraph")
        self.assertEqual(updated_state["turn"].execution_mode, "plan_execute")
        self.assertEqual(updated_state["turn"].task_complexity, "complex")

        services = self._build_plan_services()
        updated_state["turn"] = updated_state["turn"].model_copy(
            update={
                "plan": [
                    PlanStep(
                        step_id="check-1",
                        goal="整理复杂任务的基础上下文",
                        expected_output="可直接用于总结的结果",
                        risk_level="low",
                    )
                ],
                "task_complexity": "complex",
            }
        )

        result = run_plan_execute_subgraph(updated_state, services)
        event_types = [event.event_type for event in result["runtime"].emitted_events]

        self.assertIn("execute_plan_step", event_types)
        self.assertIn("collect_step_result", event_types)
        self.assertIn("all_steps_done", event_types)
        self.assertIn("complex_review", event_types)
        self.assertIn("plan_execution_summary", event_types)
        self.assertIsNotNone(result["turn"].final_task_summary)
        self.assertEqual(result["turn"].final_task_summary.status, "completed")
        self.assertEqual(result["turn"].execution_mode, "plan_execute")


if __name__ == "__main__":
    unittest.main()
