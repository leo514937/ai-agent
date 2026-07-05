from __future__ import annotations

from local_life_agent.domain.state import SessionState
from local_life_agent.planning.plans.state_update_planner import plan_state_update
from local_life_agent.target.clarification import build_pending_clarification, handle_clarification_reply


def _restore_state(result: dict[str, object], session: SessionState) -> dict[str, object]:
    return {
        "pending_clarification": result.get("pending_clarification"),
        "semantic_frame": result.get("semantic_frame") or {},
        "resolved_target": result.get("resolved_target"),
        "comparison_targets": result.get("comparison_targets") or [],
        "current_shop": session.current_shop,
        "last_recommendation_list": session.last_recommendation_list,
        "active_constraints": session.active_constraints,
    }


def test_missing_location_resume_keeps_category_and_merges_constraints() -> None:
    pending = build_pending_clarification(
        original_text="推荐几家烧烤",
        original_semantic_frame={
            "task_type": "recommendation",
            "category": "烧烤",
            "soft_preferences": {"price_preference": "value_for_money"},
        },
        original_task_type="recommendation",
        candidate_targets=[],
        reason="missing_required_slot",
    )
    session = SessionState(active_constraints={"price_preference": "value_for_money"})

    result = handle_clarification_reply("北邮附近", pending, session)

    assert result["status"] == "restore"
    assert result["resume_strategy"] == "fill_missing_location"
    assert result["task_type_source"] == "clarification_resume"
    assert result["missing_slot_type"] == "missing_location"
    assert result["pending_clarification"] is None
    assert result["resolved_target"] is None
    assert result["selected_candidate"] is None
    assert result["semantic_frame"]["category"] == "烧烤"
    assert result["semantic_frame"]["location_reference"]["location_name"] == "北邮附近"

    directive = plan_state_update(
        _restore_state(result, session),
        "recommendation",
        "RESOLVED",
    )
    assert "current_shop" not in directive["set_fields"]
    assert "last_recommendation_list" not in directive["set_fields"] or directive["set_fields"]["last_recommendation_list"] == []
    assert "active_constraints" in directive["set_fields"]
    assert directive["set_fields"]["active_constraints"]["location"]["location_name"] == "北邮附近"


def test_missing_shop_resume_uses_explicit_shop_target_without_polluting_history() -> None:
    pending = build_pending_clarification(
        original_text="这家有券吗",
        original_semantic_frame={
            "task_type": "single_shop_query",
            "deictic_references": ["这家"],
        },
        original_task_type="single_shop_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "海底捞西直门店"}],
        reason="missing_current_shop",
    )
    session = SessionState(last_recommendation_list=[{"shop_id": "r1", "shop_name": "历史列表"}])

    result = handle_clarification_reply("海底捞西直门店", pending, session)

    assert result["status"] == "restore"
    assert result["resume_strategy"] == "resolve_deictic_reference"
    assert result["missing_slot_type"] in {"unresolved_deictic_reference", "missing_shop", "missing_shop_target", "ambiguous_shop"}
    assert result["pending_clarification"] is None
    assert result["selected_candidate"]["shop_name"] == "海底捞西直门店"
    assert result["resolved_target"].status == "RESOLVED"
    assert session.last_recommendation_list == [{"shop_id": "r1", "shop_name": "历史列表"}]

    directive = plan_state_update(
        _restore_state(result, session),
        "single_shop_query",
        "RESOLVED",
    )
    assert directive["set_fields"]["current_shop"] == {"shop_id": "s1", "shop_name": "海底捞西直门店"}
    assert "last_recommendation_list" not in directive["set_fields"]


def test_comparison_targets_resume_uses_list_context() -> None:
    pending = build_pending_clarification(
        original_text="这两家哪个好",
        original_semantic_frame={"task_type": "comparison", "comparison_targets": []},
        original_task_type="comparison",
        candidate_targets=[],
        reason="comparison_targets_need_clarification",
    )
    session = SessionState(
        last_recommendation_list=[
            {"shop_id": "r1", "shop_name": "A"},
            {"shop_id": "r2", "shop_name": "B"},
        ]
    )

    result = handle_clarification_reply("第一家和第二家", pending, session)

    assert result["status"] == "restore"
    assert result["resume_strategy"] == "fill_missing_comparison_targets"
    assert result["pending_clarification"] is None
    assert len(result["comparison_targets"]) == 2
    assert result["comparison_targets"][0]["shop_name"] == "A"
    assert result["comparison_targets"][1]["shop_name"] == "B"


def test_comparison_targets_without_context_stays_typed_clarification() -> None:
    pending = build_pending_clarification(
        original_text="这两家哪个好",
        original_semantic_frame={"task_type": "comparison", "comparison_targets": []},
        original_task_type="comparison",
        candidate_targets=[],
        reason="comparison_targets_need_clarification",
    )

    result = handle_clarification_reply("第一家和第二家", pending, SessionState())

    assert result["status"] == "invalid"
    assert result["resume_strategy"] == "ask_clarification_again"
    assert result["pending_clarification"] is not None


