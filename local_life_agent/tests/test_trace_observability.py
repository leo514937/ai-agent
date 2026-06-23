from __future__ import annotations

from local_life_agent.agent import DebugInfo, run_agent_graph
from local_life_agent.engine import graph_builder
from local_life_agent.observability.trace import build_turn_trace, get_trace_spans, record_span, reset_trace_store


def test_run_agent_graph_exposes_turn_trace(monkeypatch):
    class FakeGraph:
        def invoke(self, initial, config=None):
            return {
                "final_response": "ok",
                "trace_id": initial["trace_id"],
                "session_id": initial["session_id"],
                "turn_id": "turn_1",
                "raw_text": initial["raw_text"],
                "event_log": [
                    {"node": "receive_input", "stage": "input_received", "status": "success", "duration_ms": 1},
                    {"node": "answer_verify", "stage": "answer_verify", "status": "success", "duration_ms": 2},
                ],
                "semantic_frame": {"top_intent": "local_life", "task_type": "recommendation"},
                "execution_plan": {"tool_calls": [{"call_id": "call_1"}]},
                "tool_result_set": {},
                "evidence_pack": {"ranking_snapshot": {"ranked": [{"shop_id": "shop_1"}]}},
                "session_state_before": {},
                "session_state_after": {},
                "state_update_plan": {},
                "answer_source": "llm_verbalizer",
                "answer_fallback_reason": "",
                "fallback_reason": "",
                "llm_verbalizer_error": None,
                "generated_llm_answer_before_fallback": "",
                "llm_verbalizer_violation": None,
                "answer_verify_passed": True,
                "answer_verify_violations": [],
                "rewrite_needed": False,
                "rewrite_count": 0,
                "rewrite_reason": "",
                "final_safety_status": "safe",
            }

    monkeypatch.setattr("local_life_agent.engine.graph_builder.build_graph", lambda: FakeGraph())
    monkeypatch.setattr("local_life_agent.agent._GRAPH_CACHE", None, raising=False)

    response = run_agent_graph("附近推荐火锅", session_id="trace_case")

    assert response.debug is not None
    assert response.debug.turn_trace["trace_id"] == response.trace_id
    assert response.debug.turn_trace["task_type"] == "recommendation"
    assert response.debug.turn_trace["tool_call_count"] == 1


def test_trace_store_sanitizes_sensitive_fields():
    reset_trace_store()
    record_span(
        "trace_sensitive",
        "semantic_parse",
        {
            "api_key": "secret",
            "prompt": "very long prompt",
            "status": "success",
        },
    )
    spans = get_trace_spans("trace_sensitive")
    assert spans[0].metadata["api_key"] == "<redacted>"
    assert spans[0].metadata["prompt"] == "<redacted>"


def test_build_turn_trace_captures_fallback_and_verifier():
    trace = build_turn_trace(
        {
            "trace_id": "trace_1",
            "session_id": "session_1",
            "raw_text": "测试",
            "semantic_frame": {"top_intent": "local_life", "task_type": "comparison", "primary_task": "comparison"},
            "execution_plan": {"tool_calls": [{"call_id": "a"}, {"call_id": "b"}]},
            "evidence_pack": {"comparison_matrix": {"rows": [{"shop_id": "1"}, {"shop_id": "2"}]}},
            "resolved_target": {"status": "RESOLVED", "reason": "comparison_targets_resolved"},
            "answer_source": "template_fallback",
            "answer_verify_passed": False,
            "answer_verify_violations": ["ranking_changed"],
            "rewrite_count": 1,
            "fallback_reason": "b2_mini_verifier:ranking_changed",
            "final_safety_status": "fallback",
            "event_log": [],
        },
        user_text="海底捞和川味轩哪个好",
        total_duration_ms=12,
    )
    assert trace.selected_flow == "comparison_flow"
    assert trace.decision_type == "comparison"
    assert trace.answer_verify_violations == ["ranking_changed"]
    assert trace.fallback_reason == "b2_mini_verifier:ranking_changed"


def test_trace_failure_does_not_break_handler(monkeypatch):
    def broken_record_span(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_builder, "record_span", broken_record_span)

    def handler(state):
        return {"value": 1, **graph_builder._log(state, "emit_response")}

    wrapped = graph_builder._instrument_handler("emit_response", handler)
    result = wrapped({"trace_id": "trace_x", "session_id": "sid", "turn_id": "tid", "raw_text": "hi", "event_log": []})
    assert result["value"] == 1
    assert result["event_log"]
