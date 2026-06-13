from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.domain.memory import MemoryRecord, MemoryScope, MemoryStatus, MemoryType
from learning_agent_service.infrastructure.memory.qdrant_store import QdrantLongTermMemoryIndex


class _Point:
    def __init__(self, payload):
        self.payload = payload


class _SearchClient:
    def __init__(self, points):
        self.points = points
        self.query_calls: list[dict[str, object]] = []

    def query_points(self, **kwargs):
        self.query_calls.append(dict(kwargs))
        return SimpleNamespace(points=self.points)


class MemoryQdrantGuardrailsTestCase(unittest.TestCase):
    def test_search_filters_session_pollution_and_keeps_procedural(self) -> None:
        client = _SearchClient(
            points=[
                _Point(
                    {
                        "memory_id": "active-semantic",
                        "user_id": "user-1",
                        "memory_type": "semantic",
                        "scope": "user",
                        "status": "active",
                        "is_active": True,
                        "should_vectorize": True,
                        "summary": "active semantic",
                        "source_turn_id": "turn-1",
                        "importance": 0.9,
                        "stability": 0.9,
                    }
                ),
                _Point(
                    {
                        "memory_id": "polluted-session",
                        "user_id": "user-1",
                        "memory_type": "short_term",
                        "scope": "session",
                        "status": "observed",
                        "is_active": True,
                        "should_vectorize": False,
                        "source": "system_event",
                        "summary": "这个问题还不够具体，请补充范围",
                        "source_turn_id": "turn-2",
                        "importance": 0.1,
                        "stability": 0.1,
                    }
                ),
                _Point(
                    {
                        "memory_id": "active-procedural",
                        "user_id": "user-1",
                        "memory_type": "procedural",
                        "scope": "project",
                        "status": "confirmed",
                        "is_active": True,
                        "should_vectorize": True,
                        "summary": "how to rebuild qdrant",
                        "source_turn_id": "turn-3",
                        "importance": 0.85,
                        "stability": 0.8,
                    }
                ),
                _Point(
                    {
                        "memory_id": "inactive-semantic",
                        "user_id": "user-1",
                        "memory_type": "semantic",
                        "scope": "user",
                        "status": "superseded",
                        "is_active": False,
                        "should_vectorize": True,
                        "summary": "inactive semantic",
                        "source_turn_id": "turn-4",
                        "importance": 0.9,
                        "stability": 0.9,
                    }
                ),
            ]
        )
        index = QdrantLongTermMemoryIndex(client=client, collection_name="memory", vector_size=32)

        results = index.search("rebuild qdrant", user_id="user-1", limit=10)

        self.assertEqual([item.memory_id for item in results], ["active-semantic", "active-procedural"])
        self.assertTrue(client.query_calls)
        self.assertIn("query_filter", client.query_calls[0])

    def test_polluted_session_fact_is_not_returned(self) -> None:
        client = _SearchClient(
            points=[
                _Point(
                    {
                        "memory_id": "polluted-session",
                        "user_id": "user-1",
                        "memory_type": "short_term",
                        "scope": "session",
                        "status": "observed",
                        "is_active": True,
                        "should_vectorize": False,
                        "source": "system_event",
                        "summary": "这个问题还不够具体，请补充范围",
                        "source_turn_id": "turn-1",
                        "importance": 0.1,
                        "stability": 0.1,
                    }
                )
            ]
        )
        index = QdrantLongTermMemoryIndex(client=client, collection_name="memory", vector_size=32)

        results = index.search("附近有什么好的推荐才", user_id="user-1", limit=10)

        self.assertEqual(results, [])

    def test_search_falls_back_to_text_match_when_embeddings_are_unavailable(self) -> None:
        client = _SearchClient(points=[])
        index = QdrantLongTermMemoryIndex(client=client, collection_name="memory", vector_size=32)
        index._embed_query = lambda _text: None  # type: ignore[method-assign]
        index.fallback_points = {
            "memory-1": {
                "payload": {
                    "memory_id": "memory-1",
                    "user_id": "user-1",
                    "memory_type": "semantic",
                    "scope": "user",
                    "status": "active",
                    "is_active": True,
                    "should_vectorize": True,
                    "summary": "适合约会的火锅店推荐",
                    "content": {"fact": "适合约会", "shop": "海底捞"},
                    "tags": ["约会", "火锅"],
                    "entities": ["海底捞"],
                    "source_turn_id": "turn-9",
                    "importance": 0.9,
                    "stability": 0.9,
                },
                "vector": [0.0, 0.0, 0.0],
            }
        }

        results = index.search("我想找适合约会的火锅店", user_id="user-1", limit=10)

        self.assertEqual([item.memory_id for item in results], ["memory-1"])


if __name__ == "__main__":
    unittest.main()
