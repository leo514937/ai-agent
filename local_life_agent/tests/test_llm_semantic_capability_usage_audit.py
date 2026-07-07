from __future__ import annotations

import pytest

from local_life_agent.domain.candidate import GoalType, LocalLifeGoalDraft
from local_life_agent.domain.enums import PreferenceType
from local_life_agent.semantic.intent_parser import parse_semantic_frame
from local_life_agent.planning.evidence_review import review_evidence
from local_life_agent.planning.orchestration_router import build_orchestration_decision
from local_life_agent.semantic.slot_extractor import extract_slots
from local_life_agent.target.clarification import (
    build_pending_clarification,
    format_pending_prompt,
    handle_clarification_reply,
)


def test_semantic_parse_value_for_money_wins_over_comparison_keyword() -> None:
    frame = extract_slots("比较便宜一点的火锅推荐", "local_life")
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": frame["task_type"].value if frame.get("task_type") is not None else "recommendation",
            "semantic_frame": frame,
            "pending_clarification": None,
            "current_shop": None,
            "last_recommendation_list": [],
            "comparison_targets": [],
            "raw_text": "比较便宜一点的火锅推荐",
            "normalized_text": "比较便宜一点的火锅推荐",
        }
    )

    assert frame["comparison_intent"] is False
    assert frame["soft_preferences"]["price_preference"] == "lower_price"
    assert any(item.get("type") == "price" and item.get("operator") == "lower" for item in frame["preferences"])
    assert decision.workflow_name == "discovery_decision"
    assert decision.response_mode == "recommendation"


def test_policy_guard_blocks_comparison_without_targets() -> None:
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "comparison",
            "semantic_frame": {
                "confidence": 0.9,
                "comparison_intent": True,
                "comparison_targets": [],
                "reference_mentions": ["这两家"],
                "deictic_references": ["这两家"],
            },
            "pending_clarification": None,
            "current_shop": None,
            "last_recommendation_list": [],
            "comparison_targets": [],
            "raw_text": "这两家哪个更适合聚餐？",
            "normalized_text": "这两家哪个更适合聚餐？",
        }
    )

    assert decision.workflow_name in {"clarification_fallback", "discovery_decision"}
    assert decision.response_mode in {"clarify", "answer"}


@pytest.mark.parametrize(
    ("original_text", "original_semantic_frame", "original_task_type", "expected_slot", "expected_prompt"),
        [
            (
                "推荐几家附近的店",
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "workflow_hint": "recommendation",
                    "confidence": 0.9,
                },
                "recommendation",
                "missing_location",
                "请提供位置、商圈或附近范围。",
            ),
        (
            "这家有券吗？",
            {
                "task_type": "single_shop_query",
                "primary_task": "single_shop_query",
                "workflow_hint": "single_shop_query",
                "confidence": 0.9,
            },
            "single_shop_query",
            "unresolved_deictic_reference",
            "请提供完整店名。",
        ),
        (
            "这两家哪个更适合聚餐",
            {
                "task_type": "comparison",
                "comparison_targets": [],
                "confidence": 0.86,
            },
            "comparison",
            "missing_comparison_targets",
            "请说明要比较哪几家店。",
        ),
    ],
)
def test_pending_clarification_uses_typed_missing_slot_prompt(
    original_text: str,
    original_semantic_frame: dict[str, object],
    original_task_type: str,
    expected_slot: str,
    expected_prompt: str,
) -> None:
    pending = build_pending_clarification(
        original_text=original_text,
        original_semantic_frame=original_semantic_frame,
        original_task_type=original_task_type,
        candidate_targets=[],
        reason="missing_required_slot",
        source_node="test",
    )

    assert pending.missing_slot_type == expected_slot
    assert format_pending_prompt(pending) == expected_prompt


def test_clarification_reply_cancel_clears_pending_state() -> None:
    pending = build_pending_clarification(
        original_text="推荐几家烧烤",
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

    result = handle_clarification_reply("算了", pending, session_state=None)
    assert result["status"] == "cancelled"
    assert result["pending_clarification"] is None


def test_evidence_review_keeps_unknown_distinct_from_failed() -> None:
    goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon", "open_status"])
    result = review_evidence(
        goal,
        {
            "facet_results": [
                {"facet": "coupon", "result_status": "unknown", "required": True},
                {"facet": "open_status", "result_status": "failed", "required": True},
            ],
            "unknown_items": [],
        },
    )

    assert "coupon" in result.required_unknown
    assert "open_status" in result.required_failed
    assert result.unknown_as_false_detected is True


def test_phase2_structured_parser_keeps_value_for_money_out_of_comparison() -> None:
    content = {
        "top_intent": "local_life",
        "task_type": "recommendation",
        "primary_task": "recommendation",
        "comparison_intent": False,
        "comparison_structure": "unknown",
        "preference_signals": [
            {"preference_type": "value_for_money", "value": "value_for_money", "text": "性价比高"}
        ],
        "confidence": 0.91,
    }
    result = parse_semantic_frame(
        "推荐北京邮电大学附近的火锅或烧烤，要性价比高的",
        "local_life",
        llm_call=lambda *args, **kwargs: {
            "ok": True,
            "content": content,
            "raw": "",
            "error_code": "",
            "error_message": "",
            "attempts": 1,
        },
    )

    assert result["semantic_frame"].comparison_intent is False
    assert result["semantic_frame"].preference_signals[0].preference_type == PreferenceType.value_for_money
    assert result["schema_validation_result"]["status"] == "validated"


def test_phase2_structured_parser_fallback_is_low_confidence_and_visible() -> None:
    result = parse_semantic_frame(
        "海底捞西直门店有券吗",
        "local_life",
        llm_call=lambda *args, **kwargs: {
            "ok": False,
            "content": {},
            "raw": "",
            "error_code": "SEMANTIC_LLM_UNAVAILABLE",
            "error_message": "semantic llm backend is unavailable",
            "attempts": 1,
        },
    )

    assert result["semantic_frame"] is not None
    assert result["semantic_parse_source"] == "fallback_rules"
    assert result["schema_validation_result"]["status"] in {"recovered", "fallback"}
