from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router.stages.query_merge import merge_local_life_query_context
from learning_agent_service.domain.contracts import PersistentSessionContext
from learning_agent_service.local_life.query_rewriter import normalize_query
from learning_agent_service.local_life.slot_extractor import extract_slots
from learning_agent_service.local_life.schemas import LocalLifeIntentType


class FourCaseContextRecoveryE2ETestCase(unittest.TestCase):
    def _run_pipeline(
        self,
        raw_query: str,
        *,
        persistent: PersistentSessionContext,
        client_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        client_context = dict(client_context or {})
        session_context = persistent.model_dump(mode="json")
        understanding = normalize_query(
            raw_query,
            client_context=client_context,
            session_context=session_context,
        )
        slots, clarification, intent = extract_slots(
            understanding,
            raw_query,
            client_context=client_context,
            session_context=session_context,
        )
        merged = merge_local_life_query_context(
            raw_query,
            persistent=persistent,
            parser_slots=slots.model_dump(mode="json"),
            client_context=client_context,
        )
        return {
            "understanding": understanding,
            "slots": slots,
            "clarification": clarification,
            "intent": intent,
            "merged": merged,
        }

    def test_entity_reference_follow_up_uses_session_shop_anchor(self) -> None:
        persistent = PersistentSessionContext(
            current_shop="海底捞水晶城店",
            current_shop_anchor={"shop_id": 5, "name": "海底捞水晶城店"},
            selected_shop_name="海底捞水晶城店",
            selected_shop_id=5,
        )
        result = self._run_pipeline(
            "这家有券吗？",
            persistent=persistent,
            client_context={"shopName": "海底捞水晶城店"},
        )

        understanding = result["understanding"]
        slots = result["slots"]
        clarification = result["clarification"]
        merged = result["merged"]

        self.assertFalse(clarification.need_clarification)
        self.assertEqual(result["intent"], LocalLifeIntentType.COUPON)
        self.assertEqual(slots.action, LocalLifeIntentType.COUPON)
        self.assertEqual(understanding.extra["shop_query"], "海底捞水晶城店")
        self.assertEqual(understanding.extra["follow_up_kind"], "entity_reference")
        self.assertEqual(merged.current_shop, "海底捞水晶城店")
        self.assertEqual(merged.candidate_shop_ids, [5])

    def test_intent_ellipsis_keeps_recommendation_context_without_new_anchor(self) -> None:
        persistent = PersistentSessionContext(
            current_topic="附近推荐了 A/B/C",
            current_city="北京",
            current_location={"city": "北京"},
            last_candidates=[
                {"shop_id": 1, "name": "A"},
                {"shop_id": 2, "name": "B"},
            ],
        )
        result = self._run_pipeline(
            "便宜一点的呢？",
            persistent=persistent,
        )

        understanding = result["understanding"]
        slots = result["slots"]
        clarification = result["clarification"]
        merged = result["merged"]

        self.assertFalse(clarification.need_clarification)
        self.assertEqual(result["intent"], LocalLifeIntentType.RESTAURANT_RECOMMENDATION)
        self.assertIsNone(slots.shop_query)
        self.assertEqual(understanding.extra["follow_up_kind"], "intent_ellipsis")
        self.assertEqual(understanding.extra["inherited_constraints"]["city"], "北京")
        self.assertIsNone(merged.current_shop)
        self.assertIsNone(merged.target_reference)
        self.assertEqual(merged.candidate_shop_ids, [])

    def test_constraint_inheritance_preserves_city_scene_and_new_category(self) -> None:
        persistent = PersistentSessionContext(
            current_city="北京",
            current_scene="family_dinner",
            current_constraints={
                "scene": "family_dinner",
                "location": {"city": "北京", "radius_km": 3},
            },
        )
        result = self._run_pipeline(
            "川菜呢？",
            persistent=persistent,
        )

        understanding = result["understanding"]
        slots = result["slots"]
        clarification = result["clarification"]
        merged = result["merged"]

        self.assertFalse(clarification.need_clarification)
        self.assertEqual(result["intent"], LocalLifeIntentType.RESTAURANT_RECOMMENDATION)
        self.assertEqual(slots.city, "北京")
        self.assertEqual(slots.scene, "family_dinner")
        self.assertEqual(slots.category, "川菜")
        self.assertEqual(understanding.extra["follow_up_kind"], "constraint_inheritance")
        self.assertEqual(understanding.extra["inherited_constraints"]["category"], "川菜")
        self.assertIsNone(merged.current_shop)
        self.assertIsNone(merged.target_reference)

    def test_comparison_follow_up_promotes_comparison_intent_and_targets(self) -> None:
        persistent = PersistentSessionContext(
            current_shop="湖畔私房菜",
            current_shop_anchor={"shop_id": 9, "name": "湖畔私房菜"},
            selected_shop_name="湖畔私房菜",
            selected_shop_id=9,
            last_candidates=[
                {"shop_id": 9, "name": "湖畔私房菜"},
                {"shop_id": 5, "name": "海底捞水晶城店"},
            ],
        )
        result = self._run_pipeline(
            "和海底捞比呢？",
            persistent=persistent,
        )

        understanding = result["understanding"]
        slots = result["slots"]
        clarification = result["clarification"]
        merged = result["merged"]

        self.assertFalse(clarification.need_clarification)
        self.assertEqual(result["intent"], LocalLifeIntentType.RESTAURANT_COMPARISON)
        self.assertEqual(slots.action, LocalLifeIntentType.RESTAURANT_COMPARISON)
        self.assertEqual(understanding.extra["follow_up_kind"], "comparison_completion")
        self.assertEqual(understanding.extra["comparison_targets"], ["海底捞"])
        self.assertEqual(merged.current_shop, "湖畔私房菜")
        self.assertEqual(merged.target_reference, "湖畔私房菜")
        self.assertEqual(merged.candidate_shop_ids, [9])


if __name__ == "__main__":
    unittest.main()
