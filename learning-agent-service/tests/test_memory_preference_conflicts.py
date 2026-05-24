from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain.memory import MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType
from learning_agent_service.memory.conflict import (
    ConflictResolutionAction,
    MemoryConflictResolver,
)


class MemoryPreferenceConflictTestCase(unittest.TestCase):
    def _build_record(
        self,
        *,
        memory_id: str,
        normalized_key: str,
        normalized_value: str,
        summary: str,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        confidence: float = 0.9,
        is_active: bool = True,
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            user_id="user-1",
            session_id="session-1",
            source_session_id="session-1",
            topic="food",
            type=MemoryType.PREFERENCE,
            scope=MemoryScope.USER,
            status=status,
            source=MemorySource.USER_EXPLICIT,
            summary=summary,
            content={"normalized_key": normalized_key, "normalized_value": normalized_value},
            normalized_key=normalized_key,
            normalized_value=normalized_value,
            confidence=confidence,
            importance=0.8,
            stability=0.9,
            is_active=is_active,
            source_turn_id="turn-1",
        )

    def test_temporary_constraint_resolves_to_session_only(self) -> None:
        resolver = MemoryConflictResolver()
        existing = self._build_record(
            memory_id="old",
            normalized_key="food.spicy_preference",
            normalized_value="likes_spicy",
            summary="我爱吃辣",
        )
        candidate = self._build_record(
            memory_id="new",
            normalized_key="food.spicy_preference",
            normalized_value="avoid_spicy_temporarily",
            summary="今天不想吃辣",
            confidence=0.7,
        )

        decision = resolver.resolve_preference_change(candidate, [existing], temporal_scope="session")

        self.assertEqual(decision.action, ConflictResolutionAction.SESSION_ONLY)
        self.assertFalse(decision.should_update_profile)
        self.assertFalse(decision.should_update_qdrant)
        self.assertEqual(decision.old_memory_id, "old")

    def test_long_term_change_supersedes_old_preference(self) -> None:
        resolver = MemoryConflictResolver()
        existing = self._build_record(
            memory_id="old",
            normalized_key="food.spicy_preference",
            normalized_value="likes_spicy",
            summary="我爱吃辣",
        )
        candidate = self._build_record(
            memory_id="new",
            normalized_key="food.spicy_preference",
            normalized_value="no_spicy",
            summary="我现在不吃辣了",
            confidence=0.95,
        )

        decision = resolver.resolve_preference_change(candidate, [existing], temporal_scope="long_term")

        self.assertEqual(decision.action, ConflictResolutionAction.SUPERSEDE_OLD_INSERT_NEW)
        self.assertTrue(decision.should_update_profile)
        self.assertFalse(decision.should_update_qdrant)
        self.assertEqual(decision.old_memory_id, "old")

    def test_same_value_updates_existing(self) -> None:
        resolver = MemoryConflictResolver()
        existing = self._build_record(
            memory_id="old",
            normalized_key="food.spicy_preference",
            normalized_value="no_spicy",
            summary="我不吃辣",
            confidence=0.7,
        )
        candidate = self._build_record(
            memory_id="new",
            normalized_key="food.spicy_preference",
            normalized_value="no_spicy",
            summary="我不吃辣",
            confidence=0.8,
        )

        decision = resolver.resolve_preference_change(candidate, [existing], temporal_scope="long_term")

        self.assertEqual(decision.action, ConflictResolutionAction.UPDATE_EXISTING)
        self.assertEqual(decision.old_memory_id, "old")
        self.assertEqual(decision.new_memory.memory_id, "old")
        self.assertAlmostEqual(decision.confidence, 0.8, places=4)

    def test_ambiguous_recent_expression_stays_session_only(self) -> None:
        resolver = MemoryConflictResolver()
        existing = self._build_record(
            memory_id="old",
            normalized_key="food.spicy_preference",
            normalized_value="likes_spicy",
            summary="我爱吃辣",
        )
        candidate = self._build_record(
            memory_id="new",
            normalized_key="food.spicy_preference",
            normalized_value="avoid_spicy_temporarily",
            summary="最近不太想吃辣",
            confidence=0.65,
        )

        decision = resolver.resolve_preference_change(candidate, [existing], temporal_scope="ambiguous")

        self.assertEqual(decision.action, ConflictResolutionAction.SESSION_ONLY)
        self.assertIn("ambiguous", decision.reason)


if __name__ == "__main__":
    unittest.main()
