from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ImportError:  # pragma: no cover - environment without SQLAlchemy
    create_engine = None
    sessionmaker = None

from learning_agent_service.application.dependencies import _resolve_memory_vector_size
from learning_agent_service.domain import MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType
from learning_agent_service.infrastructure.db.factories import InfrastructureClients
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime
from learning_agent_service.infrastructure.memory import LongTermMemoryRepository
from learning_agent_service.memory.reindex_qdrant import reindex_memory_collection


class _FakeEmbeddingsAPI:
    def __init__(self, vector_size: int) -> None:
        self.vector_size = vector_size
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * self.vector_size)])


class _FakeQdrantClient:
    def __init__(self, *, collection_exists: bool = True, vector_size: int = 64, distance: str = "cosine") -> None:
        self.collection_exists_flag = collection_exists
        self.vector_size = vector_size
        self.distance = distance
        self.collection_exists_calls: list[str] = []
        self.get_collection_calls: list[str] = []
        self.create_collection_calls: list[dict[str, object]] = []
        self.delete_collection_calls: list[str] = []
        self.upsert_calls: list[dict[str, object]] = []
        self._collection_name = "agent_memory_chunks"

    def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls.append(collection_name)
        return self.collection_exists_flag

    def get_collection(self, collection_name: str):
        self.get_collection_calls.append(collection_name)
        if not self.collection_exists_flag:
            raise RuntimeError("collection missing")
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={
                        "embedding": SimpleNamespace(size=self.vector_size, distance=self.distance),
                    }
                )
            )
        )

    def create_collection(self, **kwargs):
        self.create_collection_calls.append(dict(kwargs))
        self.collection_exists_flag = True
        vectors_config = kwargs.get("vectors_config") or {}
        vector_params = vectors_config.get("embedding")
        if vector_params is not None:
            self.vector_size = int(getattr(vector_params, "size", self.vector_size))
            self.distance = getattr(getattr(vector_params, "distance", None), "value", getattr(vector_params, "distance", self.distance))
        return None

    def delete_collection(self, **kwargs):
        self.delete_collection_calls.append(str(kwargs.get("collection_name") or kwargs.get("collection") or self._collection_name))
        self.collection_exists_flag = False
        return None

    def upsert(self, **kwargs):
        self.upsert_calls.append(dict(kwargs))
        return None

    def create_payload_index(self, **kwargs):
        return None


@dataclass(frozen=True)
class _FakePostgresRuntime:
    session_factory: object


