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


class Day6LangGraphChatStreamTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def _nearby_context(self) -> dict:
        return {
            "city": "北京",
            "current_city": "北京",
            "location": {
                "type": "near_user",
                "city": "北京",
                "lat": None,
                "lng": None,
                "radius_km": 3.0,
            },
        }

    def _assert_langgraph_runtime(self, result) -> dict:
        metrics = result.metrics or {}
        phase5_trace = metrics.get("phase5_trace") or {}
        self.assertEqual(phase5_trace.get("runner_kind"), "langgraph")
        self.assertEqual(phase5_trace.get("runner_backend"), "langgraph")
        self.assertTrue(phase5_trace.get("compare_ready"))
        return metrics

    def test_day6_1_recommendation_branch_via_route_gate(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day6-recommendation-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="附近有没有推荐的餐厅？",
            session_id=session_id,
            extra_payload=self._nearby_context(),
        )

        answer = result.final_answer
        metrics = self._assert_langgraph_runtime(result)
        route_gate = metrics.get("route_gate") or {}

        self.assertTrue(answer)
        self.assertEqual(route_gate.get("branch"), "recommendation")
        self.assertEqual(metrics.get("rag_mode"), "recommendation_rag")
        self.assertTrue(metrics.get("recommendation_mode"))

    def test_day6_2_mixed_facet_branch_via_route_gate(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day6-mixed-facet-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="海底捞水晶店有券吗，现在营业吗？",
            session_id=session_id,
            extra_payload={
                "shopName": "海底捞水晶店",
                "shopId": 5,
            },
        )

        answer = result.final_answer
        metrics = self._assert_langgraph_runtime(result)
        route_gate = metrics.get("route_gate") or {}
        tool_results = metrics.get("local_life_tool_results") or []

        self.assertTrue(answer)
        self.assertIn(route_gate.get("branch"), {"tool", "rag_plus_tool"})
        self.assertTrue(route_gate.get("route_reason"))
        self.assertTrue(tool_results or answer)

    def test_day6_3_clarify_branch_via_route_gate(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        session_id = f"day6-clarify-{uuid4().hex[:8]}"
        result = self.client.post_message(
            message="有券吗？",
            session_id=session_id,
        )

        answer = result.final_answer
        metrics = self._assert_langgraph_runtime(result)
        route_gate = metrics.get("route_gate") or {}

        self.assertTrue(answer)
        self.assertEqual(route_gate.get("branch"), "clarify")
        self.assertEqual((metrics.get("routing_decision") or {}).get("route_candidate"), "local_life.package_or_coupon")


if __name__ == "__main__":
    unittest.main()
