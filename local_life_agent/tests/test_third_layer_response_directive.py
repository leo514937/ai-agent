from __future__ import annotations

from ..answer.response_directive import ResponseDirective


def test_response_directive_serializes():
    directive = ResponseDirective(
        answer_text="川味轩目前营业中。",
        answer_type="single_shop",
        response_mode="answer",
        fallback_reason="",
        trace_id="trace_1",
    )
    payload = directive.model_dump()
    assert payload["answer_text"] == "川味轩目前营业中。"
    assert payload["response_mode"] == "answer"
    assert payload["trace_id"] == "trace_1"

