from __future__ import annotations

from local_life_agent.planning.orchestration_router import build_orchestration_decision
from local_life_agent.domain.enums import GroundingStatus, SemanticParseSource
from local_life_agent.domain.schemas import SemanticFrame
from local_life_agent.semantic.slot_extractor import extract_slots
from local_life_agent.target.clarification import build_pending_clarification, format_pending_prompt


def _state(**overrides):
    state = {
        "top_intent": "local_life",
        "task_type": "recommendation",
        "semantic_frame": {"confidence": 0.9},
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "comparison_targets": [],
        "raw_text": "",
        "normalized_text": "",
    }
    state.update(overrides)
    return state


def test_value_for_money_is_structured_as_preference_not_comparison() -> None:
    frame = extract_slots("推荐北京邮电大学附近的火锅或烧烤，要性价比高的", "local_life")
    decision = build_orchestration_decision(
        _state(
            task_type=frame["task_type"].value if frame.get("task_type") is not None else "recommendation",
            raw_text="推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
            normalized_text="推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
            semantic_frame=frame,
        )
    )

    assert frame["comparison_intent"] is False
    assert frame["workflow_hint"] == "recommendation"
    assert frame["soft_preferences"]["price_preference"] == "value_for_money"
    assert frame["soft_preferences"]["ranking_policy"] == "value_for_money_first"
    assert any(item.get("type") == "value_for_money" for item in frame["preferences"])
    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"
    assert decision.requires_clarification is False


def test_relative_price_phrase_is_not_misclassified_as_comparison() -> None:
    frame = extract_slots("比较便宜一点的火锅推荐", "local_life")
    decision = build_orchestration_decision(
        _state(
            task_type=frame["task_type"].value if frame.get("task_type") is not None else "recommendation",
            raw_text="比较便宜一点的火锅推荐",
            normalized_text="比较便宜一点的火锅推荐",
            semantic_frame=frame,
        )
    )

    assert frame["comparison_intent"] is False
    assert frame["soft_preferences"]["price_preference"] == "lower_price"
    assert any(item.get("type") == "price" and item.get("operator") == "lower" for item in frame["preferences"])
    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"


def test_named_pair_comparison_keeps_structured_comparison_targets() -> None:
    frame = extract_slots("海底捞(牡丹园店)和川味轩(知春路店)哪个更划算？", "local_life")

    assert frame["comparison_intent"] is True
    assert len(frame["comparison_targets"]) >= 2
    assert "value_for_money" in frame["comparison_facets"] or frame["comparison_focus"] == "value_for_money"
    assert frame["workflow_hint"] == "comparison"
    assert frame["primary_task"] == "comparison"
    assert frame["reference"]["comparison_targets"]


def test_missing_location_uses_typed_clarification_prompt() -> None:
    pending = build_pending_clarification(
        original_text="推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
        original_semantic_frame={
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "workflow_hint": "recommendation",
            "confidence": 0.9,
        },
        original_task_type="recommendation",
        candidate_targets=[],
        reason="missing_required_slot",
        source_node="test",
    )

    assert pending.missing_slot_type == "missing_location"
    assert format_pending_prompt(pending) == "请提供位置、商圈或附近范围。"


def test_phase1_schema_fields_can_be_serialized_without_router_changes() -> None:
    frame = SemanticFrame(
        top_intent="local_life",
        task_type="recommendation",
        new_task_override=True,
        constraint_update=False,
        cancel_intent=False,
        discourse_marker="先",
        parse_source=SemanticParseSource.real_llm,
        semantic_parse_source=SemanticParseSource.real_llm,
        grounding_status=GroundingStatus.grounded,
        exploration_stages=[{"stage_type": "scene", "scene": "约会"}],
    )

    restored = SemanticFrame.model_validate_json(frame.model_dump_json())
    assert restored.new_task_override is True
    assert restored.discourse_marker == "先"
    assert restored.grounding_status == GroundingStatus.grounded
    assert restored.exploration_stages[0].stage_type == "scene"


def test_router_reason_exposes_semantic_parse_metadata() -> None:
    decision = build_orchestration_decision(
        _state(
            task_type="recommendation",
            raw_text="推荐附近有券的餐厅",
            normalized_text="推荐附近有券的餐厅",
            semantic_frame={
                "confidence": 0.9,
                "workflow_hint": "recommendation",
                "filter_signals": [{"filter_type": "coupon_filter", "value": True, "required": True, "text": "有券"}],
                "semantic_parse_source": "real_llm",
                "grounding_status": "grounded",
            },
        )
    )

    assert decision.workflow_name == "discovery_decision"
    assert "semantic_parse_source=real_llm" in decision.workflow_reason
    assert "grounding_status=grounded" in decision.workflow_reason


def test_exploration_missing_location_pending_clarification_is_typed() -> None:
    pending = build_pending_clarification(
        original_text="帮我安排先吃饭再喝咖啡",
        original_semantic_frame={
            "task_type": "local_trip_plan",
            "exploration_stages": [{"stage_type": "scene", "scene": "约会"}],
        },
        original_task_type="local_trip_plan",
        candidate_targets=[],
        reason="missing_required_slot",
    )

    assert pending.missing_slot_type == "missing_exploration_location"
    assert pending.resume_strategy == "fill_missing_exploration_location"
    assert format_pending_prompt(pending) == "请提供出发地、位置或行程起点。"


def test_constraint_update_and_new_task_override_keep_semantic_flags() -> None:
    frame = extract_slots("不要烧烤了，推荐咖啡，要更便宜一点的", "local_life")

    assert frame["constraint_update"] is True
    assert frame["new_task_override"] is True
    assert frame["category"] == "咖啡"
    assert frame["comparison_intent"] is False
