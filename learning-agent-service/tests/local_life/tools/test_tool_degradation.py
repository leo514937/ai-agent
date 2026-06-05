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
from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.response_builder import build_response_bundle
from learning_agent_service.local_life.schemas import LocalLifeSlots
from learning_agent_service.local_life.tool_result_normalizer import normalize_tool_result


class _FakeCandidate(SimpleNamespace):
    def model_dump(self, mode: str = "json") -> dict:
        return {
            "shop_id": self.shop_id,
            "name": self.name,
            "vouchers": list(self.vouchers),
            "structured_features": dict(self.structured_features),
            "evidence_features": dict(self.evidence_features),
            "explainable_reasons": list(self.explainable_reasons),
            "matched_requirements": list(self.matched_requirements),
        }


class ToolDegradationTestCase(unittest.TestCase):
    def test_coupon_timeout_still_marks_realtime_supported(self) -> None:
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
        user_need = SimpleNamespace(
            required_facets=[SimpleNamespace(name="coupon")],
            recommendation_count=1,
        )
        candidate = _FakeCandidate(
            shop_id=5,
            name="海底捞水晶城店",
            vouchers=[],
            structured_features={},
            evidence_features={},
            explainable_reasons=[],
            matched_requirements=[],
        )
        bundle = FacetResultBundle(
            tool_results=[
                normalize_tool_result(
                    tool_name="get_coupon_list",
                    raw_output={"shop_id": 5, "shop_name": "海底捞水晶城店", "count": 0, "coupons": []},
                    shop_id=5,
                    shop_name="海底捞水晶城店",
                    status="timeout",
                    error_message="timeout",
                )
            ]
        )

        result = build_response_bundle(
            raw_query="海底捞水晶城店有券吗？",
            slots=LocalLifeSlots(),
            answer_contract=answer_contract,
            ranked_candidates=[candidate],
            evidence_claims=[],
            page="assistant",
            current_topic="海底捞水晶城店",
            selected_shop_id=5,
            current_shop="海底捞水晶城店",
            user_need=user_need,
            facet_result_bundle=bundle,
        )

        self.assertIn("实时优惠券信息", result.answer_text)
        self.assertTrue(result.metrics.get("answer_realtime_claim_supported"))


if __name__ == "__main__":
    unittest.main()
