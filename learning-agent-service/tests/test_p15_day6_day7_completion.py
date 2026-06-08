from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
LOCAL_LIFE_TESTS_DIR = TESTS_DIR / "local_life"
for candidate in (str(TESTS_DIR), str(LOCAL_LIFE_TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient
from learning_agent_service.local_life.eval import load_golden_cases, run_golden_cases
from learning_agent_service.testing import HarnessRunResult

try:
    from learning_agent_service.application.workflow.builder import LANGGRAPH_AVAILABLE
except Exception:  # pragma: no cover - optional dependency
    LANGGRAPH_AVAILABLE = False


class P15Day6Day7CompletionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()
        cls.golden_cases = load_golden_cases(PROJECT_ROOT / "eval" / "local_life" / "golden_cases.jsonl")

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
        self.assertEqual(metrics.get("graph_runtime"), "langgraph")
        return metrics

    def _executor(self, case):
        turns = case.turns or (case.query,)
        last_result = None
        for turn in turns:
            last_result = self.client.post_message(
                message=turn,
                session_id=f"p15-golden-{case.case_id}",
                extra_payload=dict(case.client_context or {}),
            )
        assert last_result is not None
        metrics = last_result.metrics or {}
        phase5_trace = metrics.get("phase5_trace") or {}
        return HarnessRunResult(
            case_id=case.case_id,
            passed=True,
            actual_trace={
                "routing_trace": metrics.get("routing_trace") or last_result.final_payload.get("routing_trace") or metrics.get("routing_decision") or {},
                "phase5_trace": phase5_trace,
                "graph_runtime": metrics.get("graph_runtime") or phase5_trace.get("graph_runtime"),
                "graph_fallback": metrics.get("graph_fallback") or phase5_trace.get("graph_fallback") or "none",
                "route_gate": metrics.get("route_gate") or {},
                "metrics": metrics,
            },
            actual_response_mode=str(last_result.final_payload.get("mode") or metrics.get("final_response_mode") or "unknown"),
            actual_answer=last_result.final_answer,
            failures=[],
        )

    def test_day6_langgraph_acceptance(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        recommendation = self.client.post_message(
            message="附近有没有推荐的餐馆？",
            session_id=f"day6-recommendation-{uuid4().hex[:8]}",
            extra_payload=self._nearby_context(),
        )
        recommendation_metrics = self._assert_langgraph_runtime(recommendation)
        recommendation_route_gate = recommendation_metrics.get("route_gate") or {}

        self.assertTrue(recommendation.final_answer)
        self.assertEqual(recommendation_route_gate.get("branch"), "recommendation")
        self.assertEqual(recommendation_metrics.get("rag_mode"), "recommendation_rag")
        self.assertTrue(recommendation_metrics.get("recommendation_mode"))

        mixed = self.client.post_message(
            message="海底捞水晶城店有券吗，现在营业吗？",
            session_id=f"day6-mixed-{uuid4().hex[:8]}",
            extra_payload={
                "shopName": "海底捞水晶城店",
                "shopId": 5,
            },
        )
        mixed_metrics = self._assert_langgraph_runtime(mixed)
        mixed_route_gate = mixed_metrics.get("route_gate") or {}
        mixed_tool_results = mixed_metrics.get("local_life_tool_results") or []

        self.assertTrue(mixed.final_answer)
        self.assertIn(mixed_route_gate.get("branch"), {"rag", "tool", "rag_plus_tool"})
        self.assertTrue(mixed_tool_results or mixed.final_answer)

        clarify = self.client.post_message(
            message="有券吗？",
            session_id=f"day6-clarify-{uuid4().hex[:8]}",
        )
        clarify_metrics = self._assert_langgraph_runtime(clarify)
        clarify_route_gate = clarify_metrics.get("route_gate") or {}

        self.assertTrue(clarify.final_answer)
        self.assertEqual(clarify_route_gate.get("branch"), "clarify")
        self.assertEqual((clarify_metrics.get("routing_decision") or {}).get("route_candidate"), "local_life.package_or_coupon")

    def test_day7_langgraph_acceptance(self) -> None:
        if not LANGGRAPH_AVAILABLE:
            self.skipTest("langgraph is not installed")

        single_shop = self.client.post_message(
            message="海底捞水晶城店怎么样？",
            session_id=f"day7-single-{uuid4().hex[:8]}",
        )
        single_metrics = self._assert_langgraph_runtime(single_shop)

        self.assertTrue(single_shop.final_answer)
        self.assertIn(single_metrics.get("graph_fallback"), {None, "none"})
        self.assertEqual(single_metrics.get("route_gate", {}).get("branch"), "rag")

        recommendation = self.client.post_message(
            message="附近有没有推荐的餐馆？",
            session_id=f"day7-reco-{uuid4().hex[:8]}",
            extra_payload=self._nearby_context(),
        )
        recommendation_metrics = self._assert_langgraph_runtime(recommendation)

        self.assertTrue(recommendation.final_answer)
        self.assertEqual(recommendation_metrics.get("route_gate", {}).get("branch"), "recommendation")
        self.assertEqual(recommendation_metrics.get("rag_mode"), "recommendation_rag")

        results = run_golden_cases(self.golden_cases, self._executor)
        failures = [result for result in results if not result.passed]
        if failures:
            details = "\n".join(f"{item.case_id}: {item.failures}" for item in failures)
            self.fail(f"Golden cases failed:\n{details}")

        self.assertGreaterEqual(len(results), 7)
        self.assertTrue(all("routing_trace" in result.actual_trace for result in results))


if __name__ == "__main__":
    unittest.main()
