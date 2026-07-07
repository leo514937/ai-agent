from __future__ import annotations

from typing import Any

from local_life_agent.domain.state import SessionState
from local_life_agent.domain.enums import TopIntent
from local_life_agent.engine._routes import _OUTER_ROUTE_LOCAL_LIFE
from local_life_agent.engine.subgraphs import intake_guard_router as igr
from local_life_agent.engine.subgraphs import understanding_subgraph as us
from local_life_agent.target.focus_resolver import resolve_focus_context


def test_semantic_parse_uses_contextualized_query_for_deictic_follow_up(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_parse_semantic_frame(text: str, top_intent: str, **kwargs: Any) -> dict[str, Any]:
        captured["text"] = text
        captured["top_intent"] = top_intent
        return {
            "semantic_frame": {
                "top_intent": top_intent,
                "task_type": "single_shop_query",
                "primary_task": "single_shop_query",
                "confidence": 0.88,
                "merchant_mentions": ["海底捞"],
                "reference_mentions": ["这家"],
                "need_context": False,
            },
            "error_code": "",
            "error_message": "",
            "semantic_source": "test",
            "llm_backend": "test",
            "fallback_reason": "",
            "llm_called": False,
            "dropped_facets": [],
        }

    monkeypatch.setattr(us, "parse_semantic_frame", fake_parse_semantic_frame)

    state = {
        "raw_text": "这家有券吗",
        "normalized_text": "这家有券吗",
        "top_intent": TopIntent.local_life,
        "current_shop": {"shop_id": "shop_1", "shop_name": "海底捞(牡丹园店)"},
        "session_state_before": SessionState(current_shop={"shop_id": "shop_1", "shop_name": "海底捞(牡丹园店)"}),
    }

    result = us._h_semantic_parse(state)

    assert "海底捞(牡丹园店)" in captured["text"]
    assert captured["text"] != "这家有券吗"
    assert result["semantic_frame"].task_type == "single_shop_query"


def test_focus_resolver_uses_current_shop_and_recommendation_history():
    session = SessionState(
        current_shop={"shop_id": "shop_1", "shop_name": "海底捞(牡丹园店)"},
        last_recommendation_list=[
            {"shop_id": "shop_1", "shop_name": "海底捞(牡丹园店)"},
            {"shop_id": "shop_2", "shop_name": "巴奴(知春路店)"},
        ],
    )

    current_shop_result = resolve_focus_context("这家有券吗", session_state=session, semantic_frame={})
    ordinal_result = resolve_focus_context("第二个怎么样", session_state=session, semantic_frame={})

    assert current_shop_result.focus_type == "current_shop"
    assert current_shop_result.clarification_needed is False
    assert current_shop_result.focus_object["shop_name"] == "海底捞(牡丹园店)"
    assert ordinal_result.focus_type == "recommendation_item"
    assert ordinal_result.focus_index == 2
    assert ordinal_result.focus_object["shop_name"] == "巴奴(知春路店)"


def test_mixed_intent_policy_keeps_local_life_route_when_reference_signal_exists():
    session = SessionState(current_shop={"shop_id": "shop_1", "shop_name": "海底捞(牡丹园店)"})

    assert igr._should_keep_local_life_route(
        raw_text="顺便问一下，这家有券吗",
        normalized_text="顺便问一下，这家有券吗",
        top_intent=TopIntent.chat,
        session_state=session,
        active_turn_result={},
    ) is True


def test_mixed_intent_policy_does_not_force_local_life_without_signal():
    assert igr._should_keep_local_life_route(
        raw_text="顺便问一下天气怎么样",
        normalized_text="顺便问一下天气怎么样",
        top_intent=TopIntent.chat,
        session_state=SessionState(),
        active_turn_result={},
    ) is False


def test_intake_guard_router_keeps_local_life_for_mixed_reference_signal(monkeypatch):
    class FakeSessionStore:
        def load(self, _session_id: str) -> SessionState:
            return SessionState(current_shop={"shop_id": "shop_1", "shop_name": "海底捞(牡丹园店)"})

    def fake_parse_top_intent(_text: str, llm_call=None):  # noqa: ANN001
        return {"top_intent": TopIntent.chat, "confidence": 0.9, "reason": "chatty mix"}

    monkeypatch.setattr(igr, "get_session_store", lambda: FakeSessionStore())
    monkeypatch.setattr(igr, "parse_top_intent", fake_parse_top_intent)

    result = igr.h_intake_guard_router(
        {
            "trace_id": "trace_phase5_mixed",
            "session_id": "session_phase5_mixed",
            "turn_id": "turn_phase5_mixed",
            "raw_text": "顺便问一下，这家有券吗",
            "event_log": [],
        }
    )

    assert result["intake_route"] == _OUTER_ROUTE_LOCAL_LIFE
