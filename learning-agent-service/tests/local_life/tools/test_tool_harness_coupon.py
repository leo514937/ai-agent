from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.response_builder import build_coupon_only_answer
from learning_agent_service.local_life.tool_result_normalizer import normalize_tool_result


class ToolHarnessCouponTestCase(unittest.TestCase):
    def test_coupon_tool_result_normalizes_success(self) -> None:
        result = normalize_tool_result(
            tool_name="get_coupon_list",
            raw_output={
                "shop_id": 5,
                "shop_name": "海底捞水晶城店",
                "count": 2,
                "coupons": [{"title": "88代100"}],
            },
            shop_id=5,
            shop_name="海底捞水晶城店",
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data.get("count"), 2)
        self.assertTrue(result.is_realtime)

    def test_coupon_tool_result_normalizes_empty(self) -> None:
        result = normalize_tool_result(
            tool_name="get_coupon_list",
            raw_output={
                "shop_id": 7,
                "shop_name": "炉鱼运河上街店",
                "count": 0,
                "coupons": [],
            },
            shop_id=7,
            shop_name="炉鱼运河上街店",
        )
        self.assertEqual(result.status, "empty")
        self.assertEqual(result.confidence, 0.9)

    def test_coupon_timeout_uses_degradation_answer(self) -> None:
        bundle = FacetResultBundle(
            tool_results=[
                normalize_tool_result(
                    tool_name="get_coupon_list",
                    raw_output={"shop_id": 5, "shop_name": "海底捞水晶城店", "count": 0, "coupons": []},
                    shop_id=5,
                    shop_name="海底捞水晶城店",
                    status="timeout",
                    error_message="timeout",
                )
            ]
        )
        candidate = SimpleNamespace(shop_id=5, vouchers=[])
        answer = build_coupon_only_answer("海底捞水晶城店", [candidate], [], facet_result_bundle=bundle)
        self.assertIn("实时优惠券信息", answer)
        self.assertIn("店铺页面", answer)

    def test_coupon_tool_answer_accepts_dict_bundle(self) -> None:
        bundle = {
            "tool_results": [
                normalize_tool_result(
                    tool_name="get_coupon_list",
                    raw_output={
                        "shop_id": 5,
                        "shop_name": "海底捞水晶城店",
                        "count": 1,
                        "coupons": [{"title": "88代100"}],
                    },
                    shop_id=5,
                    shop_name="海底捞水晶城店",
                ).model_dump(mode="json")
            ]
        }
        candidate = SimpleNamespace(shop_id=5, vouchers=[{"title": "88代100"}])
        answer = build_coupon_only_answer("海底捞水晶城店", [candidate], [], facet_result_bundle=bundle)
        self.assertIn("当前有1张券", answer)
        self.assertIn("88代100", answer)


if __name__ == "__main__":
    unittest.main()
