from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from learning_agent_service.application.workflow.builder import _build_graph_config, write_langgraph_visualizations
from learning_agent_service.application.workflow.plan_execute import PlanExecutionPolicy, ReactStepExecutor
from learning_agent_service.domain.contracts import ChatTurnCommand, PlanStep
from learning_agent_service.domain.state import build_initial_state


class WorkflowLoopGuardVisualizationTests(unittest.TestCase):
    def _build_state(self):
        command = ChatTurnCommand(
            trace_id="trace-loop-guard",
            session_id="session-loop-guard",
            turn_id="turn-loop-guard",
            user_id="user-loop-guard",
            message="帮我看看这个计划",
        )
        state = build_initial_state(command=command, workflow_version="test/v1")
        state["turn"] = state["turn"].model_copy(
            update={
                "plan": [
                    PlanStep(
                        step_id="step-1",
                        goal="test",
                        expected_output="ok",
                        allowed_tools=[],
                        input_payload={},
                        risk_level="low",
                        requires_approval=False,
                    ),
                    PlanStep(
                        step_id="step-2",
                        goal="test-2",
                        expected_output="ok",
                        allowed_tools=[],
                        input_payload={},
                        risk_level="low",
                        requires_approval=False,
                    ),
                ]
            }
        )
        return state

    def test_graph_config_uses_runtime_recursion_limit(self) -> None:
        state = self._build_state()
        state["runtime_context"]["graph_recursion_limit"] = 7

        config = _build_graph_config(state)

        self.assertEqual(config["recursion_limit"], 7)
        self.assertEqual(config["configurable"]["thread_id"], "session-loop-guard")

    def test_plan_executor_marks_loop_guard_triggered(self) -> None:
        state = self._build_state()
        executor = ReactStepExecutor(
            container=object(),
            append_event=lambda current_state, *_args, **_kwargs: current_state,
            policy=PlanExecutionPolicy(max_steps=1),
        )

        updated = executor.step_executor(state)

        self.assertTrue(updated["runtime"].metrics.get("loop_guard_triggered"))
        self.assertEqual(updated["runtime"].metrics.get("loop_guard_reason"), "step_executor_max_steps")
        self.assertTrue(updated["turn"].need_replan)

    def test_write_langgraph_visualizations_writes_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            written = write_langgraph_visualizations(tmp_dir)
            self.assertIn("main_graph.mmd", written)
            self.assertIn("langgraph_topology.md", written)
            main_graph = Path(written["main_graph.mmd"]).read_text(encoding="utf-8")
            topology = Path(written["langgraph_topology.md"]).read_text(encoding="utf-8")
            self.assertIn("graph TD", main_graph)
            self.assertIn("# LangGraph Topology", topology)
            self.assertIn("rag_graph.mmd", written)
            self.assertIn("tool_graph.mmd", written)
            self.assertIn("recommendation_graph.mmd", written)


if __name__ == "__main__":
    unittest.main()
