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


class HighRiskEnforcementTestCase(unittest.TestCase):
    def test_open_status_without_tool_source_is_blocked(self) -> None:
        contract = AnswerContract(
            original_query="这家店现在营业吗",
            allowed_facets=["open_status"],
            forbidden_facets=[],
            allowed_tools=["check_open_status"],
            allowed_rag_facets=[],
            forbidden_rag_facets=[],
            realtime_facets=["open_status"],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=True,
            evidence_policy="strict",
            answer_style="open_status_only",
        )

        result = apply_final_answer_safety(
            answer_text="这家店现在营业中，可以直接到店。",
            answer_contract=contract,
            ranked_candidates=[{"shop_id": 1, "name": "示例店"}],
            evidence_claims=[],
            evidence_pack={"items": []},
            route_gate={"branch": "tool", "required_action": "tool_call"},
            source_contract={"required_facets": ["open_status"]},
            review_report={"decision": "pass"},
            tool_results=[],
            answer_context={"current_shop": "示例店", "final_response_mode": "grounded"},
        )

        self.assertTrue(result.blocked)
        self.assertIn("无法确认", result.answer_text)
        self.assertNotIn("可以直接到店", result.answer_text)
        self.assertIn(result.suggested_response_mode, {"partial_grounded", "no_answer", "ask_clarification"})

    def test_booking_or_order_claims_do_not_confirm_transaction_without_approval(self) -> None:
        contract = AnswerContract(
            original_query="帮我订座",
            allowed_facets=[],
            forbidden_facets=[],
            allowed_tools=["create_booking", "create_order"],
            allowed_rag_facets=[],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=False,
            evidence_policy="strict",
            answer_style="single_shop_review",
        )

        result = apply_final_answer_safety(
            answer_text="我已经帮你订座成功，晚点直接去就行。",
            answer_contract=contract,
            ranked_candidates=[{"shop_id": 1, "name": "示例店"}],
            evidence_claims=[],
            evidence_pack={"items": []},
            route_gate={"branch": "tool", "required_action": "tool_call"},
            source_contract={"required_facets": []},
            review_report={"decision": "pass"},
            tool_results=[],
            answer_context={"current_shop": "示例店", "final_response_mode": "grounded", "approval_required": True},
        )

        self.assertTrue(result.blocked)
        self.assertNotIn("我已经帮你订座成功", result.answer_text)
        self.assertGreater(result.unsupported_claim_count, 0)

    def test_phone_and_refund_claims_follow_high_risk_policy(self) -> None:
        contract = AnswerContract(
            original_query="这家店电话多少，退款怎么处理",
            allowed_facets=["phone", "refund"],
            forbidden_facets=[],
            allowed_tools=["getShopDetail"],
            allowed_rag_facets=[],
            forbidden_rag_facets=[],
            realtime_facets=[],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=False,
            evidence_policy="strict",
            answer_style="single_shop_review",
        )

        result = apply_final_answer_safety(
            answer_text="这家店电话是 123456789，而且支持无条件退款。",
            answer_contract=contract,
            ranked_candidates=[{"shop_id": 1, "name": "示例店"}],
            evidence_claims=[],
            evidence_pack={"items": []},
            route_gate={"branch": "tool", "required_action": "tool_call"},
            source_contract={"required_facets": ["phone", "refund"]},
            review_report={"decision": "pass"},
            tool_results=[],
            answer_context={"current_shop": "示例店", "final_response_mode": "grounded"},
        )

        self.assertTrue(result.blocked)
        self.assertGreater(result.unsupported_claim_count, 0)
        self.assertTrue(any(binding["risk_level"] == "high" for binding in result.claim_bindings))


if __name__ == "__main__":
    unittest.main()
