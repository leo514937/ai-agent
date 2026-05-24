from __future__ import annotations

import uuid
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.application import dependencies as dependencies_module
from learning_agent_service.application.dependencies import InfrastructureClients
from learning_agent_service.config.settings import QdrantSettings, Settings
from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime
from learning_agent_service.infrastructure.db import qdrant as qdrant_module
from learning_agent_service.infrastructure.db.errors import InfrastructureConfigurationError
from learning_agent_service.infrastructure.db.qdrant import QdrantRuntime
from learning_agent_service.rag.defaults import DEFAULT_KNOWLEDGE_CHUNKS
from learning_agent_service.infrastructure.memory import QdrantLongTermMemoryIndex
from learning_agent_service.domain import MemoryRecord, MemoryScope, MemoryStatus, MemoryType


class _HealthyQdrantClient:
    def __init__(self, *args, **kwargs) -> None:
        self.collection_exists_calls: list[str] = []
        self.get_collection_calls: list[str] = []
        self.create_collection_calls: list[dict[str, object]] = []
        self.upsert_calls: list[dict[str, object]] = []
        self.set_payload_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.search_calls: list[dict[str, object]] = []

    def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls.append(collection_name)
        return False

    def get_collection(self, collection_name: str):
        self.get_collection_calls.append(collection_name)
        raise RuntimeError("collection missing")

    def create_collection(self, **kwargs):
        self.create_collection_calls.append(dict(kwargs))
        return None

    def upsert(self, **kwargs):
        self.upsert_calls.append(dict(kwargs))
        return None

    def set_payload(self, **kwargs):
        self.set_payload_calls.append(dict(kwargs))
        return None

    def delete(self, **kwargs):
        self.delete_calls.append(dict(kwargs))
        return None

    def search(self, **kwargs):
        self.search_calls.append(dict(kwargs))
        return []

    def query_points(self, **kwargs):
        self.search_calls.append(dict(kwargs))
        return []


class _NamedVectorCollectionClient(_HealthyQdrantClient):
    def __init__(self, vector_size: int, distance: str = "cosine") -> None:
        super().__init__()
        from types import SimpleNamespace

        self._collection_info = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={
                        "embedding": SimpleNamespace(size=vector_size, distance=distance),
                    }
                )
            )
        )

    def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls.append(collection_name)
        return True

    def get_collection(self, collection_name: str):
        self.get_collection_calls.append(collection_name)
        return self._collection_info


class _BadEmbeddingAdapter:
    model = "bad-embedding-model"

    def embed(self, text: str):
        return [0.1] * 64


class _FixedEmbeddingAdapter64:
    model = "fake-embedding-64"

    def embed(self, text: str):
        return [0.2] * 64


class _BrokenQdrantClient(_HealthyQdrantClient):
    def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls.append(collection_name)
        raise RuntimeError("502 Bad Gateway")


class _MissingHybridCollectionClient(_HealthyQdrantClient):
    def get_collection(self, collection_name: str):
        self.get_collection_calls.append(collection_name)
        raise RuntimeError("collection missing")


