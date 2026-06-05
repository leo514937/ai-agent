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


class RagEvidencePackTestCase(unittest.TestCase):
    def test_pack_exposes_grouping_and_empty_reason(self) -> None:
        pack = build_evidence_pack(
            raw_query="海底捞水晶城店有券吗？",
            ranked_candidates=[{"shop_id": 5, "name": "海底捞水晶城店"}],
            evidence_claims=[],
            slots={"shop_id": 5, "rag_mode": "single_shop_rag"},
            source_summary={"rag_mode": "single_shop_rag"},
            safety_result={},
            rag_mode="single_shop_rag",
            target_shop_id=5,
        )

        self.assertEqual(pack.rag_mode, "single_shop_rag")
        self.assertEqual(pack.target_shop_id, 5)
        self.assertEqual(pack.items, [])
        self.assertEqual(pack.evidence_items, [])
        self.assertEqual(pack.grouped_by_shop, {})
        self.assertEqual(pack.empty_reason, "no_matching_evidence")
        self.assertEqual(pack.dropped_cross_shop_evidence, [])


if __name__ == "__main__":
    unittest.main()
