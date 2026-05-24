from __future__ import annotations

import unittest
from dataclasses import dataclass

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("SQLAlchemy is not installed") from exc

from learning_agent_service.domain import MemoryCandidate, MemoryRecord, MemoryScope, MemoryStatus, MemoryTargetStore, MemoryType
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.db.redis import RedisKeySpace, RedisRuntime
from learning_agent_service.infrastructure.memory import DurableLongTermMemoryStore, LongTermMemoryRepository, QdrantLongTermMemoryIndex
from learning_agent_service.memory.jobs import MemoryDeletionWorker, MemoryMaintenanceJob
from learning_agent_service.memory.stores import InMemoryLongTermMemoryStore, InMemoryShortTermMemoryStore
from learning_agent_service.memory.consolidation import MemoryConsolidationJob
from learning_agent_service.memory.orchestrator import MemoryOrchestrator, MemoryOrchestratorPolicyConfig


class _RecordingQdrantClient:
    def __init__(self) -> None:
        self.delete_calls: list[dict[str, object]] = []

    def upsert(self, **kwargs):
        return None

    def delete(self, **kwargs):
        self.delete_calls.append(dict(kwargs))
        return None


class _RecordingRedisClient:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    def delete(self, *keys):
        self.deleted_keys.extend(list(keys))
        return len(keys)


@dataclass
class _FakeSessionStore:
    windows: dict[str, list[dict[str, object]]]
    task_contexts: dict[str, dict[str, object]]


class MemoryJobsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.repository = LongTermMemoryRepository(self.session_factory)
        self.qdrant_client = _RecordingQdrantClient()
        self.index = QdrantLongTermMemoryIndex(client=self.qdrant_client, collection_name="user_memory", vector_size=16)
        self.store = DurableLongTermMemoryStore(repository=self.repository, index=self.index)
        self.redis_client = _RecordingRedisClient()
        self.redis_runtime = RedisRuntime(client=self.redis_client, keys=RedisKeySpace(prefix="learning"))
        self.short_term_store = InMemoryShortTermMemoryStore()

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_deletion_worker_processes_all_store_targets(self) -> None:
        record = MemoryRecord(
            memory_id="mem-delete",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "delete me"},
            summary="delete me",
            source_turn_id="turn-1",
            vector_id="vec-1",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
        )
        self.store.upsert(record)
        self.short_term_store.append_messages("session-1", [{"role": "user", "content": "hello"}])
        self.short_term_store.save_task_context("session-1", {"current_topic": "LangGraph"})
        self.repository.soft_delete("mem-delete", "cleanup")

        worker = MemoryDeletionWorker(
            repository=self.repository,
            qdrant_index=self.index,
            redis_runtime=self.redis_runtime,
            short_term_store=self.short_term_store,
        )

        result = worker.run_once()
        self.assertEqual(result["succeeded"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(self.qdrant_client.delete_calls), 1)
        self.assertIn(self.redis_runtime.keys.session_state("session-1"), self.redis_client.deleted_keys)
        self.assertNotIn("session-1", self.short_term_store.windows)
        self.assertNotIn("session-1", self.short_term_store.task_contexts)

        jobs = self.repository.list_deletion_jobs()
        self.assertTrue(all(job.status.value == "succeeded" for job in jobs))

    def test_maintenance_job_runs_consolidation_and_worker(self) -> None:
        record = MemoryRecord(
            memory_id="mem-expired",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.PROCEDURAL,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"step": "old"},
            summary="old",
            source_turn_id="turn-1",
            expires_at=None,
            confidence=0.9,
            importance=0.8,
            stability=0.8,
        )
        self.store.upsert(record)
        self.repository.soft_delete("mem-expired", "cleanup")

        orchestrator = MemoryOrchestrator(
            session_store=object(),
            long_term_store=self.store,
            short_term_store=InMemoryShortTermMemoryStore(),
            consolidation_job=MemoryConsolidationJob(),
        )
        worker = MemoryDeletionWorker(
            repository=self.repository,
            qdrant_index=self.index,
            redis_runtime=self.redis_runtime,
            short_term_store=self.short_term_store,
        )
        maintenance = MemoryMaintenanceJob(orchestrator=orchestrator, deletion_worker=worker)

        result = maintenance.run(user_id="user-1")
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["merged_count"], 0)
        self.assertEqual(result["deletion_summary"]["succeeded"], 3)

    def test_orchestrator_uses_configured_confirmation_threshold(self) -> None:
        store = InMemoryLongTermMemoryStore()
        orchestrator = MemoryOrchestrator(
            session_store=object(),
            long_term_store=store,
            short_term_store=InMemoryShortTermMemoryStore(),
            consolidation_job=MemoryConsolidationJob(),
            policy=MemoryOrchestratorPolicyConfig(confirmed_confidence_threshold=0.9),
        )
        inferred_record = MemoryRecord(
            memory_id="mem-inferred",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "inferred"},
            summary="inferred",
            source_turn_id="turn-1",
            confidence=0.85,
            importance=0.8,
        )
        confirmed_record = MemoryRecord(
            memory_id="mem-confirmed",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "confirmed"},
            summary="confirmed",
            source_turn_id="turn-2",
            confidence=0.95,
            importance=0.8,
        )
        orchestrator._persist_candidates(
            [
                MemoryCandidate(
                    candidate_id="candidate-inferred",
                    should_promote=True,
                    memory_type=MemoryType.SEMANTIC,
                    target_store=MemoryTargetStore.POSTGRES,
                    confidence=0.85,
                    importance=0.8,
                    reason="test",
                    source_turn_id="turn-1",
                    record=inferred_record,
                ),
                MemoryCandidate(
                    candidate_id="candidate-confirmed",
                    should_promote=True,
                    memory_type=MemoryType.SEMANTIC,
                    target_store=MemoryTargetStore.POSTGRES,
                    confidence=0.95,
                    importance=0.8,
                    reason="test",
                    source_turn_id="turn-2",
                    record=confirmed_record,
                ),
            ]
        )
        self.assertEqual(store.records["mem-inferred"].status, MemoryStatus.INFERRED)
        self.assertEqual(store.records["mem-confirmed"].status, MemoryStatus.CONFIRMED)


if __name__ == "__main__":
    unittest.main()
