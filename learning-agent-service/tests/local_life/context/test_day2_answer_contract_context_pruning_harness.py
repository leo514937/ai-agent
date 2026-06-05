from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient


class Day2AnswerContractContextPruningHarnessTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def test_coupon_query_prunes_forbidden_context(self) -> None:
        session_id = f"day2-harness-coupon-{uuid4().hex[:8]}"

        result = self.client.post_message(
            message="海底捞水晶城店有券吗？",
            session_id=session_id,
        )

        self.assertTrue(result.final_answer)
        self.assertIn("券", result.final_answer)
        self.assertNotIn("环境", result.final_answer)
        self.assertNotIn("推荐", result.final_answer)
        self.assertIn("context_pruning", result.metrics)
        self.assertEqual(result.metrics.get("answer_lint", {}).get("passed"), True)
        self.assertEqual(result.metrics.get("answer_contract", {}).get("answer_style"), "coupon_only")
        self.assertIn("coupon", result.metrics.get("context_pruning", {}).get("kept_facets", []))
        self.assertIn("environment", result.metrics.get("context_pruning", {}).get("dropped_facets", []))

    def test_latest_turn_message_rebuilds_contract_after_recommendation(self) -> None:
        session_id = f"day2-harness-reco-{uuid4().hex[:8]}"

        self.client.post_message(
            message="附近有没有推荐的餐厅？",
            session_id=session_id,
            extra_payload={
                "city": "北京",
                "current_city": "北京",
                "location": {
                    "type": "near_user",
                    "city": "北京",
                    "lat": None,
                    "lng": None,
                    "radius_km": 3.0,
                },
            },
        )
        result = self.client.post_message(
            message="有券吗，现在营业吗，环境怎么样？",
            session_id=session_id,
        )

        self.assertTrue(result.final_answer)
        self.assertEqual(result.metrics.get("latest_turn_message"), "有券吗，现在营业吗，环境怎么样？")
        self.assertEqual(result.metrics.get("answer_contract", {}).get("answer_style"), "facet_multi")
        self.assertIn("coupon", result.metrics.get("answer_contract", {}).get("allowed_facets", []))
        self.assertIn("open_status", result.metrics.get("answer_contract", {}).get("allowed_facets", []))
        self.assertIn("environment", result.metrics.get("answer_contract", {}).get("allowed_facets", []))


if __name__ == "__main__":
    unittest.main()
