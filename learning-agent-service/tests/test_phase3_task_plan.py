from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router import ensure_task_plan
from learning_agent_service.application.workflow.subgraphs import route_after_understand
from learning_agent_service.domain import (
    ChatTurnCommand,
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
    build_initial_state,
)


class Phase3TaskPlanTestCase(unittest.TestCase):
    def _build_state(self, message: str, **persistent_kwargs):
        command = ChatTurnCommand(
            trace_id="trace-phase3",
            session_id="session-phase3",
            turn_id="turn-phase3",
            user_id="user-phase3",
            message=message,
            page="assistant",
            client_context={},
        )
        persistent = PersistentSessionContext(**persistent_kwargs)
        return build_initial_state(command, persistent=persistent)

    def test_complex_local_life_request_builds_task_plan_and_routes_to_plan_execute(self) -> None:
        state = self._build_state(
            "推荐一家适合约会、现在营业、最好有券的火锅店",
            current_city="北京",
            current_location={"area": "朝阳", "lat": 39.9, "lng": 116.4},
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
                    {"name": "recommendation_reason", "data_source": "static_rag"},
                    {"name": "open_status", "data_source": "dynamic_tool"},
                    {"name": "coupon", "data_source": "dynamic_tool"},
                ],
                "optional_facets": [
                    {"name": "location", "data_source": "slot"},
                ],
                "user_need": {
                    "intent": "local_life_recommend",
                    "slots": {
                        "city": "北京",
                        "area": "朝阳",
                        "scene": "约会",
                        "category": "火锅",
                    },
                },
            },
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})
        state = ensure_task_plan(state)
        task_plan = state["turn"].task_plan

        self.assertIsNotNone(task_plan)
        self.assertTrue(task_plan.enabled)
        self.assertEqual(task_plan.execution_mode, "plan_execute")
        self.assertEqual(task_plan.task_complexity, "complex")
        self.assertEqual(state["turn"].execution_mode, "plan_execute")
        self.assertEqual(route_after_understand(state), "plan_execute_subgraph")

        step_ids = [step.step_id for step in task_plan.steps]
        self.assertEqual(step_ids[0], "resolve_location")
        self.assertIn("search_restaurants", step_ids)
        self.assertIn("check_open_status", step_ids)
        self.assertIn("get_coupon_list", step_ids)
        self.assertIn("rank_candidates", step_ids)
        self.assertEqual(step_ids[-1], "compose_answer")

        phase3_trace = state["turn"].extra.get("phase3_trace")
        self.assertIsNotNone(phase3_trace)
        self.assertEqual(phase3_trace["task_plan_status"], "synthesized")
        self.assertTrue(phase3_trace["task_plan_enabled"])
        self.assertEqual(phase3_trace["task_plan_step_count"], len(task_plan.steps))
        self.assertEqual(phase3_trace["task_plan_step_ids"], step_ids)

        runtime_phase3_trace = state["runtime"].metrics.get("phase3_trace")
        self.assertIsNotNone(runtime_phase3_trace)
        self.assertEqual(runtime_phase3_trace["task_plan_status"], "synthesized")

    def test_simple_greeting_does_not_build_task_plan(self) -> None:
        state = self._build_state("你好")
        routing = RoutingDecision(
            required_action="direct_answer",
            should_retrieve=False,
            should_call_tool=False,
            route_candidate="greeting",
            intent=IntentRoutingDecision(name="chit_chat", confidence=0.99),
            extra={},
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})
        state = ensure_task_plan(state)

        self.assertIsNone(state["turn"].task_plan)
        self.assertNotEqual(state["turn"].execution_mode, "plan_execute")
        self.assertNotEqual(route_after_understand(state), "plan_execute_subgraph")

        phase3_trace = state["turn"].extra.get("phase3_trace")
        self.assertIsNotNone(phase3_trace)
        self.assertEqual(phase3_trace["task_plan_status"], "skipped")
        self.assertFalse(phase3_trace["task_plan_enabled"])
        self.assertEqual(phase3_trace["task_plan_step_count"], 0)


if __name__ == "__main__":
    unittest.main()
