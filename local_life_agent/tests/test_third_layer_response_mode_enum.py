from __future__ import annotations

from ..domain.enums import ResponseMode, normalize_response_mode


def test_response_mode_legacy_aliases_normalize():
    assert normalize_response_mode("direct") == ResponseMode.DIRECT
    assert normalize_response_mode("direct_response") == ResponseMode.DIRECT
    assert normalize_response_mode("reject") == ResponseMode.REJECT
    assert normalize_response_mode("clarify") == ResponseMode.CLARIFY
    assert normalize_response_mode("fallback") == ResponseMode.FALLBACK
    assert normalize_response_mode("answer") == ResponseMode.ANSWER
    assert normalize_response_mode("tool_answer") == ResponseMode.TOOL_ANSWER
    assert normalize_response_mode("comparison") == ResponseMode.COMPARISON
    assert normalize_response_mode("exploration_plan") == ResponseMode.EXPLORATION_PLAN


def test_response_mode_reject_not_direct():
    assert normalize_response_mode("reject") != ResponseMode.DIRECT


def test_response_mode_invalid_returns_none():
    assert normalize_response_mode("not_a_valid_mode") is None
