from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("SQLAlchemy is not installed") from exc

from learning_agent_service.domain.memory import (
    MemoryDeletionStatus,
    MemoryEdgeType,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    MemoryTargetStore,
    MemoryType,
)
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.repositories.memory_record_repository import MemoryRecordRepository


class MemoryRecordRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.repository = MemoryRecordRepository(self.session_factory)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_create_and_find_active_by_user(self) -> None:
        record = MemoryRecord(
            memory_id="mem-active",
            user_id="user-1",
            session_id="session-1",
            project_id="project-1",
            topic="pytest",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            summary="pytest 的基础用法",
            content={"fact": "pytest is a test runner"},
            confidence=0.92,
            importance=0.81,
            stability=0.73,
            source_turn_id="turn-1",
            vector_id="vec-1",
            raw_evidence={"source": "unit-test"},
        )

        created = self.repository.create(record)
        self.assertEqual(created.memory_id, "mem-active")

        active = self.repository.find_active_by_user("user-1")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].memory_id, "mem-active")
        self.assertEqual(active[0].topic, "pytest")
        self.assertEqual(active[0].vector_id, "vec-1")

    def test_update_status_increment_access_and_soft_delete(self) -> None:
        record = MemoryRecord(
            memory_id="mem-2",
            user_id="user-2",
            session_id="session-2",
            topic="sqlalchemy",
            type=MemoryType.EPISODIC,
            scope=MemoryScope.SESSION,
            status=MemoryStatus.CONFIRMED,
            source=MemorySource.SYSTEM_EVENT,
            summary="第一次会话",
            content={"turn": "turn-2"},
            source_turn_id="turn-2",
        )
        self.repository.create(record)

        updated = self.repository.update_status("mem-2", MemoryStatus.SUPERSEDED)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, MemoryStatus.SUPERSEDED)

        incremented = self.repository.increment_access_count("mem-2")
        self.assertIsNotNone(incremented)
        self.assertEqual(incremented.access_count, 1)

        deleted = self.repository.soft_delete("mem-2", reason="test cleanup")
        self.assertIsNotNone(deleted)
        self.assertEqual(deleted.status, MemoryStatus.DELETED)

        jobs = self.repository.list_deletion_jobs(status=MemoryDeletionStatus.PENDING)
        self.assertEqual({job.target_store for job in jobs}, {MemoryTargetStore.POSTGRES, MemoryTargetStore.QDRANT, MemoryTargetStore.REDIS})
        self.assertEqual(len(jobs), 3)

    def test_find_potential_conflicts_and_mark_superseded(self) -> None:
        old_record = MemoryRecord(
            memory_id="mem-old",
            user_id="user-3",
            session_id="session-3",
            topic="memory-governance",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            summary="旧记忆",
            content={"fact": "old"},
            source_turn_id="turn-old",
        )
        new_record = MemoryRecord(
            memory_id="mem-new",
            user_id="user-3",
            session_id="session-4",
            topic="memory-governance",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            summary="新记忆",
            content={"fact": "new"},
            source_turn_id="turn-new",
        )
        self.repository.create(old_record)
        self.repository.create(new_record)

        conflicts = self.repository.find_potential_conflicts(
            user_id="user-3",
            scope=MemoryScope.USER,
            topic="memory-governance",
            memory_type=MemoryType.SEMANTIC,
        )
        self.assertEqual({item.memory_id for item in conflicts}, {"mem-old", "mem-new"})

        edge = self.repository.mark_superseded(
            memory_id="mem-old",
            superseded_by="mem-new",
            reason="更高置信度",
            edge_type=MemoryEdgeType.SUPERSEDES,
        )
        self.assertIsNotNone(edge)
        self.assertEqual(edge.source_memory_id, "mem-old")
        self.assertEqual(edge.target_memory_id, "mem-new")

        superseded = self.repository.get("mem-old")
        self.assertIsNotNone(superseded)
        self.assertEqual(superseded.status, MemoryStatus.SUPERSEDED)
        self.assertEqual(superseded.superseded_by, "mem-new")

        jobs = self.repository.list_deletion_jobs(status=MemoryDeletionStatus.PENDING)
        self.assertIsInstance(jobs, list)

    def test_find_active_by_user_filters_inactive_and_time_bounded_records(self) -> None:
        active = MemoryRecord(
            memory_id="mem-active-2",
            user_id="user-4",
            session_id="session-4",
            topic="filtering",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.MODEL_INFERRED,
            summary="active",
            content={"fact": "active"},
            source_turn_id="turn-active",
            is_active=True,
        )
        inactive = MemoryRecord(
            memory_id="mem-inactive-2",
            user_id="user-4",
            session_id="session-4",
            topic="filtering",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.INACTIVE,
            source=MemorySource.MODEL_INFERRED,
            summary="inactive",
            content={"fact": "inactive"},
            source_turn_id="turn-inactive",
            is_active=False,
        )
        self.repository.create(active)
        self.repository.create(inactive)

        results = self.repository.find_active_by_user("user-4")

        self.assertEqual([item.memory_id for item in results], ["mem-active-2"])


if __name__ == "__main__":
    unittest.main()
