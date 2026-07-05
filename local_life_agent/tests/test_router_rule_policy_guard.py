from __future__ import annotations

import pytest

from local_life_agent.planning.orchestration_router import build_orchestration_decision, normalize_route_task
from local_life_agent.target.clarification import build_pending_clarification, format_pending_prompt


def _state(**overrides):
    state = {
        "top_intent": "local_life",
        "task_type": "recommendation",
        "semantic_frame": {"confidence": 0.86},
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "comparison_targets": [],
        "raw_text": "",
        "normalized_text": "",
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    "raw_text",
    [
        "推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
        "附近有没有比较便宜的烧烤",
        "找几家比较适合聚餐的餐厅",
        "推荐几家性价比不错的火锅",
        "附近哪家性价比最高",
        "比如北邮附近，有没有烧烤推荐",
    ],
)
def test_discovery_is_not_stolen_by_comparison_keyword(raw_text: str):
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text=raw_text,
            normalized_text=raw_text,
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert decision.requires_clarification is False
    assert "missing_comparison_targets" not in decision.missing_fields


@pytest.mark.parametrize(
    "raw_text",
    [
        "附近哪家性价比最高",
        "比如北邮附近，有没有烧烤推荐",
    ],
)
def test_weak_comparison_hints_do_not_override_discovery(raw_text: str):
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text=raw_text,
            normalized_text=raw_text,
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert "missing_comparison_targets" not in decision.missing_fields


def test_structured_exploration_routes_to_exploration_planning():
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text="五道口附近晚上约会怎么安排",
            normalized_text="五道口附近晚上约会怎么安排",
            semantic_frame={
                "confidence": 0.92,
                "workflow_hint": "exploration_planning",
                "scene": "date",
                "time": "evening",
                "location": {"text": "五道口附近", "location_name": "五道口附近"},
                "exploration_stages": [
                    {"stage_id": "stage_1", "stage_type": "eat", "candidate_query": "餐厅", "order": 1, "required": True},
                    {"stage_id": "stage_2", "stage_type": "coffee", "candidate_query": "咖啡店", "order": 2, "required": True},
                ],
                "missing_slot_type": "",
                "grounding_status": "grounded",
            },
        )
    )

    assert decision.workflow_name == "exploration_planning"
    assert decision.response_mode == "exploration_plan"
    assert decision.requires_clarification is False


def test_plain_recommendation_does_not_route_to_exploration():
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text="附近推荐咖啡",
            normalized_text="附近推荐咖啡",
            semantic_frame={
                "confidence": 0.91,
                "workflow_hint": "recommendation",
                "scene": "",
                "time": "",
                "location": {},
                "exploration_stages": [],
                "grounding_status": "grounded",
            },
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"


@pytest.mark.parametrize(
    "raw_text",
    [
        "推荐附近有券的餐厅",
        "附近有没有现在开门的火锅",
        "找几家人均100左右的烧烤",
        "适合聚餐的店，有没有优惠",
        "推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
    ],
)
def test_discovery_is_not_stolen_by_deterministic_keyword(raw_text: str):
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text=raw_text,
            normalized_text=raw_text,
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert decision.requires_clarification is False


@pytest.mark.parametrize(
    "raw_text",
    [
        "推荐附近有券的餐厅",
        "附近有没有现在开门的火锅",
        "找几家人均100左右的烧烤",
        "适合聚餐的店，有没有优惠",
        "离我近一点、有券的火锅推荐",
    ],
)
def test_discovery_facets_do_not_route_to_deterministic_tool(raw_text: str):
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text=raw_text,
            normalized_text=raw_text,
        )
    )

    assert decision.workflow_name in {"discovery_decision", "clarification_fallback"}
    assert decision.workflow_name != "deterministic_tool"
    if decision.workflow_name == "discovery_decision":
        assert decision.response_mode == "recommendation"
        assert decision.requires_tool is True
        assert decision.requires_clarification is False
    else:
        assert decision.response_mode == "clarify"


@pytest.mark.parametrize(
    "raw_text",
    [
        "这附近有什么好吃的",
        "那边有没有烧烤",
        "这个商圈附近有火锅吗",
        "学校附近有没有咖啡",
    ],
)
def test_location_reference_queries_stay_on_discovery_path(raw_text: str):
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text=raw_text,
            normalized_text=raw_text,
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert decision.requires_clarification is False
    assert "current_shop" not in decision.missing_fields


@pytest.mark.parametrize(
    "raw_text",
    [
        "这附近有什么好吃的",
        "那边有没有烧烤",
        "这个商圈附近有火锅吗",
        "学校附近有没有咖啡",
        "第一家附近还有咖啡吗",
    ],
)
def test_reference_location_queries_do_not_need_full_shop_name(raw_text: str):
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text=raw_text,
            normalized_text=raw_text,
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert "current_shop" not in decision.missing_fields


