from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.subgraphs import route_gate
from learning_agent_service.domain import (
    ChatTurnCommand,
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
    build_initial_state,
)


class P15Day5ComplexPathConvergenceTestCase(unittest.TestCase):
    def _build_state(self, message: str = "璇峰府鎴戝仛涓€涓鏉備换鍔?") -> dict:
        command = ChatTurnCommand(
            trace_id="trace-p15-day5",
            session_id="session-p15-day5",
            turn_id="turn-p15-day5",
            user_id="user-p15-day5",
            message=message,
            page="assistant",
            client_context={},
        )
        return build_initial_state(command, persistent=PersistentSessionContext(current_city="鍖椾含"))

    def test_complex_route_gate_normalizes_execution_mode_for_direct_answer(self) -> None:
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

        self.assertEqual(command.goto, "compose_answer")
        self.assertEqual(updated_state["turn"].execution_mode, "auto")
        self.assertEqual(updated_state["turn"].task_complexity, "simple")


if __name__ == "__main__":
    unittest.main()
