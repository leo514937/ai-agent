from __future__ import annotations

import sys
import unittest
from pathlib import Path

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.evidence_pack import build_evidence_pack


class RecommendationRagGroupByShopTestCase(unittest.TestCase):
    def test_recommendation_pack_groups_evidence_by_shop(self) -> None:
        pack = build_evidence_pack(
            raw_query="附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。",
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店"},
                {"shop_id": 9, "name": "新白鹿运河上街店"},
            ],
            evidence_claims=[
                {"chunk_id": "e-5-1", "shop_id": 5, "claim": "适合约会，环境安静。", "support_text": "适合约会，环境安静。", "source_type": "scene_fit", "confidence": 0.91, "metadata": {"shop_id": 5}},
                {"chunk_id": "e-5-2", "shop_id": 5, "claim": "当前有券。", "support_text": "当前有券。", "source_type": "coupon", "confidence": 0.88, "metadata": {"shop_id": 5}},
                {"chunk_id": "e-9-1", "shop_id": 9, "claim": "现在营业。", "support_text": "现在营业。", "source_type": "open_status", "confidence": 0.89, "metadata": {"shop_id": 9}},
            ],
            slots={"scene": "date", "rag_mode": "recommendation_rag"},
            source_summary={"rag_mode": "recommendation_rag"},
            safety_result={},
            rag_mode="recommendation_rag",
        )

        self.assertEqual(pack.rag_mode, "recommendation_rag")
        self.assertIsNone(pack.target_shop_id)
        self.assertEqual(sorted(pack.grouped_by_shop.keys()), ["5", "9"])
        self.assertEqual([item.shop_id for item in pack.items], [5, 5, 9])
        self.assertEqual(len(pack.dropped_cross_shop_evidence), 0)
        self.assertGreaterEqual(len(pack.grouped_by_shop["5"]), 2)
        self.assertGreaterEqual(len(pack.grouped_by_shop["9"]), 1)


if __name__ == "__main__":
    unittest.main()
