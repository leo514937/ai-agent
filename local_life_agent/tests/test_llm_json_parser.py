"""Contract tests for the stage-09 LLM client and JSON parser."""

from __future__ import annotations

import time

import pytest

from ..domain.enums import TopIntent
from ..llm.client import LLMEnumOutOfRange, LLMJSONParseError, call_llm
from ..llm.json_parser import parse_json_response


def test_parse_json_response_accepts_plain_json():
    payload = parse_json_response('{"top_intent":"local_life","confidence":0.9}')
    assert payload["top_intent"] == "local_life"
    assert payload["confidence"] == 0.9


def test_parse_json_response_accepts_fenced_json():
    payload = parse_json_response("```json\n{\"top_intent\": \"chat\"}\n```")
    assert payload["top_intent"] == "chat"


def test_parse_json_response_accepts_text_with_json():
    payload = parse_json_response("Here is the answer: {\"top_intent\": \"capability\", \"confidence\": 1.0}")
    assert payload["top_intent"] == "capability"


def test_parse_json_response_rejects_invalid_json():
    with pytest.raises(LLMJSONParseError):
        parse_json_response("not json at all")


def test_call_llm_retries_after_json_parse_fail():
    attempts = []

    def backend(**_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return "not json"
        return '{"top_intent": "local_life", "confidence": 0.95, "reason": "retry ok"}'

    result = call_llm("prompt", backend=backend, max_retries=1)

    assert result["ok"] is True
    assert result["content"]["top_intent"] == "local_life"
    assert len(attempts) == 2


def test_call_llm_retries_after_enum_out_of_range():
    attempts = []

    def backend(**_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return '{"top_intent": "bogus", "confidence": 0.5, "reason": "bad enum"}'
        return '{"top_intent": "out_of_scope", "confidence": 0.8, "reason": "fixed"}'

    def validator(payload):
        if payload.get("top_intent") not in {t.value for t in TopIntent}:
            raise ValueError("enum out of range")

    result = call_llm("prompt", backend=backend, max_retries=1, response_validator=validator)

    assert result["ok"] is True
    assert result["content"]["top_intent"] == TopIntent.out_of_scope
    assert len(attempts) == 2


def test_call_llm_captures_timeout():
    def backend(**_kwargs):
        time.sleep(0.2)
        return '{"top_intent": "chat", "confidence": 0.5}'

    result = call_llm("prompt", backend=backend, timeout_ms=10, max_retries=0)

    assert result["ok"] is False
    assert result["error_code"] == "LLM_TIMEOUT"
