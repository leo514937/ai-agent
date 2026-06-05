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

from learning_agent_service.local_life.context_arbitration import ContextArbitration
from learning_agent_service.local_life.graph_state import build_perception_context
from learning_agent_service.local_life.schemas import LocalLifeSlots, UserNeed


class Day7MemoryArbitrationHarnessTestCase(unittest.TestCase):
    def test_latest_turn_priority_keeps_current_query_in_front(self) -> None:
        slots = LocalLifeSlots(city="北京", category="烤肉")
        user_need = UserNeed.model_validate(
            {
                "intent": "restaurant_recommendation",
                "raw_query": "附近推荐几家适合约会的餐厅",
                "resolved_query": "附近推荐几家适合约会的餐厅",
                "slots": slots.model_dump(mode="json"),
                "constraints": {},
                "required_facets": [],
                "context_refs": [],
            }
        )
        perception = build_perception_context(
            raw_query="附近推荐几家适合约会的餐厅",
            normalized_query="附近推荐几家适合约会的餐厅",
            slots=slots,
            client_context={"city": "北京"},
            session_context={"pending_user_need": {"raw_query": "上一次的话题"}},
            confidence=0.9,
        )

        result = ContextArbitration().arbitrate(
            raw_query="附近推荐几家适合约会的餐厅",
            slots=slots,
            user_need=user_need,
            session_context={"pending_user_need": {"raw_query": "上一次的话题"}},
            client_context={"city": "北京"},
            perception_context=perception,
        )

        self.assertEqual(result["perception_context"]["temporal_scope"], "neutral")
        self.assertEqual(result["memory_arbitration"]["winning_sources"]["priority_source"], "latest_turn_message")
        self.assertEqual(result["memory_arbitration"]["effective_context"]["priority_source"], "latest_turn_message")

    def test_long_term_scope_promotes_memory_candidate(self) -> None:
        slots = LocalLifeSlots(city="北京", category="烤肉")
        user_need = UserNeed.model_validate(
            {
                "intent": "restaurant_recommendation",
                "raw_query": "以后都不要吃辣了",
                "resolved_query": "以后都不要吃辣了",
                "slots": slots.model_dump(mode="json"),
                "constraints": {},
                "required_facets": [],
                "context_refs": [],
            }
        )
        perception = build_perception_context(
            raw_query="以后都不要吃辣了",
            normalized_query="以后都不要吃辣了",
            slots=slots,
            client_context={"city": "北京"},
            session_context={},
            confidence=0.95,
        )

        result = ContextArbitration().arbitrate(
            raw_query="以后都不要吃辣了",
            slots=slots,
            user_need=user_need,
            session_context={},
            client_context={"city": "北京"},
            perception_context=perception,
        )

        self.assertEqual(result["perception_context"]["temporal_scope"], "long_term")
        self.assertTrue(result["memory_arbitration"]["promotion_candidates"])

    def test_dict_policy_is_coerced_to_memory_arbitration_policy(self) -> None:
        slots = LocalLifeSlots(city="北京", category="烤肉")
        user_need = UserNeed.model_validate(
            {
                "intent": "restaurant_recommendation",
                "raw_query": "附近推荐几家适合约会的餐厅",
                "resolved_query": "附近推荐几家适合约会的餐厅",
                "slots": slots.model_dump(mode="json"),
                "constraints": {},
                "required_facets": [],
                "context_refs": [],
            }
        )

        result = ContextArbitration().arbitrate(
            raw_query="附近推荐几家适合约会的餐厅",
            slots=slots,
            user_need=user_need,
            session_context={},
            client_context={"city": "北京"},
            policy={"priority_source": "latest_turn_message"},
        )

        self.assertEqual(result["memory_arbitration"]["winning_sources"]["priority_source"], "latest_turn_message")


if __name__ == "__main__":
    unittest.main()
