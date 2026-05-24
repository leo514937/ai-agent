from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ImportError:  # pragma: no cover - environment without SQLAlchemy
    create_engine = None
    sessionmaker = None

from learning_agent_service.domain import MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.memory import DurableLongTermMemoryStore, DurableSemanticMemoryStore, LongTermMemoryRepository, QdrantLongTermMemoryIndex
from learning_agent_service.memory.models import SemanticMemoryFact


class _RecordingQdrantClient:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def upsert(self, **kwargs):
        self.upsert_calls.append(dict(kwargs))
        return None

    def delete(self, **kwargs):
        self.delete_calls.append(dict(kwargs))
        return None


class LongTermMemoryStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        if create_engine is None or sessionmaker is None:
            self.skipTest("SQLAlchemy is required for long-term memory store tests")
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        self.repository = LongTermMemoryRepository(self.session_factory)
        self.qdrant_client = _RecordingQdrantClient()
        self.index = QdrantLongTermMemoryIndex(client=self.qdrant_client, collection_name="user_memory", vector_size=32)
        self.store = DurableLongTermMemoryStore(repository=self.repository, index=self.index)
        self.semantic_store = DurableSemanticMemoryStore(long_term_store=self.store)

    def test_upsert_get_search_soft_delete_and_supersede(self) -> None:
        record = MemoryRecord(
            memory_id="mem-1",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "LangGraph 支持 workflow/state-machine"},
            summary="LangGraph 支持 workflow/state-machine",
            source_turn_id="turn-1",
            confidence=0.92,
            importance=0.88,
            stability=0.85,
            tags=["semantic", "langgraph"],
            entities=["LangGraph"],
        )

        stored = self.store.upsert(record)
        self.assertEqual(stored.memory_id, "mem-1")
        self.assertIsNotNone(stored.embedding_id)
        self.assertEqual(self.store.get("mem-1").summary, "LangGraph 支持 workflow/state-machine")

        search_results = self.store.search("workflow", user_id="user-1", limit=5)
        self.assertTrue(search_results)
        self.assertEqual(search_results[0].memory_id, "mem-1")

        self.store.soft_delete("mem-1", "cleanup")
        deleted = self.store.get("mem-1")
        self.assertEqual(deleted.status, MemoryStatus.DELETED)
        self.assertFalse(self.store.search("workflow", user_id="user-1", limit=5))
        self.assertTrue(self.qdrant_client.delete_calls)
        self.assertEqual(len(self.index.fallback_points), 0)

        second = self.store.upsert(
            MemoryRecord(
                memory_id="mem-2",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                content={"fact": "RAG 适合知识问答"},
                summary="RAG 适合知识问答",
                source_turn_id="turn-2",
                confidence=0.95,
                importance=0.9,
                stability=0.85,
                tags=["semantic", "rag"],
                entities=["RAG"],
            )
        )
        self.store.supersede("mem-2", "mem-1", "duplicate")
        superseded = self.store.get("mem-2")
        self.assertEqual(superseded.status, MemoryStatus.SUPERSEDED)

    def test_search_ignores_inactive_and_superseded_records(self) -> None:
        active = self.store.upsert(
            MemoryRecord(
                memory_id="mem-active",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                content={"fact": "active"},
                summary="active",
                source_turn_id="turn-1",
                confidence=0.9,
                importance=0.8,
                stability=0.85,
            )
        )
        inactive = self.store.upsert(
            MemoryRecord(
                memory_id="mem-inactive",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.INACTIVE,
                content={"fact": "inactive"},
                summary="inactive",
                source_turn_id="turn-2",
                confidence=0.7,
                importance=0.6,
                stability=0.7,
                is_active=False,
            )
        )
        self.store.supersede("mem-active", "mem-inactive", "conflict")

        results = self.store.search("active", user_id="user-1", limit=10)

        self.assertEqual([item.memory_id for item in results], [])
        self.assertEqual(len(self.qdrant_client.delete_calls), 0)
        self.assertEqual(len(self.index.fallback_points), 1)
        fallback_payload = next(iter(self.index.fallback_points.values()))["payload"]
        self.assertEqual(fallback_payload["status"], "superseded")
        self.assertFalse(fallback_payload["is_active"])
        self.assertEqual(self.store.get("mem-active").status, MemoryStatus.SUPERSEDED)
        self.assertEqual(self.store.get("mem-active").is_active, False)

    def test_durable_semantic_store_round_trip(self) -> None:
        fact = SemanticMemoryFact(
            fact_id="fact-1",
            topic="LangGraph",
            content="LangGraph 适合 workflow/state-machine",
            fact_type="semantic",
            strength=0.9,
            created_at=datetime.now(timezone.utc),
        )

        self.semantic_store.upsert("user-1", fact)
        results = self.semantic_store.search("user-1", "LangGraph workflow", limit=3)
        self.assertTrue(results)
        self.assertEqual(results[0].topic, "LangGraph")
        self.assertEqual(results[0].fact_id, "fact-1")


if __name__ == "__main__":
    unittest.main()
