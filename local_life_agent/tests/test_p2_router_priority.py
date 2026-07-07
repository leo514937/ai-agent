from __future__ import annotations

from local_life_agent.planning.orchestration_router import build_orchestration_decision


def _base_state(**overrides):
    state = {
        "top_intent": "local_life",
        "semantic_frame": {"confidence": 0.84},
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "raw_text": "",
    }
    state.update(overrides)
    return state


def test_router_keeps_discovery_decision_when_coupon_is_only_a_facet():
    decision = build_orchestration_decision(
        _base_state(
            task_type="recommendation",
            semantic_frame={
                "confidence": 0.85,
                "candidate_category": "restaurant",
                "hard_constraints": {"nearby": True},
                "comparison_targets": [],
            },
            raw_text="附近推荐几家适合约会、现在营业、最好有券、人均100左右的餐厅",
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert decision.requires_clarification is False


def test_router_clarifies_deictic_single_shop_query_without_current_shop():
    decision = build_orchestration_decision(
        _base_state(
            task_type="single_shop_query",
            semantic_frame={
                "confidence": 0.8,
                "primary_task": "shop_coupon",
                "reference_mentions": ["这家"],
                "deictic_references": ["这家"],
            },
            raw_text="这家有券吗",
        )
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.requires_clarification is True
    assert "current_shop" in decision.missing_fields


def test_router_uses_single_shop_anchor_for_deictic_query():
    decision = build_orchestration_decision(
        _base_state(
            task_type="single_shop_query",
            current_shop={"shop_id": "shop_1", "shop_name": "测试店"},
            semantic_frame={
                "confidence": 0.85,
                "primary_task": "shop_coupon",
                "reference_mentions": ["这家"],
                "deictic_references": ["这家"],
            },
            raw_text="这家有券吗",
        )
    )

    assert decision.workflow_name == "deterministic_tool"
    assert decision.response_mode == "tool_answer"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False


def test_router_clarifies_ordinal_reference_without_last_recommendation_list():
    decision = build_orchestration_decision(
        _base_state(
            task_type="single_shop_query",
            semantic_frame={
                "confidence": 0.79,
                "primary_task": "shop_coupon",
                "reference_mentions": ["第一家"],
                "ordinal_references": ["第一家"],
            },
            raw_text="第一家有券吗",
        )
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.requires_clarification is True
    assert "current_shop" in decision.missing_fields


def test_router_uses_last_recommendation_list_for_ordinal_query():
    decision = build_orchestration_decision(
        _base_state(
            task_type="single_shop_query",
            last_recommendation_list=[{"shop_id": "shop_1", "shop_name": "第一家"}],
            semantic_frame={
                "confidence": 0.86,
                "primary_task": "shop_coupon",
                "reference_mentions": ["第一家"],
                "ordinal_references": ["第一家"],
            },
            raw_text="第一家有券吗",
        )
    )

    assert decision.workflow_name == "deterministic_tool"
    assert decision.response_mode == "tool_answer"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False


def test_router_uses_discovery_decision_for_comparison_when_targets_are_enough():
    decision = build_orchestration_decision(
        _base_state(
            task_type="comparison",
            semantic_frame={
                "confidence": 0.83,
                "comparison_targets": [
                    {"reference": "explicit", "shop_name": "海底捞"},
                    {"reference": "explicit", "shop_name": "巴奴"},
                ],
            },
            raw_text="海底捞和巴奴哪个更适合聚餐",
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "comparison"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False


def test_router_clarifies_comparison_when_targets_are_insufficient():
    decision = build_orchestration_decision(
        _base_state(
            task_type="comparison",
            last_recommendation_list=[{"shop_id": "shop_1", "shop_name": "第一家"}],
            semantic_frame={
                "confidence": 0.8,
                "comparison_targets": [{"reference": "ordinal", "source_text": "第一家", "shop_name": "第一家"}],
                "ordinal_references": ["第一家"],
            },
            raw_text="第一家和第二家哪家更适合带娃",
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.requires_clarification is False
    assert decision.response_mode == "answer"


def test_router_preserves_exploration_planning_priority():
    decision = build_orchestration_decision(
        _base_state(
            task_type="date_plan",
            semantic_frame={"confidence": 0.63},
            raw_text="周末安排一个约会行程",
        )
    )

    assert decision.workflow_name == "exploration_planning"
    assert decision.response_mode == "exploration_plan"
    assert decision.requires_tool is True
