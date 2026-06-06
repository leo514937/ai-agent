from __future__ import annotations

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

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.final_answer_audit import audit_final_answer
from learning_agent_service.testing.harness import TraceHarnessRecorder


class FinalAnswerAuditTestCase(unittest.TestCase):
    def test_audit_detects_forbidden_facet_and_tool_failure(self) -> None:
        contract = AnswerContract(
            original_query="这家店有券吗",
            allowed_facets=["coupon"],
            forbidden_facets=["environment", "recommendation"],
            allowed_tools=["get_coupon_list"],
            allowed_rag_facets=["coupon"],
            forbidden_rag_facets=["environment", "recommendation"],
            realtime_facets=["coupon"],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=True,
            evidence_policy="strict",
            answer_style="coupon_only",
        )

        audit = audit_final_answer(
            answer_text="这家店环境不错，而且推荐你去看看。",
            answer_contract=contract,
            ranked_candidates=[{"shop_id": 5, "name": "海底捞水晶城店"}],
            evidence_claims=[{"chunk_id": "e-1", "shop_id": 5, "claim": "环境不错", "metadata": {"shop_id": 5}}],
            evidence_pack={"items": [{"chunk_id": "e-1"}]},
            route_gate={"branch": "rag"},
            source_contract={"forbidden_facets": ["environment"]},
            review_report={"decision": "repair_answer"},
            tool_results=[{"failure_category": "timeout"}],
        )

        self.assertFalse(audit.passed)
        self.assertIn("forbidden_facet:environment", audit.issues)
        self.assertIn("tool_failure_observed", audit.issues)
        self.assertEqual(audit.tool_failure_categories, ["timeout"])
        self.assertEqual(audit.evidence_pack_item_count, 1)

    def test_trace_harness_records_final_answer_audit(self) -> None:
        recorder = TraceHarnessRecorder()
        recorded = recorder.record(
            {
                "turn": {"extra": {"final_answer_audit": {"passed": True, "severity": "pass"}}},
                "runtime": {"metrics": {}},
                "persistent": {},
            },
            case_id="audit-case",
        )
        self.assertIn("final_answer_audit", recorded)
        self.assertEqual(recorded["final_answer_audit"]["severity"], "pass")


if __name__ == "__main__":
    unittest.main()
