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


class Day7LangGraphDefaultChatTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def _assert_langgraph_default(self, result) -> dict:
        metrics = result.metrics or {}
        phase5_trace = metrics.get("phase5_trace") or {}
        self.assertEqual(phase5_trace.get("runner_kind"), "langgraph")
        self.assertEqual(phase5_trace.get("runner_backend"), "langgraph")
        self.assertEqual(metrics.get("graph_runtime"), "langgraph")
        self.assertIn(metrics.get("graph_fallback"), {None, "none"})
        return metrics

    def test_day7_default_single_shop_chat_uses_langgraph(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day7-default-single-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=session_id,
        )

        answer = result.final_answer
        metrics = self._assert_langgraph_default(result)

        self.assertTrue(answer)
        self.assertIn("海底捞", answer)
        self.assertEqual(metrics.get("graph_runtime"), "langgraph")

    def test_day7_default_recommendation_chat_uses_langgraph(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day7-default-reco-{uuid4().hex[:8]}"
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
        metrics = self._assert_langgraph_default(result)

        self.assertTrue(answer)
        self.assertEqual(metrics.get("route_gate", {}).get("branch"), "recommendation")
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")


if __name__ == "__main__":
    unittest.main()
