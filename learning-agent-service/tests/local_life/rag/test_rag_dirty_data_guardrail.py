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
from learning_agent_service.local_life.schemas import EvidenceClaim


class LocalLifeRagGuardrailTestCase(unittest.TestCase):
    def _build_claim(
        self,
        *,
        chunk_id: str,
        shop_id: int | None,
        claim: str,
        support_text: str,
        facet: str,
        confidence: float = 0.7,
        parent_chunk_id: str | None = None,
        chunk_role: str | None = None,
    ) -> EvidenceClaim:
        return EvidenceClaim(
            chunk_id=chunk_id,
            shop_id=shop_id,
            claim=claim,
            support_text=support_text,
            source_type="qdrant",
            confidence=confidence,
            metadata={
                "facet": facet,
                "shop_id": shop_id,
                "parent_chunk_id": parent_chunk_id,
                "chunk_role": chunk_role,
            },
        )

    def test_single_shop_drops_cross_shop_and_forbidden_facet(self) -> None:
        from learning_agent_service.local_life.rag_guardrail import LocalLifeRagGuardrail

        contract = AnswerContract(
            original_query="海底捞水晶城店环境怎么样？",
            allowed_facets=["environment"],
            forbidden_facets=["coupon", "open_status", "recommendation"],
            allowed_rag_facets=["environment", "scene_fit"],
            forbidden_rag_facets=["coupon", "open_status", "recommendation"],
            realtime_facets=["coupon", "open_status", "distance_eta"],
            answer_style="single_shop_review",
        )
        guardrail = LocalLifeRagGuardrail()
        claims = [
            self._build_claim(
                chunk_id="env-good",
                shop_id=5,
                claim="环境比较安静，适合聊天。",
                support_text="海底捞水晶城店环境比较安静，适合聊天。",
                facet="environment",
                confidence=0.86,
            ),
            self._build_claim(
                chunk_id="env-cross-shop",
                shop_id=9,
                claim="巴奴这家环境热闹。",
                support_text="巴奴毛肚火锅环境热闹。",
                facet="environment",
                confidence=0.83,
            ),
            self._build_claim(
                chunk_id="coupon-forbidden",
                shop_id=5,
                claim="有团购套餐。",
                support_text="海底捞水晶城店有团购套餐。",
                facet="coupon",
                confidence=0.81,
            ),
        ]

        result = guardrail.apply(
            raw_query="海底捞水晶城店环境怎么样？",
            latest_turn_message="海底捞水晶城店环境怎么样？",
            rag_mode="single_shop_rag",
            evidence_claims=claims,
            answer_contract=contract,
            target_shop_id=5,
        )

        self.assertEqual([item.chunk_id for item in result.clean_items], ["env-good"])
        self.assertEqual(result.metrics.get("dropped_by_shop_count"), 1)
        self.assertEqual(result.metrics.get("dropped_by_facet_count"), 1)
        self.assertEqual(result.metrics.get("final_clean_evidence_count"), 1)
        self.assertEqual(result.rag_quality_status, "ok")

    def test_all_weak_evidence_degrades_instead_of_promoting(self) -> None:
        from learning_agent_service.local_life.rag_guardrail import LocalLifeRagGuardrail

        contract = AnswerContract(
            original_query="这家适合约会吗？",
            allowed_facets=["scene_fit", "environment"],
            forbidden_facets=["coupon", "open_status"],
            allowed_rag_facets=["scene_fit", "environment"],
            forbidden_rag_facets=["coupon", "open_status"],
            realtime_facets=["coupon", "open_status", "distance_eta"],
            answer_style="single_shop_review",
        )
        guardrail = LocalLifeRagGuardrail()
        claims = [
            self._build_claim(
                chunk_id="weak-1",
                shop_id=5,
                claim="大家都挺喜欢。",
                support_text="评价不错。",
                facet="shop_detail",
                confidence=0.22,
            ),
            self._build_claim(
                chunk_id="weak-2",
                shop_id=5,
                claim="还可以。",
                support_text="整体还行。",
                facet="general_review",
                confidence=0.18,
            ),
        ]

        result = guardrail.apply(
            raw_query="这家适合约会吗？",
            latest_turn_message="这家适合约会吗？",
            rag_mode="single_shop_rag",
            evidence_claims=claims,
            answer_contract=contract,
            target_shop_id=5,
        )

        self.assertEqual(result.rag_quality_status, "weak")
        self.assertEqual(result.metrics.get("strong_evidence_count"), 0)
        self.assertEqual(result.metrics.get("medium_evidence_count"), 0)
        self.assertEqual(result.metrics.get("final_clean_evidence_count"), 0)
        self.assertTrue(result.degraded)
        self.assertIn("low_relevance_only", result.dirty_reasons)

    def test_recommendation_groups_by_shop_and_limits_per_shop(self) -> None:
        from learning_agent_service.local_life.rag_guardrail import LocalLifeRagGuardrail

        contract = AnswerContract(
            original_query="附近有没有适合约会的餐厅？推荐几家。",
            allowed_facets=["recommendation", "scene_fit", "environment"],
            forbidden_facets=[],
            allowed_rag_facets=["recommendation_reason", "scene_fit", "environment", "taste", "price"],
            forbidden_rag_facets=["coupon", "open_status"],
            realtime_facets=["coupon", "open_status", "distance_eta"],
            allow_recommendation=True,
            allow_extra_context=True,
            answer_style="multi_shop_recommendation",
        )
        guardrail = LocalLifeRagGuardrail()
        claims = [
            self._build_claim(
                chunk_id="shop5-env-1",
                shop_id=5,
                claim="环境安静，灯光柔和。",
                support_text="店里环境安静，灯光柔和，适合约会。",
                facet="environment",
                confidence=0.88,
                parent_chunk_id="parent-5",
                chunk_role="child",
            ),
            self._build_claim(
                chunk_id="shop5-scene-2",
                shop_id=5,
                claim="适合情侣约会。",
                support_text="很多人会来这里约会。",
                facet="scene_fit",
                confidence=0.82,
                parent_chunk_id="parent-5",
                chunk_role="sibling",
            ),
            self._build_claim(
                chunk_id="shop5-price-3",
                shop_id=5,
                claim="人均偏高。",
                support_text="人均偏高但环境好。",
                facet="price",
                confidence=0.80,
                parent_chunk_id="parent-5",
                chunk_role="sibling",
            ),
            self._build_claim(
                chunk_id="shop9-env-1",
                shop_id=9,
                claim="装修有氛围。",
                support_text="装修有氛围，适合约会。",
                facet="environment",
                confidence=0.84,
                parent_chunk_id="parent-9",
                chunk_role="child",
            ),
        ]

        result = guardrail.apply(
            raw_query="附近有没有适合约会的餐厅？推荐几家。",
            latest_turn_message="附近有没有适合约会的餐厅？推荐几家。",
            rag_mode="recommendation_rag",
            evidence_claims=claims,
            answer_contract=contract,
            target_shop_id=None,
        )

        kept_ids = [item.chunk_id for item in result.clean_items]
        self.assertEqual(result.metrics.get("recommendation_shop_count"), 2)
        self.assertEqual(result.metrics.get("final_clean_evidence_count"), 3)
        self.assertEqual(result.metrics.get("dropped_by_sibling_count"), 1)
        self.assertNotIn("shop5-price-3", kept_ids)


if __name__ == "__main__":
    unittest.main()
