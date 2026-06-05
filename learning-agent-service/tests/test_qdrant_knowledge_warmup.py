from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import _bootstrap  # noqa: F401

from learning_agent_service.application import bootstrap as bootstrap_module


class _FakeRAGOrchestrator:
    def __init__(self) -> None:
        self.replaced_chunks: tuple[object, ...] | None = None

    def replace_knowledge_chunks(self, chunks) -> int:
        refreshed = tuple(chunks)
        self.replaced_chunks = refreshed
        return len(refreshed)


class _FakeApp:
    def __init__(self, qdrant: object | None = object()) -> None:
        self.state = SimpleNamespace(
            container=SimpleNamespace(
                infrastructure_clients=SimpleNamespace(qdrant=qdrant),
                rag_orchestrator=_FakeRAGOrchestrator(),
            ),
            infrastructure_status={},
        )
        self.handlers: dict[str, object] = {}

    def on_event(self, event: str):
        def decorator(fn):
            self.handlers[event] = fn
            return fn

        return decorator


class QdrantKnowledgeWarmupTestCase(unittest.TestCase):
    def test_startup_hook_schedules_qdrant_warmup_without_awaiting_it(self) -> None:
        fake_app = _FakeApp()
        bootstrap_module._register_qdrant_knowledge_warmup(fake_app)

        self.assertIn("startup", fake_app.handlers)
        startup_handler = fake_app.handlers["startup"]

        with patch.object(bootstrap_module.asyncio, "create_task", return_value=SimpleNamespace(done=lambda: False)) as mock_create_task, patch.object(
            bootstrap_module,
            "_warmup_qdrant_knowledge_chunks",
            new=AsyncMock(return_value={"status": "completed"}),
        ) as mock_warmup:

            async def run_startup() -> None:
                await startup_handler()

            asyncio.run(run_startup())

        mock_warmup.assert_called_once_with(fake_app)
        mock_warmup.assert_not_awaited()
        mock_create_task.assert_called_once()
        scheduled = mock_create_task.call_args.args[0]
        scheduled.close()
        self.assertEqual(fake_app.state.infrastructure_status["rag_knowledge_warmup"]["status"], "scheduled")

    def test_background_warmup_replaces_snapshot_after_qdrant_load(self) -> None:
        fake_app = _FakeApp()

        async def run_warmup() -> None:
            with patch.object(
                bootstrap_module.asyncio,
                "to_thread",
                new=AsyncMock(return_value=("chunk-1", "chunk-2")),
            ):
                await bootstrap_module._warmup_qdrant_knowledge_chunks(fake_app)

        asyncio.run(run_warmup())

        self.assertEqual(fake_app.state.infrastructure_status["rag_knowledge_warmup"]["status"], "completed")
        self.assertEqual(fake_app.state.infrastructure_status["rag_knowledge_warmup"]["chunk_count"], 2)
        self.assertTrue(fake_app.state.infrastructure_status["rag_knowledge_warmup"]["replaced"])
        self.assertEqual(fake_app.state.container.rag_orchestrator.replaced_chunks, ("chunk-1", "chunk-2"))


if __name__ == "__main__":
    unittest.main()
