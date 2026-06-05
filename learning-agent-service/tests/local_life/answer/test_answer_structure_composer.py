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
from learning_agent_service.local_life.answer_depth_policy import derive_answer_depth_policy
from learning_agent_service.local_life.answer_structure_composer import AnswerStructureComposer


class AnswerStructureComposerTestCase(unittest.TestCase):
    def _single_shop_contract(self) -> AnswerContract:
        return AnswerContract(
            original_query="海底捞水晶城店怎么样？",
            allowed_facets=["environment", "taste", "service", "recommendation_reason", "shop_detail", "scene_fit"],
            forbidden_facets=[],
            allowed_tools=[],
            allowed_rag_facets=["environment", "taste", "service", "recommendation_reason", "shop_detail", "scene_fit"],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=False,
            allow_extra_context=True,
            realtime_required=False,
            evidence_policy="balanced",
            answer_style="single_shop_review",
        )

    def _multi_shop_contract(self) -> AnswerContract:
        return AnswerContract(
            original_query="附近有没有推荐的餐厅？",
            allowed_facets=["environment", "taste", "service", "recommendation", "recommendation_reason", "scene_fit"],
            forbidden_facets=[],
            allowed_tools=[],
            allowed_rag_facets=["environment", "taste", "service", "recommendation", "recommendation_reason", "scene_fit"],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=True,
            allow_extra_context=True,
            realtime_required=False,
            evidence_policy="balanced",
            answer_style="multi_shop_recommendation",
        )

    def test_single_shop_review_has_required_sections(self) -> None:
        composer = AnswerStructureComposer()
        policy = derive_answer_depth_policy(self._single_shop_contract(), clean_evidence_count=3, strong_evidence_count=2)

        result = composer.compose(
            answer_contract=self._single_shop_contract(),
            topic_name="海底捞水晶城店",
            ranked_candidates=[
                {
                    "shop_id": 5,
                    "name": "海底捞水晶城店",
                    "structured_features": {"score": 4.8, "avg_price": 120, "distance_km": 1.2},
                    "explainable_reasons": ["环境稳", "适合约会"],
                }
            ],
            evidence_claims=[
                {"shop_id": 5, "claim": "环境安静", "support_text": "环境安静", "source_type": "review", "confidence": 0.9},
                {"shop_id": 5, "claim": "适合约会", "support_text": "适合约会", "source_type": "review", "confidence": 0.9},
            ],
            answer_depth_policy=policy,
        )

        self.assertIn("总体结论", result.answer_text)
        self.assertIn("核心优点", result.answer_text)
        self.assertIn("可能不足", result.answer_text)
        self.assertIn("适合场景", result.answer_text)
        self.assertIn("到店建议", result.answer_text)
        self.assertGreaterEqual(result.section_count, 4)
        self.assertEqual(result.duplicate_sentence_count, 0)

    def test_multi_shop_recommendation_groups_by_shop(self) -> None:
        composer = AnswerStructureComposer()
        policy = derive_answer_depth_policy(self._multi_shop_contract(), clean_evidence_count=4, strong_evidence_count=3)

        result = composer.compose(
            answer_contract=self._multi_shop_contract(),
            topic_name="附近推荐",
            ranked_candidates=[
                {
                    "shop_id": 1001,
                    "name": "店A",
                    "structured_features": {"score": 4.8, "avg_price": 100, "distance_km": 1.0},
                    "explainable_reasons": ["环境好", "适合约会"],
                },
                {
                    "shop_id": 1002,
                    "name": "店B",
                    "structured_features": {"score": 4.7, "avg_price": 130, "distance_km": 1.3},
                    "explainable_reasons": ["口味稳", "服务好"],
                },
            ],
            evidence_claims=[
                {"shop_id": 1001, "claim": "环境好", "support_text": "环境好", "source_type": "review", "confidence": 0.9},
                {"shop_id": 1001, "claim": "适合约会", "support_text": "适合约会", "source_type": "review", "confidence": 0.8},
                {"shop_id": 1002, "claim": "口味稳", "support_text": "口味稳", "source_type": "review", "confidence": 0.9},
                {"shop_id": 1002, "claim": "服务好", "support_text": "服务好", "source_type": "review", "confidence": 0.8},
            ],
            answer_depth_policy=policy,
        )

        self.assertIn("1.", result.answer_text)
        self.assertIn("2.", result.answer_text)
        self.assertIn("推荐理由", result.answer_text)
        self.assertIn("适合场景", result.answer_text)
        self.assertGreaterEqual(result.recommendation_duplicate_shop_count, 0)
        self.assertEqual(result.duplicate_sentence_count, 0)

    def test_multi_shop_recommendation_uses_evidence_fallback_when_ranked_candidates_missing(self) -> None:
        composer = AnswerStructureComposer()
        policy = derive_answer_depth_policy(self._multi_shop_contract(), clean_evidence_count=3, strong_evidence_count=2)

        result = composer.compose(
            answer_contract=self._multi_shop_contract(),
            topic_name="附近推荐",
            ranked_candidates=[],
            evidence_claims=[
                {
                    "shop_id": 2001,
                    "metadata": {"shop_name": "店C"},
                    "claim": "环境安静，适合约会",
                    "support_text": "环境安静，适合约会",
                    "source_type": "review",
                    "confidence": 0.9,
                },
                {
                    "shop_id": 2002,
                    "metadata": {"shop_name": "店D"},
                    "claim": "口味稳定，排队不长",
                    "support_text": "口味稳定，排队不长",
                    "source_type": "review",
                    "confidence": 0.8,
                },
            ],
            answer_depth_policy=policy,
        )

        self.assertIn("1.", result.answer_text)
        self.assertIn("2.", result.answer_text)
        self.assertIn("推荐理由", result.answer_text)
        self.assertIn("店C", result.answer_text)
        self.assertIn("店D", result.answer_text)


if __name__ == "__main__":
    unittest.main()
