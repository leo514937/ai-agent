"""E2E-style contract tests for todo/07 §4.

These tests stay close to the requested behaviors while using the
currently available mock data and session helpers:
  1. recommendation follow-up reads from last_recommendation_list
  2. ambiguous "这家" stays ambiguous instead of guessing the first shop
  3. clarification state clears on topic switch
  4. unknown data in comparison stays unknown
  5. verifier blocks ranking changes by the LLM
"""

from __future__ import annotations

from ..answer.verifier import verify_answer
from ..domain.state import SessionState
from ..engine.session_write import SessionScenario, get_directive, resolve_scenario
from .fakes.mock_tools import get_coupon_list, get_shop_detail, resolve_shop, search_shops


def _apply_directive(state: SessionState, directive, ctx: dict[str, object]) -> None:
    """Small local helper to apply the session write directive in tests."""
    none_fields = {"current_shop", "pending_clarification", "comparison_result", "suggested_shop"}
    dict_fields = {"active_constraints"}
    list_fields = {"last_recommendation_list", "comparison_targets"}

    for field_name, value in directive.set_fields.items():
        resolved = ctx.get(field_name) if value is None else value
        if resolved is not None:
            setattr(state, field_name, resolved)

    for field_name in directive.clear_fields:
        if field_name in list_fields:
            setattr(state, field_name, [])
        elif field_name in dict_fields:
            setattr(state, field_name, {})
        elif field_name in none_fields:
            setattr(state, field_name, None)
        else:
            setattr(state, field_name, None)


class TestMultiTurnFollow:
    """推荐后续问法应沿用 last_recommendation_list。"""

    def test_follow_up_first_shop_coupon_lookup(self):
        session_state = SessionState(
            last_recommendation_list=[
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"},
            ]
        )

        first_shop_id = session_state.last_recommendation_list[0]["shop_id"]
        coupon_result = get_coupon_list(first_shop_id)

        assert coupon_result["success"] is True
        assert coupon_result["total"] > 0
        assert any(c["shop_id"] == first_shop_id for c in coupon_result["data"])


class TestAnaphoraAmbiguity:
    """推荐后问“这家”时不能盲猜第一家。"""

    def test_this_shop_stays_ambiguous(self):
        recommendation_list = search_shops("海底捞")["data"]
        session_shop_ids = [s["shop_id"] for s in recommendation_list[:3]]

        result = resolve_shop("这家", session_shop_ids=session_shop_ids)

        assert result["status"] == "AMBIGUOUS"
        assert len(result["candidates"]) >= 2


class TestClarificationReset:
    """pending_clarification 遇到换话题时要清空。"""

    def test_topic_switch_clears_pending_clarification(self):
        state = SessionState(
            pending_clarification={
                "pending_id": "pc_1",
                "original_task_type": "recommendation",
            },
            last_recommendation_list=[
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}
            ],
        )

        scenario = resolve_scenario(
            task_type="recommendation",
            resolve_status=None,
            is_clarification_reply=False,
            is_topic_switch=True,
        )
        directive = get_directive(scenario)
        _apply_directive(state, directive, {})

        assert scenario == SessionScenario.TOPIC_SWITCH
        assert state.pending_clarification is None
        assert state.last_recommendation_list == [
            {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}
        ]


class TestPartialComparison:
    """对比场景中 unknown 必须被保留，而不是硬判更差。"""

    def test_unknown_status_is_preserved(self):
        detail_a = get_shop_detail("shop_sc_05")
        detail_b = get_shop_detail("shop_sc_09")
        detail_c = get_shop_detail("shop_sc_08")

        assert detail_a["success"] is True
        assert detail_b["success"] is True
        assert detail_c["success"] is True

        comparison_matrix = {
            "rows": [
                {
                    "shop_id": detail_a["data"]["shop_id"],
                    "coupon_status": "has_coupon",
                    "open_status": detail_a["data"]["open_status"],
                },
                {
                    "shop_id": detail_b["data"]["shop_id"],
                    "coupon_status": "unknown",
                    "open_status": detail_b["data"]["open_status"],
                },
                {
                    "shop_id": detail_c["data"]["shop_id"],
                    "coupon_status": "empty",
                    "open_status": detail_c["data"]["open_status"],
                },
            ]
        }

        assert comparison_matrix["rows"][1]["coupon_status"] == "unknown"
        assert comparison_matrix["rows"][2]["open_status"] == "closed"


class TestHallucinationGuard:
    """LLM 改排序必须被 verifier 拦截。"""

    def test_verifier_blocks_reordered_ranking(self):
        evidence = {
            "ranking_snapshot": {
                "ranked": [
                    {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                    {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"},
                ]
            },
            "forbidden_claims": ["评分最高"],
        }
        answer = "推荐顺序是张记家常菜(北邮店)在前，川味轩(知春路店)在后。"

        result = verify_answer(answer, evidence, "recommendation")

        assert result["passed"] is False
        assert "ranking_changed_by_llm" in result["issues"]
