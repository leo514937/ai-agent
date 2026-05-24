from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain.memory import (
    MemoryCandidate,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryTargetStore,
    MemoryType,
)
from learning_agent_service.memory.governance import MemoryGovernancePolicy


class MemoryGovernanceTestCase(unittest.TestCase):
    def _build_candidate(self, *, sensitivity: MemorySensitivity) -> MemoryCandidate:
        return MemoryCandidate(
            should_promote=True,
            memory_type=MemoryType.SEMANTIC,
            target_store=MemoryTargetStore.POSTGRES,
            confidence=0.92,
            importance=0.8,
            stability=0.9,
            reason="test",
            source_turn_id="turn-1",
            record=MemoryRecord(
                memory_id="memory-1",
                user_id="user-1",
                session_id="session-1",
                topic="governance",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.MODEL_INFERRED,
                sensitivity=sensitivity,
                summary="治理测试",
                content={"fact": "memory"},
                source_turn_id="turn-1",
            ),
        )

    def test_approve_public_high_confidence_candidate(self) -> None:
        candidate = self._build_candidate(sensitivity=MemorySensitivity.PUBLIC)
        governed = MemoryGovernancePolicy().evaluate(candidate)

        self.assertEqual(governed.governance_action, "approve")
        self.assertTrue(governed.should_promote)
        self.assertFalse(governed.require_confirmation)

    def test_require_confirmation_for_restricted_candidate(self) -> None:
        candidate = self._build_candidate(sensitivity=MemorySensitivity.RESTRICTED)
        governed = MemoryGovernancePolicy().evaluate(candidate)

        self.assertEqual(governed.governance_action, "require_confirmation")
        self.assertTrue(governed.require_confirmation)
        self.assertFalse(governed.should_promote)


if __name__ == "__main__":
    unittest.main()
