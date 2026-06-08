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
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety


class FinalAnswerSafetyTestCase(unittest.TestCase):
    def test_apply_final_answer_safety_sanitizes_and_flags_forbidden_facet(self) -> None:
        contract = AnswerContract(
            original_query="这家店环境怎么样",
            allowed_facets=["coupon"],
            forbidden_facets=["environment"],
            allowed_tools=[],
            allowed_rag_facets=["coupon"],
            forbidden_rag_facets=["environment"],
            realtime_facets=["coupon"],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=False,
            evidence_policy="strict",
            answer_style="single_shop_review",
        )

        result = apply_final_answer_safety(
            answer_text="这家店环境不错 [chunk-1]",
            answer_contract=contract,
            ranked_candidates=[{"shop_id": 1, "name": "测试店"}],
            evidence_claims=[{"chunk_id": "c-1", "shop_id": 1, "claim": "环境不错"}],
            evidence_pack={"items": [{"chunk_id": "c-1"}]},
            route_gate={"branch": "rag"},
            source_contract={"forbidden_facets": ["environment"]},
            review_report={"decision": "repair_answer"},
            tool_results=[],
            shop_lookup={1: "测试店"},
        )

        self.assertTrue(result.sanitized)
        self.assertFalse(result.passed)
        self.assertEqual(result.severity, "warn")
        self.assertNotIn("[chunk-1]", result.answer_text)
        self.assertIn("forbidden_facet:environment", result.issues)
        self.assertEqual(result.final_answer_audit["severity"], "warn")
        self.assertEqual(result.answer_lint["severity"], "warn")


if __name__ == "__main__":
    unittest.main()
