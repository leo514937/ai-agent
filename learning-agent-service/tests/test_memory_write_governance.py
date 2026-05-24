from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.dependencies import _build_semantic_memory_store
from learning_agent_service.config import Settings
from learning_agent_service.domain import (
    MasteryUpdateCommand,
    MemoryUpdateSummary,
    PersistSessionCommand,
    PersistentSessionContext,
)
from learning_agent_service.infrastructure.repositories.in_memory import (
    InMemoryAsyncLogStore,
    InMemorySessionContextStore,
    InMemoryTopicMasteryStore,
)
from learning_agent_service.memory.protocols import NoOpSemanticMemoryStore
from learning_agent_service.memory.service import MemoryService


class MemoryWriteGovernanceTestCase(unittest.TestCase):
    def _build_service(self) -> MemoryService:
        return MemoryService(
            session_store=InMemorySessionContextStore(),
            mastery_store=InMemoryTopicMasteryStore(),
            async_log_store=InMemoryAsyncLogStore(),
            settings=Settings(environment="development", debug=True, allow_in_memory_fallback=True),
            semantic_memory_store=NoOpSemanticMemoryStore(),
        )

    def _build_session_write_command(self) -> PersistSessionCommand:
        return PersistSessionCommand(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            workflow_version="workflow/v1",
            raw_query="请总结一下 Redis 的核心特点",
            answer_text="Redis 是一个内存数据库。",
            request_ts=datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc),
            persistent=PersistentSessionContext(
                current_topic="Redis",
                recent_entities=["Redis"],
                user_preferences={"preferred_output_style": "detailed"},
            ),
        )

    def _build_topic_write_command(self) -> MasteryUpdateCommand:
        return MasteryUpdateCommand(
            trace_id="trace-1",
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            raw_query="请总结一下 Redis 的核心特点",
            answer_text="Redis 是一个内存数据库。",
            resolved_topic="Redis",
            request_ts=datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc),
            persistent=PersistentSessionContext(
                current_topic="Redis",
                recent_entities=["Redis"],
                user_preferences={"preferred_output_style": "detailed"},
            ),
            memory_updates=MemoryUpdateSummary(current_topic="Redis"),
        )

    def test_session_write_exposes_unified_memory_write_result(self) -> None:
        service = self._build_service()

        result = service.persist_session(self._build_session_write_command())

        self.assertIsNotNone(result.memory_write)
        self.assertEqual(result.memory_write.idempotency_key, "session-1:turn-1")
        self.assertEqual(result.memory_updates.memory_trace_id, "session-1:turn-1")
        self.assertEqual(result.memory_updates.write_status, result.memory_write.status)
        self.assertIn("session_context", result.memory_updates.write_targets)
        self.assertIn("semantic_facts", result.memory_updates.write_targets)
        self.assertIn("outbox", result.memory_updates.write_targets)
        self.assertIn("session_context", result.memory_write.degraded_parts)
        self.assertIn("semantic_facts", result.memory_write.degraded_parts)
        self.assertIn("outbox", result.memory_write.degraded_parts)
        self.assertEqual(result.memory_write.status, "degraded")

    def test_topic_write_exposes_fallback_backend_as_degraded(self) -> None:
        service = self._build_service()

        result = service.update_mastery(self._build_topic_write_command())

        self.assertIsNotNone(result.memory_write)
        self.assertEqual(result.memory_write.idempotency_key, "session-1:turn-1")
        self.assertIn("topic_mastery", result.memory_write.degraded_parts)
        self.assertIn("semantic_index", result.memory_write.degraded_parts)
        self.assertEqual(result.memory_write.status, "degraded")
        self.assertEqual(result.memory_write.trace_id, "session-1:turn-1")

    def test_semantic_memory_store_fallback_is_disabled_in_production(self) -> None:
        settings = Settings(environment="production", debug=False, allow_in_memory_fallback=True, prefer_real_adapters=True)
        infra = SimpleNamespace(qdrant=None)

        with self.assertRaises(RuntimeError):
            _build_semantic_memory_store(settings, infra)


if __name__ == "__main__":
    unittest.main()
