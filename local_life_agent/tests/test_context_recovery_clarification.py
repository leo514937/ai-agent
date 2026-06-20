"""Stage 12 acceptance tests for session state, context recovery, and clarification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ..agent import run_agent
from ..domain.schemas import PendingClarification
from ..domain.state import SessionState
from ..engine.graph_builder import build_graph
from ..target.context_recovery import recover_context
from ..session.store import InMemorySessionStore, get_session_store, reset_session_store, set_session_store


GRAPH = build_graph()


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store()
    yield
    reset_session_store()


def _base_state(text: str, session_id: str) -> dict:
    return {
        "raw_text": text,
        "session_id": session_id,
        "trace_id": f"trace_{session_id}",
        "turn_id": "",
        "user_id": "",
        "normalized_text": "",
        "input_type": "text",
        "top_intent": None,
        "task_type": None,
        "semantic_frame": None,
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "active_constraints": {},
        "comparison_targets": [],
        "resolved_target": None,
        "resolve_shop_result": None,
        "execution_plan": None,
        "validated_plan": None,
        "tool_results": {},
        "tool_result_set": {},
        "evidence_pack": None,
        "answer_plan": None,
        "final_response": "",
        "state_update_plan": None,
        "session_state_before": None,
        "session_state_after": None,
        "event_log": [],
        "metrics_tags": {},
        "trace_spans": [],
        "rewrite_count": 0,
        "session_state": None,
        "pending_check_result": "pass",
        "error_code": "",
        "error_message": "",
        "plan_validation_result": "",
        "failed_stage": "",
        "guard_result": "",
        "verify_result": "",
        "draft_response": "",
    }


def _invoke(text: str, session_id: str = "sess") -> dict:
    return GRAPH.invoke(_base_state(text, session_id))


def _tool_names(state: dict) -> list[str]:
    results = state.get("tool_result_set") or state.get("tool_results") or {}
    names: list[str] = []
    for result in results.values():
        names.append(getattr(result, "tool_name", "") or str(result.get("tool_name", "")))
    return names


def test_session_store_load_save_clear():
    store = InMemorySessionStore()
    state = store.load("missing")
    assert isinstance(state, SessionState)
    assert state.current_shop is None

    store.save("s1", SessionState(current_shop={"shop_id": "x", "shop_name": "A"}))
    loaded = store.load("s1")
    assert loaded.current_shop == {"shop_id": "x", "shop_name": "A"}

    store.clear("s1")
    assert store.load("s1").current_shop is None

    store.save("a", SessionState(current_shop={"shop_id": "a", "shop_name": "A"}))
    store.save("b", SessionState(current_shop={"shop_id": "b", "shop_name": "B"}))
    assert store.load("a").current_shop["shop_id"] == "a"
    assert store.load("b").current_shop["shop_id"] == "b"


def test_ambiguous_shop_writes_pending_and_does_not_call_coupon_tool():
    result = _invoke("海底捞有券吗", "amb_1")
    assert "1." in result["final_response"]
    assert "2." in result["final_response"]
    assert "请回复编号" in result["final_response"]
    assert "海底捞" in result["final_response"]
    assert result["pending_clarification"] is not None
    assert result["pending_clarification"]["candidate_targets"]
    assert _tool_names(result) == []
    assert get_session_store().load("amb_1").pending_clarification is not None


def test_pending_reply_number_restores_original_coupon_task():
    first = _invoke("海底捞有券吗", "pend_1")
    assert first["pending_clarification"] is not None

    second = _invoke("1", "pend_1")
    assert "有券" in second["final_response"]
    assert "get_coupon_list" in _tool_names(second)
    assert second["pending_clarification"] is None
    assert second["current_shop"]["shop_name"] == "海底捞(牡丹园店)"
    assert get_session_store().load("pend_1").pending_clarification is None


def test_pending_reply_chinese_ordinal_restores_task():
    _invoke("海底捞有券吗", "pend_2")
    second = _invoke("第二个", "pend_2")
    assert "get_coupon_list" in _tool_names(second)
    assert second["current_shop"]["shop_name"] == "海底捞火锅(水晶城购物中心店)"
    assert second["pending_clarification"] is None


def test_pending_reply_out_of_range_keeps_pending():
    pending = PendingClarification(
        pending_id="pc_test",
        original_task_type="coupon_query",
        candidate_targets=[
            {"shop_id": "s1", "shop_name": "A"},
            {"shop_id": "s2", "shop_name": "B"},
        ],
        expected_reply_type="shop_selection",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        original_text="海底捞有券吗",
        original_semantic_frame={"task_type": "coupon_query", "merchant_mentions": ["海底捞"]},
        reason="ambiguous_shop",
        source_node="target_resolve",
    )
    get_session_store().save("pend_3", SessionState(pending_clarification=pending.model_dump()))

    result = _invoke("3", "pend_3")
    assert "没有第 3 个选项" in result["final_response"]
    assert result["pending_clarification"] is not None
    assert _tool_names(result) == []
    assert get_session_store().load("pend_3").pending_clarification is not None


def test_pending_reply_invalid_keeps_pending():
    pending = PendingClarification(
        pending_id="pc_test",
        original_task_type="coupon_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "A"}],
        expected_reply_type="shop_selection",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        original_text="海底捞有券吗",
        original_semantic_frame={"task_type": "coupon_query", "merchant_mentions": ["海底捞"]},
        reason="ambiguous_shop",
        source_node="target_resolve",
    )
    get_session_store().save("pend_4", SessionState(pending_clarification=pending.model_dump()))

    result = _invoke("我不懂", "pend_4")
    assert "请回复编号或店名" in result["final_response"]
    assert result["pending_clarification"] is not None
    assert _tool_names(result) == []
    assert get_session_store().load("pend_4").pending_clarification is not None


def test_pending_reply_topic_change_clears_pending():
    _invoke("海底捞有券吗", "pend_5")
    result = _invoke("算了，附近推荐火锅", "pend_5")
    assert get_session_store().load("pend_5").pending_clarification is None
    assert "get_coupon_list" not in _tool_names(result)


def test_pending_expired_clears_pending():
    pending = PendingClarification(
        pending_id="pc_expired",
        original_task_type="coupon_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "A"}],
        expected_reply_type="shop_selection",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        original_text="海底捞有券吗",
        original_semantic_frame={"task_type": "coupon_query", "merchant_mentions": ["海底捞"]},
        reason="ambiguous_shop",
        source_node="target_resolve",
    )
    get_session_store().save("pend_6", SessionState(pending_clarification=pending.model_dump()))

    result = _invoke("1", "pend_6")
    assert "之前的问题已过期" in result["final_response"]
    assert get_session_store().load("pend_6").pending_clarification is None
    assert _tool_names(result) == []


def test_run_agent_uses_graph_and_exposes_session_debug():
    first = run_agent("海底捞有券吗", "run_agent_1")
    assert "1." in first.answer_text
    assert first.debug is not None
    assert first.debug.session_state_before.get("current_shop") is None
    assert first.debug.session_state_before.get("pending_clarification") is None
    assert first.debug.session_state_after.get("pending_clarification")
    assert "pending_clarification" in first.debug.state_update_plan.get("set_fields", [])

    second = run_agent("1", "run_agent_1")
    assert second.debug is not None
    assert any(
        getattr(result, "tool_name", "") == "get_coupon_list" or str(result.get("tool_name", "")) == "get_coupon_list"
        for result in second.debug.tool_results.values()
    )
    assert second.debug.session_state_after.get("pending_clarification") is None


def test_build_graph_does_not_clear_session_store():
    store = get_session_store()
    store.save("graph_reset", SessionState(current_shop={"shop_id": "keep", "shop_name": "Keep"}))

    build_graph()

    assert get_session_store().load("graph_reset").current_shop == {"shop_id": "keep", "shop_name": "Keep"}


def test_current_shop_reference_after_single_shop_success():
    first = _invoke("川味轩(知春路店)有券吗", "shop_ref_1")
    assert first["current_shop"]["shop_name"] == "川味轩(知春路店)"

    second = _invoke("这家现在营业吗", "shop_ref_1")
    assert "check_open_status" in _tool_names(second)
    assert second["current_shop"]["shop_name"] == "川味轩(知春路店)"
    assert "营业" in second["final_response"]


def test_explicit_shop_overrides_current_shop():
    get_session_store().save(
        "override_1",
        SessionState(current_shop={"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}),
    )

    result = _invoke("川味轩(知春路店)有券吗", "override_1")
    assert "get_coupon_list" in _tool_names(result)
    assert result["current_shop"]["shop_name"] == "川味轩(知春路店)"


def test_first_item_reference_uses_last_recommendation_list():
    get_session_store().save(
        "reco_1",
        SessionState(
            last_recommendation_list=[
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
                {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"},
            ]
        ),
    )

    result = _invoke("第一家有券吗", "reco_1")
    assert "get_coupon_list" in _tool_names(result)
    assert result["current_shop"]["shop_name"] == "川味轩(知春路店)"


def test_this_shop_after_recommendation_list_must_clarify():
    get_session_store().save(
        "reco_2",
        SessionState(
            last_recommendation_list=[
                {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"},
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
            ]
        ),
    )

    result = _invoke("这家有券吗", "reco_2")
    assert "请提供完整店名" in result["final_response"]
    assert "get_coupon_list" not in _tool_names(result)
    assert result["current_shop"] is None


def test_active_constraints_can_be_inherited_without_overriding_explicit_constraints():
    session_state = SessionState(active_constraints={"price": "cheap", "distance": "near"})
    explicit_frame = {
        "merchant_mentions": [],
        "hard_constraints": {"price": "expensive"},
    }
    recovered = recover_context(session_state, explicit_frame, text="有券吗")

    assert "inherited_constraints" not in recovered.get("context_resolution", {})

    inherited_frame = {
        "merchant_mentions": [],
        "hard_constraints": {},
        "soft_preferences": {},
        "ranking_signals": {},
    }
    inherited = recover_context(session_state, inherited_frame, text="有券吗")

    assert inherited["context_resolution"]["inherited_constraints"] == {"price": "cheap", "distance": "near"}
    assert "resolved_target" not in inherited


def test_single_shop_multifacet_success_writes_current_shop():
    result = _invoke("川味轩(知春路店)有券吗，营业吗，远不远？", "multi_1")
    assert result["current_shop"]["shop_name"] == "川味轩(知春路店)"
    assert result["pending_clarification"] is None
    assert {"get_coupon_list", "check_open_status", "get_distance_eta"}.issuperset(set(_tool_names(result)))


def test_tool_failed_does_not_update_current_shop():
    result = _invoke("远方烧烤(清河店)有券吗", "fail_1")
    assert result["current_shop"] is None
    assert get_session_store().load("fail_1").current_shop is None
    assert "get_coupon_list" in _tool_names(result)