def test_missing_exploration_location_resume_preserves_stages() -> None:
    pending = build_pending_clarification(
        original_text="帮我安排先吃饭再喝咖啡",
        original_semantic_frame={
            "task_type": "local_trip_plan",
            "exploration_stages": [
                {"stage_type": "scene", "scene": "约会"},
                {"stage_type": "activity", "activity": "吃饭"},
                {"stage_type": "activity", "activity": "喝咖啡"},
            ],
        },
        original_task_type="local_trip_plan",
        candidate_targets=[],
        reason="missing_required_slot",
    )

    result = handle_clarification_reply("五道口附近", pending, SessionState())

    assert result["status"] == "restore"
    assert result["resume_strategy"] == "fill_missing_exploration_location"
    assert result["semantic_frame"]["exploration_stages"][0]["scene"] == "约会"
    assert "附近" in result["semantic_frame"]["location_reference"]["location_name"]


def test_new_task_override_clears_old_pending_and_starts_new_task() -> None:
    pending = build_pending_clarification(
        original_text="推荐几家烧烤",
        original_semantic_frame={"task_type": "recommendation", "category": "烧烤"},
        original_task_type="recommendation",
        candidate_targets=[],
        reason="missing_required_slot",
    )

    result = handle_clarification_reply("不要烧烤了，推荐咖啡", pending, SessionState())

    assert result["status"] == "topic_switch"
    assert result["resume_strategy"] == "start_new_task"
    assert result["pending_clarification"] is None
    assert result["semantic_frame"]["category"] == "咖啡"
    assert result["semantic_frame"]["new_task_override"] is True
    assert result["semantic_frame"].get("constraint_update") is True


def test_cancel_clears_pending_and_stops_old_task() -> None:
    pending = build_pending_clarification(
        original_text="推荐几家烧烤",
        original_semantic_frame={"task_type": "recommendation", "category": "烧烤"},
        original_task_type="recommendation",
        candidate_targets=[],
        reason="missing_required_slot",
    )

    result = handle_clarification_reply("算了", pending, SessionState())

    assert result["status"] == "cancelled"
    assert result["resume_strategy"] == "cancel_pending_task"
    assert result["pending_clarification"] is None


def test_ordinal_reference_with_context_resolves_without_polluting_list() -> None:
    pending = build_pending_clarification(
        original_text="第一家有券吗",
        original_semantic_frame={"task_type": "single_shop_query", "ordinal_references": ["第一家"]},
        original_task_type="single_shop_query",
        candidate_targets=[
            {"shop_id": "r1", "shop_name": "A"},
            {"shop_id": "r2", "shop_name": "B"},
        ],
        reason="ambiguous_shop",
    )
    session = SessionState(
        last_recommendation_list=[
            {"shop_id": "r1", "shop_name": "A"},
            {"shop_id": "r2", "shop_name": "B"},
        ]
    )

    result = handle_clarification_reply("第一家有券吗", pending, session)

    assert result["status"] == "restore"
    assert result["resume_strategy"] == "resolve_shop_reference"
    assert result["selected_candidate"]["shop_name"] == "A"
    assert session.last_recommendation_list == [
        {"shop_id": "r1", "shop_name": "A"},
        {"shop_id": "r2", "shop_name": "B"},
    ]


def test_ordinal_reference_without_context_stays_typed_clarification() -> None:
    pending = build_pending_clarification(
        original_text="第一家有券吗",
        original_semantic_frame={"task_type": "single_shop_query", "ordinal_references": ["第一家"]},
        original_task_type="single_shop_query",
        candidate_targets=[],
        reason="missing_current_shop",
    )

    result = handle_clarification_reply("第一家有券吗", pending, SessionState())

    assert result["status"] == "invalid"
    assert result["resume_strategy"] == "ask_clarification_again"
    assert result["pending_clarification"] is not None


def test_deictic_reference_with_current_shop_resolves_without_defaulting_first_candidate() -> None:
    pending = build_pending_clarification(
        original_text="这家有券吗",
        original_semantic_frame={"task_type": "single_shop_query", "deictic_references": ["这家"]},
        original_task_type="single_shop_query",
        candidate_targets=[],
        reason="missing_current_shop",
    )
    session = SessionState(current_shop={"shop_id": "cur1", "shop_name": "当前店"})

    result = handle_clarification_reply("这家有券吗", pending, session)

    assert result["status"] == "restore"
    assert result["resume_strategy"] == "resolve_deictic_reference"
    assert result["selected_candidate"]["shop_name"] == "当前店"


def test_deictic_reference_without_current_shop_stays_typed_clarification() -> None:
    pending = build_pending_clarification(
        original_text="这家有券吗",
        original_semantic_frame={"task_type": "single_shop_query", "deictic_references": ["这家"]},
        original_task_type="single_shop_query",
        candidate_targets=[],
        reason="missing_current_shop",
    )

    result = handle_clarification_reply("这家有券吗", pending, SessionState())

    assert result["status"] == "invalid"
    assert result["resume_strategy"] == "ask_clarification_again"
    assert result["pending_clarification"] is not None