def test_deictic_single_shop_query_without_current_shop_stays_typed():
    pending = build_pending_clarification(
        original_text="这家有券吗？",
        original_semantic_frame={"task_type": "single_shop_query", "confidence": 0.9},
        original_task_type="single_shop_query",
        candidate_targets=[],
        reason="missing_current_shop",
        source_node="test",
    )

    assert pending.missing_slot_type == "unresolved_deictic_reference"
    assert format_pending_prompt(pending) == "请补充你指的是哪一家店。"


def test_location_hint_pending_clarification_uses_location_prompt():
    pending = build_pending_clarification(
        original_text="推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
        original_semantic_frame={
            "task_type": "recommendation",
            "primary_task": "推荐附近火锅烧烤",
            "confidence": 0.9,
        },
        original_task_type="recommendation",
        candidate_targets=[],
        reason="missing_required_slot",
        source_node="test",
    )

    assert pending.missing_slot_type == "missing_location"
    assert format_pending_prompt(pending) == "请提供位置、商圈或附近范围。"


def test_comparison_pending_clarification_is_typed():
    pending = build_pending_clarification(
        original_text="这两家哪个更适合聚餐",
        original_semantic_frame={
            "task_type": "comparison",
            "comparison_targets": [],
            "confidence": 0.86,
        },
        original_task_type="comparison",
        candidate_targets=[],
        reason="comparison_targets_need_clarification",
        source_node="test",
    )

    assert pending.missing_slot_type == "missing_comparison_targets"
    assert format_pending_prompt(pending) == "请说明要比较哪几家店。"


