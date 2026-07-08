from __future__ import annotations

from types import SimpleNamespace

from local_life_agent.memory.preferences import (
    InMemoryPreferenceBackend,
    MemoryOperation,
    MemoryPolarity,
    MemoryReadContext,
    MemoryScope,
    MemoryType,
    MemoryUpdatePlan,
    build_preference_memories_from_semantic_frame,
    build_preference_memory,
    merge_preference_memory_summaries,
)
from local_life_agent.domain.state import SessionState
from local_life_agent.observability.debug_bundle import build_debug_bundle
from local_life_agent.planning.context_packing import build_context_packing_plan
from local_life_agent.planning.evaluation import DEFAULT_EVALUATION_RUBRIC, rubric_dimension_keys
from local_life_agent.planning.evidence.tool_capabilities import TOOL_CAPABILITY_REGISTRY, build_tool_call_dict
from local_life_agent.planning.evidence.tool_governance import TOOL_GOVERNANCE_REGISTRY, get_tool_governance
from local_life_agent.planning.llm_utils import invoke_structured_llm
from local_life_agent.planning.model_policy import NODE_MODEL_POLICY, get_node_model_profile
from local_life_agent.planning.replay import build_replay_cassette
from local_life_agent.streaming.cancellation_policy import DEFAULT_CANCELLATION_POLICY, decide_cancellation_action
from local_life_agent.engine.subgraphs import state_update_plan as sup
from local_life_agent.session.store import InMemorySessionStore


def test_tool_governance_covers_existing_tools():
    assert set(TOOL_CAPABILITY_REGISTRY).issubset(set(TOOL_GOVERNANCE_REGISTRY))
    spec = get_tool_governance("get_coupon_list")
    assert spec is not None
    assert spec.tool_side_effect == "read"
    assert spec.requires_user_confirmation is False
    assert spec.allowed_in_preview is True


def test_replay_cassette_roundtrip():
    cassette = build_replay_cassette(
        query="附近推荐火锅",
        session_state_before={"current_shop": None},
        orchestration_decision={"workflow_name": "discovery_decision"},
        execution_plan={"tool_calls": [{"tool_name": "search_shops"}]},
        tool_calls=[{"tool_name": "search_shops", "call_id": "call_1"}],
        tool_results={"call_1": {"success": True}},
        evidence_pack={"ranking_snapshot": {"snapshot_id": "snap_1"}},
        decision_plan={"answer_type": "recommendation"},
        answer_plan={"answer_type": "recommendation"},
        state_update_plan={"final_response": "ok"},
        final_response="ok",
        trace_id="trace_1",
        metadata={"source": "unit-test"},
    )

    assert cassette.query == "附近推荐火锅"
    assert cassette.execution_plan["tool_calls"][0]["tool_name"] == "search_shops"
    assert cassette.final_response == "ok"
    assert cassette.metadata["source"] == "unit-test"


def test_debug_bundle_collects_core_fields():
    response = SimpleNamespace(
        answer_text="川味轩有券。",
        debug={
            "semantic_frame": {"task_type": "single_shop_query"},
            "execution_plan": {"tool_calls": [{"tool_name": "get_coupon_list"}]},
            "evidence_pack": {"ranking_snapshot": {"snapshot_id": "snap_2"}},
            "answer_plan": {"answer_type": "single_shop"},
            "decision_plan": {"answer_type": "single_shop"},
            "session_state_before": {"current_shop": {"shop_name": "川味轩"}},
            "session_state_after": {"current_shop": {"shop_name": "川味轩"}},
        },
    )

    bundle = build_debug_bundle(query="川味轩有券吗", normalized_query="川味轩有券吗", response=response, trace_spans=[{"node": "answer"}])

    assert bundle.final_response == "川味轩有券。"
    assert bundle.execution_plan["tool_calls"][0]["tool_name"] == "get_coupon_list"
    assert bundle.evidence_pack["ranking_snapshot"]["snapshot_id"] == "snap_2"
    assert bundle.trace_spans[0]["node"] == "answer"


def test_model_policy_has_expected_profiles():
    assert "semantic_parse" in NODE_MODEL_POLICY
    assert get_node_model_profile("answer_verify").fallback_strategy == "rewrite_instruction"
    assert get_node_model_profile("hard_guard").primary_model == "rules"


def test_rubric_dimensions_cover_expected_axes():
    keys = rubric_dimension_keys(DEFAULT_EVALUATION_RUBRIC)
    assert "route_correctness" in keys
    assert "facet_recall" in keys
    assert "latency_bucket" in keys
    assert len(keys) >= 10


def test_context_packing_uses_session_summary():
    plan = build_context_packing_plan(
        {
            "current_shop": {"shop_name": "川味轩(知春路店)"},
            "last_recommendation_list": [{"shop_name": "川味轩(知春路店)"}],
            "comparison_targets": [{"shop_name": "海底捞(牡丹园店)"}],
            "active_constraints": {"price_preference": "lower_price"},
            "pending_clarification": {"expected_reply_type": "shop_choice"},
            "active_preferences": [
                {"preference_type": "taste", "polarity": "avoid", "value": "不吃辣"},
            ],
        },
        conversation_continuity={"previous_task_type": "recommendation"},
        evidence_pack={"ranking_snapshot": {"snapshot_id": "rank_1"}},
    )

    assert plan.session_summary.has_context is True
    assert plan.prompt_fields["conversation_continuity"]["previous_task_type"] == "recommendation"
    assert "current_shop_name" in plan.prompt_fields
    assert "preference_hints" in plan.prompt_fields
    assert "last_recommendation_list" in plan.session_only_fields
    assert "rank_1" in plan.evidence_refs


