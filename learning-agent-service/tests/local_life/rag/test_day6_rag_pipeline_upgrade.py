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


class Day6RagPipelineUpgradeTestCase(unittest.TestCase):
    def test_single_shop_pack_isolated_and_reviewable(self) -> None:
        pack = build_evidence_pack(
            raw_query="海底捞水晶城店环境怎么样？",
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店"},
                {"shop_id": 9, "name": "巴奴毛肚火锅"},
            ],
            evidence_claims=[
                {
                    "chunk_id": "e-5-1",
                    "shop_id": 5,
                    "claim": "环境比较安静，适合约会。",
                    "support_text": "环境比较安静，适合约会。",
                    "source_type": "scene_fit",
                    "confidence": 0.92,
                    "metadata": {"shop_id": 5},
                },
                {
                    "chunk_id": "e-9-1",
                    "shop_id": 9,
                    "claim": "巴奴那边也很热闹。",
                    "support_text": "巴奴那边也很热闹。",
                    "source_type": "scene_fit",
                    "confidence": 0.91,
                    "metadata": {"shop_id": 9},
                },
            ],
            slots={"scene": "date", "shop_id": 5, "rag_mode": "single_shop_rag"},
            source_summary={
                "rag_mode": "single_shop_rag",
                "rag_quality_status": "ok",
                "degraded_reason": None,
            },
            safety_result={},
            rag_mode="single_shop_rag",
            target_shop_id=5,
        )

        self.assertEqual(pack.rag_mode, "single_shop_rag")
        self.assertEqual(pack.target_shop_id, 5)
        self.assertEqual([item.shop_id for item in pack.items], [5])
        self.assertEqual([item.shop_id for item in pack.dropped_cross_shop_evidence], [9])
        self.assertEqual(pack.citations, ["e-5-1"])
        self.assertEqual(pack.evidence_status, "OK")
        self.assertEqual(pack.discard_summary["cross_shop_dropped_count"], 1)
        self.assertEqual(pack.discard_summary["rag_quality_status"], "ok")
        self.assertIsNone(pack.empty_reason)

    def test_weak_evidence_is_marked_as_degraded_not_strong(self) -> None:
        pack = build_evidence_pack(
            raw_query="这家店适合约会吗？",
            ranked_candidates=[{"shop_id": 5, "name": "海底捞水晶城店"}],
            evidence_claims=[
                {
                    "chunk_id": "weak-1",
                    "shop_id": 5,
                    "claim": "大家好像还行。",
                    "support_text": "大家好像还行。",
                    "source_type": "general_review",
                    "confidence": 0.22,
                    "metadata": {"shop_id": 5},
                },
                {
                    "chunk_id": "weak-2",
                    "shop_id": 5,
                    "claim": "可以试试。",
                    "support_text": "可以试试。",
                    "source_type": "general_review",
                    "confidence": 0.19,
                    "metadata": {"shop_id": 5},
                },
            ],
            slots={"scene": "date", "shop_id": 5, "rag_mode": "single_shop_rag"},
            source_summary={"rag_mode": "single_shop_rag"},
            safety_result={},
            rag_mode="single_shop_rag",
            target_shop_id=5,
        )

        self.assertEqual(pack.evidence_status, "WEAK")
        self.assertEqual(pack.discard_summary["rag_quality_status"], "weak")
        self.assertEqual([item.evidence_id for item in pack.items], ["weak-1", "weak-2"])
        self.assertEqual(pack.empty_reason, None)

    def test_empty_pack_is_reviewable_and_degraded(self) -> None:
        pack = build_evidence_pack(
            raw_query="附近有什么推荐的餐厅？",
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店"},
                {"shop_id": 9, "name": "巴奴毛肚火锅"},
            ],
            evidence_claims=[],
            slots={"rag_mode": "recommendation_rag"},
            source_summary={
                "rag_mode": "recommendation_rag",
                "degraded_reason": "no_matching_evidence",
            },
            safety_result={"approval_required": False},
            rag_mode="recommendation_rag",
        )

        self.assertEqual(pack.items, [])
        self.assertEqual(pack.citations, [])
        self.assertEqual(pack.evidence_status, "EMPTY")
        self.assertEqual(pack.empty_reason, "no_matching_evidence")
        self.assertEqual(pack.discard_summary["rag_mode"], "recommendation_rag")
        self.assertEqual(pack.discard_summary["empty_reason"], "no_matching_evidence")
        self.assertEqual(pack.discard_summary["cross_shop_dropped_count"], 0)


if __name__ == "__main__":
    unittest.main()