class QdrantRuntimeTestCase(unittest.TestCase):
    def test_qdrant_settings_default_knowledge_collection_uses_hybrid_collection(self) -> None:
        settings = QdrantSettings(url="http://localhost:6333", api_key="", prefer_grpc=False)

        self.assertEqual(settings.knowledge_collection, "local_life_hybrid_chunks")

    def test_qdrant_settings_reject_duplicate_collection_names(self) -> None:
        with self.assertRaises(ValueError):
            QdrantSettings(
                knowledge_collection="knowledge_chunks",
                local_life_hybrid_collection="local_life_hybrid_chunks",
                local_life_parent_child_collection="local_life_hybrid_chunks",
                memory_collection="user_semantic_memory",
            )

    def test_build_qdrant_runtime_allows_missing_collection_when_probe_succeeds(self) -> None:
        settings = QdrantSettings(url="http://localhost:6333", api_key="", prefer_grpc=False)

        with patch.object(qdrant_module, "QdrantClient", _HealthyQdrantClient):
            runtime = qdrant_module.build_qdrant_runtime(settings)

        self.assertEqual(runtime.user_memory_collection, "user_semantic_memory")
        self.assertEqual(runtime.memory_collection, "user_semantic_memory")
        self.assertEqual(runtime.memory_vector_name, "embedding")
        self.assertEqual(runtime.memory_vector_size, 4096)
        self.assertEqual(runtime.memory_distance, "cosine")
        self.assertEqual(runtime.knowledge_collection, "local_life_hybrid_chunks")
        self.assertEqual(runtime.knowledge_vector_name, "embedding")
        self.assertEqual(runtime.knowledge_sparse_vector_name, "sparse_embedding")
        self.assertEqual(runtime.client.collection_exists_calls, ["user_semantic_memory"])
        self.assertEqual(settings.knowledge_vector_size, 4096)

    def test_build_qdrant_runtime_raises_when_probe_fails(self) -> None:
        settings = QdrantSettings(url="http://localhost:6333", api_key="", prefer_grpc=False)

        with patch.object(qdrant_module, "QdrantClient", _BrokenQdrantClient):
            with self.assertRaises(InfrastructureConfigurationError):
                qdrant_module.build_qdrant_runtime(settings)

    def test_qdrant_index_upsert_normalizes_point_id_and_uses_non_blocking_write(self) -> None:
        client = _HealthyQdrantClient()
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=32)
        record = MemoryRecord(
            memory_id="mem-1",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "Qdrant 可用于语义记忆索引"},
            summary="Qdrant 可用于语义记忆索引",
            source_turn_id="turn-1",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
            tags=["semantic"],
            entities=["Qdrant"],
        )

        embedding_id = index.upsert(record)

        self.assertNotEqual(embedding_id, "mem-1")
        self.assertEqual(str(uuid.UUID(embedding_id)), embedding_id)
        self.assertEqual(client.collection_exists_calls, ["user_memory"])
        self.assertEqual(client.get_collection_calls, [])
        self.assertEqual(len(client.create_collection_calls), 1)
        self.assertEqual(str(client.upsert_calls[0]["points"][0].id), embedding_id)
        self.assertEqual(client.upsert_calls[0]["wait"], False)

    def test_qdrant_index_uses_lightweight_payload(self) -> None:
        client = _HealthyQdrantClient()
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=32)
        record = MemoryRecord(
            memory_id="mem-light",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "payload slimming"},
            summary="payload slimming",
            source_turn_id="turn-light",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
            tags=["semantic"],
            entities=["payload"],
            raw_evidence={"full": "should stay in postgres"},
        )

        index.upsert(record)

        payload = client.upsert_calls[0]["points"][0].payload
        self.assertEqual(
            set(payload.keys()),
            {
                "memory_id",
                "user_id",
                "session_id",
                "project_id",
                "memory_type",
                "scope",
                "status",
                "is_active",
                "should_vectorize",
                "normalized_key",
                "topic",
                "summary",
                "tags",
                "entities",
                "confidence",
                "importance",
                "stability",
                "sensitivity",
                "source",
                "source_turn_id",
                "source_session_id",
                "created_at",
                "updated_at",
                "effective_from",
                "effective_to",
                "valid_until",
                "schema_version",
            },
        )
        self.assertNotIn("raw_evidence", payload)
        self.assertNotIn("content", payload)
        self.assertEqual(payload["memory_id"], "mem-light")
        self.assertNotEqual(str(client.upsert_calls[0]["points"][0].id), "mem-light")
        self.assertEqual(str(uuid.UUID(str(client.upsert_calls[0]["points"][0].id))), str(client.upsert_calls[0]["points"][0].id))

    def test_qdrant_index_rejects_embedding_dimension_mismatch(self) -> None:
        client = _HealthyQdrantClient()
        index = QdrantLongTermMemoryIndex(
            client=client,
            collection_name="user_memory",
            vector_size=1536,
            embedding_adapter=_BadEmbeddingAdapter(),
        )
        record = MemoryRecord(
            memory_id="mem-dim",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "dimension mismatch"},
            summary="dimension mismatch",
            source_turn_id="turn-dim",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
        )

        with self.assertRaisesRegex(RuntimeError, "Memory embedding dimension mismatch"):
            index.upsert(record)

    def test_qdrant_index_accepts_explicit_64_dimension_fake_embedding(self) -> None:
        client = _HealthyQdrantClient()
        index = QdrantLongTermMemoryIndex(
            client=client,
            collection_name="user_memory",
            vector_size=64,
            embedding_adapter=_FixedEmbeddingAdapter64(),
        )
        record = MemoryRecord(
            memory_id="mem-64",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "explicit 64 dimension"},
            summary="explicit 64 dimension",
            source_turn_id="turn-64",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
        )

        embedding_id = index.upsert(record)

        self.assertTrue(embedding_id)
        self.assertEqual(len(client.upsert_calls), 1)

    def test_qdrant_index_rejects_collection_shape_mismatch(self) -> None:
        client = _NamedVectorCollectionClient(vector_size=64, distance="cosine")
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=1536)

        with self.assertRaisesRegex(RuntimeError, "Memory Qdrant collection shape mismatch"):
            index.ensure_collection()

    def test_qdrant_index_requires_explicit_vector_size(self) -> None:
        client = _HealthyQdrantClient()
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=None)
        record = MemoryRecord(
            memory_id="mem-missing-size",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "missing vector size"},
            summary="missing vector size",
            source_turn_id="turn-missing",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
        )

        with self.assertRaisesRegex(RuntimeError, "requires an explicit vector_size"):
            index.upsert(record)

    def test_qdrant_index_search_filters_to_active_payloads(self) -> None:
        client = _HealthyQdrantClient()

        class _Point:
            def __init__(self, payload):
                self.payload = payload

        def _search(**kwargs):
            client.search_calls.append(dict(kwargs))
            return [
                _Point(
                    {
                        "memory_id": "active",
                        "user_id": "user-1",
                        "status": "active",
                        "is_active": True,
                        "memory_type": "semantic",
                        "scope": "user",
                        "content": {"fact": "active"},
                        "summary": "active",
                        "source_turn_id": "turn-1",
                        "should_vectorize": True,
                        "importance": 0.9,
                        "stability": 0.9,
                    }
                ),
                _Point(
                    {
                        "memory_id": "old",
                        "user_id": "user-1",
                        "status": "superseded",
                        "is_active": False,
                        "memory_type": "semantic",
                        "scope": "user",
                        "content": {"fact": "old"},
                        "summary": "old",
                        "source_turn_id": "turn-2",
                    }
                ),
            ]

        client.query_points = _search
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=32)

        results = index.search("active", user_id="user-1", limit=5)

        self.assertEqual([item.memory_id for item in results], ["active"])
        self.assertTrue(client.search_calls)
        self.assertIn("query_filter", client.search_calls[0])

    def test_qdrant_index_can_filter_procedural_memory_type(self) -> None:
        client = _HealthyQdrantClient()

        class _Point:
            def __init__(self, payload):
                self.payload = payload

        def _search(**kwargs):
            client.search_calls.append(dict(kwargs))
            return [
                _Point(
                    {
                        "memory_id": "semantic",
                        "user_id": "user-1",
                        "status": "active",
                        "is_active": True,
                        "memory_type": "semantic",
                        "scope": "user",
                        "summary": "semantic",
                        "source_turn_id": "turn-1",
                        "should_vectorize": True,
                        "importance": 0.9,
                        "stability": 0.9,
                    }
                ),
                _Point(
                    {
                        "memory_id": "procedural",
                        "user_id": "user-1",
                        "status": "active",
                        "is_active": True,
                        "memory_type": "procedural",
                        "scope": "project",
                        "summary": "procedural",
                        "source_turn_id": "turn-2",
                        "should_vectorize": True,
                        "importance": 0.9,
                        "stability": 0.9,
                    }
                ),
            ]

        client.query_points = _search
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=32)

        results = index.search("workflow", user_id="user-1", limit=5, memory_types=(MemoryType.PROCEDURAL,))

        self.assertEqual([item.memory_id for item in results], ["procedural"])
        self.assertTrue(client.search_calls)
        query_filter = client.search_calls[0]["query_filter"]
        self.assertIsNotNone(query_filter)

    def test_qdrant_index_soft_deactivate_marks_payload_inactive_without_delete(self) -> None:
        client = _HealthyQdrantClient()
        index = QdrantLongTermMemoryIndex(client=client, collection_name="user_memory", vector_size=32)
        record = MemoryRecord(
            memory_id="mem-1",
            user_id="user-1",
            session_id="session-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            content={"fact": "Qdrant soft deactivate"},
            summary="Qdrant soft deactivate",
            source_turn_id="turn-1",
            confidence=0.9,
            importance=0.8,
            stability=0.8,
        )
        index.upsert(record)

        index.soft_deactivate(record.memory_id, payload={"memory_id": record.memory_id, "user_id": record.user_id})

        self.assertTrue(client.set_payload_calls)
        self.assertEqual(client.set_payload_calls[0]["payload"]["is_active"], False)
        self.assertEqual(client.delete_calls, [])

    def test_build_rag_orchestrator_falls_back_when_knowledge_snapshot_is_missing(self) -> None:
        fake_qdrant = QdrantRuntime(
            client=SimpleNamespace(),
            knowledge_collection="knowledge_chunks",
            local_life_hybrid_collection="local_life_hybrid_chunks",
            local_life_parent_child_collection="local_life_parent_child_chunks",
            memory_collection="user_semantic_memory",
            user_memory_collection="user_semantic_memory",
            knowledge_vector_name="embedding",
            knowledge_sparse_vector_name="sparse_embedding",
            knowledge_vector_size=32,
            knowledge_distance="cosine",
            memory_vector_name="embedding",
            memory_vector_size=32,
            memory_distance="cosine",
        )
        fake_openai = OpenAIRuntime(client=SimpleNamespace(), default_model="gpt-test")
        settings = Settings(prefer_real_adapters=True, allow_in_memory_fallback=True)

        with patch.object(
            dependencies_module,
            "_load_qdrant_knowledge_chunks",
            side_effect=RuntimeError("collection missing"),
        ):
            orchestrator, status = dependencies_module._build_rag_orchestrator(
                settings,
                InfrastructureClients(qdrant=fake_qdrant, openai=fake_openai),
            )

        self.assertEqual(status.mode, "fallback")
        self.assertEqual(status.details["reason"], "qdrant_unavailable_empty_or_disabled")
        self.assertEqual(status.details["fallback_from"], "qdrant")
        self.assertEqual(status.details["error"], "RuntimeError")
        self.assertFalse(status.details["snapshot_loaded"])
        self.assertEqual(status.details["snapshot_source"], "bundled_defaults")
        self.assertFalse(status.details["online_dense_available"])
        self.assertFalse(status.details["online_metadata_available"])
        self.assertEqual(orchestrator.knowledge_chunks, DEFAULT_KNOWLEDGE_CHUNKS)
        self.assertEqual(orchestrator._dense_retriever._vector_name, "embedding")
        self.assertEqual(orchestrator._metadata_retriever._vector_name, "embedding")

    def test_build_rag_orchestrator_falls_back_when_online_hybrid_collection_is_missing(self) -> None:
        fake_qdrant = QdrantRuntime(
            client=_MissingHybridCollectionClient(),
            knowledge_collection="knowledge_chunks",
            local_life_hybrid_collection="local_life_hybrid_chunks",
            local_life_parent_child_collection="local_life_parent_child_chunks",
            memory_collection="user_semantic_memory",
            user_memory_collection="user_semantic_memory",
            knowledge_vector_name="embedding",
            knowledge_sparse_vector_name="sparse_embedding",
            knowledge_vector_size=32,
            knowledge_distance="cosine",
            memory_vector_name="embedding",
            memory_vector_size=32,
            memory_distance="cosine",
        )
        fake_openai = OpenAIRuntime(client=SimpleNamespace(), default_model="gpt-test")
        settings = Settings(prefer_real_adapters=True, allow_in_memory_fallback=True)

        with patch.object(
            dependencies_module,
            "_load_qdrant_knowledge_chunks",
            return_value=DEFAULT_KNOWLEDGE_CHUNKS,
        ):
            orchestrator, status = dependencies_module._build_rag_orchestrator(
                settings,
                InfrastructureClients(qdrant=fake_qdrant, openai=fake_openai),
            )

        self.assertEqual(status.mode, "real")
        self.assertIsInstance(orchestrator._dense_retriever, dependencies_module.HeuristicDenseRetriever)
        self.assertIsInstance(orchestrator._metadata_retriever, dependencies_module.HeuristicMetadataRetriever)
        self.assertEqual(fake_qdrant.client.get_collection_calls, ["local_life_hybrid_chunks"] * 2)

    def test_rag_runtime_details_detect_online_client_capabilities(self) -> None:
        fake_qdrant = QdrantRuntime(
            client=SimpleNamespace(query_points=lambda **kwargs: {"points": []}),
            knowledge_collection="knowledge_chunks",
            local_life_hybrid_collection="local_life_hybrid_chunks",
            local_life_parent_child_collection="local_life_parent_child_chunks",
            memory_collection="user_semantic_memory",
            user_memory_collection="user_semantic_memory",
            knowledge_vector_name="embedding",
            knowledge_sparse_vector_name="sparse_embedding",
            knowledge_vector_size=32,
            knowledge_distance="cosine",
            memory_vector_name="embedding",
            memory_vector_size=32,
            memory_distance="cosine",
        )
        fake_openai = OpenAIRuntime(
            client=SimpleNamespace(
                embeddings=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
                )
            ),
            default_model="gpt-test",
        )
        settings = Settings(prefer_real_adapters=True, allow_in_memory_fallback=True)

        details = dependencies_module._build_rag_runtime_details(
            settings,
            InfrastructureClients(qdrant=fake_qdrant, openai=fake_openai),
            chunks=DEFAULT_KNOWLEDGE_CHUNKS,
            load_error=None,
            fallback_reason="",
        )

        self.assertTrue(details["dense_query_capable"])
        self.assertTrue(details["metadata_query_capable"])
        self.assertTrue(details["embedding_capable"])
        self.assertTrue(details["online_dense_available"])
        self.assertTrue(details["online_metadata_available"])


if __name__ == "__main__":
    unittest.main()
