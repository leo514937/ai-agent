from __future__ import annotations

import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.application.dependencies import InfrastructureClients
from learning_agent_service.config.settings import OpenAISettings, PostgresSettings, QdrantSettings, Settings
from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime

try:  # pragma: no cover - optional runtime dependency
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except Exception:  # pragma: no cover - optional runtime dependency
    create_engine = None
    sessionmaker = None


class MemoryVectorSizeProbeTestCase(unittest.TestCase):
    def _build_session_factory(self):
        if create_engine is None or sessionmaker is None:
            self.skipTest("SQLAlchemy is unavailable in the test runtime")
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)

    def test_resolve_memory_vector_size_probes_embedding_when_missing(self) -> None:
        dependencies_module = importlib.import_module("learning_agent_service.application.dependencies")
        settings = Settings(
            prefer_real_adapters=True,
            allow_in_memory_fallback=False,
            postgres=PostgresSettings(dsn="sqlite+pysqlite:///:memory:"),
            qdrant=QdrantSettings(url="http://localhost:6333", api_key="", prefer_grpc=False, memory_vector_size=None),
            openai=OpenAISettings(api_key="test-key", base_url=""),
        )

        adapter = dependencies_module.OpenAIEmbeddingAdapter(
            runtime=OpenAIRuntime(client=SimpleNamespace(), default_model="probe-model"),
            model="probe-model",
        )

        with patch.object(dependencies_module.OpenAIEmbeddingAdapter, "embed", return_value=[0.0] * 1536) as mocked_embed:
            size = dependencies_module._resolve_memory_vector_size(settings, adapter)

        self.assertEqual(size, 1536)
        self.assertEqual(settings.qdrant.memory_vector_size, 1536)
        mocked_embed.assert_called_once()

    def test_build_durable_memory_backend_infers_missing_vector_size(self) -> None:
        dependencies_module = importlib.import_module("learning_agent_service.application.dependencies")
        session_factory = self._build_session_factory()
        settings = Settings(
            prefer_real_adapters=True,
            allow_in_memory_fallback=False,
            postgres=PostgresSettings(dsn="sqlite+pysqlite:///:memory:"),
            qdrant=QdrantSettings(
                url="http://localhost:6333",
                api_key="",
                prefer_grpc=False,
                memory_collection="user_semantic_memory",
                memory_vector_name="embedding",
                memory_vector_size=None,
                memory_distance="cosine",
            ),
            openai=OpenAISettings(api_key="test-key", base_url="", embedding_model="probe-model"),
        )
        infra = InfrastructureClients(
            postgres=SimpleNamespace(session_factory=session_factory),
            qdrant=SimpleNamespace(
                client=SimpleNamespace(),
                memory_collection="user_semantic_memory",
                memory_vector_name="embedding",
                memory_distance="cosine",
                memory_vector_size=None,
            ),
            openai=OpenAIRuntime(client=SimpleNamespace(), default_model="probe-model"),
        )

        with patch.object(dependencies_module.OpenAIEmbeddingAdapter, "embed", return_value=[0.0] * 768) as mocked_embed:
            result = dependencies_module._build_durable_memory_backend(settings, infra)

        self.assertIsNotNone(result)
        self.assertEqual(settings.qdrant.memory_vector_size, 768)
        self.assertIsNone(infra.qdrant.memory_vector_size)
        mocked_embed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
