from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.config.settings import OpenAISettings, QdrantSettings, Settings


class _FakeBusinessClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeQdrantClient:
    def __init__(self, existing_collections: set[str], point_counts: dict[str, int | None] | None = None) -> None:
        self.existing_collections = set(existing_collections)
        self.point_counts = dict(point_counts or {})
        self.collection_exists_calls: list[str] = []
        self.count_calls: list[str] = []

    def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls.append(collection_name)
        return collection_name in self.existing_collections

    def count(self, *, collection_name: str, exact: bool = True):
        self.count_calls.append(collection_name)
        return type("CountResult", (), {"count": self.point_counts.get(collection_name, 0)})()


class _FakeQdrantRuntime:
    def __init__(self, client: _FakeQdrantClient) -> None:
        self.client = client


class LocalLifeBootstrapTestCase(unittest.TestCase):
    def test_ensure_local_life_collections_seeds_only_missing_collections(self) -> None:
        from learning_agent_service.bootstrap import local_life as bootstrap_module

        settings = Settings(
            qdrant=QdrantSettings(
                url="http://localhost:6333",
                api_key="",
                knowledge_collection="local_life_hybrid_chunks",
                local_life_hybrid_collection="local_life_hybrid_chunks",
                local_life_parent_child_collection="local_life_parent_child_chunks",
                memory_collection="user_semantic_memory",
                user_memory_collection="user_semantic_memory",
                knowledge_vector_name="embedding",
                knowledge_vector_size=4096,
                knowledge_distance="cosine",
            ),
            openai=OpenAISettings(api_key="", embedding_model="text-embedding-3-large"),
        )
        fake_business_client = _FakeBusinessClient()
        fake_qdrant_runtime = _FakeQdrantRuntime(
            _FakeQdrantClient(
                existing_collections={"local_life_hybrid_chunks", "local_life_parent_child_chunks"},
                point_counts={
                    "local_life_hybrid_chunks": 0,
                    "local_life_parent_child_chunks": 8,
                },
            )
        )
        seeded_targets: list[str] = []

        def _seed_hybrid(**kwargs):
            seeded_targets.append(kwargs["settings"].qdrant.local_life_hybrid_collection)
            return type(
                "SeedResult",
                (),
                dict(
                    collection_name=kwargs["settings"].qdrant.local_life_hybrid_collection,
                    vector_name="embedding",
                    vector_size=4096,
                    chunk_count=1,
                    point_count=1,
                    chunk_role_counts={},
                    source_type_counts={},
                    upsert_batches=(),
                    deleted_point_count=0,
                    duration_seconds=0.0,
                ),
            )()

        def _seed_parent_child(**kwargs):
            seeded_targets.append(kwargs["settings"].qdrant.local_life_parent_child_collection)
            return type(
                "SeedResult",
                (),
                dict(
                    collection_name=kwargs["settings"].qdrant.local_life_parent_child_collection,
                    vector_name="embedding",
                    vector_size=4096,
                    chunk_count=1,
                    point_count=1,
                    chunk_role_counts={},
                    source_type_counts={},
                    upsert_batches=(),
                    deleted_point_count=0,
                    duration_seconds=0.0,
                ),
            )()

        with patch.object(bootstrap_module, "JavaBusinessClient", return_value=fake_business_client), patch.object(
            bootstrap_module, "build_openai_runtime", return_value=SimpleNamespace()
        ), patch.object(
            bootstrap_module, "build_qdrant_runtime", return_value=fake_qdrant_runtime
        ), patch.object(
            bootstrap_module, "seed_local_life_hybrid_knowledge_from_settings", side_effect=_seed_hybrid
        ), patch.object(
            bootstrap_module, "seed_local_life_parent_child_knowledge_from_settings", side_effect=_seed_parent_child
        ), patch.object(
            bootstrap_module, "validate_qdrant_collection_shape"
        ) as validate_mock:
            ensured = bootstrap_module.ensure_local_life_collections(settings)

        self.assertEqual(ensured, ("local_life_hybrid_chunks",))
        self.assertEqual(seeded_targets, ["local_life_hybrid_chunks"])
        self.assertEqual(
            fake_qdrant_runtime.client.count_calls,
            ["local_life_hybrid_chunks", "local_life_parent_child_chunks"],
        )
        self.assertTrue(fake_business_client.closed)
        validate_mock.assert_called_once_with(
            fake_qdrant_runtime.client,
            collection_name="local_life_parent_child_chunks",
            vector_name="embedding",
            vector_size=4096,
            distance="cosine",
            action_hint="run the dedicated local-life seed or reindex command",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
