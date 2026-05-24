from __future__ import annotations

import importlib
import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.builder import LANGGRAPH_AVAILABLE, create_workflow_runner
from learning_agent_service.domain import ChatTurnCommand, PlanStep, build_initial_state
from learning_agent_service.domain.enums import IntentType


class PlanExecutionRuntimeTestCase(unittest.TestCase):
    def _load_runtime_stack(self):
        try:
            dependencies_module = importlib.import_module("learning_agent_service.application.dependencies")
            service_module = importlib.import_module("learning_agent_service.application.service")
        except Exception as exc:
            self.skipTest("application runtime modules are not available in this slice: {error}".format(error=exc))

        dependencies = dependencies_module.build_dependencies()
        service = service_module.create_learning_agent_service(dependencies.container)
        return {
            "dependencies": dependencies,
            "service": service,
        }

    def _build_state(self, *, message: str = "推荐一家适合带爸妈吃饭的餐厅"):
        return build_initial_state(
            ChatTurnCommand(
                trace_id="trace-plan",
                session_id="session-plan",
                turn_id="turn-plan",
                user_id="user-plan",
                message=message,
            )
        )

    def test_plan_execute_success_emits_plan_events_and_final_summary(self) -> None:
        runtime = self._load_runtime_stack()
        state = self._build_state(message="推荐一家适合带爸妈吃饭的餐厅")
        state["turn"] = state["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "intent": IntentType.RECOMMEND,
                "slots": {"scene": "family_dinner", "preferences": ["quiet", "elder_friendly"]},
            }
        )

        result = runtime["service"].chat_use_case._workflow_runner.run_state(state)
        event_types = [event.event_type for event in result["runtime"].emitted_events]

        self.assertIn("plan_execution_started", event_types)
        self.assertIn("plan_step_result", event_types)
        self.assertIn("plan_execution_summary", event_types)
        self.assertIsNotNone(result["turn"].final_task_summary)
        self.assertEqual(result["turn"].final_task_summary.status, "completed")
        self.assertIn("Plan execution", result["turn"].final_answer or "")

    def test_plan_execute_requires_approval_emits_approval_event(self) -> None:
        runtime = self._load_runtime_stack()
        state = self._build_state(message="推荐一家适合带爸妈吃饭的餐厅")
        state["turn"] = state["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "intent": IntentType.RECOMMEND,
                "plan": [
                    PlanStep(
                        step_id="approval-step",
                        goal="创建订座请求",
                        allowed_tools=["create_booking"],
                        risk_level="low",
                    )
                ],
                "slots": {"shop_name": "某某家常菜"},
            }
        )

        result = runtime["service"].chat_use_case._workflow_runner.run_state(state)
        event_types = [event.event_type for event in result["runtime"].emitted_events]

        self.assertIn("approval_required", event_types)
        self.assertIn("plan_step_result", event_types)
        self.assertEqual(result["turn"].final_task_summary.status, "need_approval")
        self.assertTrue(result["turn"].need_human_approval)

    def test_plan_execute_replans_when_initial_plan_is_invalid(self) -> None:
        runtime = self._load_runtime_stack()
        state = self._build_state(message="推荐一家适合带爸妈吃饭的餐厅")
        state["turn"] = state["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "intent": IntentType.RECOMMEND,
                "plan": [
                    PlanStep(
                        step_id="broken-step",
                        goal="没有可用工具的步骤",
                        allowed_tools=[],
                        risk_level="low",
                    )
                ],
                "slots": {"topic": "Spring AOP"},
            }
        )

        result = runtime["service"].chat_use_case._workflow_runner.run_state(state)
        event_types = [event.event_type for event in result["runtime"].emitted_events]

        self.assertIn("plan_replanned", event_types)
        self.assertIsNotNone(result["turn"].final_task_summary)
        self.assertGreaterEqual(len(result["turn"].step_results), 1)

    def test_fallback_runner_matches_langgraph_when_available(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        runtime = self._load_runtime_stack()
        services = runtime["service"].chat_use_case._build_workflow_services()
        langgraph_runner = create_workflow_runner(services, prefer_langgraph=True)
        fallback_runner = create_workflow_runner(services, prefer_langgraph=False)

        state_a = self._build_state(message="推荐一家适合带爸妈吃饭的餐厅")
        state_a["turn"] = state_a["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "intent": IntentType.RECOMMEND,
                "slots": {"scene": "family_dinner"},
            }
        )
        state_b = self._build_state(message="推荐一家适合带爸妈吃饭的餐厅")
        state_b["turn"] = state_b["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "intent": IntentType.RECOMMEND,
                "slots": {"scene": "family_dinner"},
            }
        )

        langgraph_state = langgraph_runner.run_state(state_a)
        fallback_state = fallback_runner.run_state(state_b)

        langgraph_events = [event.event_type for event in langgraph_state["runtime"].emitted_events]
        fallback_events = [event.event_type for event in fallback_state["runtime"].emitted_events]

        self.assertEqual(langgraph_events, fallback_events)
        self.assertEqual(
            langgraph_state["turn"].final_task_summary.status,
            fallback_state["turn"].final_task_summary.status,
        )


if __name__ == "__main__":
    unittest.main()
