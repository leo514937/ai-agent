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
import yaml
from chat_test_client import ChatStreamTestClient

class Day2AnswerContractTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def test_day2_1_coupon_only_not_env(self) -> None:
        """Case D2-1：coupon-only 不得答环境"""
        session_id = f"day2-coupon-only-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店有券吗？",
            session_id=session_id
        )
        print("\n=== D2-1 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        
        self.assertTrue(any(x in answer for x in ["券", "优惠", "暂无", "实时"]))
        for x in ["环境", "氛围", "口味", "服务", "推荐", "适合"]:
            self.assertNotIn(x, answer)

        # Trace assertions
        metrics = result.metrics
        self.assertIsNotNone(metrics.get("answer_contract"))
        contract = metrics.get("answer_contract")
        self.assertIn("coupon", contract.get("allowed_facets", []))
        self.assertIn("environment", contract.get("forbidden_facets", []))

    def test_day2_2_open_status_only_not_recommend(self) -> None:
        """Case D2-2：open-status-only 不得答推荐"""
        session_id = f"day2-open-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店现在营业吗？",
            session_id=session_id
        )
        print("\n=== D2-2 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        self.assertTrue(any(x in answer for x in ["营业", "开门", "休息", "时间", "暂时无法确认", "开着"]))
        for x in ["环境", "口味", "服务", "推荐", "适合"]:
            self.assertNotIn(x, answer)

    def test_day2_3_general_review(self) -> None:
        """Case D2-3：general-review 可以综合回答"""
        session_id = f"day2-review-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        print("\n=== D2-3 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        self.assertTrue(any(x in answer for x in ["整体", "评价", "环境", "口味", "服务", "价格", "评分"]))
        self.assertTrue("海底捞" in answer or "水晶城" in answer)
        self.assertNotIn("巴奴", answer)

    def test_day2_4_multi_turn_facet_leak(self) -> None:
        """Case D2-4：多轮上下文只继承实体，不继承 facet"""
        session_id = f"day2-context-facet-{uuid4().hex[:8]}"
        
        # Turn 1: Environment
        result1 = self.client.post_message(
            message="海底捞水晶城店环境怎么样？",
            session_id=session_id
        )
        print("\n=== D2-4 Turn 1 Answer ===")
        print(result1.final_answer)
        print("=========================")
        
        # Turn 2: Coupon only
        result2 = self.client.post_message(
            message="有券吗？",
            session_id=session_id
        )
        print("\n=== D2-4 Turn 2 Answer ===")
        print(result2.final_answer)
        print("=========================")

        answer2 = result2.final_answer
        self.assertTrue(any(x in answer2 for x in ["券", "优惠", "暂无", "实时"]))
        for x in ["环境", "氛围", "口味", "服务", "适合"]:
            self.assertNotIn(x, answer2)

    def test_day2_regression_day1_1(self) -> None:
        """Regression D1-1: 显式单店评价"""
        session_id = f"day2-reg-d1-1-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        self.assertTrue("海底捞" in result.final_answer or "水晶城" in result.final_answer)
        self.assertEqual(result.metrics.get("target_shop.source"), "current_query")
        self.assertEqual(result.metrics.get("single_shop_mode"), True)

    def test_day2_regression_day1_2(self) -> None:
        """Regression D1-2: 多轮显式新商铺覆盖旧商铺"""
        session_id = f"day2-reg-d1-2-{uuid4().hex[:8]}"
        result1 = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        result2 = self.client.post_message(
            message="巴奴毛肚火锅怎么样？",
            session_id=session_id
        )
        self.assertIn("巴奴", result2.final_answer)
        self.assertNotIn("海底捞水晶城", result2.final_answer)
        self.assertEqual(result2.metrics.get("target_shop.source"), "current_query")

    def test_day2_regression_day1_3(self) -> None:
        """Regression D1-3: 指代词继承旧商铺"""
        session_id = f"day2-reg-d1-3-{uuid4().hex[:8]}"
        result1 = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        result2 = self.client.post_message(
            message="它有券吗？",
            session_id=session_id
        )
        self.assertTrue("券" in result2.final_answer or "优惠" in result2.final_answer)
        self.assertEqual(result2.metrics.get("target_shop.source"), "pronoun_session")

if __name__ == "__main__":
    unittest.main()
