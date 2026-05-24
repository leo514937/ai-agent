from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.memory.models import MemoryPromotionInput, PersistentSessionContext
from learning_agent_service.memory.promotion import MemoryPromotionPolicy


class MemoryPromotionGuardrailsTestCase(unittest.TestCase):
    def test_clarification_event_stays_session_only(self) -> None:
        result = MemoryPromotionPolicy().evaluate(
            MemoryPromotionInput(
                session_id="session-clarify",
                turn_id="turn-clarify",
                user_id="user-1",
                query="附近有什么好的推荐才",
                answer_text="这个问题还不够具体，请补充范围。",
                resolved_topic="附近推荐",
                current_session=PersistentSessionContext(current_topic="附近推荐"),
                extra={
                    "clarification_result": {"missing_slots": ["location"]},
                    "missing_slots": {"location": "范围"},
                },
            )
        )

        session_requests = [item for item in result.durable_fact_requests if item.fact_type == "session_fact"]
        self.assertTrue(session_requests)
        payload = dict(session_requests[0].payload)
        self.assertEqual(payload["source"], "system_event")
        self.assertEqual(payload["memory_type"], "short_term")
        self.assertEqual(payload["scope"], "session")
        self.assertFalse(payload["should_vectorize"])
        self.assertIsNotNone(payload["ttl_seconds"])
        self.assertEqual(payload["ttl_seconds"], 86400)
        self.assertFalse(result.semantic_facts)
        self.assertTrue(result.session_update.pending_clarification)

    def test_long_term_preference_emits_profile_update(self) -> None:
        result = MemoryPromotionPolicy().evaluate(
            MemoryPromotionInput(
                session_id="session-preference",
                turn_id="turn-preference",
                user_id="user-1",
                query="我以后不吃辣",
                answer_text="我以后不吃辣",
                current_session=PersistentSessionContext(),
            )
        )

        self.assertTrue(result.profile_updates)
        profile_update = dict(result.profile_updates[0])
        self.assertEqual(profile_update["preference_key"], "food.spicy_preference")
        self.assertEqual(profile_update["current_value"], "no_spicy")
        self.assertEqual(profile_update["confidence"], 0.96)

    def test_guest_low_value_query_stays_session_only(self) -> None:
        result = MemoryPromotionPolicy().evaluate(
            MemoryPromotionInput(
                session_id="session-guest",
                turn_id="turn-guest",
                user_id="guest",
                query="附近有什么好的推荐才",
                answer_text="这个问题还不够具体，请补充范围。",
                resolved_topic="附近推荐",
                current_session=PersistentSessionContext(current_topic="附近推荐"),
            )
        )

        session_requests = [item for item in result.durable_fact_requests if item.fact_type == "session_fact"]
        self.assertTrue(session_requests)
        payload = dict(session_requests[0].payload)
        self.assertEqual(payload["scope"], "session")
        self.assertFalse(payload["should_vectorize"])
        self.assertIsNotNone(payload["ttl_seconds"])
        self.assertLessEqual(payload["importance"], 0.2)
        self.assertLessEqual(payload["stability"], 0.2)


if __name__ == "__main__":
    unittest.main()
