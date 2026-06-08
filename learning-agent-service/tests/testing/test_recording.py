from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.testing import EvalCaseRecorder, EvaluationHarness, HarnessRunResult, TraceWriter


@dataclass
class _Case:
    case_id: str
    query: str


class RecordingTestCase(unittest.TestCase):
    def test_eval_case_recorder_writes_trace_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "traces.jsonl"
            recorder = EvalCaseRecorder(trace_writer=TraceWriter(trace_path))
            result = HarnessRunResult(
                case_id="case-1",
                passed=False,
                actual_trace={
                    "final_answer_safety": {"severity": "warn", "issues": ["forbidden_facet:environment"]},
                    "final_answer_audit": {"severity": "warn", "issues": ["forbidden_facet:environment"]},
                },
                actual_response_mode="rag",
                actual_answer="这家店环境不错",
                failures=["forbidden_facet:environment"],
            )

            record = recorder.record_case("case-1", result, case=_Case(case_id="case-1", query="这家店环境怎么样"))

            self.assertTrue(trace_path.exists())
            self.assertEqual(record["case_id"], "case-1")
            self.assertEqual(record["final_answer_safety"]["severity"], "warn")
            self.assertEqual(record["final_answer_audit"]["severity"], "warn")
            payload = json.loads(trace_path.read_text(encoding="utf-8").strip())
            self.assertEqual(payload["case_id"], "case-1")
            self.assertEqual(payload["final_answer_safety"]["severity"], "warn")

    def test_evaluation_harness_summarize_counts_final_answer_safety(self) -> None:
        report = EvaluationHarness().summarize(
            [
                HarnessRunResult(
                    case_id="case-1",
                    passed=True,
                    actual_trace={
                        "final_answer_safety": {"severity": "warn"},
                        "final_answer_audit": {"severity": "block"},
                        "phase0_trace": {"final_response_mode": "rag", "response_origin": "model", "initial_routing_decision": "rag", "evidence_quality": "good"},
                        "phase5_trace": {"runner_kind": "langgraph", "graph_runtime": "langgraph"},
                    },
                    actual_response_mode="rag",
                    actual_answer="ok",
                    failures=[],
                )
            ]
        )

        self.assertEqual(report.metric_summary["final_answer_safety_severity_distribution"], {"warn": 1})
        self.assertEqual(report.metric_summary["final_answer_audit_severity_distribution"], {"block": 1})


if __name__ == "__main__":
    unittest.main()
