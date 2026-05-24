from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("langgraph is not installed") from exc

from learning_agent_service.application.workflow import (
    UnderstandTurnServices,
    WorkflowServices,
    create_workflow_runner,
)
from learning_agent_service.api.contracts import SseEnvelope
from learning_agent_service.config.settings import Settings
from learning_agent_service.domain import ChatTurnCommand, build_initial_state
from learning_agent_service.domain.errors import TerminalEvent
from learning_agent_service.domain.enums import TurnDecision
from learning_agent_service.infrastructure.db.factories import InfrastructureClients


class LangGraphCheckpointingTestCase(unittest.TestCase):
    def test_settings_expose_sqlite_checkpoint_configuration(self) -> None:
        settings = Settings()

        self.assertTrue(settings.workflow_checkpoint_enabled)
        self.assertTrue(settings.workflow_checkpoint_sqlite_path)

    def test_build_dependencies_wires_sqlite_checkpointer(self) -> None:
        dependencies_module = importlib.import_module("learning_agent_service.application.dependencies")
        runtime_settings = Settings(
            prefer_real_adapters=False,
            allow_in_memory_fallback=True,
            workflow_checkpoint_enabled=True,
            workflow_checkpoint_sqlite_path=str(Path(tempfile.gettempdir()) / "langgraph-checkpoints.sqlite"),
        )

        with patch.object(dependencies_module, "build_infrastructure_clients", return_value=InfrastructureClients()):
            dependencies = dependencies_module.build_dependencies(settings=runtime_settings)

        self.assertIsNotNone(dependencies.container.workflow_checkpointer)
        self.assertIsInstance(dependencies.container.workflow_checkpointer, SqliteSaver)

    def test_workflow_runner_preserves_state_across_runner_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "checkpoints.sqlite"
            with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                runner = create_workflow_runner(
                    services=self._build_minimal_services(),
                    prefer_langgraph=True,
                    workflow_version="workflow/v1",
                    checkpointer=saver,
                )
                state = self._build_direct_answer_state(session_id="session-checkpoint")
                result = runner.run_state(state)

            self.assertEqual(result["turn"].final_answer, "persisted answer")

            with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                runner_again = create_workflow_runner(
                    services=self._build_minimal_services(),
                    prefer_langgraph=True,
                    workflow_version="workflow/v1",
                    checkpointer=saver,
                )
                snapshot = runner_again._graph.get_state(
                    {"configurable": {"thread_id": "session-checkpoint"}}
                )

            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.values["turn"].final_answer, "persisted answer")
            self.assertEqual(snapshot.values["runtime"].session_id, "session-checkpoint")

            with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                runner_missing = create_workflow_runner(
                    services=self._build_minimal_services(),
                    prefer_langgraph=True,
                    workflow_version="workflow/v1",
                    checkpointer=saver,
                )
                missing_snapshot = runner_missing._graph.get_state(
                    {"configurable": {"thread_id": "session-missing"}}
                )

            self.assertEqual(missing_snapshot.values, {})

    def _build_direct_answer_state(self, *, session_id: str):
        state = build_initial_state(
            ChatTurnCommand(
                trace_id="trace-checkpoint",
                session_id=session_id,
                turn_id="turn-checkpoint",
                user_id="user-checkpoint",
                message="请给我一个简短回答",
            )
        )
        state["turn"] = state["turn"].model_copy(update={"decision": TurnDecision.DIRECT_ANSWER})
        return state

    def _build_minimal_services(self) -> WorkflowServices:
        def load_context(state):
            state["persistent"] = state["persistent"].model_copy(update={"extra": dict(state["persistent"].extra)})
            return state

        def parse_intent_slots(state):
            state["turn"] = state["turn"].model_copy(update={"slots": dict(state["turn"].slots)})
            return state

        def resolve_reference(state):
            state["persistent"] = state["persistent"].model_copy(update={"extra": dict(state["persistent"].extra)})
            return state

        def ambiguity_check(state):
            state["turn"] = state["turn"].model_copy(update={"slots": dict(state["turn"].slots)})
            return state

        def rewrite_query(state):
            state["turn"] = state["turn"].model_copy(update={"slots": dict(state["turn"].slots)})
            return state

        def compose_answer(state):
            state["turn"] = state["turn"].model_copy(update={"final_answer": "persisted answer"})
            return state

        def checkpoint_session_state(state):
            state["runtime"] = state["runtime"].model_copy(update={"extra": dict(state["runtime"].extra)})
            return state

        def emit_final(state):
            runtime = state["runtime"]
            envelope = SseEnvelope(
                event_type=TerminalEvent.FINAL.value,
                trace_id=runtime.trace_id,
                session_id=runtime.session_id,
                turn_id=runtime.turn_id,
                timestamp=runtime.request_ts,
                workflow_version=runtime.workflow_version,
                payload={"answer_text": state["turn"].final_answer or ""},
            )
            state["runtime"] = runtime.model_copy(
                update={
                    "terminal_event": TerminalEvent.FINAL,
                    "emitted_events": list(runtime.emitted_events) + [envelope],
                }
            )
            return state

        services = WorkflowServices(
            load_context=load_context,
            understand_turn=UnderstandTurnServices(
                parse_intent_slots=parse_intent_slots,
                resolve_reference=resolve_reference,
                ambiguity_check=ambiguity_check,
                rewrite_query=rewrite_query,
            ),
            compose_answer=compose_answer,
            emit_final=emit_final,
        )
        services.persist_session = checkpoint_session_state
        return services


if __name__ == "__main__":
    unittest.main()
