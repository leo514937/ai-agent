"""Contract tests for the stage-09 input layer."""

from __future__ import annotations

from ..domain.schemas import UserContext
from ..input.normalizer import normalize_text
from ..input.receiver import receive_input
from ..input.validator import validate_basic_input


def test_receive_input_defaults_to_missing_user_context():
    result = receive_input("你好")

    assert result["input_type"] == "text"
    assert result["raw_text"] == "你好"
    assert result["user_context"]["location_status"] == "missing"
    assert result["user_context"]["location_source"] == "receiver"
    assert result["user_context"]["location_missing_reason"] == "user_location_not_provided"
    assert result["user_context"]["lat"] is None
    assert result["user_context"]["lng"] is None


def test_receive_input_preserves_explicit_test_mock_user_context():
    user_context = UserContext(
        location_name="测试位置",
        lat=39.96,
        lng=116.35,
        location_status="test_mock",
        location_source="test_mock",
    )
    result = receive_input("你好", user_context=user_context)

    assert result["user_context"]["location_status"] == "test_mock"
    assert result["user_context"]["location_source"] == "test_mock"
    assert result["user_context"]["lat"] == 39.96
    assert result["user_context"]["lng"] == 116.35


def test_validate_basic_input_rejects_invalid_payloads():
    assert validate_basic_input(None)["valid"] is False
    assert validate_basic_input("   ")["error_code"] == "EMPTY_INPUT"


def test_normalize_text_standardises_punctuation_without_losing_shop_names():
    text = "海底捞（水晶城店），  附近推荐火锅"
    assert normalize_text(text) == "海底捞(水晶城店), 附近推荐火锅"
