from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router import build_initial_routing_decision, routing_trace_payload
from learning_agent_service.application.workflow.subgraphs import route_gate
from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, RoutingDecision, IntentRoutingDecision, build_initial_state


class P15Day3RouterDegradationTestCase(unittest.TestCase):
    def _build_state(self, message: str) -> dict:
        command = ChatTurnCommand(
            trace_id="trace-p15-day3",
            session_id="session-p15-day3",
            turn_id="turn-p15-day3",
            user_id="user-p15-day3",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=PersistentSessionContext())

    def test_execution_mode_is_classified_for_clarify(self) -> None:
        routing = build_initial_routing_decision("有券吗？", PersistentSessionContext())
        self.assertEqual(routing.required_action, "clarify")
        self.assertEqual(routing.execution_mode, "clarify")

        trace = routing_trace_payload(routing)
        self.assertEqual(trace["execution_mode"], "clarify")
        self.assertEqual(trace["required_action"], "clarify")

    def test_execution_mode_is_simple_for_direct_chat(self) -> None:
        routing = build_initial_routing_decision("谢谢", PersistentSessionContext())
        self.assertEqual(routing.required_action, "direct_answer")
        self.assertEqual(routing.execution_mode, "simple")
        self.assertEqual(routing.route_candidate, "thanks")
        trace = routing_trace_payload(routing)
        self.assertEqual(trace["execution_mode"], "simple")

    def test_simple_execution_mode_can_route_directly_to_tool_subgraph(self) -> None:
        state = self._build_state("查一下有没有券")
        routing = RoutingDecision(
            required_action="tool_call",
            should_call_tool=True,
            route_candidate="knowledge",
            intent=IntentRoutingDecision(name="tool_lookup", confidence=0.9),
            execution_mode="simple",
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})

        command = route_gate(state)

        self.assertEqual(command.goto, "tool_subgraph")
        updated_state = command.update
        gate_trace = updated_state["turn"].extra.get("route_gate") or {}
        self.assertEqual(gate_trace.get("execution_mode"), "simple")
        self.assertEqual(updated_state["turn"].extra.get("execution_mode"), "simple")
        self.assertEqual(updated_state["runtime"].metrics.get("execution_mode"), "simple")
        self.assertEqual(updated_state["turn"].routing_decision.execution_mode, "simple")
        self.assertEqual(updated_state["turn"].routing_decision.required_action, "tool_call")

    def test_complex_execution_mode_routes_to_plan_execute_subgraph(self) -> None:
        state = self._build_state("一份需要多步处理的复杂请求")
        routing = RoutingDecision(
            required_action="rag_plus_tool",
            should_retrieve=True,
            should_call_tool=True,
            route_candidate="local_life.combo",
            intent=IntentRoutingDecision(name="local_life_recommend", confidence=0.95),
            execution_mode="complex",
            extra={
                "required_facets": [
                    {"name": "scene_fit"},
                    {"name": "open_status"},
                    {"name": "coupon"},
                ],
                "recommendation_mode": True,
            },
        )
        state["turn"] = state["turn"].model_copy(update={"routing_decision": routing, "extra": {}})

        command = route_gate(state)

        self.assertEqual(command.goto, "plan_execute_subgraph")
        updated_state = command.update
        gate_trace = updated_state["turn"].extra.get("route_gate") or {}
        self.assertEqual(gate_trace.get("execution_mode"), "complex")
        self.assertEqual(gate_trace.get("branch"), "complex")
        self.assertEqual(updated_state["runtime"].metrics.get("execution_mode"), "complex")
        self.assertEqual(updated_state["turn"].routing_decision.execution_mode, "complex")


if __name__ == "__main__":
    unittest.main()
