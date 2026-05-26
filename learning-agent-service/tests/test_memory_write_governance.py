from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.dependencies import _build_semantic_memory_store
from learning_agent_service.config import Settings
from learning_agent_service.domain import (
    ClarificationCard,
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
from learning_agent_service.memory.models import PersistSessionPlan
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

    def test_session_persist_preserves_consumed_clarification_flag(self) -> None:
        class _ClarificationOverwritePolicy:
            def __init__(self) -> None:
                self.config = SimpleNamespace(preference_promote_count=3)

            def evaluate(self, payload):
                return SimpleNamespace(reasons=())

            def build_write_plan(self, current, result):
                return PersistSessionPlan(
                    updated_context=PersistentSessionContext(
                        current_topic=current.current_topic,
                        current_shop=current.current_shop,
                        recent_entities=list(current.recent_entities),
                        clarification_result={
                            "original_query": "附近有什么推荐菜",
                            "original_intent": "local_life_recommend",
                            "original_route": "rag_retrieval",
                            "question": "你更想找哪个城市、哪类场景的店？",
                            "ambiguity_type": "location",
                            "follow_up_query": "北京",
                            "consumed": False,
                        },
                        user_preferences=dict(current.user_preferences),
                        last_retrieval_topic=current.last_retrieval_topic,
                        history_summary=current.history_summary,
                        open_questions=list(current.open_questions),
                        confirmed_facts=list(current.confirmed_facts),
                        next_steps=list(current.next_steps),
                        summary_version=current.summary_version,
                        summary_updated_at=current.summary_updated_at,
                        pending_clarification=None,
                        current_city="北京",
                        current_location={"city": "北京"},
                        extra=dict(current.extra),
                    )
                )

        session_store = InMemorySessionContextStore()
        service = MemoryService(
            session_store=session_store,
            mastery_store=InMemoryTopicMasteryStore(),
            async_log_store=InMemoryAsyncLogStore(),
            settings=Settings(environment="development", debug=True, allow_in_memory_fallback=True),
            semantic_memory_store=NoOpSemanticMemoryStore(),
        )
        service.promotion_policy = _ClarificationOverwritePolicy()

        command = PersistSessionCommand(
            trace_id="trace-clarification",
            session_id="session-clarification",
            turn_id="turn-clarification",
            user_id="user-clarification",
            workflow_version="workflow/v1",
            raw_query="北京",
            answer_text="好的，继续帮你找。",
            request_ts=datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc),
            persistent=PersistentSessionContext(
                current_topic="附近有什么推荐菜",
                recent_entities=["附近有什么推荐菜"],
                clarification_result={
                    "original_query": "附近有什么推荐菜",
                    "original_intent": "local_life_recommend",
                    "original_route": "rag_retrieval",
                    "question": "你更想找哪个城市、哪类场景的店？",
                    "ambiguity_type": "location",
                    "consumed": True,
                },
                pending_clarification=None,
                current_city="北京",
                current_location={"city": "北京"},
            ),
        )

        result = service.persist_session(command)
        persisted = session_store.load("session-clarification", "user-clarification")

        self.assertTrue(result.updated_context.clarification_result["consumed"])
        self.assertTrue(persisted.clarification_result["consumed"])
        self.assertEqual(persisted.clarification_result["follow_up_query"], "北京")
        self.assertEqual(persisted.current_city, "北京")

    def test_session_persist_does_not_fail_when_preference_profile_times_out(self) -> None:
        class _FailingPreferenceStore:
            def get(self, user_id: str):
                raise TimeoutError("preference store timeout")

        session_store = InMemorySessionContextStore()
        service = MemoryService(
            session_store=session_store,
            mastery_store=InMemoryTopicMasteryStore(),
            async_log_store=InMemoryAsyncLogStore(),
            settings=Settings(environment="development", debug=True, allow_in_memory_fallback=True),
            semantic_memory_store=NoOpSemanticMemoryStore(),
            preference_store=_FailingPreferenceStore(),
        )

        result = service.persist_session(self._build_session_write_command())

        self.assertIsNotNone(result.memory_write)
        persisted = session_store.load("session-1", "user-1")
        self.assertTrue(persisted.current_topic)
        self.assertEqual(persisted.current_topic, result.updated_context.current_topic)
        self.assertEqual(result.memory_updates.current_topic, result.updated_context.current_topic)

    def test_session_persist_keeps_pending_clarification(self) -> None:
        session_store = InMemorySessionContextStore()
        service = MemoryService(
            session_store=session_store,
            mastery_store=InMemoryTopicMasteryStore(),
            async_log_store=InMemoryAsyncLogStore(),
            settings=Settings(environment="development", debug=True, allow_in_memory_fallback=True),
            semantic_memory_store=NoOpSemanticMemoryStore(),
        )
        pending = ClarificationCard(
            card_id="session-1:turn-1:clarification",
            question="你更想找哪个城市、哪类场景的店？",
            options=[],
            ambiguity_type="location",
            source_turn_id="turn-1",
            expires_at=None,
        )
        command = self._build_session_write_command().model_copy(
            update={
                "persistent": PersistentSessionContext(
                    current_topic="附近有什么推荐菜",
                    recent_entities=["附近有什么推荐菜"],
                    history_summary="附近有什么推荐菜",
                    clarification_result={
                        "original_query": "附近有什么推荐菜",
                        "original_intent": "local_life_recommend",
                        "original_route": "rag_retrieval",
                        "question": "你更想找哪个城市、哪类场景的店？",
                        "ambiguity_type": "location",
                    },
                    pending_clarification=pending,
                )
            }
        )

        result = service.persist_session(command)
        persisted = session_store.load("session-1", "user-1")

        self.assertIsNotNone(result.updated_context.pending_clarification)
        self.assertIsNotNone(persisted.pending_clarification)
        self.assertEqual(persisted.pending_clarification.question, pending.question)
        self.assertEqual(persisted.clarification_result["original_query"], "附近有什么推荐菜")

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
