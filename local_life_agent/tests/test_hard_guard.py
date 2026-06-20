"""Contract tests for the stage-09 HardGuard."""

from __future__ import annotations

from ..input.hard_guard import check_hard_guard


def test_pure_greeting_is_blocked():
    result = check_hard_guard("\u4f60\u597d")

    assert result["passed"] is False
    assert result["label"] == "greeting"


def test_punctuation_only_is_invalid():
    result = check_hard_guard("\uff0c")

    assert result["passed"] is False
    assert result["label"] == "invalid"


def test_greeting_with_business_intent_is_safe():
    result = check_hard_guard("\u4f60\u597d\uff0c\u9644\u8fd1\u63a8\u8350\u706b\u9505")

    assert result["passed"] is True
    assert result["label"] == "safe"


def test_capability_with_business_intent_is_safe():
    result = check_hard_guard("\u4f60\u6709\u4ec0\u4e48\u4f5c\u7528\uff0c\u987a\u4fbf\u63a8\u8350\u706b\u9505")

    assert result["passed"] is True
    assert result["label"] == "safe"


def test_pure_capability_question_is_blocked():
    result = check_hard_guard("\u4f60\u6709\u4ec0\u4e48\u4f5c\u7528")

    assert result["passed"] is False
    assert result["label"] == "capability"


def test_store_name_keeps_guard_open():
    result = check_hard_guard("\u6d77\u5e95\u635e\u6709\u4ec0\u4e48\u4f5c\u7528")

    assert result["passed"] is True
    assert result["label"] == "safe"


def test_function_rich_mall_question_is_safe():
    result = check_hard_guard("\u9644\u8fd1\u6709\u4ec0\u4e48\u529f\u80fd\u6bd4\u8f83\u5168\u7684\u5546\u573a")

    assert result["passed"] is True
    assert result["label"] == "safe"
