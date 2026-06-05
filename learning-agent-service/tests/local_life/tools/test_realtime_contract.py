from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.realtime_contract import fallback_message_for_facet, get_realtime_contract
from learning_agent_service.local_life.tool_planner import LocalLifeToolPlanner


class RealtimeContractTestCase(unittest.TestCase):
    def test_coupon_contract_cannot_infer_from_rag(self) -> None:
        contract = get_realtime_contract("coupon")
        self.assertIsNotNone(contract)
        self.assertEqual(contract.allowed_tools, ["get_coupon_list"])
        self.assertTrue(contract.requires_tool)
        self.assertTrue(contract.cannot_infer_from_rag)

    def test_single_shop_coupon_plan_requires_tool(self) -> None:
        answer_contract = AnswerContract(
            original_query="海底捞有券吗",
            allowed_facets=["coupon"],
            forbidden_facets=["environment"],
            allowed_tools=["get_coupon_list"],
            allowed_rag_facets=[],
            forbidden_rag_facets=["coupon", "environment"],
            realtime_facets=["coupon"],
            allow_recommendation=False,
            allow_extra_context=False,
            realtime_required=True,
            evidence_policy="strict",
            answer_style="coupon_only",
        )
        target_shop = SimpleNamespace(shop_id=5, shop_name="海底捞水晶城店")

        plan = LocalLifeToolPlanner.plan(
            answer_contract=answer_contract,
            target_shop=target_shop,
            user_need=SimpleNamespace(intent="package_or_coupon"),
            latest_turn_message="它有券吗？",
            current_intent="package_or_coupon",
            ranked_candidates=[],
        )

        self.assertEqual(plan.required_tools, ["get_coupon_list"])
        self.assertEqual(plan.execution_mode, "single_shop")
        self.assertFalse(plan.blocked_by_realtime_contract)
        self.assertEqual(plan.runs[0].shop_id, 5)
        self.assertEqual(plan.latest_turn_message, "它有券吗？")

    def test_fallback_message_is_shop_aware(self) -> None:
        message = fallback_message_for_facet("open_status", "海底捞水晶城店")
        self.assertIn("海底捞水晶城店", message or "")
        self.assertIn("实时状态", message or "")


if __name__ == "__main__":
    unittest.main()
