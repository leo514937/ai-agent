from __future__ import annotations

import sys
import unittest
from pathlib import Path

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.rag.eval import build_default_eval_service
from learning_agent_service.rag.models import RetrievalPlan


class RetrievalTraceContractTestCase(unittest.TestCase):
    def test_empty_query_exposes_empty_reason_and_counts(self) -> None:
        service = build_default_eval_service()

        result = service.retrieve(
            RetrievalPlan(
                semantic_query="完全不存在的本地生活查询 987654321",
                keyword_query="完全不存在的本地生活查询 987654321",
                extra={"raw_query": "完全不存在的本地生活查询 987654321"},
            )
        )

        self.assertIsNotNone(result.debug_trace)
        self.assertEqual(result.debug_trace.retrieval_mode, "empty")
        self.assertEqual(result.debug_trace.empty_reason, "no_hits")
        self.assertEqual(result.debug_trace.kept_count, 0)
        self.assertGreaterEqual(result.debug_trace.rejected_count, 0)
        self.assertEqual(result.debug_trace.extra["retrieval_mode"], "empty")
        self.assertEqual(result.debug_trace.extra["empty_reason"], "no_hits")
        self.assertIn("dense", result.debug_trace.route_hit_counts)
        self.assertIn("sparse", result.debug_trace.route_hit_counts)
        self.assertIn("metadata", result.debug_trace.route_hit_counts)


if __name__ == "__main__":
    unittest.main()
