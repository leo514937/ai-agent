import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap

from learning_agent_service.local_life.answer_contract import AnswerContract
from learning_agent_service.local_life.response_builder import build_multi_shop_recommendation_answer
from learning_agent_service.local_life.schemas import (
    LocalLifeIntentType,
    LocalLifeSlots,
    LocationNorm,
    QueryUnderstandingResult,
    RankedCandidate,
    RequiredFacet,
)
from learning_agent_service.local_life.slot_extractor import extract_slots


class Day7LangGraphDefaultCutoverContractTestCase(unittest.TestCase):
    def test_recommendation_query_does_not_inherit_session_shop(self) -> None:
        query = "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"
        understanding = QueryUnderstandingResult(
            normalized_query=query,
            semantic_query=query,
            keyword_query=query,
            location_norm=LocationNorm(),
            confidence=0.8,
        )
        slots, _, _ = extract_slots(
            understanding,
            query,
            session_context={"current_shop": "海底捞水晶城店"},
        )

        self.assertIsNone(slots.shop_query)

    def test_recommendation_contract_prefers_multi_shop(self) -> None:
        query = "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"
        user_need = SimpleNamespace(
            intent="restaurant_recommendation",
            raw_query=query,
            required_facets=[
                RequiredFacet(name="location", required=True, data_source="client_context", freshness="near_realtime_required", entity_keys=["city"], missing_policy="ask_clarification"),
                RequiredFacet(name="scene_fit", required=True, data_source="static_rag", freshness="static_ok", entity_keys=["shop_id"], missing_policy="partial_grounded"),
                RequiredFacet(name="coupon", required=True, data_source="dynamic_tool", freshness="near_realtime_required", entity_keys=["shop_id"], missing_policy="partial_grounded"),
                RequiredFacet(name="open_status", required=True, data_source="dynamic_tool", freshness="near_realtime_required", entity_keys=["shop_id"], missing_policy="partial_grounded"),
            ],
            recommendation_count=3,
        )

        contract = AnswerContract.build_contract(user_need, target_shop=None)

        self.assertEqual(contract.answer_style, "multi_shop_recommendation")

    def test_multi_shop_answer_includes_date_coupon_open_signals(self) -> None:
        query = "附近有没有适合约会、有券、现在还营业的餐厅？推荐几家。"
        user_need = SimpleNamespace(
            intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION.value,
            raw_query=query,
            required_facets=[
                SimpleNamespace(name="location"),
                SimpleNamespace(name="scene_fit"),
                SimpleNamespace(name="coupon"),
                SimpleNamespace(name="open_status"),
            ],
            recommendation_count=3,
        )
        candidates = [
            RankedCandidate(
                shop_id=1,
                name="新白鹿餐厅(运河上街店)",
                structured_features={"distance_km": 1.2, "avg_price": 88, "score": 4.7, "open_hours": "10:00-22:00"},
                explainable_reasons=["适合约会", "环境安静"],
                vouchers=[{"title": "双人套餐券", "payValue": 99, "actualValue": 149}],
            ),
            RankedCandidate(
                shop_id=2,
                name="云味食集·湖墅店",
                structured_features={"distance_km": 1.8, "avg_price": 72, "score": 4.6},
                explainable_reasons=["适合约会", "停车方便"],
                vouchers=[],
            ),
            RankedCandidate(
                shop_id=3,
                name="Mamala(杭州远洋乐堤港店)",
                structured_features={"distance_km": 2.5, "avg_price": 128, "score": 4.5, "open_hours": "11:00-23:00"},
                explainable_reasons=["适合约会", "氛围感强"],
                vouchers=[{"title": "晚餐券", "payValue": 199, "actualValue": 259}],
            ),
        ]

        answer = build_multi_shop_recommendation_answer("附近餐厅", candidates, [], user_need=user_need)

        self.assertIn("我帮你推荐以下这几家店", answer)
        self.assertIn("适合约会", answer)
        self.assertIn("券", answer)
        self.assertIn("营业", answer)
        self.assertIn("1.", answer)
        self.assertIn("2.", answer)
        self.assertIn("3.", answer)


if __name__ == "__main__":
    unittest.main()
