from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, MemoryRecord, MemoryStatus, MemoryType, build_initial_state
from learning_agent_service.domain.memory import MemoryMetadata, MemoryScope, MemorySource


class MemoryModelTestCase(unittest.TestCase):
    def test_initial_state_includes_sensory_and_short_term_memory(self) -> None:
        state = build_initial_state(
            ChatTurnCommand(
                trace_id="trace-memory",
                session_id="session-memory",
                turn_id="turn-memory",
                user_id="user-memory",
                message="请解释一下 RAG",
                topic_hint="RAG",
                client_context={"source": "unit-test"},
            )
        )

        self.assertEqual(state["turn"].sensory_memory["raw_message"], "请解释一下 RAG")
        self.assertEqual(state["turn"].short_term_window[0]["role"], "user")
        self.assertEqual(state["turn"].short_term_window[0]["content"], "请解释一下 RAG")

    def test_memory_record_syncs_metadata(self) -> None:
        record = MemoryRecord(
            memory_id="mem-1",
            user_id="user-1",
            session_id="session-1",
            project_id="project-1",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=MemoryStatus.CONFIRMED,
            content={"fact": "LangGraph is a workflow engine"},
            summary="LangGraph 是工作流引擎",
            source_turn_id="turn-1",
            confidence=0.9,
            importance=0.8,
            tags=["langgraph", "workflow"],
            entities=["LangGraph"],
        )

        self.assertIsNotNone(record.metadata)
        self.assertEqual(record.metadata.memory_id, "mem-1")
        self.assertEqual(record.metadata.type, MemoryType.SEMANTIC)
        self.assertEqual(record.metadata.scope, MemoryScope.USER)
        self.assertEqual(record.metadata.source, MemorySource.SYSTEM_EVENT)

    def test_memory_metadata_model_serializes(self) -> None:
        metadata = MemoryMetadata(
            memory_id="mem-2",
            user_id="user-1",
            type=MemoryType.PROCEDURAL,
            scope=MemoryScope.PROJECT,
            source=MemorySource.USER_EXPLICIT,
            source_turn_id="turn-2",
        )

        dumped = metadata.model_dump(mode="json")
        self.assertEqual(dumped["memory_id"], "mem-2")
        self.assertEqual(dumped["type"], "procedural")
        self.assertEqual(dumped["scope"], "project")


if __name__ == "__main__":
    unittest.main()
