import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.builder import (
    LANGGRAPH_AVAILABLE,
    create_workflow_runner,
    describe_langgraph_topology,
    export_langgraph_mermaid,
)
from learning_agent_service.application.workflow.services import WorkflowServices
from learning_agent_service.testing.harness import EvaluationHarness, HarnessRunResult, TraceHarnessRecorder


class LangGraphSmokeTestCase(unittest.TestCase):
    def test_langgraph_topology_exports_expected_nodes_and_edges(self) -> None:
        topology = describe_langgraph_topology()
        self.assertIn("load_context", topology["nodes"])
        self.assertIn("emit_final", topology["nodes"])
        self.assertIn(("persist_session", "emit_final"), topology["edges"])
        mermaid = export_langgraph_mermaid()
        self.assertIn("graph TD", mermaid)
        self.assertIn("emit_final --> END", mermaid)

    def test_workflow_runner_selection_prefers_langgraph_by_default(self) -> None:
        runner = create_workflow_runner(WorkflowServices(), prefer_langgraph=True, workflow_version="smoke/v1")
        if LANGGRAPH_AVAILABLE:
            self.assertEqual(getattr(runner, "runner_kind", None), "langgraph")
        else:
            self.assertEqual(getattr(runner, "runner_kind", None), "sequential")

    def test_harness_records_graph_runtime_fields(self) -> None:
        recorder = TraceHarnessRecorder()
        state = {
            "turn": {
                "extra": {
                    "phase0_trace": {},
                    "phase5_trace": {
                        "runner_kind": "langgraph",
                        "runner_backend": "langgraph",
                        "graph_runtime": "langgraph",
                    },
                }
            },
            "runtime": {
                "trace_id": "trace-smoke",
                "session_id": "session-smoke",
                "turn_id": "turn-smoke",
                "metrics": {
                    "phase5_trace": {
                        "runner_kind": "langgraph",
                        "runner_backend": "langgraph",
                        "graph_runtime": "langgraph",
                        "graph_fallback": "none",
                    }
                },
            },
            "persistent": {
                "selected_shop_id": 5,
                "selected_shop_name": "海底捞火锅(水晶城购物中心店）",
                "extra": {},
            },
        }
        recorded = recorder.record(state, case_id="smoke-case")
        self.assertEqual(recorded["graph_runtime"], "langgraph")
        self.assertEqual(recorded["graph_fallback"], "none")
        self.assertEqual(recorded["phase5_trace"]["graph_runtime"], "langgraph")
        report = EvaluationHarness().summarize([
            HarnessRunResult(
                case_id="smoke-case",
                passed=True,
                actual_trace=recorded,
                actual_response_mode="direct_answer",
                actual_answer="ok",
                failures=[],
            )
        ])
        self.assertEqual(report.metric_summary["graph_runtime_distribution"]["langgraph"], 1)


if __name__ == "__main__":
    unittest.main()
