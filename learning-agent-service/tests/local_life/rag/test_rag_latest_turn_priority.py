from __future__ import annotations

import sys
import unittest
from pathlib import Path

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.evidence_pack import build_evidence_pack
from learning_agent_service.rag.local_life_eval import (
    evaluate_local_life_rag_cases,
    load_local_life_rag_eval_cases,
    summarize_local_life_rag_observation,
)


class RagLatestTurnPriorityTestCase(unittest.TestCase):
    def test_latest_turn_message_drives_eval_priority(self) -> None:
        cases_path = REPO_ROOT / "eval" / "local_life" / "rag_eval_cases.jsonl"
        case = next(
            item
            for item in load_local_life_rag_eval_cases(cases_path)
            if item.case_id == "recommendation_after_single_shop_anchor_001"
        )
        pack = build_evidence_pack(
            raw_query=case.query,
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店"},
                {"shop_id": 9, "name": "新白鹿运河上街店"},
            ],
            evidence_claims=[
                {"chunk_id": "r-5-1", "shop_id": 5, "claim": "适合约会。", "support_text": "适合约会。", "source_type": "scene_fit", "confidence": 0.9, "metadata": {"shop_id": 5}},
                {"chunk_id": "r-5-2", "shop_id": 5, "claim": "有券可参考。", "support_text": "有券可参考。", "source_type": "package_description", "confidence": 0.88, "metadata": {"shop_id": 5}},
                {"chunk_id": "r-9-1", "shop_id": 9, "claim": "现在营业。", "support_text": "现在营业。", "source_type": "open_status", "confidence": 0.89, "metadata": {"shop_id": 9}},
            ],
            slots={"rag_mode": "recommendation_rag"},
            source_summary={"rag_mode": "recommendation_rag"},
            safety_result={},
            rag_mode="recommendation_rag",
        )
        observation = summarize_local_life_rag_observation(
            case=case,
            answer="1. 海底捞水晶城店 2. 新白鹿运河上街店",
            metrics={
                "rag_mode": "recommendation_rag",
                "latest_turn_message": case.turns[-1],
                "route_gate": {"branch": "recommendation"},
            },
            evidence_pack=pack,
        )

        metrics = evaluate_local_life_rag_cases((case,), (observation,))
        self.assertEqual(metrics["latest_turn_priority_rate"], 1.0)
        self.assertEqual(metrics["rag_mode_match_rate"], 1.0)
        self.assertEqual(metrics["route_match_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
