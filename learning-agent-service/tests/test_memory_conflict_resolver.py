from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain.memory import (
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from learning_agent_service.memory.conflict import MemoryConflictResolutionStrategy, MemoryConflictResolver


class MemoryConflictResolverTestCase(unittest.TestCase):
    def _build_record(self, *, memory_id: str, confidence: float, sensitivity: MemorySensitivity) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            user_id="user-1",
            session_id="session-1",
            topic="conflict",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            confidence=confidence,
            importance=0.8,
            stability=0.9,
            sensitivity=sensitivity,
            summary="冲突测试",
            content={"fact": memory_id},
            source_turn_id="turn-1",
        )

    def test_high_confidence_new_record_supersedes_old_record(self) -> None:
        resolver = MemoryConflictResolver()
        old_record = self._build_record(memory_id="old", confidence=0.6, sensitivity=MemorySensitivity.PUBLIC)
        new_record = self._build_record(memory_id="new", confidence=0.95, sensitivity=MemorySensitivity.PUBLIC)

        result = resolver.resolve(new_record, [old_record])

        self.assertEqual(result.strategy, MemoryConflictResolutionStrategy.SUPERSEDE_OLD)
        self.assertEqual(result.winner.memory_id, "new")
        self.assertEqual([item.memory_id for item in result.losers], ["old"])

    def test_restricted_record_requires_confirmation(self) -> None:
        resolver = MemoryConflictResolver()
        new_record = self._build_record(memory_id="new", confidence=0.95, sensitivity=MemorySensitivity.RESTRICTED)

        result = resolver.resolve(new_record, [])

        self.assertEqual(result.strategy, MemoryConflictResolutionStrategy.REQUIRE_CONFIRMATION)
        self.assertTrue(result.requires_confirmation)
        self.assertEqual(result.winner.memory_id, "new")


if __name__ == "__main__":
    unittest.main()
