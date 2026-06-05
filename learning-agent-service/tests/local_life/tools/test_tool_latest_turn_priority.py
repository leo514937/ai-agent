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
from learning_agent_service.local_life.tool_planner import LocalLifeToolPlanner


class ToolLatestTurnPriorityTestCase(unittest.TestCase):
    def test_recommendation_scope_is_not_polluted_by_previous_single_shop(self) -> None:
        answer_contract = AnswerContract(
            original_query="附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。",
            allowed_facets=["scene_fit", "coupon", "open_status", "recommendation_reason"],
            forbidden_facets=[],
            allowed_tools=["search_restaurants", "get_coupon_list", "check_open_status"],
            allowed_rag_facets=["scene_fit", "recommendation_reason"],
            forbidden_rag_facets=["coupon", "open_status"],
            realtime_facets=["coupon", "open_status"],
            allow_recommendation=True,
            allow_extra_context=True,
            realtime_required=True,
            evidence_policy="balanced",
            answer_style="multi_shop_recommendation",
        )
        ranked_candidates = [
            SimpleNamespace(shop_id=5, name="海底捞水晶城店"),
            SimpleNamespace(shop_id=17, name="巴奴毛肚火锅"),
            SimpleNamespace(shop_id=19, name="新白鹿餐厅"),
        ]
        previous_single_shop = SimpleNamespace(shop_id=5, shop_name="海底捞水晶城店")

        plan = LocalLifeToolPlanner.plan(
            answer_contract=answer_contract,
            target_shop=previous_single_shop,
            user_need=SimpleNamespace(intent="restaurant_recommendation"),
            latest_turn_message="附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。",
            current_intent="restaurant_recommendation",
            ranked_candidates=ranked_candidates,
        )

        self.assertEqual(plan.execution_mode, "per_candidate")
        self.assertIsNone(plan.target_shop_id)
        planned_shop_ids = [item.shop_id for item in plan.runs if item.tool_name == "get_coupon_list"]
        self.assertGreaterEqual(len(set(planned_shop_ids)), 2)
        self.assertNotEqual(planned_shop_ids, [5])


if __name__ == "__main__":
    unittest.main()
