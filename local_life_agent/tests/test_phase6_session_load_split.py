from __future__ import annotations

from local_life_agent.domain.schemas import PendingClarification
from local_life_agent.domain.state import SessionState
from local_life_agent.engine.subgraphs import intake_guard_router as igr


class _SpySessionStore:
    def __init__(self, session_state: SessionState | None = None) -> None:
        self.session_state = session_state or SessionState()
        self.load_calls = 0

    def load(self, session_id: str) -> SessionState:
        self.load_calls += 1
        return self.session_state.model_copy(deep=True)


def test_invalid_session_id_is_rejected_before_session_load(monkeypatch):
    store = _SpySessionStore(
        SessionState(current_shop={"shop_id": "s1", "shop_name": "测试店"})
    )
    monkeypatch.setattr(igr, "get_session_store", lambda: store)

    result = igr.h_intake_guard_router(
        {
            "trace_id": "trace_phase6_invalid_session",
            "turn_id": "turn_phase6_invalid_session",
            "session_id": "bad session/id",
            "raw_text": "推荐附近火锅",
            "event_log": [],
        }
    )

    assert store.load_calls == 0
    assert result["error_code"] == "INVALID_SESSION_ID"
    assert result["response_mode"] == "reject"


def test_load_session_state_is_pure_read(monkeypatch):
    pending = PendingClarification(
        pending_id="pc_1",
        original_task_type="single_shop_query",
        candidate_targets=[{"shop_id": "s1", "shop_name": "测试店"}],
        missing_slot_type="missing_shop",
        expected_reply_type="shop_selection",
        original_text="测试",
        original_semantic_frame={"task_type": "single_shop_query"},
        reason="missing_shop",
        source_node="target_resolve",
    )
    store = _SpySessionStore(
        SessionState(
            current_shop={"shop_id": "s1", "shop_name": "测试店"},
            last_recommendation_list=[{"shop_id": "s1", "shop_name": "测试店"}],
            comparison_targets=[{"shop_id": "c1", "shop_name": "对比店"}],
            pending_clarification=pending.model_dump(),
        )
    )
    monkeypatch.setattr(igr, "get_session_store", lambda: store)

    result = igr._h_load_session({"session_id": "session_1", "event_log": []})

    assert store.load_calls == 1
    assert result["session_state"].current_shop == {"shop_id": "s1", "shop_name": "测试店"}
    assert result["session_state_before"].current_shop == {"shop_id": "s1", "shop_name": "测试店"}
    assert "current_shop" not in result
    assert "last_recommendation_list" not in result
    assert "comparison_targets" not in result
    assert "pending_clarification" not in result
    assert "clarification_request" not in result


def test_expand_session_context_restores_compatibility_fields():
    pending = PendingClarification(
        pending_id="pc_2",
        original_task_type="comparison",
        candidate_targets=[{"shop_id": "a", "shop_name": "A店"}, {"shop_id": "b", "shop_name": "B店"}],
        missing_slot_type="missing_comparison_targets",
        expected_reply_type="comparison_targets",
        original_text="A店和B店哪个好",
        original_semantic_frame={"task_type": "comparison"},
        reason="comparison_targets_need_clarification",
        source_node="target_resolve",
    )
    session = SessionState(
        current_shop={"shop_id": "s1", "shop_name": "测试店"},
        last_recommendation_list=[{"shop_id": "r1", "shop_name": "推荐店1"}],
        active_constraints={"coupon": True},
        comparison_targets=[{"shop_id": "a", "shop_name": "A店"}, {"shop_id": "b", "shop_name": "B店"}],
        pending_clarification=pending.model_dump(),
    )

    result = igr._h_expand_session_context({"session_state": session, "event_log": []})

    assert result["current_shop"] == {"shop_id": "s1", "shop_name": "测试店"}
    assert result["last_recommendation_list"] == [{"shop_id": "r1", "shop_name": "推荐店1"}]
    assert result["comparison_targets"] == [{"shop_id": "a", "shop_name": "A店"}, {"shop_id": "b", "shop_name": "B店"}]
    assert result["pending_clarification"] == pending.model_dump()
    assert result["clarification_request"] is not None
    assert result["clarification_request"].clarification_type == "missing_comparison_targets"
    assert result["focus_context"] is not None
    assert result["focus_context"].focus_type == "current_shop"
