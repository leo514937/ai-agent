from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.final_answer_safety import apply_final_answer_safety


class ClaimBindingTestCase(unittest.TestCase):
    def test_apply_final_answer_safety_binds_tool_and_rag_sources_per_claim(self) -> None:
        contract = AnswerContract(
            original_query="海底捞水晶城店有券吗，营业吗，环境怎么样",
            allowed_facets=["coupon", "open_status", "environment"],
            forbidden_facets=[],
            allowed_tools=["get_coupon_list", "check_open_status"],
            allowed_rag_facets=["environment"],
            forbidden_rag_facets=[],
            realtime_facets=["coupon", "open_status"],
            allow_recommendation=False,
            allow_extra_context=True,
            realtime_required=True,
            evidence_policy="strict",
            answer_style="facet_multi",
        )

        result = apply_final_answer_safety(
            answer_text="\n".join(
                [
                    "券信息：海底捞水晶城店当前有1张券。",
                    "营业状态：海底捞水晶城店现在营业中。",
                    "环境评价：从评价看，环境偏安静。",
                ]
            ),
            answer_contract=contract,
            ranked_candidates=[
                {
                    "shop_id": 5,
                    "name": "海底捞水晶城店",
                    "score": 4.8,
                    "distance_km": 1.2,
                    "avg_price": 96,
                    "explainable_reasons": ["评分高", "距离近"],
                }
            ],
            evidence_claims=[
                {
                    "chunk_id": "rag-1",
                    "shop_id": 5,
                    "claim": "环境安静",
                    "support_text": "用户评价提到环境比较安静，适合家庭聚餐。",
                    "source_type": "review_summary",
                    "confidence": 0.92,
                }
            ],
            facet_result_bundle={
                "coupon_result": {
                    "tool_name": "get_coupon_list",
                    "status": "success",
                    "data": {"shop_id": 5, "shop_name": "海底捞水晶城店", "coupon_count": 1},
                },
                "open_status_result": {
                    "tool_name": "check_open_status",
                    "status": "success",
                    "data": {"shop_id": 5, "shop_name": "海底捞水晶城店", "open_status": "open"},
                },
                "tool_results": [
                    {
                        "facet": "coupon",
                        "shop_id": 5,
                        "status": "success",
                        "tool_name": "get_coupon_list",
                        "data": {"shop_id": 5, "shop_name": "海底捞水晶城店", "coupon_count": 1},
                    },
                    {
                        "facet": "open_status",
                        "shop_id": 5,
                        "status": "success",
                        "tool_name": "check_open_status",
                        "data": {"shop_id": 5, "shop_name": "海底捞水晶城店", "open_status": "open"},
                    },
                ],
            },
            route_gate={"branch": "tool", "required_action": "tool_call"},
            source_contract={"required_facets": ["coupon", "open_status", "environment"]},
            review_report={"decision": "pass"},
            tool_results=[
                {
                    "tool_name": "get_coupon_list",
                    "status": "success",
                    "normalized_output": {"data": {"shop_id": 5, "coupon_count": 1}},
                },
                {
                    "tool_name": "check_open_status",
                    "status": "success",
                    "normalized_output": {"data": {"shop_id": 5, "open_status": "open"}},
                },
            ],
            answer_context={"current_shop": "海底捞水晶城店", "final_response_mode": "grounded"},
        )

        self.assertGreaterEqual(result.claim_count, 3)
        self.assertEqual(result.unsupported_claim_count, 0)
        self.assertFalse(result.blocked)
        self.assertIn("claim_bindings", result.final_answer_audit)
        support_statuses = {binding["support_status"] for binding in result.claim_bindings}
        self.assertEqual(support_statuses, {"supported"})
        claim_types = {binding["claim_type"] for binding in result.claim_bindings}
        self.assertTrue({"coupon", "open_status", "environment"}.issubset(claim_types))
        self.assertTrue(any(binding["risk_level"] == "high" for binding in result.claim_bindings))
        self.assertTrue(all("facet" in binding for binding in result.claim_bindings))
        self.assertTrue(all("entity_id" in binding for binding in result.claim_bindings))
        self.assertTrue(all("shop_id" in binding for binding in result.claim_bindings))
        self.assertTrue(all(binding["supporting_sources"] for binding in result.claim_bindings))

    def test_apply_final_answer_safety_blocks_fabricated_high_risk_claims(self) -> None:
        contract = AnswerContract(
            original_query="海底捞水晶城店现在营业吗，有券吗",
            allowed_facets=["coupon", "open_status"],
            forbidden_facets=[],
            allowed_tools=["get_coupon_list", "check_open_status"],
            allowed_rag_facets=[],
            forbidden_rag_facets=[],
            realtime_facets=["coupon", "open_status"],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=True,
            evidence_policy="strict",
            answer_style="coupon_only",
        )

        result = apply_final_answer_safety(
            answer_text="海底捞水晶城店评分 4.9，而且今天还有 3 张券。",
            answer_contract=contract,
            ranked_candidates=[{"shop_id": 5, "name": "海底捞水晶城店", "score": 4.8}],
            evidence_claims=[],
            evidence_pack={"items": []},
            route_gate={"branch": "tool", "required_action": "tool_call"},
            source_contract={"required_facets": ["coupon", "open_status"]},
            review_report={"decision": "pass"},
            tool_results=[],
            answer_context={"current_shop": "海底捞水晶城店", "final_response_mode": "grounded", "approval_required": True},
        )

        self.assertTrue(result.blocked)
        self.assertGreater(result.unsupported_claim_count, 0)
        self.assertNotIn("评分 4.9", result.answer_text)
        self.assertNotIn("3 张券", result.answer_text)
        self.assertIn("unsupported_claim_observed", result.final_answer_audit["issues"])


if __name__ == "__main__":
    unittest.main()
