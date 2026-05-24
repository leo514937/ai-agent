from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("SQLAlchemy is not installed") from exc

from learning_agent_service.domain import ChatTurnCommand, MemoryStatus, MemoryType, PlanExecutionSummary, build_initial_state
from learning_agent_service.domain.memory import MemoryRecord, MemoryScope
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.memory import DurableLongTermMemoryStore, LongTermMemoryRepository
from learning_agent_service.infrastructure.repositories.in_memory import InMemorySessionContextStore, InMemoryTopicMasteryStore
from learning_agent_service.infrastructure.repositories.memory_trace_repository import MemoryTraceRepository
from learning_agent_service.memory.injection import MemoryInjectionPolicy
from learning_agent_service.memory.orchestrator import MemoryOrchestrator
from learning_agent_service.memory.retrieval import MemoryRetrievalPolicy


class _FailingQdrantIndex:
    def upsert(self, record: MemoryRecord) -> str:
        raise RuntimeError("qdrant upsert failed")

    def search(self, query: str, user_id: str, limit: int = 10):  # noqa: D401 - test stub
        return []

    def delete_many(self, point_ids):  # noqa: D401 - test stub
        return None


class MemoryE2EFlowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.long_term_repository = LongTermMemoryRepository(self.session_factory)
        self.trace_repository = MemoryTraceRepository(self.session_factory)
        self.long_term_store = DurableLongTermMemoryStore(
            repository=self.long_term_repository,
            index=_FailingQdrantIndex(),
        )
        self.orchestrator = MemoryOrchestrator(
            session_store=InMemorySessionContextStore(),
            mastery_store=InMemoryTopicMasteryStore(),
            long_term_store=self.long_term_store,
            retrieval_policy=MemoryRetrievalPolicy(),
            injection_policy=MemoryInjectionPolicy(),
            trace_repository=self.trace_repository,
        )

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_full_memory_flow_persists_trace_and_recalls_preference(self) -> None:
        first_state = build_initial_state(
            ChatTurnCommand(
                trace_id="trace-first",
                session_id="session-e2e",
                turn_id="turn-1",
                user_id="user-e2e",
                message="以后回答我 Agent 架构问题时，多用中文和 ASCII 图。",
                topic_hint="Agent 架构",
            )
        )
        first_state["persistent"] = first_state["persistent"].model_copy(update={"current_topic": "Agent 架构"})
        first_state["turn"] = first_state["turn"].model_copy(
            update={
                "final_answer": "明白了，我会优先用中文和 ASCII 图。",
                "final_task_summary": PlanExecutionSummary(
                    status="completed",
                    completed_steps=1,
                    total_steps=1,
                    key_findings=["记住中文和 ASCII 图偏好"],
                    final_decision="已记录偏好",
                ),
            }
        )

        first_plan = self.orchestrator.promote_from_state(first_state)
        preference_candidate = next(candidate for candidate in first_plan.candidates if candidate.memory_type == MemoryType.PREFERENCE)
        self.assertTrue(preference_candidate.should_promote)
        self.assertEqual(preference_candidate.governance_action, "approve")
        self.assertEqual(preference_candidate.record.status, MemoryStatus.ACTIVE)

        stored_preference = self.long_term_store.get(preference_candidate.record.memory_id)
        self.assertIsNotNone(stored_preference)
        self.assertEqual(stored_preference.type, MemoryType.PREFERENCE)

        first_trace = self.trace_repository.get_by_trace_id("trace-first")
        self.assertIsNotNone(first_trace)
        self.assertTrue(first_trace.candidates)
        self.assertTrue(first_trace.promoted)
        self.assertTrue(first_trace.qdrant_degraded)

        second_state = build_initial_state(
            ChatTurnCommand(
                trace_id="trace-second",
                session_id="session-e2e",
                turn_id="turn-2",
                user_id="user-e2e",
                message="LangGraph 的 supervisor 架构怎么设计？",
                topic_hint="LangGraph",
            )
        )
        second_state["persistent"] = second_state["persistent"].model_copy(
            update={
                "current_topic": "Agent 架构",
                "history_summary": "Agent 架构",
            }
        )

        pack = self.orchestrator.retrieve_for_state(second_state)
        injection = self.orchestrator.build_injection_plan(pack)
        second_state = self.orchestrator.attach_to_state(second_state, pack, injection)
        self.assertTrue(any(memory.type == MemoryType.PREFERENCE for memory in injection.prompt_memories))
        self.assertTrue(any(memory.memory_id == preference_candidate.record.memory_id for memory in injection.prompt_memories))

        second_state["turn"] = second_state["turn"].model_copy(
            update={
                "final_answer": "可以先拆 supervisor 的职责，再把工具调用和状态保存分层。",
                "final_task_summary": PlanExecutionSummary(
                    status="completed",
                    completed_steps=1,
                    total_steps=1,
                    key_findings=["召回了偏好记忆"],
                    final_decision="完成回答",
                ),
            }
        )
        second_plan = self.orchestrator.promote_from_state(second_state)
        self.assertTrue(second_plan.candidates)

        second_trace = self.trace_repository.get_by_trace_id("trace-second")
        self.assertIsNotNone(second_trace)
        self.assertIn(preference_candidate.record.memory_id, second_trace.retrieved)
        self.assertIn(preference_candidate.record.memory_id, second_trace.injected)
        self.assertTrue(second_trace.candidates)
        self.assertTrue(second_trace.promoted)

        traces = self.trace_repository.list_by_session("session-e2e")
        self.assertEqual([item.trace_id for item in traces], ["trace-second", "trace-first"])


if __name__ == "__main__":
    unittest.main()
