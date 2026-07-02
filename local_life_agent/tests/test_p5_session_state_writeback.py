from __future__ import annotations

from local_life_agent.domain.state import SessionState, SessionValueMeta
from local_life_agent.engine.subgraphs.state_update_plan import _h_persist_session
from local_life_agent.planning.plans.state_update_planner import plan_state_update
from local_life_agent.target.clarification import build_pending_clarification, handle_clarification_reply


def _meta(value: SessionValueMeta | dict | None) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return value.model_dump()


def test_session_value_meta_defaults_are_serializable():
    meta = SessionValueMeta()

    assert meta.source == ""
    assert meta.ttl is None
    assert meta.evidence_ref == ""
    assert meta.location_context == {}
    assert meta.resume_strategy == ""
    assert SessionValueMeta.model_validate_json(meta.model_dump_json()) == meta


def test_persist_session_coerces_meta_dicts_to_models():
    state = {
        "session_id": "p5_persist_1",
        "state_update_plan": {
            "set_fields": {
                "current_shop": {"shop_id": "shop_1", "shop_name": "A"},
                "current_shop_meta": {
                    "source": "explicit_shop_name",
                    "ttl": None,
                    "evidence_ref": "ev_1",
                    "location_context": {"location_name": "北邮"},
                    "resume_strategy": "",
                },
            },
            "clear_fields": [],
        },
    }

    result = _h_persist_session(state)

    assert isinstance(result["session_state_after"].current_shop_meta, SessionValueMeta)
    assert result["session_state_after"].current_shop_meta.source == "explicit_shop_name"
    assert result["session_state_after"].current_shop_meta.evidence_ref == "ev_1"


def test_build_pending_clarification_records_resume_strategy():
    pending = build_pending_clarification(
        original_text="第一家有券吗",
        original_semantic_frame={"task_type": "coupon_query"},
        original_task_type="coupon_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "A"}],
        reason="ambiguous_shop",
    )

    assert pending.resume_strategy == "resume_original_task"
    assert pending.expires_at is not None
    assert pending.expires_at > pending.created_at


def test_pending_reply_restore_round_trip_keeps_original_task():
    pending = build_pending_clarification(
        original_text="第一家有券吗",
        original_semantic_frame={"task_type": "coupon_query"},
        original_task_type="coupon_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "A"}],
        reason="ambiguous_shop",
    )
    restored = handle_clarification_reply("1", pending, SessionState(current_shop={"shop_id": "old", "shop_name": "Old"}))

    assert restored["status"] == "restore"
    assert restored["pending_clarification"] is None
    assert restored["restored_task"] == "coupon_query"
    assert restored["resolved_target"].status == "RESOLVED"
    assert restored["comparison_targets"]


def test_tool_failure_does_not_clear_existing_session_state():
    directive = plan_state_update(
        {
            "current_shop": {"shop_id": "shop_1", "shop_name": "A"},
            "pending_clarification": {"pending_id": "pc_1", "resume_strategy": "resume_original_task"},
            "tool_result_set": {
                "call_1": {"tool_name": "get_coupon_list", "result_status": "failed", "success": False}
            },
            "validated_plan": {
                "tool_calls": [
                    {"call_id": "call_1", "tool_name": "get_coupon_list", "required": True},
                ]
            },
            "user_location": {"lat": 39.96, "lng": 116.36, "location_name": "北邮"},
        },
        "single_shop_query",
        "RESOLVED",
    )

    assert directive["set_fields"] == {}
    assert directive["clear_fields"] == []


def test_single_shop_state_update_keeps_current_shop_metadata():
    user_location = {"lat": 39.96, "lng": 116.36, "location_name": "北邮"}
    directive = plan_state_update(
        {
            "resolved_target": {"resolved_shop": {"shop_id": "shop_1", "shop_name": "A"}},
            "reference_resolution_source": "explicit_shop_name",
            "evidence_pack": {
                "evidence_items": [
                    {"evidence_id": "ev_shop_1", "call_id": "call_1", "shop_id": "shop_1", "facet": "coupon"}
                ]
            },
            "user_location": user_location,
        },
        "single_shop_query",
        "RESOLVED",
    )

    assert directive["set_fields"]["current_shop"] == {"shop_id": "shop_1", "shop_name": "A"}
    current_meta = _meta(directive["set_fields"]["current_shop_meta"])
    assert current_meta["source"] == "explicit_shop_name"
    assert current_meta["evidence_ref"] == "ev_shop_1"
    assert current_meta["location_context"] == user_location


def test_recommendation_state_update_keeps_traceable_metadata():
    user_location = {"lat": 39.96, "lng": 116.36, "location_name": "北邮"}
    directive = plan_state_update(
        {
            "local_life_goal_draft": {"candidate_source": "recommendation"},
            "resolved_target": {"resolved_shop": {"shop_id": "shop_1", "shop_name": "A"}},
            "reference_resolution_source": "last_recommendation_list",
            "last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "A"}],
            "evidence_pack": {
                "evidence_items": [
                    {"evidence_id": "ev_1", "call_id": "call_1", "shop_id": "shop_1", "facet": "coupon"}
                ],
                "ranking_snapshot": {"snapshot_id": "rank_1"},
            },
            "user_location": user_location,
        },
        "recommendation",
        "RESOLVED",
    )

    assert directive["set_fields"]["last_recommendation_list"] == [{"shop_id": "shop_1", "shop_name": "A"}]
    last_meta = _meta(directive["set_fields"]["last_recommendation_list_meta"])
    assert last_meta["source"] == "recommendation"
    assert last_meta["evidence_ref"] == "ev_1"
    assert last_meta["location_context"] == user_location


def test_comparison_state_update_keeps_traceable_metadata():
    user_location = {"lat": 39.96, "lng": 116.36, "location_name": "北邮"}
    directive = plan_state_update(
        {
            "comparison_targets": [{"shop_id": "shop_1", "shop_name": "A"}, {"shop_id": "shop_2", "shop_name": "B"}],
            "comparison_result": {"rows": [{"shop_id": "shop_1"}, {"shop_id": "shop_2"}]},
            "evidence_pack": {"comparison_matrix": {"matrix_id": "cmp_matrix_1"}},
            "user_location": user_location,
        },
        "comparison",
        "RESOLVED",
    )

    assert directive["set_fields"]["comparison_targets"] == [{"shop_id": "shop_1", "shop_name": "A"}, {"shop_id": "shop_2", "shop_name": "B"}]
    comparison_meta = _meta(directive["set_fields"]["comparison_targets_meta"])
    assert comparison_meta["source"] == "comparison_targets"
    assert comparison_meta["evidence_ref"] == "cmp_matrix_1"
    assert comparison_meta["location_context"] == user_location


def test_pending_state_update_keeps_resume_strategy_and_ttl():
    pending = build_pending_clarification(
        original_text="这家有券吗",
        original_semantic_frame={"task_type": "coupon_query"},
        original_task_type="coupon_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "A"}],
        reason="ambiguous_shop",
    )
    directive = plan_state_update(
        {
            "pending_clarification": pending.model_dump(),
            "user_location": {"lat": 39.96, "lng": 116.36, "location_name": "北邮"},
        },
        "coupon_query",
        "AMBIGUOUS",
    )

    pending_meta = _meta(directive["set_fields"]["pending_clarification_meta"])
    assert pending_meta["source"] == "target_resolve"
    assert pending_meta["resume_strategy"] == "resume_original_task"
    assert pending_meta["ttl"] is not None
