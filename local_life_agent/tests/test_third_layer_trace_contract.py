from __future__ import annotations

from local_life_agent.observability.trace import build_turn_trace


def test_third_layer_trace_contract_captures_decision_and_response():
    trace = build_turn_trace(
        {
            "trace_id": "trace_stage_3",
            "session_id": "session_stage_3",
            "turn_id": "turn_stage_3",
            "raw_text": "这家有券吗？",
            "top_intent": "local_life",
            "workflow_name": "clarification_fallback",
            "response_mode": "clarify",
            "task_type": "coupon_query",
            "semantic_frame": {"task_type": "coupon_query", "llm_called": True},
            "answer_plan": {"answer_type": "clarification", "uncertainty_notes": ["需要补充店名"]},
            "verifier_result": "pass",
            "answer_source": "clarification_fallback_workflow",
            "fallback_reason": "missing_required_slot",
            "final_response": "请说明要查询哪家店。",
            "preview_text": "请说明要查询哪家店。",
            "response_directive": {
                "answer_text": "请说明要查询哪家店。",
                "preview_text": "请说明要查询哪家店。",
                "final_response": "请说明要查询哪家店。",
                "answer_source": "clarification_fallback_workflow",
            },
            "event_log": [
                {"node": "answer_verify", "stage": "answer_verify", "status": "success", "duration_ms": 1},
                {"node": "clarify_response", "stage": "clarify_response", "status": "success", "duration_ms": 1},
                {"node": "final_response_build", "stage": "final_response_build", "status": "success", "duration_ms": 1},
            ],
        },
        user_text="这家有券吗？",
        total_duration_ms=5,
    )

    decision_span = next(span for span in trace.stage_spans if span.span_name == "decision_span")
    response_span = next(span for span in trace.stage_spans if span.span_name == "response_span")
    assert decision_span.decision == "pass"
    assert response_span.output_snapshot["answer_source"] == "clarification_fallback_workflow"
    assert response_span.output_snapshot["final_response"] == "请说明要查询哪家店。"
