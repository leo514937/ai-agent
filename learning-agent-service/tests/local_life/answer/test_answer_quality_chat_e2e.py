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

try:
    from learning_agent_service.application.workflow.builder import LANGGRAPH_AVAILABLE
except Exception:  # pragma: no cover - optional dependency
    LANGGRAPH_AVAILABLE = False


class AnswerQualityChatE2ETestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def _assert_quality_metrics(self, result) -> dict:
        metrics = result.metrics or {}
        self.assertIn("answer_quality", metrics)
        self.assertIn("answer_depth_policy", metrics)
        self.assertIn("repetition_guard", metrics)
        self.assertEqual(metrics.get("answer_quality", {}).get("final_answer_char_count") is not None, True)
        return metrics

    def test_single_shop_review_is_structured_and_not_too_short(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day6-quality-single-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id,
            extra_payload={
                "shopName": "海底捞水晶城店",
                "shopId": 5,
            },
        )

        answer = result.final_answer
        metrics = self._assert_quality_metrics(result)
        quality = metrics.get("answer_quality") or {}

        self.assertTrue(answer)
        self.assertIn("总体结论", answer)
        self.assertIn("核心优点", answer)
        self.assertIn("可能不足", answer)
        self.assertIn("适合场景", answer)
        self.assertIn("到店建议", answer)
        self.assertFalse(quality.get("answer_too_short"))
        self.assertFalse(quality.get("answer_too_repetitive"))
        self.assertGreaterEqual(quality.get("final_answer_char_count", 0), 120)

    def test_multi_shop_recommendation_has_multiple_distinct_candidates(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day6-quality-multi-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="附近推荐几家适合约会的餐厅",
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

        answer = result.final_answer
        metrics = self._assert_quality_metrics(result)
        quality = metrics.get("answer_quality") or {}

        self.assertTrue(answer)
        self.assertIn("推荐", answer)
        self.assertIn("推荐理由", answer)
        self.assertIn("适合场景", answer)
        self.assertEqual(quality.get("answer_style"), "multi_shop_recommendation")
        self.assertGreaterEqual(quality.get("final_answer_char_count", 0), 100)
        self.assertFalse(quality.get("answer_too_repetitive"))
        self.assertLessEqual(quality.get("recommendation_duplicate_shop_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
