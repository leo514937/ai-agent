from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters.helpers import apply_fast_decision_to_routing
from learning_agent_service.application.workflow.adapters.helpers import build_initial_routing_decision
from learning_agent_service.application.workflow.adapters.helpers import routing_trace_payload
from learning_agent_service.application.workflow.adapters.helpers import route_execution_mode
from learning_agent_service.application.routing_policy_validator import RoutingPolicyValidator
from learning_agent_service.application.workflow.subgraphs import route_gate
from learning_agent_service.domain import ChatTurnCommand, FastDecision, IntentRoutingDecision, IntentType, PersistentSessionContext, RoutingDecision, build_initial_state


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

    def test_tool_call_execution_mode_prefers_standard(self) -> None:
        routing = RoutingDecision(
            required_action="tool_call",
            should_call_tool=True,
            route_candidate="local_life.realtime",
            intent=IntentRoutingDecision(name="local_life", confidence=0.9),
        )

        complexity = route_execution_mode(routing)

        self.assertEqual(complexity.execution_mode, "standard")
        self.assertEqual(complexity.reason, "evidence_capable_route")

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
        self.assertEqual(gate_trace.get("execution_mode"), "standard")
        self.assertEqual(updated_state["turn"].extra.get("execution_mode"), "standard")
        self.assertEqual(updated_state["runtime"].metrics.get("execution_mode"), "standard")
        self.assertEqual(updated_state["turn"].routing_decision.execution_mode, "simple")
        self.assertEqual(updated_state["turn"].routing_decision.required_action, "tool_call")

    def test_complex_execution_mode_routes_to_direct_answer(self) -> None:
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

        self.assertEqual(command.goto, "compose_answer")
        updated_state = command.update
        gate_trace = updated_state["turn"].extra.get("route_gate") or {}
        self.assertEqual(gate_trace.get("execution_mode"), "complex")
        self.assertEqual(gate_trace.get("branch"), "direct")
        self.assertEqual(updated_state["runtime"].metrics.get("execution_mode"), "complex")
        self.assertEqual(updated_state["turn"].routing_decision.execution_mode, "complex")

    def test_fast_decision_promotes_top_level_intent_and_tool_path(self) -> None:
        routing = RoutingDecision(
            required_action="rag_retrieval",
            should_retrieve=True,
            should_call_tool=False,
            route_candidate="query",
            intent=IntentRoutingDecision(name="query", confidence=0.2),
        )
        decision = FastDecision(
            intent=IntentType.RECOMMEND,
            needs_rag=True,
            needs_tool=True,
            needs_clarify=False,
            confidence=0.91,
            extra={
                "route_candidate": "recommendation",
                "top_level_intent": {
                    "intent": "recommendation",
                    "confidence": 0.91,
                    "reason": "llm_recommendation",
                    "source": "llm",
                },
            },
        )

        updated = apply_fast_decision_to_routing(routing, decision)

        self.assertEqual(updated.required_action, "recommendation")
        self.assertEqual(updated.capability_line, "recommendation_tool")
        self.assertEqual(updated.intent.name, "recommendation")
        self.assertEqual(updated.route_candidate, "recommendation")
        self.assertEqual(updated.extra.get("top_level_intent", {}).get("intent"), "recommendation")
        self.assertEqual(updated.extra.get("route_candidate"), "recommendation")

    def test_routing_policy_validator_keeps_tool_path_without_facet_plan(self) -> None:
        routing = RoutingDecision(
            required_action="tool_call",
            should_call_tool=True,
            capability_line="single_shop_tool",
            intent=IntentRoutingDecision(name="local_life", confidence=0.9),
        )

        validated = RoutingPolicyValidator().validate(routing)

        self.assertTrue(validated.should_call_tool)
        self.assertEqual(validated.capability_line, "single_shop_tool")

    def test_routing_policy_validator_downgrades_unknown_route(self) -> None:
        routing = RoutingDecision(
            required_action="mystery_action",
            should_call_tool=True,
            capability_line="single_shop_tool",
            route_candidate="mystery_route",
            intent=IntentRoutingDecision(name="unknown", confidence=0.1),
        )

        validated = RoutingPolicyValidator().validate(routing)

        self.assertFalse(validated.should_call_tool)
        self.assertEqual(validated.capability_line, "direct")
        self.assertEqual(validated.extra.get("unsupported_route_candidate"), "mystery_route")


if __name__ == "__main__":
    unittest.main()
