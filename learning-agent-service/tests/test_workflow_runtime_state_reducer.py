from __future__ import annotations

import unittest
from datetime import datetime, timezone

from learning_agent_service.application.workflow.state import (
    append_runtime_error,
    append_runtime_event,
    append_stage_timeline_entry,
    build_runtime_context,
)
from learning_agent_service.domain.contracts import ChatTurnCommand
from learning_agent_service.domain.errors import WorkflowErrorCode, build_error
from learning_agent_service.domain.state import build_initial_state


class WorkflowRuntimeStateReducerTests(unittest.TestCase):
    def _build_state(self):
        command = ChatTurnCommand(
            trace_id="trace-runtime-reducer",
            session_id="session-runtime-reducer",
            turn_id="turn-runtime-reducer",
            user_id="user-runtime-reducer",
            message="帮我看看这家店",
            client_context={"shop_name": "测试门店"},
        )
        return build_initial_state(command=command, workflow_version="test/v1")

    def test_build_initial_state_exposes_runtime_context_and_reducer_buckets(self) -> None:
        state = self._build_state()

        self.assertIn("runtime_context", state)
        self.assertIn("sse_events", state)
        self.assertIn("errors", state)
        self.assertIn("stage_timeline", state)
        self.assertIn("retrieval_traces", state)
        self.assertIn("tool_results", state)
        self.assertIn("shop_analyses", state)

        runtime_context = build_runtime_context(state)
        self.assertEqual(runtime_context["session_id"], "session-runtime-reducer")
        self.assertEqual(runtime_context["client_context"]["shop_name"], "测试门店")

        self.assertEqual(state["sse_events"], [])
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["stage_timeline"], [])

    def test_append_helpers_keep_runtime_and_reducer_buckets_in_sync(self) -> None:
        state = self._build_state()

        append_runtime_event(state, "load_context_started", {"stage": "load_context", "status": "started"})
        append_stage_timeline_entry(
            state,
            {
                "stage": "load_context",
                "status": "started",
                "route_decision": "direct_answer",
                "route_reason": "test",
                "detail": {"source": "unit_test"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        append_runtime_error(
            state,
            build_error(
                WorkflowErrorCode.INTERNAL_ERROR,
                stage="load_context",
                message="boom",
                retryable=False,
                is_terminal=False,
            ),
        )

        self.assertEqual(len(state["runtime"].emitted_events), 1)
        self.assertEqual(len(state["sse_events"]), 1)
        self.assertEqual(len(state["runtime"].errors), 1)
        self.assertEqual(len(state["errors"]), 1)
        self.assertEqual(len(state["turn"].stage_timeline), 1)
        self.assertEqual(len(state["stage_timeline"]), 1)


if __name__ == "__main__":
    unittest.main()
