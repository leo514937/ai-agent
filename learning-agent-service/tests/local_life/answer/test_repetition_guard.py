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

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.repetition_guard import RepetitionGuard


class RepetitionGuardTestCase(unittest.TestCase):
    def _contract(self) -> AnswerContract:
        return AnswerContract(
            original_query="附近推荐几家适合约会的餐厅",
            allowed_facets=["recommendation", "scene_fit"],
            forbidden_facets=[],
            allowed_tools=[],
            allowed_rag_facets=["recommendation", "scene_fit"],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=True,
            allow_extra_context=True,
            realtime_required=False,
            evidence_policy="balanced",
            answer_style="multi_shop_recommendation",
        )

    def test_dedupes_repeated_sentences_and_low_information_phrases(self) -> None:
        guard = RepetitionGuard()

        result = guard.dedupe(
            text="整体不错。\n整体不错。\n环境不错。\n环境不错。\n推荐理由：环境不错。\n推荐理由：环境不错。",
            answer_contract=self._contract(),
            ranked_candidates=[{"shop_id": 1, "name": "店A"}],
        )

        self.assertIn("整体不错", result.text)
        self.assertEqual(result.text.count("整体不错"), 1)
        self.assertEqual(result.text.count("环境不错"), 1)
        self.assertGreaterEqual(result.duplicate_sentence_count, 2)
        self.assertGreaterEqual(result.duplicate_ratio, 0.3)
        self.assertTrue(result.deduped)

    def test_dedupes_duplicate_shop_ids_in_recommendation_context(self) -> None:
        guard = RepetitionGuard()

        result = guard.dedupe(
            text="1. 店A，推荐理由：环境好。\n2. 店A，推荐理由：服务好。\n3. 店B，推荐理由：口味稳。",
            answer_contract=self._contract(),
            ranked_candidates=[
                {"shop_id": 1001, "name": "店A"},
                {"shop_id": 1002, "name": "店B"},
            ],
        )

        self.assertIn("店A", result.text)
        self.assertIn("店B", result.text)
        self.assertLessEqual(result.recommendation_duplicate_shop_count, 1)
        self.assertTrue(result.deduped)


if __name__ == "__main__":
    unittest.main()
