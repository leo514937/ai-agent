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


class TargetShopPolicyHarnessTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def test_explicit_shop_beats_history_anchor(self) -> None:
        session_id = f"day1-harness-explicit-{uuid4().hex[:8]}"

        self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="巴奴毛肚火锅怎么样？",
            session_id=session_id,
        )

        self.assertIn("巴奴", result.final_answer)
        self.assertNotIn("海底捞水晶城", result.final_answer)
        self.assertEqual(result.metrics.get("target_shop.source"), "current_query")
        self.assertEqual(result.metrics.get("target_shop.resolution_source"), "explicit_query")
        self.assertEqual(result.metrics.get("latest_turn_message"), "巴奴毛肚火锅怎么样？")
        self.assertEqual(result.metrics.get("should_clarify"), False)

    def test_client_selected_shop_beats_session_current_shop(self) -> None:
        session_id = f"day1-harness-client-selected-{uuid4().hex[:8]}"

        self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="这家有券吗？",
            session_id=session_id,
            extra_payload={
                "shopId": 9,
                "shopName": "INLOVE KTV(水晶城店)",
            },
        )

        self.assertTrue("券" in result.final_answer or "优惠" in result.final_answer)
        self.assertEqual(result.metrics.get("target_shop.source"), "pronoun_session")
        self.assertEqual(result.metrics.get("target_shop.resolution_source"), "client_selected_shop")
        self.assertEqual(result.metrics.get("single_shop_mode"), True)

    def test_recommendation_does_not_lock_current_shop(self) -> None:
        session_id = f"day1-harness-reco-{uuid4().hex[:8]}"

        self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id,
        )
        result = self.client.post_message(
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

        self.assertTrue(result.final_answer)
        self.assertEqual(result.metrics.get("single_shop_mode"), False)
        # self.assertEqual(result.metrics.get("target_shop.resolution_source"), "ambiguous")
        self.assertIsNone(result.metrics.get("target_shop.shop_id"))
        self.assertNotIn("海底捞水晶城", result.final_answer)

    def test_candidate_reference_resolves_first_shop(self) -> None:
        session_id = f"day1-harness-first-candidate-{uuid4().hex[:8]}"

        res1 = self.client.post_message(
            message="附近多推荐几家餐厅",
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
        print(f"DEBUG RECO RESULT answer: {res1.final_answer}")
        print(f"DEBUG RECO RESULT metrics: {res1.metrics}")
        print(f"DEBUG RECO RESULT candidates: {res1.final_payload.get('last_candidates')}")
        result = self.client.post_message(
            message="第一家有券吗？",
            session_id=session_id,
        )

        print(f"DEBUG candidate reference answer: {result.final_answer}")
        self.assertTrue("券" in result.final_answer or "优惠" in result.final_answer)
        self.assertEqual(result.metrics.get("target_shop.source"), "candidate_selection")
        self.assertEqual(result.metrics.get("target_shop.resolution_source"), "candidate_reference")
        self.assertTrue(result.metrics.get("target_shop.shop_id") is not None)

    def test_low_information_input_is_clarified_without_tools(self) -> None:
        session_id = f"day1-harness-low-info-{uuid4().hex[:8]}"

        result = self.client.post_message(
            message="，",
            session_id=session_id,
        )

        self.assertTrue(result.final_answer)
        self.assertTrue("店" in result.final_answer or "补充" in result.final_answer or "哪家" in result.final_answer)
        print(f"DEBUG low info metrics: {result.metrics}")
        # self.assertEqual(result.metrics.get("low_information_input"), True)
        self.assertEqual(result.metrics.get("should_clarify"), True)
        self.assertEqual(result.metrics.get("target_shop.resolution_source"), "missing")
        self.assertFalse(result.tool_calls)
        self.assertFalse(result.retrieval_events)


if __name__ == "__main__":
    unittest.main()
