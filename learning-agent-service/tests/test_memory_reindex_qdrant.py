from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.config import Settings
from learning_agent_service.domain.memory import MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.repositories.memory_record_repository import MemoryRecordRepository
from learning_agent_service.memory.reindex_qdrant import reindex_memory_collection

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ImportError as exc:  # pragma: no cover - optional dependency in some environments
    raise unittest.SkipTest("SQLAlchemy is required for memory reindex tests") from exc


class _FakeQdrantClient:
    def __init__(self, *, existing_size: int | None = None, distance: str = "cosine", embedding_size: int | None = None) -> None:
        self.collections: dict[str, dict[str, object]] = {}
        self.create_collection_calls: list[dict[str, object]] = []
        self.delete_collection_calls: list[str] = []
        self.payload_index_calls: list[dict[str, object]] = []
        self.upsert_calls: list[dict[str, object]] = []
        self.embedding_size = embedding_size
        if existing_size is not None:
            self.collections["memory"] = {
                "size": existing_size,
                "distance": distance,
            }

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def get_collection(self, collection_name: str):
        if collection_name not in self.collections:
            raise RuntimeError("missing collection")
        config = SimpleNamespace(
            params=SimpleNamespace(
                vectors={
                    "embedding": SimpleNamespace(
                        size=self.collections[collection_name]["size"],
                        distance=self.collections[collection_name]["distance"],
                    )
                }
            )
        )
        return SimpleNamespace(config=config)

    def delete_collection(self, collection_name: str):
        self.delete_collection_calls.append(collection_name)
        self.collections.pop(collection_name, None)

    def create_collection(self, **kwargs):
        self.create_collection_calls.append(dict(kwargs))
        vectors_config = kwargs.get("vectors_config") or {}
        vector_params = vectors_config.get("embedding")
        self.collections[kwargs["collection_name"]] = {
            "size": getattr(vector_params, "size", None),
            "distance": getattr(vector_params, "distance", None),
        }

    def create_payload_index(self, **kwargs):
        self.payload_index_calls.append(dict(kwargs))

    def upsert(self, **kwargs):
        self.upsert_calls.append(dict(kwargs))


class _FakeOpenAIAdapter:
    def __init__(self, vector_size: int) -> None:
        self.vector_size = vector_size
        self.client = SimpleNamespace(
            embeddings=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1] * self.vector_size)]
                )
            )
        )
        self.default_model = "fake-embedding-model"


class _FakeShortEmbeddingAdapter(_FakeOpenAIAdapter):
    def __init__(self) -> None:
        super().__init__(vector_size=64)


class MemoryReindexQdrantTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.repository = MemoryRecordRepository(self.session_factory)
        self.settings = Settings(
            prefer_real_adapters=True,
            allow_in_memory_fallback=True,
            qdrant={"memory_vector_size": 1536, "memory_vector_name": "embedding", "memory_collection": "memory"},
            openai={"embedding_model": "fake-embedding-model"},
        )

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _persist_records(self) -> None:
        records = [
            MemoryRecord(
                memory_id="semantic-active",
                user_id="user-1",
                session_id="session-1",
                source_session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.MODEL_INFERRED,
                summary="active semantic",
                content={"fact": "active semantic"},
                confidence=0.9,
                importance=0.9,
                stability=0.9,
                should_vectorize=True,
                source_turn_id="turn-1",
                tags=["semantic"],
            ),
            MemoryRecord(
                memory_id="episodic-active",
                user_id="user-1",
                session_id="session-1",
                source_session_id="session-1",
                type=MemoryType.EPISODIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.CONFIRMED,
                source=MemorySource.MODEL_INFERRED,
                summary="active episodic",
                content={"fact": "active episodic"},
                confidence=0.9,
                importance=0.8,
                stability=0.8,
                should_vectorize=True,
                source_turn_id="turn-2",
                tags=["episodic"],
            ),
            MemoryRecord(
                memory_id="procedural-active",
                user_id="user-1",
                session_id="session-1",
                source_session_id="session-1",
                type=MemoryType.PROCEDURAL,
                scope=MemoryScope.PROJECT,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.MODEL_INFERRED,
                summary="active procedural",
                content={"fact": "active procedural"},
                confidence=0.9,
                importance=0.85,
                stability=0.8,
                should_vectorize=True,
                source_turn_id="turn-3",
                tags=["procedural"],
            ),
            MemoryRecord(
                memory_id="semantic-inactive",
                user_id="user-1",
                session_id="session-1",
                source_session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.INACTIVE,
                source=MemorySource.MODEL_INFERRED,
                summary="inactive semantic",
                content={"fact": "inactive"},
                confidence=0.9,
                importance=0.9,
                stability=0.9,
                should_vectorize=True,
                is_active=False,
                source_turn_id="turn-4",
            ),
            MemoryRecord(
                memory_id="session-pollution",
                user_id="user-1",
                session_id="session-1",
                source_session_id="session-1",
                type=MemoryType.SHORT_TERM,
                scope=MemoryScope.SESSION,
                status=MemoryStatus.OBSERVED,
                source=MemorySource.SYSTEM_EVENT,
                summary="这个问题还不够具体，请补充范围",
                content={"fact": "polluted"},
                confidence=0.2,
                importance=0.1,
                stability=0.1,
                should_vectorize=False,
                ttl_seconds=3600,
                source_turn_id="turn-5",
            ),
        ]
        for record in records:
            self.repository.create(record)

    def test_reindex_only_indexes_active_vectorizable_memory(self) -> None:
        self._persist_records()
        fake_qdrant = _FakeQdrantClient()
        infra = SimpleNamespace(
            postgres=SimpleNamespace(session_factory=self.session_factory),
            qdrant=SimpleNamespace(client=fake_qdrant),
            openai=_FakeOpenAIAdapter(vector_size=1536),
        )

        result = reindex_memory_collection(
            self.settings,
            infra=infra,
            collection_name="memory",
            vector_size=1536,
            vector_name="embedding",
        )

        self.assertEqual(result.scanned_memory_count, 3)
        self.assertEqual(result.indexed_memory_count, 3)
        self.assertEqual(result.failed_memory_count, 0)
        self.assertEqual(
            {call["points"][0].payload["memory_id"] for call in fake_qdrant.upsert_calls},
            {"semantic-active", "episodic-active", "procedural-active"},
        )

    def test_drop_existing_recreates_collection(self) -> None:
        fake_qdrant = _FakeQdrantClient(existing_size=64)
        infra = SimpleNamespace(
            postgres=SimpleNamespace(session_factory=self.session_factory),
            qdrant=SimpleNamespace(client=fake_qdrant),
            openai=_FakeOpenAIAdapter(vector_size=1536),
        )

        result = reindex_memory_collection(
            self.settings,
            infra=infra,
            collection_name="memory",
            vector_size=1536,
            vector_name="embedding",
            drop_existing=True,
            expected_old_vector_size=64,
        )

        self.assertEqual(fake_qdrant.delete_collection_calls, ["memory"])
        self.assertEqual(fake_qdrant.create_collection_calls[0]["collection_name"], "memory")
        self.assertEqual(result.vector_size, 1536)

    def test_embedding_dimension_mismatch_raises(self) -> None:
        self._persist_records()
        fake_qdrant = _FakeQdrantClient()
        infra = SimpleNamespace(
            postgres=SimpleNamespace(session_factory=self.session_factory),
            qdrant=SimpleNamespace(client=fake_qdrant),
            openai=_FakeShortEmbeddingAdapter(),
        )

        with self.assertRaisesRegex(RuntimeError, "memory reindex failed"):
            reindex_memory_collection(
                self.settings,
                infra=infra,
                collection_name="memory",
                vector_size=1536,
                vector_name="embedding",
            )


if __name__ == "__main__":
    unittest.main()
