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


class Day5RagParentChildHybridEvalHarnessTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def _nearby_context(self) -> dict:
        return {
            "city": "北京",
            "current_city": "北京",
            "location": {
                "type": "near_user",
                "city": "北京",
                "lat": None,
                "lng": None,
                "radius_km": 3.0,
            },
        }

    def test_single_shop_chat_keeps_latest_turn_and_shop_isolation(self) -> None:
        session_id = f"day5-single-shop-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店适合约会吗？",
            session_id=session_id,
        )

        metrics = result.metrics or {}
        evidence_shop_ids = metrics.get("evidence_shop_ids") or []

        self.assertTrue(result.final_answer)
        self.assertEqual(metrics.get("rag_mode"), "single_shop_rag")
        self.assertEqual(metrics.get("latest_turn_message"), "海底捞水晶城店适合约会吗？")
        self.assertTrue(evidence_shop_ids)
        self.assertTrue(all(shop_id == evidence_shop_ids[0] for shop_id in evidence_shop_ids))
        self.assertNotIn("巴奴", result.final_answer)

    def test_recommendation_chat_switches_to_recommendation_rag_after_anchor(self) -> None:
        session_id = f"day5-reco-anchor-{uuid4().hex[:8]}"
        self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。",
            session_id=session_id,
            extra_payload=self._nearby_context(),
        )

        metrics = result.metrics or {}
        route_gate = metrics.get("route_gate") or {}

        self.assertTrue(result.final_answer)
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")
        self.assertEqual(metrics.get("latest_turn_message"), "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。")
        self.assertEqual(route_gate.get("branch"), "recommendation")
        self.assertGreaterEqual(len(metrics.get("evidence_shop_groups") or []), 1)


if __name__ == "__main__":
    unittest.main()
