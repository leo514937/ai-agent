from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient


class Day4ToolRealtimeContractChatTestCase(unittest.TestCase):
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

    def test_day4_1_single_shop_multi_tool_trace(self) -> None:
        session_id = f"day4-tool-trace-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶店有券吗，现在营业吗？",
            session_id=session_id,
            extra_payload={"shopName": "海底捞水晶店", "shopId": 5},
        )

        metrics = result.metrics or {}
        tool_plan = metrics.get("tool_plan") or {}
        tool_results = metrics.get("local_life_tool_results") or []

        self.assertTrue(result.final_answer)
        self.assertIn("get_coupon_list", tool_plan.get("required_tools", []))
        self.assertIn("check_open_status", tool_plan.get("required_tools", []))
        self.assertTrue(metrics.get("answer_realtime_claim_supported"))
        for item in tool_results:
            self.assertIn("status", item)
            self.assertIn("fetched_at", item)
            self.assertIn("is_realtime", item)

    def test_day4_2_latest_turn_priority_not_environment(self) -> None:
        session_id = f"day4-latest-turn-{uuid4().hex[:8]}"
        self.client.post_message(
            message="海底捞水晶城店环境怎么样？",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="有券吗？",
            session_id=session_id,
        )

        metrics = result.metrics or {}
        tool_plan = metrics.get("tool_plan") or {}
        answer_contract = metrics.get("answer_contract") or {}

        self.assertTrue(any(token in result.final_answer for token in ("券", "优惠", "实时", "暂无")))
        self.assertNotIn("环境", result.final_answer)
        self.assertEqual(metrics.get("latest_turn_message"), "有券吗？")
        self.assertIn("environment", answer_contract.get("forbidden_facets", []))

    def test_day4_3_recommendation_scope_not_single_shop_polluted(self) -> None:
        session_id = f"day4-reco-scope-{uuid4().hex[:8]}"
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
        tool_plan = metrics.get("tool_plan") or {}
        tool_results = metrics.get("local_life_tool_results") or []
        recommendation_tool_scope = metrics.get("recommendation_tool_scope") or {}
        shop_ids = {item.get("shop_id") for item in tool_results if item.get("shop_id") not in (None, "")}

        self.assertTrue(result.final_answer)
        self.assertEqual(tool_plan.get("execution_mode"), "per_candidate")
        self.assertIsNone(tool_plan.get("target_shop_id"))
        self.assertTrue(recommendation_tool_scope.get("enabled"))
        self.assertFalse(len(shop_ids) == 1 and "5" in {str(item) for item in shop_ids} and (metrics.get("candidate_count") or 0) > 1)


if __name__ == "__main__":
    unittest.main()
