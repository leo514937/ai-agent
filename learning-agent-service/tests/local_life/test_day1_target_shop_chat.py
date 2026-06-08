import sys
import unittest
from pathlib import Path
from typing import Any
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

class Day1TargetShopChatTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()
        cls.cases_file = Path(__file__).resolve().parent / "golden_cases" / "local_life_chat_cases.yaml"
        with open(cls.cases_file, "r", encoding="utf-8") as f:
            cls.cases_data = yaml.safe_load(f)

    def test_day1_1_explicit_single_shop(self) -> None:
        """Case D1-1: 显式单店评价"""
        session_id = f"day1-single-shop-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        
        print("\n=== D1-1 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        self.assertTrue(
            "海底捞" in result.final_answer or "水晶城" in result.final_answer,
            "Answer must be about Haidilao Crystal City"
        )
        self.assertNotIn("巴奴", result.final_answer)

        # Trace assertions
        metrics = result.metrics
        self.assertEqual(metrics.get("target_shop.source"), "current_query")
        self.assertEqual(metrics.get("single_shop_mode"), True)

    def test_day1_2_multi_turn_override(self) -> None:
        """Case D1-2: 多轮显式新商铺覆盖旧商铺"""
        session_id = f"day1-switch-shop-{uuid4().hex[:8]}"
        
        # Turn 1
        result1 = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )
        
        # Turn 2
        result2 = self.client.post_message(
            message="巴奴毛肚火锅怎么样？",
            session_id=session_id
        )

        print("\n=== D1-2 Turn 2 Answer ===")
        print(result2.final_answer)
        print("==========================")

        self.assertIn("巴奴", result2.final_answer)
        self.assertNotIn("海底捞水晶城", result2.final_answer)
        self.assertEqual(result2.metrics.get("target_shop.source"), "current_query")

    def test_day1_2b_multi_turn_override_preserves_explicit_resolution_source(self) -> None:
        """Case D1-2b: 多轮显式新商铺覆盖旧商铺时，保留 explicit_query 指标"""
        session_id = f"day1-switch-shop-resolution-{uuid4().hex[:8]}"

        self.client.post_message(
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
        self.assertEqual(result2.metrics.get("target_shop.resolution_source"), "explicit_query")

    def test_day1_3_pronoun_inheritance(self) -> None:
        """Case D1-3: 指代词继承旧商铺"""
        session_id = f"day1-pronoun-{uuid4().hex[:8]}"

        # Turn 1
        result1 = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id
        )

        # Turn 2
        result2 = self.client.post_message(
            message="它有券吗？",
            session_id=session_id
        )

        print("\n=== D1-3 Turn 2 Answer ===")
        print(result2.final_answer)
        print("==========================")

        self.assertTrue("券" in result2.final_answer or "优惠" in result2.final_answer)
        self.assertNotIn("环境", result2.final_answer)
        self.assertNotIn("口味", result2.final_answer)
        self.assertNotIn("服务", result2.final_answer)
        self.assertEqual(result2.metrics.get("target_shop.source"), "pronoun_session")

    def test_day1_4_baseline_snapshot(self) -> None:
        """Case D1-4: Baseline 五问题快照记录"""
        questions = [
            ("海底捞水晶城店环境怎么样？", f"day1-snapshot-1-{uuid4().hex[:8]}"),
            ("海底捞水晶城店有几张券？", f"day1-snapshot-2-{uuid4().hex[:8]}"),
            ("附近有没有推荐的餐厅？", f"day1-snapshot-3-{uuid4().hex[:8]}"),
            ("有券吗？", f"day1-snapshot-4-{uuid4().hex[:8]}"),
        ]

        snapshots = []
        for q, sess in questions:
            result = self.client.post_message(message=q, session_id=sess)
            snapshot = {
                "session_id": sess,
                "message": q,
                "final_answer": result.final_answer,
                "all_sse_events": [e.get("event_type") for e in result.events],
                "tool_calls": result.tool_calls,
                "tool_results": result.tool_results,
                "retrieval_results": result.retrieval_events,
                "metrics": result.metrics,
            }
            snapshots.append(snapshot)
            print(f"\nSnapshot for '{q}': Answer = {result.final_answer[:100]}...")

        # Save snapshot file to scratch directory
        snapshot_dir = Path(__file__).resolve().parents[2] / "scratch"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "day1_baseline_snapshots.yaml"
        with open(snapshot_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(snapshots, f, allow_unicode=True)
        print(f"\nBaseline snapshot saved to {snapshot_path}")

if __name__ == "__main__":
    unittest.main()
