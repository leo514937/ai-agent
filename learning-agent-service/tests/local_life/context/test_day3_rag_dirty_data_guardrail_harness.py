from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient


class Day3RagDirtyDataGuardrailHarnessTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def test_single_shop_environment_query_emits_guardrail_trace(self) -> None:
        session_id = f"day3-rag-guardrail-{uuid4().hex[:8]}"

        result = self.client.post_message(
            message="海底捞水晶城店环境怎么样？",
            session_id=session_id,
        )

        self.assertTrue(result.final_answer)
        self.assertNotIn("巴奴", result.final_answer)
        guardrail = result.metrics.get("rag_guardrail") or {}
        self.assertEqual(result.metrics.get("rag_mode"), "single_shop_rag")
        self.assertEqual(guardrail.get("rag_mode"), "single_shop_rag")
        self.assertEqual(guardrail.get("latest_turn_message"), "海底捞水晶城店环境怎么样？")
        self.assertIn("environment", guardrail.get("final_allowed_facets", []))
        self.assertIn("coupon", guardrail.get("forbidden_facets", []))
        self.assertIn("final_clean_evidence_count", guardrail)

    def test_recommendation_query_emits_recommendation_guardrail_trace(self) -> None:
        session_id = f"day3-rag-reco-{uuid4().hex[:8]}"

        result = self.client.post_message(
            message="附近有没有适合约会的餐厅？推荐几家。",
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

        self.assertTrue(result.final_answer)
        guardrail = result.metrics.get("rag_guardrail") or {}
        self.assertEqual(result.metrics.get("rag_mode"), "recommendation_rag")
        self.assertEqual(guardrail.get("rag_mode"), "recommendation_rag")
        self.assertGreaterEqual(int(guardrail.get("recommendation_shop_count") or 0), 1)
        self.assertIn("scene_fit", guardrail.get("final_allowed_facets", []))


if __name__ == "__main__":
    unittest.main()
