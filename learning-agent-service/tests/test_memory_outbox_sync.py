from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("SQLAlchemy is not installed") from exc

from learning_agent_service.domain import MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.memory import DurableLongTermMemoryStore, LongTermMemoryRepository, QdrantLongTermMemoryIndex
from learning_agent_service.infrastructure.repositories.memory_outbox import MemoryOutboxRepository


class _FlakyQdrantClient:
    def __init__(self, *, fail_upserts: int = 0) -> None:
        self.fail_upserts = fail_upserts
        self.upsert_calls: list[dict[str, object]] = []
        self.set_payload_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def upsert(self, **kwargs):
        self.upsert_calls.append(dict(kwargs))
        if self.fail_upserts > 0:
            self.fail_upserts -= 1
            raise RuntimeError("qdrant upsert failed")
        return None

    def set_payload(self, **kwargs):
        self.set_payload_calls.append(dict(kwargs))
        return None

    def delete(self, **kwargs):
        self.delete_calls.append(dict(kwargs))
        return None


class MemoryOutboxSyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "memory.sqlite"
        self.engine = create_engine(
            f"sqlite+pysqlite:///{db_path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.repository = LongTermMemoryRepository(self.session_factory)
        self.outbox_repository = MemoryOutboxRepository(self.session_factory)
        self.qdrant_client = _FlakyQdrantClient(fail_upserts=1)
        self.index = QdrantLongTermMemoryIndex(client=self.qdrant_client, collection_name="user_memory", vector_size=32)
        self.store = DurableLongTermMemoryStore(
            repository=self.repository,
            index=self.index,
            memory_outbox_repository=self.outbox_repository,
        )

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        self.tempdir.cleanup()

    def _build_record(self, memory_id: str, summary: str, normalized_key: str = "food.spicy_preference", normalized_value: str = "likes_spicy") -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            user_id="user-1",
            session_id="session-1",
            source_session_id="session-1",
            type=MemoryType.PREFERENCE,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.USER_EXPLICIT,
            summary=summary,
            content={"normalized_key": normalized_key, "normalized_value": normalized_value},
            normalized_key=normalized_key,
            normalized_value=normalized_value,
            confidence=0.9,
            importance=0.8,
            stability=0.9,
            is_active=True,
            source_turn_id="turn-1",
        )

    def test_qdrant_sync_failure_retries_via_memory_outbox(self) -> None:
        record = MemoryRecord(
            memory_id="mem-1",
            user_id="user-1",
            session_id="session-1",
            source_session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.USER_EXPLICIT,
            summary="Qdrant retry test",
            content={"fact": "retry"},
            source_turn_id="turn-1",
            confidence=0.9,
            importance=0.8,
            stability=0.9,
            tags=["semantic"],
            entities=["Qdrant"],
        )

        stored = self.store.upsert(record)
        self.assertEqual(stored.memory_id, "mem-1")
        pending = self.outbox_repository.list_recent(limit=10, aggregate_type="memory", event_type_prefix="memory.vector")
        self.assertTrue(pending)
        self.assertEqual(pending[0].status, "pending")
        self.assertGreaterEqual(pending[0].attempts, 1)
        self.assertEqual(len(self.qdrant_client.upsert_calls), 1)

        self.qdrant_client.fail_upserts = 0
        retry_result = self.store.process_memory_outbox_once(limit=10)

        self.assertGreaterEqual(retry_result["published"], 1)
        self.assertEqual(self.outbox_repository.list_recent(limit=10, aggregate_type="memory", event_type_prefix="memory.vector")[0].status, "published")
        self.assertEqual(self.qdrant_client.delete_calls, [])
        self.assertTrue(self.qdrant_client.upsert_calls)

    def test_supersede_soft_deactivates_vector_without_delete(self) -> None:
        old_record = self._build_record("mem-old", "旧偏好", normalized_value="likes_spicy")
        new_record = self._build_record("mem-new", "新偏好", normalized_value="no_spicy")
        self.store.upsert(old_record)
        self.store.upsert(new_record)

        self.store.supersede("mem-old", "mem-new", "preference_changed")

        self.assertEqual(self.qdrant_client.delete_calls, [])
        self.assertTrue(self.qdrant_client.set_payload_calls)
        self.assertEqual(self.qdrant_client.set_payload_calls[-1]["payload"]["is_active"], False)

    def test_concurrent_active_updates_keep_single_row(self) -> None:
        barrier = threading.Barrier(2)
        results: list[str] = []
        errors: list[str] = []

        def worker(record: MemoryRecord) -> None:
            try:
                barrier.wait(timeout=5)
                stored = self.repository.upsert(record)
                results.append(stored.memory_id)
            except Exception as exc:  # pragma: no cover - thread failure path
                errors.append(str(exc))

        first = self._build_record("mem-a", "爱吃辣", normalized_value="likes_spicy")
        second = self._build_record("mem-b", "不吃辣", normalized_value="no_spicy")
        thread_a = threading.Thread(target=worker, args=(first,))
        thread_b = threading.Thread(target=worker, args=(second,))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        self.assertFalse(errors, msg=f"concurrent update errors: {errors}")
        self.assertEqual(len(results), 2)
        active_records = self.repository.find_active_by_user("user-1")
        spicy_active = [record for record in active_records if record.normalized_key == "food.spicy_preference"]

        self.assertEqual(len(spicy_active), 1)
        self.assertIn(spicy_active[0].normalized_value, {"likes_spicy", "no_spicy"})


if __name__ == "__main__":
    unittest.main()
