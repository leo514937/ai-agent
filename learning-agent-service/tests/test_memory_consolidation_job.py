from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import _bootstrap  # noqa: F401

from learning_agent_service.domain import MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from learning_agent_service.memory.consolidation import ConsolidationPolicyConfig, MemoryConsolidationJob


class MemoryConsolidationJobTestCase(unittest.TestCase):
    def test_consolidate_prefers_high_value_duplicate(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            MemoryRecord(
                memory_id="mem-1",
                user_id="user-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                content={"fact": "LangGraph"},
                summary="LangGraph 支持 workflow",
                source_turn_id="turn-1",
                confidence=0.7,
                importance=0.6,
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(days=2),
            ),
            MemoryRecord(
                memory_id="mem-2",
                user_id="user-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.CONFIRMED,
                content={"fact": "LangGraph"},
                summary="LangGraph 支持 workflow",
                source_turn_id="turn-2",
                confidence=0.95,
                importance=0.9,
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            ),
        ]

        job = MemoryConsolidationJob()
        merged, conflicts, plans = job.consolidate(records)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].memory_id, "mem-2")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].winner_memory_id, "mem-2")
        self.assertEqual(len(plans), 1)

    def test_expire_marks_outdated_records(self) -> None:
        expired = MemoryRecord(
            memory_id="mem-expired",
            user_id="user-1",
            type=MemoryType.PROCEDURAL,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"sop": "先理解，再路由"},
            summary="先理解，再路由",
            source_turn_id="turn-1",
            confidence=0.8,
            importance=0.75,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        job = MemoryConsolidationJob()
        updated = job.expire_or_supersede([expired])
        self.assertEqual(updated[0].status, MemoryStatus.EXPIRED)

    def test_custom_policy_controls_merge_and_score(self) -> None:
        now = datetime.now(timezone.utc)
        records = [
            MemoryRecord(
                memory_id="mem-1",
                user_id="user-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                content={"fact": "LangGraph"},
                summary="LangGraph 支持 workflow",
                source_turn_id="turn-1",
                confidence=0.7,
                importance=0.6,
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(days=2),
            ),
            MemoryRecord(
                memory_id="mem-2",
                user_id="user-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.CONFIRMED,
                content={"fact": "LangGraph"},
                summary="LangGraph 支持 workflow",
                source_turn_id="turn-2",
                confidence=0.95,
                importance=0.9,
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            ),
            MemoryRecord(
                memory_id="mem-3",
                user_id="user-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                content={"fact": "LangGraph"},
                summary="LangGraph 支持 workflow",
                source_turn_id="turn-3",
                confidence=0.88,
                importance=0.85,
                created_at=now - timedelta(hours=12),
                updated_at=now - timedelta(hours=12),
            ),
        ]

        job = MemoryConsolidationJob(
            config=ConsolidationPolicyConfig(
                minimum_duplicate_group_size=2,
                max_conflicts=1,
                confirmed_explicitness=1.75,
                inferred_explicitness=0.25,
                recency_window_seconds=60 * 60 * 24,
            )
        )
        merged, conflicts, plans = job.consolidate(records)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(len(plans), 1)
        confirmed = MemoryRecord(
            memory_id="score-confirmed",
            user_id="user-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.CONFIRMED,
            content={"fact": "LangGraph"},
            summary="LangGraph 支持 workflow",
            source_turn_id="turn-score-1",
            confidence=0.8,
            importance=0.7,
            updated_at=now,
        )
        inferred = MemoryRecord(
            memory_id="score-inferred",
            user_id="user-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.INFERRED,
            content={"fact": "LangGraph"},
            summary="LangGraph 支持 workflow",
            source_turn_id="turn-score-2",
            confidence=0.8,
            importance=0.7,
            updated_at=now,
        )
        self.assertGreater(job.score_memory(confirmed), job.score_memory(inferred))
        self.assertAlmostEqual(job.score_memory(confirmed) - job.score_memory(inferred), 1.5, places=1)


if __name__ == "__main__":
    unittest.main()
