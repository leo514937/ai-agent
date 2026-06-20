"""Contract tests for the stage-09 input layer."""

from __future__ import annotations

from ..config import MOCK_LOCATION
from ..input.normalizer import normalize_text
from ..input.receiver import receive_input
from ..input.validator import validate_basic_input


def test_receive_input_injects_mock_user_context():
    result = receive_input("\u4f60\u597d")

    assert result["input_type"] == "text"
    assert result["raw_text"] == "\u4f60\u597d"
    assert result["user_context"]["location_name"] == MOCK_LOCATION["name"]
    assert result["user_context"]["lat"] == MOCK_LOCATION["lat"]
    assert result["user_context"]["lng"] == MOCK_LOCATION["lng"]


def test_validate_basic_input_rejects_invalid_payloads():
    assert validate_basic_input(None)["valid"] is False
    assert validate_basic_input("   ")["error_code"] == "EMPTY_INPUT"


def test_normalize_text_standardises_punctuation_without_losing_shop_names():
    text = "\u6d77\u5e95\u635e\uff08\u6c34\u6676\u57ce\u5e97\uff09\uff0c  \u9644\u8fd1\u63a8\u8350\u706b\u9505"
    assert normalize_text(text) == "\u6d77\u5e95\u635e(\u6c34\u6676\u57ce\u5e97), \u9644\u8fd1\u63a8\u8350\u706b\u9505"
