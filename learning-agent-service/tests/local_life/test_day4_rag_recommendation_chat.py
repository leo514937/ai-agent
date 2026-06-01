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


class Day4RagRecommendationTestCase(unittest.TestCase):
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

    def test_day4_1_single_shop_rag(self) -> None:
        """Case D4-1：single_shop_rag evidence 全部属于目标店"""
        session_id = f"day4-single-rag-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店环境怎么样？",
            session_id=session_id
        )
        print("\n=== D4-1 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        self.assertTrue(any(x in answer for x in ["海底捞", "水晶城"]))
        self.assertNotIn("巴奴", answer)
        self.assertNotIn("新发现", answer)

        metrics = result.metrics or {}
        self.assertEqual(metrics.get("rag_mode"), "single_shop_rag")
        self.assertEqual(metrics.get("single_shop_mode"), True)

        # Check strict target shop isolation in evidence shop IDs
        evidence_shop_ids = metrics.get("evidence_shop_ids") or []
        target_shop_id = (
            metrics.get("selected_shop_id")
            or metrics.get("target_shop.shop_id")
            or (evidence_shop_ids[0] if evidence_shop_ids else None)
        )
        self.assertIsNotNone(target_shop_id, "single_shop_rag must resolve a concrete target shop id")
        for sid in evidence_shop_ids:
            self.assertEqual(
                sid,
                target_shop_id,
                f"Leaked evidence from shop {sid} into single-shop RAG for target shop {target_shop_id}",
            )

    def test_day4_2_switch_shop_rag(self) -> None:
        """Case D4-2：第二家店 RAG 不混入第一家店"""
        session_id = f"day4-rag-switch-{uuid4().hex[:8]}"
        result1 = self.client.post_message(
            message="海底捞水晶城店环境怎么样？",
            session_id=session_id
        )
        
        result2 = self.client.post_message(
            message="新白鹿餐厅(运河上街店)怎么样？",
            session_id=session_id
        )
        print("\n=== D4-2 Turn 2 Answer ===")
        print(result2.final_answer)
        print("=========================")

        answer2 = result2.final_answer
        self.assertIn("新白鹿", answer2)
        self.assertNotIn("海底捞水晶城", answer2)

        metrics2 = result2.metrics or {}
        evidence_shop_ids2 = metrics2.get("evidence_shop_ids") or []
        # Enforce that no Haidilao evidence (shop_id 5) is returned in the second turn
        self.assertNotIn(5, evidence_shop_ids2, "Leaked Haidilao evidence into second shop RAG session")

    def test_day4_3_reco_default_three(self) -> None:
        """Case D4-3：附近推荐默认 3 家"""
        session_id = f"day4-reco-{uuid4().hex[:8]}"
        self.client.post_message(
            message="我在北京",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="附近有没有推荐的餐厅？",
            session_id=session_id,
            extra_payload=self._nearby_context(),
        )
        print("\n=== D4-3 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        metrics = result.metrics or {}
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")

        # Extract numbered items (e.g. 1. 2. 3.) to see how many shops are recommended
        shop_items = re.findall(r"\d+\.\s+([^\n，,。]+)", answer)
        print(f"Extracted recommended shops: {shop_items}")
        # There should be 3 unique shops
        self.assertTrue(len(set(shop_items)) >= 3 or metrics.get("candidate_count", 0) < 3)

    def test_day4_4_reco_one(self) -> None:
        """Case D4-4：用户明确推荐一家"""
        session_id = f"day4-reco-one-{uuid4().hex[:8]}"
        self.client.post_message(
            message="我在北京",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="附近推荐一家餐厅",
            session_id=session_id,
            extra_payload=self._nearby_context(),
        )
        print("\n=== D4-4 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        metrics = result.metrics or {}
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")

        shop_items = re.findall(r"\d+\.\s+([^\n，,。]+)", answer)
        print(f"Extracted recommended shops: {shop_items}")
        self.assertEqual(len(set(shop_items)), 1)
        self.assertTrue(any(x in answer for x in ["理由", "因为", "适合", "优点", "特色", "推荐"]))

    def test_day4_5_reco_many(self) -> None:
        """Case D4-5：多推荐几家"""
        session_id = f"day4-reco-many-{uuid4().hex[:8]}"
        self.client.post_message(
            message="我在北京",
            session_id=session_id,
        )
        result = self.client.post_message(
            message="附近多推荐几家餐厅",
            session_id=session_id,
            extra_payload=self._nearby_context(),
        )
        print("\n=== D4-5 Final Answer ===")
        print(result.final_answer)
        print("=========================")

        answer = result.final_answer
        metrics = result.metrics or {}
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")

        shop_items = re.findall(r"\d+\.\s+([^\n，,。]+)", answer)
        print(f"Extracted recommended shops: {shop_items}")
        self.assertTrue(len(set(shop_items)) >= 5 or metrics.get("candidate_count", 0) < 5)


if __name__ == "__main__":
    unittest.main()