def test_comparison_with_explicit_targets_still_routes_to_discovery_decision():
    decision = build_orchestration_decision(
        _state(
            task_type="comparison",
            raw_text="海底捞和聚宝源哪个更划算",
            normalized_text="海底捞和聚宝源哪个更划算",
            semantic_frame={
                "confidence": 0.9,
                "comparison_targets": [
                    {"reference": "explicit", "shop_name": "海底捞"},
                    {"reference": "explicit", "shop_name": "聚宝源"},
                ],
            },
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "comparison"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False


def test_comparison_ordinal_reference_with_context_still_routes_to_comparison():
    decision = build_orchestration_decision(
        _state(
            task_type="comparison",
            raw_text="第一家和第二家比一下",
            normalized_text="第一家和第二家比一下",
            last_recommendation_list=[
                {"shop_id": "shop_1", "shop_name": "第一家"},
                {"shop_id": "shop_2", "shop_name": "第二家"},
            ],
            semantic_frame={
                "confidence": 0.88,
                "comparison_targets": [
                    {"reference": "ordinal", "shop_name": "第一家"},
                    {"reference": "ordinal", "shop_name": "第二家"},
                ],
                "ordinal_references": ["第一家", "第二家"],
            },
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "comparison"
    assert decision.requires_tool is True


def test_value_for_money_phrase_keeps_semantic_intent_winning():
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text="推荐几家性价比不错的火锅",
            normalized_text="推荐几家性价比不错的火锅",
            semantic_frame={
                "confidence": 0.87,
                "candidate_category": "restaurant",
                "hard_constraints": {"nearby": True},
            },
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert "router_policy_conflict" not in decision.workflow_reason


def test_exploration_queries_keep_exploration_priority():
    first = build_orchestration_decision(
        _state(
            task_type="local_trip_plan",
            raw_text="帮我安排一个先吃饭再喝咖啡的约会路线",
            normalized_text="帮我安排一个先吃饭再喝咖啡的约会路线",
            semantic_frame={"confidence": 0.82},
        )
    )
    second = build_orchestration_decision(
        _state(
            task_type="local_trip_plan",
            raw_text="北京邮电大学附近先吃饭再喝咖啡怎么安排",
            normalized_text="北京邮电大学附近先吃饭再喝咖啡怎么安排",
            semantic_frame={"confidence": 0.82},
        )
    )

    assert first.workflow_name == "exploration_planning"
    assert second.workflow_name == "exploration_planning"
    assert first.response_mode == "exploration_plan"
    assert second.response_mode == "exploration_plan"


def test_single_shop_reference_with_current_shop_stays_deterministic():
    decision = build_orchestration_decision(
        _state(
            task_type="single_shop_query",
            current_shop={"shop_id": "shop_1", "shop_name": "测试店"},
            raw_text="这家现在开吗？",
            normalized_text="这家现在开吗？",
            semantic_frame={
                "confidence": 0.9,
                "primary_task": "shop_status",
                "deictic_references": ["这家"],
                "reference_mentions": ["这家"],
            },
        )
    )

    assert decision.workflow_name == "deterministic_tool"
    assert decision.response_mode == "tool_answer"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False


def test_deterministic_without_current_shop_asks_for_target():
    decision = build_orchestration_decision(
        _state(
            task_type="single_shop_query",
            current_shop=None,
            raw_text="这家有券吗？",
            normalized_text="这家有券吗？",
            semantic_frame={
                "confidence": 0.9,
                "primary_task": "shop_coupon",
                "deictic_references": ["这家"],
                "reference_mentions": ["这家"],
            },
        )
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.response_mode == "clarify"
    assert decision.requires_clarification is True


def test_explicit_shop_coupon_stays_deterministic():
    decision = build_orchestration_decision(
        _state(
            task_type="single_shop_query",
            current_shop=None,
            raw_text="海底捞西直门店有券吗？",
            normalized_text="海底捞西直门店有券吗？",
            semantic_frame={
                "confidence": 0.95,
                "primary_task": "shop_coupon",
                "merchant_mentions": ["海底捞西直门店"],
            },
        )
    )

    assert decision.workflow_name == "deterministic_tool"
    assert decision.response_mode == "tool_answer"
    assert decision.requires_tool is True


def test_comparison_without_candidates_asks_for_targets():
    decision = build_orchestration_decision(
        _state(
            task_type="comparison",
            raw_text="这两家哪个更适合聚餐？",
            normalized_text="这两家哪个更适合聚餐？",
            semantic_frame={
                "confidence": 0.84,
                "comparison_targets": [],
                "reference_mentions": ["这两家"],
                "deictic_references": ["这两家"],
            },
            last_recommendation_list=[],
        )
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.response_mode == "clarify"
    assert "missing_comparison_targets" in decision.missing_fields or decision.requires_clarification is True


def test_exploration_without_location_routes_to_exploration():
    decision = build_orchestration_decision(
        _state(
            task_type="local_trip_plan",
            raw_text="帮我安排一个先吃饭再喝咖啡的约会路线",
            normalized_text="帮我安排一个先吃饭再喝咖啡的约会路线",
            semantic_frame={"confidence": 0.82},
        )
    )

    assert decision.workflow_name == "exploration_planning"
    assert decision.response_mode == "exploration_plan"


def test_exploration_with_location_routes_to_exploration():
    decision = build_orchestration_decision(
        _state(
            task_type="local_trip_plan",
            raw_text="北京邮电大学附近先吃饭再喝咖啡怎么安排",
            normalized_text="北京邮电大学附近先吃饭再喝咖啡怎么安排",
            semantic_frame={"confidence": 0.82},
        )
    )

    assert decision.workflow_name == "exploration_planning"
    assert decision.response_mode == "exploration_plan"


def test_exploration_missing_location_routes_to_clarification():
    decision = build_orchestration_decision(
        _state(
            task_type="local_trip_plan",
            raw_text="帮我安排一个先吃饭再喝咖啡的约会路线",
            normalized_text="帮我安排一个先吃饭再喝咖啡的约会路线",
            semantic_frame={
                "confidence": 0.81,
                "workflow_hint": "exploration_planning",
                "exploration_stages": [
                    {"stage_type": "scene", "scene": "eat", "query": "吃饭"},
                    {"stage_type": "scene", "scene": "coffee", "query": "咖啡"},
                ],
                "missing_slot_type": "missing_exploration_location",
                "grounding_status": "partially_grounded",
            },
        )
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.requires_clarification is True
    assert "missing_exploration_location" in decision.missing_fields


def test_cancel_intent_short_circuits_to_direct_response():
    decision = build_orchestration_decision(
        _state(
            task_type="clarification_reply",
            raw_text="算了",
            normalized_text="算了",
            semantic_frame={
                "confidence": 0.92,
                "cancel_intent": True,
            },
        )
    )

    assert decision.workflow_name == "direct_response"
    assert decision.response_mode == "direct_response"
    assert decision.requires_tool is False


def test_new_task_override_escapes_pending_clarification():
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            pending_clarification={"reason": "missing_required_slot"},
            raw_text="不要烧烤了，推荐咖啡",
            normalized_text="不要烧烤了，推荐咖啡",
            semantic_frame={
                "confidence": 0.88,
                "new_task_override": True,
                "constraint_update": True,
                "category": "咖啡",
            },
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert decision.requires_clarification is False


def test_constraint_update_stays_on_semantic_recommendation_path():
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            pending_clarification={"reason": "missing_required_slot"},
            raw_text="要更便宜一点的",
            normalized_text="要更便宜一点的",
            semantic_frame={
                "confidence": 0.85,
                "constraint_update": True,
                "soft_preferences": {"price_preference": "lower_price"},
            },
        )
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.response_mode == "clarify"
    assert decision.requires_clarification is True
    assert "comparison" not in decision.workflow_reason.lower()
