from __future__ import annotations

import json
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

from learning_agent_service.testing.harness import EvaluationHarness, HarnessRunResult


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "grounding_cases.jsonl"


def _primary_source_type(claim_type: str, support_status: str) -> str:
    if support_status == "unsupported":
        return "llm_generated"
    if claim_type in {"environment", "service", "taste", "pitfall"}:
        return "rag_evidence"
    if claim_type in {"scene_fit", "recommendation", "comparison"}:
        return "rerank_reason" if support_status == "supported" else "tool_structured"
    if claim_type in {"booking", "order"}:
        return "template" if support_status == "supported" else "llm_generated"
    return "realtime_tool" if claim_type in {"coupon", "open_status", "distance_eta"} else "tool_structured"


class GroundingEvalTestCase(unittest.TestCase):
    def test_evaluation_harness_reports_grounding_metrics(self) -> None:
        records = [json.loads(line) for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(records), 12)

        results: list[HarnessRunResult] = []
        for record in records:
            claim_type = str(record["claim_type"])
            support_status = str(record["support_status"])
            claim_binding = {
                "claim_id": f"{record['case_id']}-claim-1",
                "claim_type": claim_type,
                "text": record["query"],
                "primary_source_type": _primary_source_type(claim_type, support_status),
                "source_ids": [f"{record['case_id']}-src-1"],
                "supporting_sources": [
                    {
                        "source_type": _primary_source_type(claim_type, support_status),
                        "source_id": f"{record['case_id']}-src-1",
                        "confidence": 0.9 if support_status == "supported" else 0.4,
                    }
                ],
                "support_status": support_status,
            }
            safety = {
                "answer_text": record["query"],
                "passed": support_status != "unsupported",
                "severity": record["severity"],
                "suggested_response_mode": record["final_response_mode"],
                "issues": [] if support_status != "unsupported" else ["unsupported_claim_observed"],
                "sanitized": bool(record["sanitized"]),
                "blocked": bool(record["blocked"]),
                "claim_bindings": [claim_binding],
                "claim_count": 1,
                "supported_claim_count": 1 if support_status == "supported" else 0,
                "partial_claim_count": 1 if support_status == "partial" else 0,
                "unsupported_claim_count": 1 if support_status == "unsupported" else 0,
                "conflicted_claim_count": 0,
            }
            audit = {
                "passed": support_status != "unsupported",
                "severity": record["severity"],
                "issues": [] if support_status != "unsupported" else ["unsupported_claim_observed"],
                "claim_bindings": [claim_binding],
                "claim_count": 1,
                "supported_claim_count": 1 if support_status == "supported" else 0,
                "partial_claim_count": 1 if support_status == "partial" else 0,
                "unsupported_claim_count": 1 if support_status == "unsupported" else 0,
                "conflicted_claim_count": 0,
            }
            actual_trace = {
                "phase0_trace": {
                    "final_response_mode": record["final_response_mode"],
                    "response_origin": record["route_origin"],
                },
                "phase5_trace": {
                    "runner_kind": "langgraph",
                    "graph_runtime": "langgraph",
                },
                "phase4_trace": {
                    "verifier_passed": support_status != "unsupported",
                    "suggested_response_mode": record["final_response_mode"],
                    "verifier_issues": [] if support_status != "unsupported" else ["unsupported_claim_observed"],
                },
                "final_answer_safety": safety,
                "final_answer_audit": audit,
                "claim_bindings": [claim_binding],
                "routing_trace": {"route_origin": record["route_origin"]},
            }
            results.append(
                HarnessRunResult(
                    case_id=record["case_id"],
                    passed=support_status != "unsupported",
                    actual_trace=actual_trace,
                    actual_response_mode=record["final_response_mode"],
                    actual_answer=record["query"],
                    failures=[] if support_status != "unsupported" else ["unsupported_claim"],
                )
            )

        report = EvaluationHarness().summarize(results)
        metrics = report.metric_summary

        self.assertEqual(report.total_cases, len(records))
        self.assertEqual(report.failed_cases, 3)
        self.assertIn("hallucination_rate", metrics)
        self.assertIn("unsupported_claim_rate", metrics)
        self.assertIn("repair_rate", metrics)
        self.assertIn("degrade_rate", metrics)
        self.assertIn("repair_degrade_ratio", metrics)
        self.assertIn("claim_coverage", metrics)
        self.assertIn("high_risk_subset", metrics)
        self.assertIn("claim_facet_distribution", metrics["claim_coverage"])
        self.assertIn("claim_risk_level_distribution", metrics["claim_coverage"])
        self.assertAlmostEqual(metrics["hallucination_rate"], 3 / 12, places=6)
        self.assertAlmostEqual(metrics["unsupported_claim_rate"], 3 / 12, places=6)
        self.assertAlmostEqual(metrics["repair_rate"], 4 / 12, places=6)
        self.assertAlmostEqual(metrics["degrade_rate"], 5 / 12, places=6)
        self.assertAlmostEqual(metrics["repair_degrade_ratio"], 4 / 5, places=6)
        self.assertEqual(metrics["claim_coverage"]["claim_count"], 12)
        self.assertEqual(metrics["claim_coverage"]["unsupported_claim_count"], 3)
        self.assertGreater(metrics["high_risk_subset"]["case_count"], 0)


if __name__ == "__main__":
    unittest.main()
