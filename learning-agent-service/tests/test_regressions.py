from __future__ import annotations

import importlib
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters import WorkflowNodeAdapter
from learning_agent_service.domain import (
    ChatTurnCommand,
    EvidencePack,
    MasteryUpdateResult,
    MemoryUpdateSummary,
    PersistSessionResult,
    PersistentSessionContext,
    ReferenceResolutionRequest,
    ReferenceResolutionResult,
    build_initial_state,
    build_error,
)
from learning_agent_service.domain.errors import WorkflowErrorCode
from learning_agent_service.infrastructure.repositories.records import UserPreferenceProfileRecord
from learning_agent_service.infrastructure.repositories.runtime_adapters import DurablePreferenceStore
from learning_agent_service.memory.models import MemoryCapabilityError
from learning_agent_service.rag.domain_adapter import DomainRagAdapter
from learning_agent_service.rag.reference import ReferenceResolver


class _SessionWriteFailureMemoryService:
    def persist_session(self, command):
        raise MemoryCapabilityError(
            code=WorkflowErrorCode.SESSION_PERSIST_FAILED,
            stage="session_write.session_store",
            message="session store unavailable",
            retryable=True,
            degraded_to="session_write_skipped",
        )


class _TopicWriteFailureMemoryService:
    def update_mastery(self, command):
        raise MemoryCapabilityError(
            code=WorkflowErrorCode.MASTERY_UPDATE_FAILED,
            stage="topic_update.mastery_store",
            message="mastery store unavailable",
            retryable=True,
            degraded_to="skip_topic_update",
        )


class _CapturingMemoryService:
    def __init__(self) -> None:
        self.last_persist_command = None

    def persist_session(self, command):
        self.last_persist_command = command
        updated_context = command.persistent.model_copy(update={"current_topic": command.resolved_topic})
        return PersistSessionResult(
            updated_context=updated_context,
            memory_updates=MemoryUpdateSummary(current_topic=command.resolved_topic),
        )


class _CapturingTopicSignalsMemoryService:
    def __init__(self) -> None:
        self.last_persist_command = None
        self.last_update_command = None

    def persist_session(self, command):
        self.last_persist_command = command
        return PersistSessionResult(
            updated_context=command.persistent,
            memory_updates=MemoryUpdateSummary(),
        )

    def update_mastery(self, command):
        self.last_update_command = command
        return MasteryUpdateResult()


class _PreferenceRepository:
    def __init__(self, record: UserPreferenceProfileRecord | None) -> None:
        self.record = record

    def get(self, user_id: str):
        return self.record if self.record and self.record.user_id == user_id else None


class RegressionFixesTestCase(unittest.TestCase):
    def _build_state(self, *, current_topic: str = "JVM"):
        state = build_initial_state(
            ChatTurnCommand(
                trace_id="trace-1",
                session_id="session-1",
                turn_id="turn-1",
                user_id="user-1",
                message="What about Redis?",
            ),
            persistent=PersistentSessionContext(current_topic=current_topic, recent_entities=[current_topic]),
        )
        state["turn"] = state["turn"].model_copy(update={"final_answer": "Redis is an in-memory store."})
        return state

    def test_rag_domain_adapter_module_imports(self) -> None:
        module = importlib.import_module("learning_agent_service.rag.domain_adapter")
        self.assertTrue(hasattr(module, "DomainRagAdapter"))

    def test_domain_rag_adapter_restores_follow_up_resolution_from_context(self) -> None:
        adapter = DomainRagAdapter()
        internal_request = adapter.build_reference_request(
            ReferenceResolutionRequest(
                raw_query="再解释一下",
                current_topic="Spring AOP",
                recent_entities=["Spring AOP"],
                history_summary="We were discussing Spring AOP proxy behavior.",
            )
        )

        self.assertTrue(internal_request.follow_up_intent)
        resolution = ReferenceResolver().resolve(internal_request)
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.resolved_entity, "Spring AOP")

    def test_session_write_memory_capability_error_is_non_terminal(self) -> None:
        adapter = WorkflowNodeAdapter(SimpleNamespace(memory_service=_SessionWriteFailureMemoryService()))
        state = self._build_state()

        updated = adapter.persist_session(state)

        self.assertIsNone(updated["runtime"].terminal_event)
        self.assertFalse(updated["runtime"].session_persisted)
        self.assertEqual(updated["runtime"].errors[-1].code, WorkflowErrorCode.SESSION_PERSIST_FAILED)
        self.assertEqual(updated["runtime"].degrade_to, "session_write_skipped")

    def test_topic_write_memory_capability_error_is_non_terminal(self) -> None:
        adapter = WorkflowNodeAdapter(SimpleNamespace(memory_service=_TopicWriteFailureMemoryService()))
        state = self._build_state()

        updated = adapter.update_mastery(state)

        self.assertIsNone(updated["runtime"].terminal_event)
        self.assertEqual(updated["runtime"].errors[-1].code, WorkflowErrorCode.MASTERY_UPDATE_FAILED)
        self.assertEqual(updated["runtime"].degrade_to, "skip_topic_update")
        self.assertEqual(updated["runtime"].memory_updates, MemoryUpdateSummary())

    def test_session_write_prefers_turn_resolved_topic_over_current_topic(self) -> None:
        memory_service = _CapturingMemoryService()
        adapter = WorkflowNodeAdapter(SimpleNamespace(memory_service=memory_service))
        state = self._build_state(current_topic="JVM")
        state["turn"] = state["turn"].model_copy(
            update={
                "reference_resolution": ReferenceResolutionResult(
                    resolved=True,
                    confidence=0.98,
                    resolved_entity="Redis",
                )
            }
        )

        updated = adapter.persist_session(state)

        self.assertEqual(memory_service.last_persist_command.resolved_topic, "Redis")
        self.assertEqual(updated["persistent"].current_topic, "Redis")

    def test_durable_preference_store_get_returns_current_profile_fields(self) -> None:
        store = DurablePreferenceStore(
            repository=_PreferenceRepository(
                UserPreferenceProfileRecord(
                    user_id="user-1",
                    answer_style="interview",
                    explanation_depth="concise",
                    extra={"response_profile": "interview"},
                )
            )
        )

        profile = store.get("user-1")

        self.assertEqual(profile.answer_style, "interview")
        self.assertEqual(profile.explanation_depth, "concise")
        self.assertEqual(profile.extra["response_profile"], "interview")

    def test_session_write_carries_degraded_turn_signals_into_topic_update(self) -> None:
        memory_service = _CapturingTopicSignalsMemoryService()
        adapter = WorkflowNodeAdapter(SimpleNamespace(memory_service=memory_service))
        state = self._build_state(current_topic="Redis")
        state["turn"] = state["turn"].model_copy(update={"evidence_pack": EvidencePack(), "citations": []})
        state["runtime"] = state["runtime"].model_copy(
            update={
                "errors": [
                    build_error(
                        WorkflowErrorCode.EVIDENCE_INSUFFICIENT,
                        stage="evaluate_evidence",
                        message="No stable evidence survived the governance pipeline.",
                    )
                ]
            }
        )

        persisted = adapter.persist_session(state)
        adapter.update_mastery(persisted)

        self.assertEqual(memory_service.last_update_command.memory_updates.extra["evidence_count"], 0)
        self.assertFalse(memory_service.last_update_command.memory_updates.extra["was_resolved"])
        self.assertTrue(memory_service.last_update_command.memory_updates.extra["was_confused"])


if __name__ == "__main__":
    unittest.main()
