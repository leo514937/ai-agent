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

from chat_test_client import ChatStreamTestClient
from learning_agent_service.local_life.eval import load_golden_cases, run_golden_cases
from learning_agent_service.testing import HarnessRunResult


class Day7GoldenCasesChatTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()
        cls.cases = load_golden_cases(PROJECT_ROOT / "eval" / "local_life" / "golden_cases.jsonl")

    def _executor(self, case):
        turns = case.turns or (case.query,)
        last_result = None
        for turn in turns:
            last_result = self.client.post_message(
                message=turn,
                session_id=f"golden-{case.case_id}",
                extra_payload=dict(case.client_context or {}),
            )
        assert last_result is not None
        metrics = last_result.metrics or {}
        phase5_trace = metrics.get("phase5_trace") or {}
        return HarnessRunResult(
            case_id=case.case_id,
            passed=True,
            actual_trace={
                "phase5_trace": phase5_trace,
                "graph_runtime": metrics.get("graph_runtime") or phase5_trace.get("graph_runtime"),
                "graph_fallback": metrics.get("graph_fallback") or phase5_trace.get("graph_fallback") or "none",
                "route_gate": metrics.get("route_gate") or {},
                "metrics": metrics,
            },
            actual_response_mode=str(last_result.final_payload.get("mode") or metrics.get("final_response_mode") or "unknown"),
            actual_answer=last_result.final_answer,
            failures=[],
        )

    def test_golden_cases_cover_day1_to_day7(self) -> None:
        results = run_golden_cases(self.cases, self._executor)
        failures = [result for result in results if not result.passed]
        if failures:
            details = "\n".join(f"{item.case_id}: {item.failures}" for item in failures)
            self.fail(f"Golden cases failed:\n{details}")
        self.assertGreaterEqual(len(results), 7)
        self.assertTrue(all("routing_trace" in result.actual_trace for result in results))


if __name__ == "__main__":
    unittest.main()
