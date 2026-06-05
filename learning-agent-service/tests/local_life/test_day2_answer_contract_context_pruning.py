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

from learning_agent_service.local_life.answer_planner import build_answer_planner_request


class Day2AnswerContractContextPruningTestCase(unittest.TestCase):
    def test_answer_planner_request_prunes_forbidden_context(self) -> None:
        prompt = build_answer_planner_request(
            raw_query="海底捞水晶城店有券吗？",
            slots={"category": "美食", "shop_name": "海底捞水晶城店"},
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店", "why": ["环境安静"], "risks": ["高峰期排队"], "coupon_summary": "有券"},
                {"shop_id": 9, "name": "INLOVE KTV(水晶城店)", "why": ["适合约会"], "risks": ["价格偏高"], "coupon_summary": "优惠券"},
            ],
            evidence_pack={
                "raw_query": "海底捞水晶城店有券吗？",
                "items": [
                    {"chunk_id": "coupon-1", "claim": "有券", "metadata": {"facet": "coupon", "shop_id": 5}},
                    {"chunk_id": "env-1", "claim": "环境安静", "metadata": {"facet": "environment", "shop_id": 5}},
                    {"chunk_id": "reco-1", "claim": "推荐附近几家", "metadata": {"facet": "recommendation", "shop_id": 9}},
                ],
                "ranked_candidates": [],
                "source_summary": {},
                "safety_result": {},
            },
            safety_result={"passed": True},
            answer_contract={
                "allowed_facets": ["coupon"],
                "forbidden_facets": ["environment", "recommendation"],
                "answer_style": "coupon_only",
                "missing_info_policy": "say_unknown",
            },
        )

        self.assertIn("context_pruning", prompt)
        self.assertEqual(prompt["context_pruning"]["kept_facets"], ["coupon"])
        self.assertIn("environment", prompt["context_pruning"]["dropped_facets"])
        self.assertIn("recommendation", prompt["context_pruning"]["dropped_facets"])
        self.assertEqual(prompt["answer_contract"]["allowed_facets"], ["coupon"])
        self.assertEqual(prompt["answer_contract"]["forbidden_facets"], ["environment", "recommendation"])


if __name__ == "__main__":
    unittest.main()
