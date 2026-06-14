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
from learning_agent_service.local_life.answer_quality_gate import AnswerQualityGate


class AnswerQualityGateTestCase(unittest.TestCase):
    def _contract(self, answer_style: str) -> AnswerContract:
        return AnswerContract(
            original_query="海底捞水晶城店怎么样？",
            allowed_facets=["environment", "taste", "service", "recommendation_reason", "scene_fit"],
            forbidden_facets=[],
            allowed_tools=[],
            allowed_rag_facets=["environment", "taste", "service", "recommendation_reason", "scene_fit"],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=answer_style == "multi_shop_recommendation",
            allow_extra_context=answer_style != "coupon_only",
            realtime_required=False,
            evidence_policy="balanced",
            answer_style=answer_style,
        )

    def test_expands_short_single_shop_answer_when_evidence_is_sufficient(self) -> None:
        contract = self._contract("single_shop_review")
        policy = derive_answer_depth_policy(contract, clean_evidence_count=3, strong_evidence_count=2)
        gate = AnswerQualityGate()

        result = gate.finalize(
            draft_answer="整体不错。",
            answer_contract=contract,
            answer_depth_policy=policy,
            clean_evidence_count=3,
            strong_evidence_count=2,
            medium_evidence_count=1,
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
        )

        self.assertTrue(result.expanded_by_quality_gate)
        self.assertFalse(result.answer_too_short)
        self.assertFalse(result.answer_too_repetitive)
        self.assertIn("总体结论", result.final_answer)
        self.assertIn("到店建议", result.final_answer)
        self.assertGreater(result.final_answer_char_count, len("整体不错。"))
        self.assertGreaterEqual(result.section_count, 4)

    def test_keeps_coupon_only_answer_short_without_expansion(self) -> None:
        contract = self._contract("coupon_only")
        policy = derive_answer_depth_policy(contract, clean_evidence_count=0, strong_evidence_count=0)
        gate = AnswerQualityGate()

        result = gate.finalize(
            draft_answer="暂时没有查到可用券。",
            answer_contract=contract,
            answer_depth_policy=policy,
            clean_evidence_count=0,
            strong_evidence_count=0,
            medium_evidence_count=0,
            topic_name="海底捞水晶城店",
            ranked_candidates=[],
            evidence_claims=[],
        )

        self.assertFalse(result.expanded_by_quality_gate)
        self.assertFalse(result.answer_too_repetitive)
        self.assertLessEqual(result.section_count, 2)
        self.assertIn("暂时没有查到可用券", result.final_answer)

    def test_preserves_multi_shop_recommendation_draft_with_reasons(self) -> None:
        contract = self._contract("multi_shop_recommendation")
        policy = derive_answer_depth_policy(contract, clean_evidence_count=0, strong_evidence_count=0)
        gate = AnswerQualityGate()

        result = gate.finalize(
            draft_answer=(
                "我帮你推荐以下这几家店铺：\n\n"
                "1. 店A\n- 推荐理由：环境安静，适合约会。\n"
                "2. 店B\n- 推荐理由：口味稳定，排队不长。\n"
                "3. 店C\n- 推荐理由：距离近，综合体验稳。"
            ),
            answer_contract=contract,
            answer_depth_policy=policy,
            clean_evidence_count=0,
            strong_evidence_count=0,
            medium_evidence_count=0,
            topic_name="附近推荐",
            ranked_candidates=[],
            evidence_claims=[],
        )

        self.assertFalse(result.expanded_by_quality_gate)
        self.assertIn("推荐理由", result.final_answer)
        self.assertIn("店A", result.final_answer)
        self.assertIn("店B", result.final_answer)
        self.assertIn("店C", result.final_answer)

    def test_preserves_structured_single_shop_draft_without_rewriting(self) -> None:
        contract = self._contract("single_shop_review")
        policy = derive_answer_depth_policy(contract, clean_evidence_count=2, strong_evidence_count=1)
        gate = AnswerQualityGate()

        structured_draft = (
            "**海底捞(望京店)** 人均120元，评分4.8，离你1.2km\n\n"
            "**优点：** 服务到位，适合家庭聚餐。\n"
            "**注意：** 饭点可能需要排队。"
        )

        result = gate.finalize(
            draft_answer=structured_draft,
            answer_contract=contract,
            answer_depth_policy=policy,
            clean_evidence_count=2,
            strong_evidence_count=1,
            medium_evidence_count=0,
            topic_name="海底捞水晶城店",
            ranked_candidates=[
                {
                    "shop_id": 5,
                    "name": "海底捞水晶城店",
                    "structured_features": {"score": 4.8, "avg_price": 120, "distance_km": 1.2},
                    "explainable_reasons": ["服务稳", "适合约会"],
                }
            ],
            evidence_claims=[
                {"shop_id": 5, "claim": "服务稳定", "support_text": "服务稳定", "source_type": "review", "confidence": 0.8},
            ],
        )

        self.assertFalse(result.expanded_by_quality_gate)
        self.assertIn("优点", result.final_answer)
        self.assertIn("注意", result.final_answer)
        self.assertNotIn("总体结论", result.final_answer)


if __name__ == "__main__":
    unittest.main()
