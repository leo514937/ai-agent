"""Contract tests for the streaming event DTOs.

This file only verifies the event contract and factory helpers. It does
not exercise any HTTP/SSE transport layer.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ..domain.enums import ToolResultStatus
from ..streaming.events import (
    StreamEventEnvelope,
    StreamEventType,
    make_error,
    make_final,
    make_tool_call_finished,
    make_tool_call_started,
    make_trace_started,
)


def test_trace_started_missing_required_field_fails():
    with pytest.raises(ValidationError):
        StreamEventEnvelope.model_validate(
            {
                "event_type": "trace_started",
                "session_id": "session_1",
                "turn_id": "turn_1",
                "payload": {"workflow_version": "v1"},
            }
        )


def test_ack_alias_maps_to_trace_started():
    event = StreamEventEnvelope.model_validate(
        {
            "event_type": "ack",
            "trace_id": "trace_1",
            "session_id": "session_1",
            "turn_id": "turn_1",
            "payload": {"workflow_version": "v1"},
        }
    )
    assert event.event_type == StreamEventType.TRACE_STARTED


def test_tool_call_finished_supports_all_statuses():
    for status in ToolResultStatus:
        event = make_tool_call_finished(
            trace_id="trace_1",
            session_id="session_1",
            turn_id="turn_1",
            call_id="call_1",
            tool_name="get_coupon_list",
            status=status,
        )
        assert event.event_type == StreamEventType.TOOL_CALL_FINISHED
        assert event.payload["status"] == status.value


def test_final_must_include_answer_text():
    with pytest.raises(ValidationError):
        StreamEventEnvelope.model_validate(
            {
                "event_type": "final",
                "trace_id": "trace_1",
                "session_id": "session_1",
                "turn_id": "turn_1",
                "payload": {},
            }
        )

    event = make_final(
        trace_id="trace_1",
        session_id="session_1",
        turn_id="turn_1",
        answer_text="最终答案",
    )
    assert event.payload["answer_text"] == "最终答案"


def test_error_requires_code_message_stage():
    with pytest.raises(ValidationError):
        StreamEventEnvelope.model_validate(
            {
                "event_type": "error",
                "trace_id": "trace_1",
                "session_id": "session_1",
                "turn_id": "turn_1",
                "payload": {"code": "ERR"},
            }
        )

    event = make_error(
        trace_id="trace_1",
        session_id="session_1",
        turn_id="turn_1",
        code="ERR",
        message="failure",
        stage="plan_validator",
    )
    assert event.payload["code"] == "ERR"
    assert event.payload["stage"] == "plan_validator"


def test_event_json_serializes_enum_as_string():
    event = make_trace_started(
        trace_id="trace_1",
        session_id="session_1",
        turn_id="turn_1",
        workflow_version="v1",
    )
    raw = json.loads(event.model_dump_json())
    assert raw["event_type"] == "trace_started"


def test_answer_delta_is_dto_only():
    event = StreamEventEnvelope.model_validate(
        {
            "event_type": "answer_delta",
            "trace_id": "trace_1",
            "session_id": "session_1",
            "turn_id": "turn_1",
            "payload": {"delta_text": "部分输出"},
        }
    )
    assert event.event_type == StreamEventType.ANSWER_DELTA
    assert event.payload["delta_text"] == "部分输出"


def test_tool_call_started_factory_includes_trace_context():
    event = make_tool_call_started(
        trace_id="trace_1",
        session_id="session_1",
        turn_id="turn_1",
        call_id="call_1",
        tool_name="search_shops",
        target_shop_id="shop_sc_01",
    )
    assert event.trace_id == "trace_1"
    assert event.session_id == "session_1"
    assert event.turn_id == "turn_1"
    assert event.payload["target_shop_id"] == "shop_sc_01"
