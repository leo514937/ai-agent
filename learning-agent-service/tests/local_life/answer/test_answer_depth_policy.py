from __future__ import annotations

import sys
import unittest
from pathlib import Path

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.answer_depth_policy import derive_answer_depth_policy
from learning_agent_service.local_life.answer_planner import build_answer_planner_request


class AnswerDepthPolicyTestCase(unittest.TestCase):
    def _contract(self, answer_style: str) -> AnswerContract:
        return AnswerContract(
            original_query="测试问题",
            allowed_facets=["environment", "recommendation"],
            forbidden_facets=[],
            allowed_tools=[],
            allowed_rag_facets=["environment", "recommendation"],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=answer_style == "multi_shop_recommendation",
            allow_extra_context=answer_style != "coupon_only",
            realtime_required=False,
            evidence_policy="balanced",
            answer_style=answer_style,
        )

    def test_single_shop_review_uses_normal_depth_when_evidence_is_clean(self) -> None:
        policy = derive_answer_depth_policy(
            self._contract("single_shop_review"),
            clean_evidence_count=3,
            strong_evidence_count=2,
            medium_evidence_count=1,
        )

        self.assertEqual(policy.depth_level, "normal")
        self.assertGreaterEqual(policy.min_sections, 4)
        self.assertTrue(policy.require_summary)
        self.assertTrue(policy.require_evidence_reasoning)
        self.assertTrue(policy.require_risk_or_caveat)
        self.assertTrue(policy.require_next_step)

    def test_coupon_only_stays_short_even_with_more_evidence(self) -> None:
        policy = derive_answer_depth_policy(
            self._contract("coupon_only"),
            clean_evidence_count=4,
            strong_evidence_count=2,
            medium_evidence_count=1,
        )

        self.assertEqual(policy.depth_level, "short")
        self.assertLessEqual(policy.max_sections, 2)
        self.assertFalse(policy.require_evidence_reasoning)
        self.assertFalse(policy.require_risk_or_caveat)

    def test_answer_planner_prompt_contains_depth_policy_and_structure_requirements(self) -> None:
        request = build_answer_planner_request(
            raw_query="海底捞水晶城店怎么样？",
            slots={},
            ranked_candidates=[],
            evidence_pack=None,
            safety_result={},
            answer_contract=self._contract("single_shop_review"),
        )

        self.assertIn("answer_depth_policy", request)
        self.assertIn("answer_structure_requirements", request["instructions"])
        self.assertEqual(request["answer_depth_policy"]["answer_style"], "single_shop_review")
        self.assertIn("总体结论", request["answer_structure_requirements"]["single_shop_review"]["sections"])


if __name__ == "__main__":
    unittest.main()
