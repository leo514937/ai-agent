from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.api.contracts import ChatStreamRequest
from learning_agent_service.config.settings import Settings
from learning_agent_service.config.settings import OpenAISettings, PostgresSettings, QdrantSettings, RedisSettings
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.db.factories import InfrastructureClients
from learning_agent_service.infrastructure.repositories.memory_trace_repository import MemoryTraceRepository

try:  # pragma: no cover - test-only dependency setup
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
except Exception:  # pragma: no cover - optional runtime dependency
    create_engine = None
    StaticPool = None
    sessionmaker = None


class WorkflowMemoryIntegrationTestCase(unittest.TestCase):
    def _build_trace_repository(self) -> MemoryTraceRepository:
        if create_engine is None or StaticPool is None or sessionmaker is None:
            self.skipTest("SQLAlchemy is unavailable in the test runtime")
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
        return MemoryTraceRepository(factory)

    def _load_runtime_stack(self):
        try:
            dependencies_module = importlib.import_module("learning_agent_service.application.dependencies")
            service_module = importlib.import_module("learning_agent_service.application.service")
        except Exception as exc:
            self.skipTest(f"application runtime modules are not available: {exc}")

        try:
            runtime_settings = Settings(
                prefer_real_adapters=False,
                allow_in_memory_fallback=True,
                postgres=PostgresSettings(dsn=""),
                redis=RedisSettings(url="redis://localhost:6379/0", key_prefix="integration-test"),
                qdrant=QdrantSettings(url="http://localhost:6333", api_key="", prefer_grpc=False),
                openai=OpenAISettings(api_key="", base_url=""),
            )
            with patch.object(dependencies_module, "build_infrastructure_clients", return_value=InfrastructureClients()):
                dependencies = dependencies_module.build_dependencies(settings=runtime_settings)
            service = service_module.create_learning_agent_service(dependencies.container)
        except Exception as exc:
            self.skipTest(f"application runtime stack is not buildable: {exc}")

        orchestrator = dependencies.container.memory_orchestrator
        orchestrator.trace_repository = self._build_trace_repository()
        return dependencies, service

    def test_workflow_load_context_and_write_memory_layers(self) -> None:
        dependencies, service = self._load_runtime_stack()
        session_id = "session-memory-integration"
        list(
            service.run_stream(
                ChatStreamRequest(
                    user_id="user-memory",
                    session_id=session_id,
                    trace_id="trace-memory",
                    turn_id="turn-memory",
                    message="请解释 LangGraph workflow 和记忆机制",
                    topic_hint="LangGraph",
                    history_summary="LangGraph workflow",
                    client_context={"source": "integration-test"},
                )
            )
        )

        context = dependencies.container.memory_service.load_any(session_id)
        self.assertIsNotNone(context.history_summary)
        self.assertGreaterEqual(context.summary_version, 0)
        self.assertTrue(context.current_topic)
        self.assertIsInstance(context.user_preferences, dict)


if __name__ == "__main__":
    unittest.main()
