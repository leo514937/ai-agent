from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.schemas import EvidenceClaim, LocalLifeSlots, RankedCandidate
from learning_agent_service.safety.guards import LocalLifeSafetyGuard


class SafetyGuardTestCase(unittest.TestCase):
    def test_recommendation_turn_is_allowed_and_grounded(self) -> None:
        guard = LocalLifeSafetyGuard()
        decision = guard.evaluate(
            raw_query="今晚想带爸妈吃饭，别太吵，人均150左右，离我近一点",
            slots=LocalLifeSlots(
                city="北京",
                scene="family_dinner",
                preferences=["quiet", "parking_available", "elder_friendly"],
                avoid=["queue_risk"],
            ),
            ranked_candidates=[
                RankedCandidate(
                    shop_id=1001,
                    name="某某家常菜",
                    structured_features={
                        "distance_km": 1.2,
                        "avg_price": 145,
                        "parking": True,
                        "family_friendly": True,
                        "elder_friendly": True,
                    },
                    evidence_features={
                        "quiet": 0.84,
                        "family_dinner": 0.8,
                        "elder_friendly": 0.76,
                    },
                    explainable_reasons=["距离约1.2km", "评论摘要中多次提到环境安静"],
                )
            ],
            evidence_claims=[
                EvidenceClaim(
                    chunk_id="review-1",
                    shop_id=1001,
                    claim="环境安静",
                    support_text="评论摘要显示环境安静，适合家庭聚餐。",
                    source_type="review_summary",
                    confidence=0.84,
                )
            ],
        )

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.approval_required)
        self.assertGreater(decision.fact_check.evidence_score, 0.0)
        self.assertIn("grounded", decision.reason)

    def test_transaction_turn_requires_approval(self) -> None:
        guard = LocalLifeSafetyGuard()
        decision = guard.evaluate(
            raw_query="帮我给某某家常菜订座",
            intent=None,
            slots=LocalLifeSlots(
                city="北京",
                shop_query="某某家常菜",
                preferences=["quiet"],
            ),
            ranked_candidates=[
                RankedCandidate(
                    shop_id=1001,
                    name="某某家常菜",
                    structured_features={"distance_km": 1.2, "avg_price": 145, "parking": True},
                    evidence_features={"quiet": 0.8},
                    explainable_reasons=["距离近", "环境安静"],
                )
            ],
            evidence_claims=[],
            selected_shop_id=1001,
            selected_shop_name="某某家常菜",
        )

        self.assertTrue(decision.approval_required)
        self.assertEqual(decision.risk_level, "medium")
        self.assertEqual(decision.transaction_draft.action, "booking")
        self.assertTrue(decision.approval_request)


if __name__ == "__main__":
    unittest.main()
