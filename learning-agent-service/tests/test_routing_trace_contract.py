from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.router.trace import (
    StageTrace,
    build_routing_trace,
    build_routing_trace_from_state,
    routing_trace_to_dict,
)
from learning_agent_service.domain import IntentRoutingDecision, RoutingDecision


class RoutingTraceContractTestCase(unittest.TestCase):
    def test_build_routing_trace_collects_stage_snapshots(self) -> None:
        trace = build_routing_trace(
            query="附近有什么推荐",
            session_id="session-1",
            turn_id="turn-1",
            trace_id="trace-1",
            stages={
                "phase0_trace": {"input": {"query": "附近有什么推荐"}, "output": {"harness_mode": "off"}},
                "phase5_trace": StageTrace(output={"runner_kind": "langgraph"}, duration_ms=12.5),
            },
            final_decision={"required_action": "clarify", "execution_mode": "clarify"},
        )
        payload = routing_trace_to_dict(trace)

        self.assertEqual(trace.query, "附近有什么推荐")
        self.assertEqual(trace.session_id, "session-1")
        self.assertEqual(trace.turn_id, "turn-1")
        self.assertEqual(trace.trace_id, "trace-1")
        self.assertEqual(payload["execution_mode"], "clarify")
        self.assertEqual(payload["stages"]["phase0_trace"]["output"], {"harness_mode": "off"})
        self.assertEqual(payload["stages"]["phase5_trace"]["output"], {"runner_kind": "langgraph"})
        self.assertEqual(payload["final_decision"]["required_action"], "clarify")

    def test_build_routing_trace_from_state_uses_turn_and_runtime(self) -> None:
        routing = RoutingDecision(
            required_action="rag_retrieval",
            should_retrieve=True,
            should_call_tool=False,
            route_candidate="local_life.recommend",
            intent=IntentRoutingDecision(name="local_life_recommend", confidence=0.88),
            execution_mode="standard",
        )
        state = SimpleNamespace(
            turn=SimpleNamespace(
                raw_query="附近有什么推荐",
                extra={
                    "phase0_trace": {"harness_mode": "off"},
                    "phase3_trace": {"task_plan_status": "synthesized"},
                },
                routing_decision=routing,
            ),
            runtime=SimpleNamespace(
                trace_id="trace-2",
                session_id="session-2",
                turn_id="turn-2",
                metrics={"phase5_trace": {"runner_kind": "sequential"}},
            ),
        )

        trace = build_routing_trace_from_state(state)
        payload = routing_trace_to_dict(trace)

        self.assertEqual(payload["query"], "附近有什么推荐")
        self.assertEqual(payload["trace_id"], "trace-2")
        self.assertEqual(payload["execution_mode"], "standard")
        self.assertEqual(payload["stages"]["phase0_trace"]["output"]["harness_mode"], "off")
        self.assertEqual(payload["stages"]["phase3_trace"]["output"]["task_plan_status"], "synthesized")
        self.assertEqual(payload["stages"]["phase5_trace"]["output"]["runner_kind"], "sequential")
        self.assertEqual(payload["final_decision"]["required_action"], "rag_retrieval")


if __name__ == "__main__":
    unittest.main()
