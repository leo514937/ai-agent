"""Unit tests for active_turn_resolver — the pending-clarification routing node."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from local_life_agent.domain.schemas import ActiveTurnResult, PendingClarification
from local_life_agent.engine.subgraphs.active_turn_resolver import (
    _CANCEL_TERMS,
    resolve_active_turn,
    _should_treat_as_topic_switch,
    _rule_recognizer,
    _fuzzy_recognizer,
    _pending_expired,
)
from local_life_agent.engine.subgraphs.active_turn_resolver import _h_active_turn_resolver

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

_DUMMY_CANDIDATES: list[dict[str, str]] = [
    {"shop_id": "s1", "shop_name": "海底捞(牡丹园店)", "address": "牡丹园"},
    {"shop_id": "s2", "shop_name": "海底捞火锅(水晶城购物中心店)", "address": "水晶城"},
    {"shop_id": "s3", "shop_name": "川味轩(知春路店)", "address": "知春路"},
]


def _make_pending(
    candidates: list[dict[str, str]] | None = None,
    expires_in_seconds: int | None = 300,
) -> dict[str, Any]:
    created = datetime.now(timezone.utc)
    expires = created + timedelta(seconds=expires_in_seconds) if expires_in_seconds else None
    return {
        "pending_id": "pc_test",
        "original_task_type": "coupon_query",
        "candidate_targets": candidates or _DUMMY_CANDIDATES,
        "expected_reply_type": "shop_selection",
        "created_at": created,
        "expires_at": expires,
        "original_text": "海底捞有券吗",
        "original_semantic_frame": {"task_type": "coupon_query", "merchant_mentions": ["海底捞"]},
        "reason": "ambiguous_shop",
        "source_node": "target_resolve",
    }


def _make_expired_pending(candidates: list[dict[str, str]] | None = None) -> dict[str, Any]:
    created = datetime.now(timezone.utc) - timedelta(minutes=10)
    expires = datetime.now(timezone.utc) - timedelta(minutes=5)
    return {
        "pending_id": "pc_expired",
        "original_task_type": "coupon_query",
        "candidate_targets": candidates or _DUMMY_CANDIDATES,
        "expected_reply_type": "shop_selection",
        "created_at": created,
        "expires_at": expires,
        "original_text": "海底捞有券吗",
        "reason": "ambiguous_shop",
        "source_node": "target_resolve",
    }


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — no pending
# ═══════════════════════════════════════════════════════════════════════


def test_no_pending_returns_normal_query():
    result = resolve_active_turn("海底捞有券吗", None)
    assert isinstance(result, ActiveTurnResult)
    assert result.route == "normal_query"
    assert result.confidence == 1.0


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — digit selection
# ═══════════════════════════════════════════════════════════════════════


def test_pending_digit_selects_first_candidate():
    result = resolve_active_turn("1", _make_pending())
    assert result.route == "pending_restored"
    assert result.selected_index == 1
    assert result.selected_candidate is not None
    assert result.selected_candidate["shop_id"] == "s1"
    assert result.confidence == 1.0


def test_pending_digit_selects_third_candidate():
    result = resolve_active_turn("3", _make_pending())
    assert result.route == "pending_restored"
    assert result.selected_index == 3
    assert result.selected_candidate is not None
    assert result.selected_candidate["shop_id"] == "s3"


def test_pending_digit_out_of_range():
    result = resolve_active_turn("99", _make_pending())
    assert result.route == "pending_out_of_range"
    assert result.selected_index == 99


def test_pending_digit_zero():
    result = resolve_active_turn("0", _make_pending())
    # 0 is not in 1..candidate_count, so it should be out_of_range
    assert result.route == "pending_out_of_range"


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — Chinese ordinal selection
# ═══════════════════════════════════════════════════════════════════════


def test_pending_ordinal_selects_second():
    result = resolve_active_turn("第二个", _make_pending())
    assert result.route == "pending_restored"
    assert result.selected_index == 2
    assert result.selected_candidate is not None
    assert result.selected_candidate["shop_id"] == "s2"


def test_pending_ordinal_out_of_range():
    result = resolve_active_turn("第四个", _make_pending())
    assert result.route == "pending_out_of_range"
    assert result.selected_index == 4


def test_pending_ordinal_fulltext():
    result = resolve_active_turn("选第二个", _make_pending())
    assert result.route == "pending_restored"
    assert result.selected_index == 2


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — cancel
# ═══════════════════════════════════════════════════════════════════════


def test_pending_cancel():
    result = resolve_active_turn("取消", _make_pending())
    assert result.route == "pending_cancelled"
    assert result.confidence == 1.0


def test_pending_cancel_alternative():
    result = resolve_active_turn("算了", _make_pending())
    assert result.route == "pending_cancelled"


def test_pending_cancel_substring():
    for term in _CANCEL_TERMS:
        result = resolve_active_turn(term, _make_pending())
        assert result.route == "pending_cancelled", f"cancel term '{term}' should route to pending_cancelled"


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — expired
# ═══════════════════════════════════════════════════════════════════════


def test_pending_expired_returns_expired():
    result = resolve_active_turn("1", _make_expired_pending())
    assert result.route == "pending_expired"
    assert result.reason == "pending_expired"
    assert result.confidence == 1.0


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — exact name match
# ═══════════════════════════════════════════════════════════════════════


def test_pending_exact_name_match():
    result = resolve_active_turn("川味轩(知春路店)", _make_pending())
    assert result.route == "pending_restored"
    assert result.selected_index == 3
    assert result.selected_candidate is not None
    assert result.selected_candidate["shop_id"] == "s3"


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — fuzzy name match
# ═══════════════════════════════════════════════════════════════════════


def test_pending_fuzzy_branch_only():
    """Fuzzy match on a unique branch name not shared by other candidates."""
    candidates = [
        {"shop_id": "s1", "shop_name": "海底捞(牡丹园店)"},
        {"shop_id": "s2", "shop_name": "海底捞火锅(水晶城购物中心店)"},
        {"shop_id": "s3", "shop_name": "川味轩(知春路店)"},
    ]
    result = resolve_active_turn("牡丹园", _make_pending(candidates=candidates))
    assert result.route == "pending_restored"
    assert result.selected_index == 1
    assert result.source == "fuzzy"


def test_pending_fuzzy_branch_name():
    result = resolve_active_turn("知春路", _make_pending())
    assert result.route == "pending_restored"
    assert result.selected_index == 3


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — no match / invalid
# ═══════════════════════════════════════════════════════════════════════


def test_pending_no_match_returns_invalid():
    result = resolve_active_turn("完全不知道这是什么", _make_pending())
    assert result.route == "pending_invalid"
    assert result.confidence == 0.0
    assert "no_rule_fuzzy_or_llm_match" in result.reason


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — topic switch heuristic
# ═══════════════════════════════════════════════════════════════════════


def test_pending_topic_switch_heuristic():
    """Topic-switch keywords trigger topic_switch via _h_active_turn_resolver."""
    from local_life_agent.domain.state import SessionState
    session = SessionState(pending_clarification=_make_pending())
    state: dict[str, Any] = {
        "raw_text": "附近推荐火锅",
        "normalized_text": "附近推荐火锅",
        "session_state_before": session,
        "session_state": session,
    }
    result = _h_active_turn_resolver(state)
    atr = result.get("active_turn_result", {})
    # resolve_active_turn returns pending_invalid (no rule/fuzzy match),
    # but _h_active_turn_resolver applies topic_switch heuristic on top
    assert atr.get("route") == "topic_switch"
    assert atr.get("new_query") == "附近推荐火锅"


def test_pending_topic_switch_cancel():
    """Cancel keywords take priority over topic switch — cancel fires first."""
    result = resolve_active_turn("算了，附近推荐火锅", _make_pending())
    # "算了" is in _CANCEL_TERMS, so the cancel rule fires first
    assert result.route == "pending_cancelled"


def test_pending_topic_switch_short_no_keyword():
    """Short text without topic keywords should not trigger topic switch."""
    result = resolve_active_turn("我不懂", _make_pending())
    assert result.route == "pending_invalid"


def test_semantic_new_task_override_short_circuits_pending():
    from local_life_agent.domain.state import SessionState

    session = SessionState(pending_clarification=_make_pending())
    state: dict[str, Any] = {
        "raw_text": "不要烧烤了，推荐咖啡",
        "normalized_text": "不要烧烤了，推荐咖啡",
        "session_state_before": session,
        "session_state": session,
    }
    result = _h_active_turn_resolver(state)
    atr = result.get("active_turn_result", {})
    assert atr.get("route") == "topic_switch"
    assert atr.get("source") == "semantic"
    assert atr.get("reason") == "semantic_new_task_override"


def test_semantic_constraint_update_short_circuits_pending():
    from local_life_agent.domain.state import SessionState

    session = SessionState(pending_clarification=_make_pending())
    state: dict[str, Any] = {
        "raw_text": "要更便宜一点的",
        "normalized_text": "要更便宜一点的",
        "session_state_before": session,
        "session_state": session,
    }
    result = _h_active_turn_resolver(state)
    atr = result.get("active_turn_result", {})
    assert atr.get("route") == "topic_switch"
    assert atr.get("source") == "semantic"
    assert atr.get("reason") == "semantic_constraint_update"


# ═══════════════════════════════════════════════════════════════════════
# resolve_active_turn — edge cases
# ═══════════════════════════════════════════════════════════════════════


def test_empty_text_no_pending():
    result = resolve_active_turn("", None)
    assert result.route == "normal_query"


def test_single_candidate_deictic():
    """With exactly one candidate, '就这个' should restore."""
    single = [{"shop_id": "s1", "shop_name": "海底捞(牡丹园店)"}]
    result = resolve_active_turn("就这个", _make_pending(candidates=single))
    assert result.route == "pending_restored"
    assert result.selected_index == 1


# ═══════════════════════════════════════════════════════════════════════
# _should_treat_as_topic_switch
# ═══════════════════════════════════════════════════════════════════════


def test_topic_switch_hint():
    assert _should_treat_as_topic_switch("换一家店") is True
    assert _should_treat_as_topic_switch("重新推荐火锅") is True
    assert _should_treat_as_topic_switch("讲个笑话") is True


def test_topic_switch_keyword():
    assert _should_treat_as_topic_switch("附近有火锅店吗") is True
    assert _should_treat_as_topic_switch("这家店营业吗") is True


def test_topic_switch_short():
    assert _should_treat_as_topic_switch("好") is False
    assert _should_treat_as_topic_switch("1") is False


# ═══════════════════════════════════════════════════════════════════════
# _pending_expired
# ═══════════════════════════════════════════════════════════════════════


def test_pending_expired_check():
    assert _pending_expired(_make_expired_pending()) is True
    assert _pending_expired(_make_pending()) is False
    assert _pending_expired(None) is False


# ═══════════════════════════════════════════════════════════════════════
# _h_active_turn_resolver step handler (unit)
# ═══════════════════════════════════════════════════════════════════════


def test_h_active_turn_resolver_normal():
    state: dict[str, Any] = {
        "raw_text": "海底捞有券吗",
        "normalized_text": "海底捞有券吗",
        "session_state_before": None,
        "session_state": None,
    }
    result = _h_active_turn_resolver(state)
    atr = result.get("active_turn_result", {})
    assert atr.get("route") == "normal_query"


def test_h_active_turn_resolver_with_pending():
    from local_life_agent.domain.state import SessionState

    session = SessionState(pending_clarification=_make_pending())
    state: dict[str, Any] = {
        "raw_text": "1",
        "normalized_text": "1",
        "session_state_before": session,
        "session_state": session,
    }
    result = _h_active_turn_resolver(state)
    atr = result.get("active_turn_result", {})
    assert atr.get("route") == "pending_restored"
    assert atr.get("selected_index") == 1


def test_h_active_turn_resolver_empty_text():
    state: dict[str, Any] = {
        "raw_text": "",
        "normalized_text": "",
        "session_state_before": None,
        "session_state": None,
    }
    result = _h_active_turn_resolver(state)
    atr = result.get("active_turn_result", {})
    assert atr.get("route") == "normal_query"