class MemoryQdrantReindexTestCase(unittest.TestCase):
    def setUp(self) -> None:
        if create_engine is None or sessionmaker is None:
            self.skipTest("SQLAlchemy is required for memory reindex tests")
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        self.repository = LongTermMemoryRepository(self.session_factory)

    def _build_infra(self, qdrant_client: _FakeQdrantClient, vector_size: int = 4096) -> InfrastructureClients:
        openai_runtime = OpenAIRuntime(
            client=SimpleNamespace(embeddings=_FakeEmbeddingsAPI(vector_size)),
            default_model="qwen-embedding-8b",
        )
        return InfrastructureClients(
            postgres=_FakePostgresRuntime(session_factory=self.session_factory),
            qdrant=SimpleNamespace(
                client=qdrant_client,
                memory_collection="agent_memory_chunks",
                memory_vector_name="embedding",
                memory_distance="cosine",
            ),
            openai=openai_runtime,
        )

    def test_resolve_memory_vector_size_requires_explicit_setting(self) -> None:
        settings = SimpleNamespace(qdrant=SimpleNamespace(memory_vector_size=None))

        with self.assertRaisesRegex(RuntimeError, "explicit vector size"):
            _resolve_memory_vector_size(settings)  # type: ignore[arg-type]

    def test_reindex_rebuilds_64_dimensional_collection_and_keeps_postgres_records(self) -> None:
        records = [
            MemoryRecord(
                memory_id="semantic-1",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.MODEL_INFERRED,
                content={"fact": "semantic"},
                summary="semantic",
                source_turn_id="turn-1",
                confidence=0.95,
                importance=0.9,
                stability=0.9,
            ),
            MemoryRecord(
                memory_id="episodic-1",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.EPISODIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.CONFIRMED,
                source=MemorySource.MODEL_INFERRED,
                content={"fact": "episodic"},
                summary="episodic",
                source_turn_id="turn-2",
                confidence=0.9,
                importance=0.85,
                stability=0.85,
            ),
            MemoryRecord(
                memory_id="procedural-1",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.PROCEDURAL,
                scope=MemoryScope.GLOBAL,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.MODEL_INFERRED,
                content={
                    "title": "步骤整理",
                    "scenario": "复杂任务执行",
                    "operating_steps": ["先收集证据", "再定位问题", "最后执行"],
                    "failure_handling": ["失败时回滚", "必要时重试"],
                    "tags": ["procedural", "workflow"],
                },
                summary="步骤整理；先收集证据；再定位问题；最后执行",
                source_turn_id="turn-3",
                confidence=0.92,
                importance=0.8,
                stability=0.8,
                tags=["procedural", "workflow"],
            ),
            MemoryRecord(
                memory_id="inactive-1",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.INACTIVE,
                is_active=False,
                source=MemorySource.MODEL_INFERRED,
                content={"fact": "inactive"},
                summary="inactive",
                source_turn_id="turn-4",
                confidence=0.9,
                importance=0.9,
                stability=0.9,
            ),
            MemoryRecord(
                memory_id="session-fact-1",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.SYSTEM_EVENT,
                content={"fact_type": "session_fact", "fact": "session scoped"},
                summary="session scoped",
                source_turn_id="turn-5",
                confidence=0.95,
                importance=0.95,
                stability=0.95,
            ),
            MemoryRecord(
                memory_id="clarification-1",
                user_id="user-1",
                session_id="session-1",
                type=MemoryType.SEMANTIC,
                scope=MemoryScope.USER,
                status=MemoryStatus.ACTIVE,
                source=MemorySource.SYSTEM_EVENT,
                content={"fact_type": "clarification_event", "fact": "问题还不够具体，请补充"},
                summary="问题还不够具体，请补充",
                source_turn_id="turn-6",
                confidence=0.95,
                importance=0.95,
                stability=0.95,
            ),
        ]
        for record in records:
            self.repository.upsert(record)

        qdrant_client = _FakeQdrantClient(collection_exists=True, vector_size=64)
        result = reindex_memory_collection(
            SimpleNamespace(
                qdrant=SimpleNamespace(
                    memory_collection="agent_memory_chunks",
                    memory_vector_name="embedding",
                    memory_vector_size=4096,
                    memory_distance="cosine",
                ),
                embedding=SimpleNamespace(
                    memory_provider="openai",
                    memory_model="qwen-embedding-8b",
                ),
                prefer_real_adapters=True,
            ),
            infra=self._build_infra(qdrant_client),
            drop_existing=True,
            expected_old_vector_size=64,
            batch_size=64,
        )

        self.assertEqual(result.collection_name, "agent_memory_chunks")
        self.assertEqual(result.vector_name, "embedding")
        self.assertEqual(result.vector_size, 4096)
        self.assertEqual(result.indexed_memory_count, 3)
        self.assertEqual(result.skipped_memory_count, 2)
        self.assertEqual(result.failed_memory_count, 0)
        self.assertEqual(result.scanned_memory_count, 5)
        self.assertTrue(qdrant_client.delete_collection_calls)
        self.assertTrue(qdrant_client.create_collection_calls)
        self.assertEqual(self.repository.get("semantic-1").summary, "semantic")
        self.assertEqual(self.repository.get("procedural-1").summary, "步骤整理；先收集证据；再定位问题；最后执行")
        self.assertEqual(len(qdrant_client.upsert_calls), 3)

    def test_reindex_refuses_nonstandard_existing_collection_without_explicit_confirm(self) -> None:
        qdrant_client = _FakeQdrantClient(collection_exists=True, vector_size=4096)
        with self.assertRaisesRegex(RuntimeError, "Refusing to delete"):
            reindex_memory_collection(
                SimpleNamespace(
                    qdrant=SimpleNamespace(
                        memory_collection="agent_memory_chunks",
                        memory_vector_name="embedding",
                        memory_vector_size=4096,
                        memory_distance="cosine",
                    ),
                    embedding=SimpleNamespace(
                        memory_provider="openai",
                        memory_model="qwen-embedding-8b",
                    ),
                    prefer_real_adapters=True,
                ),
                infra=self._build_infra(qdrant_client),
                drop_existing=True,
                expected_old_vector_size=64,
                batch_size=64,
            )


if __name__ == "__main__":
    unittest.main()
