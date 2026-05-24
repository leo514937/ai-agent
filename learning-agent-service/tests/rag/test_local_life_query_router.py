from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.query_router import LocalLifeQueryRouter
from learning_agent_service.local_life.schemas import LocalLifeIntentType, LocalLifeSlots, LocationNorm, PriceNorm


class LocalLifeQueryRouterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.router = LocalLifeQueryRouter()

    def test_structured_filter_query_routes_to_business_first(self) -> None:
        slots = LocalLifeSlots(
            city="北京",
            location=LocationNorm(city="北京", lat=39.9, lng=116.4),
            price=PriceNorm(target=150),
            category="家常菜",
            preferences=["quiet"],
        )
        decision = self.router.route(
            "朝阳公园附近人均150评分高的家常菜，最好安静一点",
            slots=slots,
            intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        )

        self.assertEqual(decision.route, "structured_first")
        self.assertTrue(decision.use_business_candidates)
        self.assertTrue(decision.use_qdrant)
        self.assertGreater(decision.parent_top_k, 0)

    def test_realtime_business_query_skips_qdrant(self) -> None:
        decision = self.router.route(
            "这个订单现在能退款吗",
            slots=LocalLifeSlots(city="北京"),
            intent=LocalLifeIntentType.ORDER_STATUS,
        )

        self.assertEqual(decision.route, "realtime_tool")
        self.assertFalse(decision.use_qdrant)
        self.assertFalse(decision.use_business_candidates)

    def test_memory_query_skips_local_life_retrieval(self) -> None:
        decision = self.router.route(
            "你记得我们聊过什么吗",
            slots=LocalLifeSlots(),
            intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        )

        self.assertEqual(decision.route, "general_chat")
        self.assertEqual(decision.retrieval_strategy, "general_answer_only")
        self.assertFalse(decision.use_qdrant)
        self.assertFalse(decision.use_business_candidates)
        self.assertEqual(decision.parent_top_k, 0)
        self.assertEqual(decision.child_top_k, 0)

    def test_guide_rule_query_routes_to_rule_rag(self) -> None:
        decision = self.router.route(
            "平台规则和团购攻略怎么选",
            slots=LocalLifeSlots(city="北京"),
            intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        )

        self.assertEqual(decision.route, "guide_rule_rag")
        self.assertTrue(decision.use_qdrant)
        self.assertIn("local_guide", decision.preferred_roles)
        self.assertIn("platform_rule", decision.preferred_roles)

    def test_comparison_query_routes_to_multi_parent(self) -> None:
        decision = self.router.route(
            "A和B哪家更适合约会，对比一下",
            slots=LocalLifeSlots(city="北京"),
            intent=LocalLifeIntentType.RESTAURANT_COMPARISON,
        )

        self.assertEqual(decision.route, "compare_multi_parent")
        self.assertGreaterEqual(decision.parent_top_k, 8)
        self.assertGreaterEqual(decision.child_top_k, 40)
        self.assertIn("merchant_review_summary", decision.preferred_roles)


if __name__ == "__main__":
    unittest.main()
