from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import sys
from pathlib import Path
import unittest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.application.service import WorkflowLearningAgentService
from learning_agent_service.application.workflow.builder import create_workflow_runner
from learning_agent_service.application.workflow.services import WorkflowServices
from learning_agent_service.api.contracts import ApprovalSubmitRequest, ForkRequest, ReplayRequest
from learning_agent_service.domain.contracts import PersistentSessionContext


@dataclass
class _SaveRecord:
    context: PersistentSessionContext
    runtime: object


class _InMemorySessionStore:
    def __init__(self, initial: PersistentSessionContext | None = None) -> None:
        self._records: dict[str, PersistentSessionContext] = {}
        self.saved: list[_SaveRecord] = []
        if initial is not None:
            self._records["session-1"] = initial

    def load_any(self, session_id: str):
        return self._records.get(session_id)

    def load(self, session_id: str, user_id: str):
        return self._records.get(session_id)

    def save(self, context, runtime):
        session_id = str(getattr(runtime, "session_id", "") or "").strip() or "session-1"
        self._records[session_id] = context
        self.saved.append(_SaveRecord(context=context, runtime=runtime))


class WorkflowServiceGraphGuardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _InMemorySessionStore(
            PersistentSessionContext(
                current_topic="海底捞",
                extra={"user_id": "user-1"},
            )
        )
        self.container = SimpleNamespace(
            settings=SimpleNamespace(workflow_version="test-workflow"),
            session_context_store=self.store,
            memory_service=SimpleNamespace(),
        )
        self.service = WorkflowLearningAgentService.__new__(WorkflowLearningAgentService)
        self.service.container = self.container
        self.service.chat_use_case = SimpleNamespace(
            _workflow_runner=SimpleNamespace(
                _graph=SimpleNamespace(_graph=None),
                _checkpointer=object(),
            )
        )
        self.service.session_query_use_case = SimpleNamespace(
            get=lambda session_id: self.store.load_any(session_id) or PersistentSessionContext()
        )

    def test_replay_session_state_falls_back_when_graph_proxy_is_empty(self) -> None:
        response = self.service.replay_session_state("session-1", ReplayRequest(checkpoint_id="cp-1"))

        self.assertEqual(response.session_id, "session-1")
        self.assertEqual(response.current_topic, "海底捞")
        self.assertEqual(response.extra, {"user_id": "user-1"})

    def test_fork_session_state_falls_back_when_graph_proxy_is_empty(self) -> None:
        response = self.service.fork_session_state(
            "session-1",
            ForkRequest(checkpoint_id="cp-1", target_session_id="session-fork"),
        )

        self.assertEqual(response.session_id, "session-fork")
        self.assertEqual(response.current_topic, "海底捞")

    def test_submit_approval_falls_back_when_graph_proxy_is_empty(self) -> None:
        response = self.service.submit_approval(
            ApprovalSubmitRequest(
                user_id="user-1",
                session_id="session-1",
                trace_id="trace-1",
                turn_id="turn-1",
                decision="approved",
                approval_request={"step_id": "step-1"},
            )
        )

        self.assertEqual(response.approval_state, "approved")
        self.assertTrue(self.store.saved)
        self.assertEqual(self.store.saved[-1].context.extra["approval_resume_decision"], "approved")

    def test_workflow_runner_factory_returns_compiled_graph(self) -> None:
        runner = create_workflow_runner(WorkflowServices())

        self.assertIsNotNone(runner)
        self.assertIsNotNone(getattr(runner, "_graph", None))
        self.assertIsNotNone(getattr(getattr(runner, "_graph", None), "_graph", None))


if __name__ == "__main__":
    unittest.main()
