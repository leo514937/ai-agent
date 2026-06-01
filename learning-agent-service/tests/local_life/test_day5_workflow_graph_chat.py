from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient

try:
    from learning_agent_service.application.workflow.builder import LANGGRAPH_AVAILABLE
except Exception:  # pragma: no cover - optional dependency
    LANGGRAPH_AVAILABLE = False


class Day5WorkflowGraphChatTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def test_day5_graph_runner_handles_local_life_chat(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day5-graph-local-life-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞火锅(水晶城购物中心店）有券吗，现在营业吗？",
            session_id=session_id,
            extra_payload={
                "shopName": "海底捞火锅(水晶城购物中心店）",
                "shopId": 5,
            },
        )

        answer = result.final_answer
        metrics = result.metrics or {}
        phase5_trace = metrics.get("phase5_trace") or {}

        self.assertTrue(answer)
        self.assertEqual(phase5_trace.get("runner_kind"), "langgraph")
        self.assertEqual(phase5_trace.get("runner_backend"), "langgraph")
        self.assertTrue(phase5_trace.get("compare_ready"))

    def test_day5_graph_runner_keeps_recommendation_default_count(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day5-graph-reco-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="附近有没有推荐的餐厅？",
            session_id=session_id,
            extra_payload={
                "city": "北京",
                "current_city": "北京",
                "location": {
                    "type": "near_user",
                    "city": "北京",
                    "lat": None,
                    "lng": None,
                    "radius_km": 3.0,
                },
            },
        )

        answer = result.final_answer
        metrics = result.metrics or {}
        phase5_trace = metrics.get("phase5_trace") or {}

        self.assertTrue(answer)
        self.assertEqual(phase5_trace.get("runner_kind"), "langgraph")
        self.assertEqual(metrics.get("route_gate", {}).get("branch"), "recommendation")
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")


if __name__ == "__main__":
    unittest.main()