def test_cancellation_policy_routes_events():
    assert decide_cancellation_action("user_cancel", DEFAULT_CANCELLATION_POLICY) == "stop"
    assert decide_cancellation_action("tool_timeout", DEFAULT_CANCELLATION_POLICY) == "degrade"
    assert decide_cancellation_action("unknown_event", DEFAULT_CANCELLATION_POLICY) == "continue"


def test_structured_llm_uses_node_policy_defaults(monkeypatch):
    captured = {}

    def fake_load_two_part_prompt(name: str):
        return "system prompt", "user prompt {{TEXT}}"

    def fake_call_llm(*args, **kwargs):
        captured["timeout_ms"] = kwargs.get("timeout_ms")
        captured["max_retries"] = kwargs.get("max_retries")
        return {"ok": True, "content": {"status": "ok"}, "llm_backend": "fake", "raw": "{}"}

    monkeypatch.setattr("local_life_agent.planning.llm_utils.load_two_part_prompt", fake_load_two_part_prompt)

    result = invoke_structured_llm(
        prompt_name="goal_planner",
        replacements={"{{TEXT}}": "附近推荐火锅"},
        response_validator=lambda payload: payload,
        llm_call=fake_call_llm,
    )

    assert result["ok"] is True
    assert captured["timeout_ms"] == 1500
    assert captured["max_retries"] == 1


def test_tool_call_dict_includes_governance():
    call = build_tool_call_dict(
        "calculate_distance_km",
        "distance",
        call_id="call_1",
        origin={"lat": 39.9, "lng": 116.4},
        destination={"lat": 39.8, "lng": 116.3},
    )

    assert call["governance"]["tool_name"] == "calculate_distance_km"
    assert call["governance"]["permission_scope"] == "location:read"
    assert call["args"]["origin"]["lat"] == 39.9


def test_memory_backend_crud_and_query_priority():
    backend = InMemoryPreferenceBackend()
    spicy_avoid = build_preference_memory(
        user_id="user_1",
        preference_type=MemoryType.dietary_restriction,
        value="不吃辣",
        polarity=MemoryPolarity.avoid,
        scope=MemoryScope.local_life,
        confidence=0.9,
        evidence_ref="turn_1",
    )
    quiet_like = build_preference_memory(
        user_id="user_1",
        preference_type=MemoryType.ambience,
        value="安静一点",
        polarity=MemoryPolarity.like,
        scope=MemoryScope.local_life,
        confidence=0.8,
        evidence_ref="turn_2",
    )

    saved = backend.upsert(spicy_avoid)
    quiet_saved = backend.upsert(quiet_like)
    context = backend.read_context(
        MemoryReadContext(
            user_id="user_1",
            query_text="今天就想吃辣",
            query_intent="local_life",
            allowed_scopes=["local_life"],
            max_items=5,
        )
    )
    assert saved.preference_id
    assert quiet_saved.preference_id
    assert len(backend.list_active("user_1")) == 2
    assert spicy_avoid.preference_id not in context.memory_used
    assert quiet_saved.preference_id in context.memory_ignored or quiet_saved.preference_id in context.memory_used

    deleted = backend.delete("user_1", saved.preference_id)
    assert deleted is not None
    assert deleted.status.value == "deleted"

    update = MemoryUpdatePlan(operation=MemoryOperation.no_op, reason="noop")
    assert update.operation == MemoryOperation.no_op


def test_preference_memory_writeback_and_session_summary(monkeypatch):
    store = InMemorySessionStore()
    monkeypatch.setattr(sup, "get_session_store", lambda: store)

    state = {
        "session_id": "session_pref_1",
        "user_id": "user_pref_1",
        "task_type": "recommendation",
        "session_state": SessionState(),
        "semantic_frame": {
            "preference_signals": [
                {"preference_type": "relative_price_preference", "value": "lower_price", "operator": "like", "text": "便宜点"},
            ],
            "soft_preferences": {"price_preference": "lower_price"},
            "hard_constraints": {"category": "火锅"},
        },
    }

    result = sup._h_persist_session(state)
    saved = store.load("session_pref_1")

    assert saved.active_preferences
    assert saved.active_preferences[0]["value"] == "lower_price"
    assert saved.active_preferences[0]["preference_type"] == "budget"
    assert result["session_state_after"].active_preferences == saved.active_preferences

    merged = merge_preference_memory_summaries(
        saved.active_preferences,
        build_preference_memories_from_semantic_frame(
            {"soft_preferences": {"scene": "date"}},
            user_id="user_pref_1",
            session_id="session_pref_1",
            evidence_ref="turn_2",
        ),
    )
    assert any(item["preference_type"] == "scene" for item in merged)
