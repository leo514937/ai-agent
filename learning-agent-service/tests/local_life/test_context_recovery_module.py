from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain.contracts import PersistentSessionContext
from learning_agent_service.local_life.context_recovery import recover_follow_up_context


class ContextRecoveryModuleTestCase(unittest.TestCase):
    def test_classifies_entity_reference(self) -> None:
        result = recover_follow_up_context(
            "这家有券吗？",
            session_context=PersistentSessionContext(
                current_shop="海底捞水晶城店",
                current_shop_anchor={"shop_id": 5, "name": "海底捞水晶城店"},
            ).model_dump(mode="json"),
        )

        self.assertEqual(result.follow_up_kind, "entity_reference")
        self.assertEqual(result.anchor_shop.name, "海底捞水晶城店")
        self.assertEqual(result.promoted_intent, "restaurant_detail")

    def test_classifies_price_ellipsis_without_new_shop_anchor(self) -> None:
        result = recover_follow_up_context(
            "便宜一点的呢？",
            session_context=PersistentSessionContext(
                current_topic="附近推荐",
                current_city="北京",
            ).model_dump(mode="json"),
        )

        self.assertEqual(result.follow_up_kind, "intent_ellipsis")
        self.assertIsNone(result.anchor_shop)
        self.assertEqual(result.promoted_intent, "restaurant_recommendation")

    def test_classifies_price_ellipsis_variants(self) -> None:
        result = recover_follow_up_context(
            "再便宜点呢？",
            session_context=PersistentSessionContext(
                current_topic="附近推荐",
                current_city="上海",
            ).model_dump(mode="json"),
        )

        self.assertEqual(result.follow_up_kind, "intent_ellipsis")
        self.assertIsNone(result.anchor_shop)
        self.assertEqual(result.inherited_constraints["city"], "上海")

    def test_classifies_constraint_inheritance(self) -> None:
        result = recover_follow_up_context(
            "川菜呢？",
            session_context=PersistentSessionContext(
                current_city="北京",
                current_scene="family_dinner",
            ).model_dump(mode="json"),
        )

        self.assertEqual(result.follow_up_kind, "constraint_inheritance")
        self.assertEqual(result.inherited_constraints["category"], "川菜")
        self.assertEqual(result.inherited_constraints["city"], "北京")

    def test_classifies_comparison_completion(self) -> None:
        result = recover_follow_up_context(
            "和海底捞比呢？",
            session_context=PersistentSessionContext(
                current_shop="湖畔私房菜",
                current_shop_anchor={"shop_id": 9, "name": "湖畔私房菜"},
            ).model_dump(mode="json"),
        )

        self.assertEqual(result.follow_up_kind, "comparison_completion")
        self.assertEqual(result.anchor_shop.name, "湖畔私房菜")
        self.assertEqual([item.name for item in result.comparison_targets], ["海底捞"])
        self.assertEqual(result.promoted_intent, "restaurant_comparison")

    def test_classifies_comparison_completion_with_explicit_anchor(self) -> None:
        result = recover_follow_up_context(
            "湖畔私房菜和海底捞比呢？",
            session_context=PersistentSessionContext(
                current_shop="湖畔私房菜",
                current_shop_anchor={"shop_id": 9, "name": "湖畔私房菜"},
            ).model_dump(mode="json"),
        )

        self.assertEqual(result.follow_up_kind, "comparison_completion")
        self.assertEqual(result.anchor_shop.name, "湖畔私房菜")
        self.assertEqual([item.name for item in result.comparison_targets], ["海底捞"])

    def test_price_and_comparison_phrases_do_not_become_anchor_shops(self) -> None:
        cheap_result = recover_follow_up_context("便宜一点的呢？", session_context={})
        compare_result = recover_follow_up_context("和海底捞比呢？", session_context={})

        self.assertNotEqual(cheap_result.follow_up_kind, "entity_reference")
        self.assertNotEqual(compare_result.follow_up_kind, "entity_reference")
        self.assertIsNone(cheap_result.anchor_shop)
        self.assertIsNone(compare_result.anchor_shop)


if __name__ == "__main__":
    unittest.main()
