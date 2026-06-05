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


class Day4ToolRealtimeContractHarnessTestCase(unittest.TestCase):
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

    def test_single_shop_trace_fields_are_visible(self) -> None:
        session_id = f"day4-harness-single-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店有券吗？",
            session_id=session_id,
        )

        metrics = result.metrics or {}
        self.assertEqual(metrics.get("latest_turn_message"), "海底捞水晶城店有券吗？")
        self.assertIn("tool_plan", metrics)
        self.assertIn("answer_realtime_claim_supported", metrics)

    def test_recommendation_trace_uses_per_candidate_scope(self) -> None:
        session_id = f"day4-harness-reco-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。",
            session_id=session_id,
            extra_payload=self._nearby_context(),
        )

        metrics = result.metrics or {}
        tool_plan = metrics.get("tool_plan") or {}
        recommendation_tool_scope = metrics.get("recommendation_tool_scope") or {}

        self.assertTrue(result.final_answer)
        self.assertEqual(tool_plan.get("execution_mode"), "per_candidate")
        self.assertTrue(recommendation_tool_scope.get("enabled"))


if __name__ == "__main__":
    unittest.main()
