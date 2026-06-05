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


class SingleShopRagNoCrossShopTestCase(unittest.TestCase):
    def test_single_shop_pack_filters_cross_shop_evidence(self) -> None:
        pack = build_evidence_pack(
            raw_query="海底捞水晶城店适合约会吗？",
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店"},
                {"shop_id": 9, "name": "巴奴火锅"},
            ],
            evidence_claims=[
                {"chunk_id": "e-5-1", "shop_id": 5, "claim": "环境安静，适合约会。", "support_text": "环境安静，适合约会。", "source_type": "scene_fit", "confidence": 0.92, "metadata": {"shop_id": 5}},
                {"chunk_id": "e-9-1", "shop_id": 9, "claim": "巴奴也很热闹。", "support_text": "巴奴也很热闹。", "source_type": "scene_fit", "confidence": 0.91, "metadata": {"shop_id": 9}},
            ],
            slots={"scene": "date", "shop_id": 5, "rag_mode": "single_shop_rag"},
            source_summary={"rag_mode": "single_shop_rag"},
            safety_result={},
            rag_mode="single_shop_rag",
            target_shop_id=5,
        )

        self.assertEqual(pack.rag_mode, "single_shop_rag")
        self.assertEqual(pack.target_shop_id, 5)
        self.assertEqual([item.shop_id for item in pack.items], [5])
        self.assertEqual(sorted(pack.grouped_by_shop.keys()), ["5"])
        self.assertEqual([item.shop_id for item in pack.dropped_cross_shop_evidence], [9])
        self.assertTrue(all(item.shop_id == 5 for item in pack.items))
        self.assertIsNone(pack.empty_reason)


if __name__ == "__main__":
    unittest.main()
