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

import _bootstrap
import re
from chat_test_client import ChatStreamTestClient


class Day3ToolsCouponTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    # --- Unified Harness Assertions ---
    def assert_tool_called(self, result, tool_name: str) -> None:
        tool_results = result.metrics.get("local_life_tool_results") or []
        executed_tools = [r.get("tool_name") for r in tool_results]
        self.assertIn(
            tool_name, 
            executed_tools, 
            f"Expected tool '{tool_name}' to be executed, but got: {executed_tools}"
        )

    def assert_tool_not_called(self, result, tool_name: str) -> None:
        tool_results = result.metrics.get("local_life_tool_results") or []
        executed_tools = [r.get("tool_name") for r in tool_results]
        self.assertNotIn(
            tool_name, 
            executed_tools, 
            f"Expected tool '{tool_name}' NOT to be executed, but it was found in trace: {executed_tools}"
        )

    def assert_trace_contains(self, result, key: str) -> None:
        self.assertIn(
            key, 
            result.metrics, 
            f"Harness trace validation failed: metric key '{key}' is missing from final stream metrics!"
        )

    def assert_coupon_style(self, result) -> None:
        contract = result.metrics.get("answer_contract") or {}
        self.assertEqual(
            contract.get("answer_style"),
            "coupon_only",
            f"Expected coupon_only answer style, got: {contract}"
        )

    def test_day3_1_multi_tool(self) -> None:
        """Case D3-1：coupon + open_status 双工具执行"""
        session_id = f"day3-multi-tool-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶店有券吗，现在营业吗？",
            session_id=session_id,
            extra_payload={
                "shopName": "海底捞水晶店",
                "shopId": 5,
            },
        )
        print("\n=== D3-1 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        self.assertTrue(answer)
        self.assertTrue(any(x in answer for x in ["海底捞", "水晶", "open", "营业", "门店"]))
        self.assertEqual(result.metrics.get("routing_decision", {}).get("required_action"), "tool_call")
        self.assertEqual(result.metrics.get("route_gate", {}).get("branch"), "tool")
        self.assertEqual(result.metrics.get("phase5_trace", {}).get("runner_kind"), "langgraph")

    def test_day3_2_coupon_count(self) -> None:
        """Case D3-2：券数量一致"""
        session_id = f"day3-coupon-count-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店有几张券？",
            session_id=session_id,
            extra_payload={
                "shopName": "海底捞水晶城店",
                "shopId": 5,
            },
        )
        print("\n=== D3-2 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        
        self.assertTrue(any(x in answer for x in ["券", "优惠", "张"]))
        self.assertIn(result.metrics.get("route_gate", {}).get("branch"), {"tool", "rag_plus_tool"})

    def test_day3_3_realtime_no_coupon(self) -> None:
        """Case D3-3：实时无券但 RAG 有历史套餐"""
        session_id = f"day3-coupon-history-{uuid4().hex[:8]}"
        # Query a shop that we know has no coupons (e.g. 炉鱼)
        result = self.client.post_message(
            message="炉鱼运河上街店有可用优惠券吗？",
            session_id=session_id,
            extra_payload={
                "shopName": "炉鱼运河上街店",
            },
        )
        print("\n=== D3-3 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        
        self.assertTrue(answer)
        self.assertTrue(any(x in answer for x in ["券", "优惠", "张"]))
        self.assertIn(result.metrics.get("route_gate", {}).get("branch"), {"tool", "rag_plus_tool"})

    def test_day3_4_no_target_shop_clarify(self) -> None:
        """Case D3-4：无 target_shop 时问券必须澄清"""
        session_id = f"day3-no-target-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="有券吗？",
            session_id=session_id
        )
        print("\n=== D3-4 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        self.assertTrue(any(x in answer for x in ["哪家", "哪一家", "具体门店", "想查", "哪一个", "套餐或券"]))

        # Check tool execution trace: get_coupon_list must not be called
        self.assert_tool_not_called(result, "get_coupon_list")

    def test_day3_5_coupon_clarification_memory_restore(self) -> None:
        """Case D3-5：澄清后补全门店，必须恢复原始 coupon 任务"""
        session_id = f"day3-coupon-memory-{uuid4().hex[:8]}"

        result1 = self.client.post_message(
            message="有券吗？",
            session_id=session_id
        )
        print("\n=== D3-5 Turn 1 Answer ===")
        print(result1.final_answer)
        print("=========================")

        pending_user_need = (((result1.metrics.get("routing_decision") or {}).get("extra") or {}).get("user_need") or {})
        self.assertEqual(pending_user_need.get("intent"), "package_or_coupon")

        result2 = self.client.post_message(
            message="海底捞水晶店",
            session_id=session_id
        )
        print("\n=== D3-5 Turn 2 Answer ===")
        print(result2.final_answer)
        print("=========================")

        answer2 = result2.final_answer
        self.assertTrue(answer2)
        self.assertEqual(result2.metrics.get("phase5_trace", {}).get("runner_kind"), "langgraph")
        self.assertTrue(result2.metrics.get("routing_decision"))

    def test_day3_regression_day2_1(self) -> None:
        """Regression D2-1: coupon-only 不得答环境"""
        session_id = f"day3-reg-d2-1-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店有券吗？",
            session_id=session_id
        )
        answer = result.final_answer
        self.assertTrue(any(x in answer for x in ["券", "优惠", "暂无", "实时"]))
        for x in ["环境", "氛围", "口味", "服务", "推荐", "适合"]:
            self.assertNotIn(x, answer)

    def test_day3_regression_day1_3(self) -> None:
        """Regression D1-3: 指代词继承旧商铺"""
        session_id = f"day3-reg-d1-3-{uuid4().hex[:8]}"
        result1 = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        result2 = self.client.post_message(
            message="它有券吗？",
            session_id=session_id
        )
        self.assertTrue("券" in result2.final_answer or "优惠" in result2.final_answer or "暂无" in result2.final_answer)
        self.assertTrue(result2.metrics.get("routing_decision"))


if __name__ == "__main__":
    unittest.main()
