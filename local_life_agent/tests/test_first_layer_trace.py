from __future__ import annotations

from local_life_agent.observability.trace import build_turn_trace


def test_stage_trace_spans_cover_intake_to_response():
    trace = build_turn_trace(
        {
            "trace_id": "trace_stage_1",
            "session_id": "session_stage_1",
            "turn_id": "turn_stage_1",
            "raw_text": "海底捞(牡丹园店)有券吗？",
            "normalized_text": "海底捞(牡丹园店)有券吗？",
            "input_type": "text",
            "top_intent": "local_life",
            "workflow_name": "single_shop_fact_workflow",
            "response_mode": "answer",
            "task_type": "single_shop_query",
            "semantic_frame": {"task_type": "single_shop_query", "llm_called": True},
            "router_policy_decision": {"decision": "proceed", "workflow_name": "single_shop_fact_workflow"},
            "execution_plan": {"tool_calls": [{"call_id": "call_coupon", "tool_name": "get_coupon_list"}]},
            "tool_results": {"call_coupon": {"tool_name": "get_coupon_list", "result_status": "ok"}},
            "evidence_pack": {"claims": [{"text": "海底捞当前有券"}]},
            "answer_plan": {"answer_type": "single_shop", "uncertainty_notes": []},
            "response_directive": {
                "answer_text": "海底捞当前有券。",
                "preview_text": "海底捞当前有券。",
                "final_response": "海底捞当前有券。",
                "answer_source": "llm_verbalizer",
            },
            "answer_source": "llm_verbalizer",
            "final_response": "海底捞当前有券。",
            "preview_text": "海底捞当前有券。",
            "event_log": [
                {"node": "receive_input", "stage": "receive_input", "status": "success", "duration_ms": 1},
                {"node": "top_intent_router", "stage": "top_intent_router", "status": "success", "duration_ms": 1},
                {"node": "semantic_parse", "stage": "semantic_parse", "status": "success", "duration_ms": 1},
                {"node": "planning_subgraph", "stage": "planning_subgraph", "status": "success", "duration_ms": 1},
                {"node": "tool_execute", "stage": "tool_execute", "status": "success", "duration_ms": 1},
                {"node": "evidence_build", "stage": "evidence_build", "status": "success", "duration_ms": 1},
                {"node": "answer_verify", "stage": "answer_verify", "status": "success", "duration_ms": 1},
                {"node": "final_response_build", "stage": "final_response_build", "status": "success", "duration_ms": 1},
            ],
        },
        user_text="海底捞(牡丹园店)有券吗？",
        total_duration_ms=12,
    )

    stage_names = [span.span_name for span in trace.stage_spans]
    assert stage_names == [
        "intake_span",
        "routing_span",
        "understanding_span",
        "planning_span",
        "execution_span",
        "evidence_span",
        "decision_span",
        "response_span",
    ]
    assert trace.stage_spans[0].input_snapshot["raw_text"] == "海底捞(牡丹园店)有券吗？"
    assert trace.stage_spans[-1].output_snapshot["answer_source"] == "llm_verbalizer"
    assert trace.stage_spans[-1].decision == "llm_verbalizer"
    assert all(span.latency_ms is not None for span in trace.stage_spans)
