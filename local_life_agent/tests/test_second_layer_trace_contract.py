from __future__ import annotations

from local_life_agent.observability.trace import build_turn_trace, validate_turn_trace


def test_second_layer_trace_contract_contains_planning_execution_evidence():
    trace = build_turn_trace(
        {
            "trace_id": "trace_stage_2",
            "session_id": "session_stage_2",
            "turn_id": "turn_stage_2",
            "raw_text": "海底捞和川味轩哪个好？",
            "top_intent": "local_life",
            "workflow_name": "comparison_decision_workflow",
            "response_mode": "comparison",
            "task_type": "comparison",
            "semantic_frame": {"task_type": "comparison", "llm_called": True},
            "router_policy_decision": {"decision": "proceed", "workflow_name": "comparison_decision_workflow"},
            "execution_plan": {"tool_calls": [{"call_id": "call_1"}, {"call_id": "call_2"}]},
            "tool_results": {"call_1": {"tool_name": "get_shop_detail", "result_status": "ok"}, "call_2": {"tool_name": "get_shop_detail", "result_status": "ok"}},
            "evidence_pack": {"comparison_matrix": {"rows": [{"shop_id": "1"}, {"shop_id": "2"}]}},
            "answer_plan": {"answer_type": "comparison", "uncertainty_notes": []},
            "answer_source": "llm_verbalizer",
            "final_response": "海底捞更适合你。",
            "preview_text": "海底捞更适合你。",
            "response_directive": {
                "answer_text": "海底捞更适合你。",
                "preview_text": "海底捞更适合你。",
                "final_response": "海底捞更适合你。",
                "answer_source": "llm_verbalizer",
            },
            "event_log": [
                {"node": "planning_subgraph", "stage": "planning_subgraph", "status": "success", "duration_ms": 2},
                {"node": "tool_execute", "stage": "tool_execute", "status": "success", "duration_ms": 3},
                {"node": "evidence_build", "stage": "evidence_build", "status": "success", "duration_ms": 2},
                {"node": "answer_verify", "stage": "answer_verify", "status": "success", "duration_ms": 1},
                {"node": "final_response_build", "stage": "final_response_build", "status": "success", "duration_ms": 1},
            ],
        },
        user_text="海底捞和川味轩哪个好？",
        total_duration_ms=9,
    )

    validated = validate_turn_trace(trace)
    assert validated.stage_spans
    assert validated.stage_spans[3]["stage"] == "planning_span"
    assert validated.stage_spans[4]["stage"] == "execution_span"
    assert validated.stage_spans[5]["stage"] == "evidence_span"
    assert validated.stage_spans[6]["stage"] == "decision_span"
    assert validated.stage_spans[7]["stage"] == "response_span"
