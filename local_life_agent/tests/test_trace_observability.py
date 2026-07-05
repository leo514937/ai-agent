from __future__ import annotations

from local_life_agent.agent import _audit_turn_completeness, DebugInfo, run_agent_graph
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
                "semantic_frame": {
                    "top_intent": "local_life",
                    "task_type": "recommendation",
                    "grounding_status": "grounded",
                    "missing_slot_type": "",
                },
                "schema_validation_result": {"valid": True},
                "router_policy_decision": {"workflow_name": "discovery_decision", "decision": "proceed"},
                "router_policy_conflicts": ["keyword_vs_semantic"],
                "target_resolution": {"status": "RESOLVED", "reason": "resolved_by_target_resolve"},
                "target_resolution_status": "RESOLVED",
                "resolved_target": {"status": "RESOLVED", "shop_name": "海底捞西直门店"},
                "comparison_target_resolution": {"status": "RESOLVED", "targets": [{"shop_name": "A"}, {"shop_name": "B"}]},
                "grounding_result": {"status": "RESOLVED"},
                "grounding_status": "grounded",
                "missing_slot_type": "",
                "pending_clarification": None,
                "execution_plan": {"tool_calls": [{"call_id": "call_1"}]},
                "tool_result_set": {},
                "evidence_pack": {"ranking_snapshot": {"ranked": [{"shop_id": "shop_1"}]}},
                "evidence_status": "grounded",
                "evidence_review_result": {"next_action": "pass", "supported": True},
                "answer_verify_result": {"status": "pass", "supported": True},
                "unsupported_reasons": ["none"],
                "unknown_fields": ["coupon"],
                "failed_tools": ["tool_1"],
                "partial_fields": ["distance"],
                "comparison_support_status": "supported",
                "ranking_preserved": True,
                "session_state_before": {},
                "session_state_after": {},
                "state_update_plan": {"set_fields": {"current_shop": {"shop_name": "海底捞西直门店"}}},
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
                "workflow_candidate_reason": "semantic_frame:explicit_shop",
                "session_state_before": {
                    "current_shop": {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"},
                    "last_task_type": "single_shop_query",
                    "active_constraints": {"location": "北京邮电大学附近"},
                },
                "conversation_continuity": {"previous_focus": "海底捞西直门店", "is_follow_up": True},
            }

    monkeypatch.setattr("local_life_agent.engine.graph_builder.build_graph", lambda: FakeGraph())
    monkeypatch.setattr("local_life_agent.agent._GRAPH_CACHE", None, raising=False)

    response = run_agent_graph("附近推荐火锅", session_id="trace_case")

    assert response.debug is not None
    assert response.debug.turn_trace["trace_id"] == response.trace_id
    assert response.debug.turn_trace["task_type"] == "recommendation"
    assert response.debug.turn_trace["tool_call_count"] == 1
    assert response.debug.turn_trace["legacy_used"] is False
    assert response.debug.turn_trace["fallback_used"] is False
    assert response.debug.turn_trace["semantic_frame"]["grounding_status"] == "grounded"
    assert response.debug.turn_trace["schema_validation_result"]["valid"] is True
    assert response.debug.turn_trace["router_policy_decision"]["workflow_name"] == "discovery_decision"
    assert response.debug.turn_trace["router_policy_conflicts"] == ["keyword_vs_semantic"]
    assert response.debug.turn_trace["target_resolution_status"] == "RESOLVED"
    assert response.debug.turn_trace["resolved_target"]["shop_name"] == "海底捞西直门店"
    assert response.debug.turn_trace["comparison_target_resolution"]["status"] == "RESOLVED"
    assert response.debug.turn_trace["grounding_result"]["status"] == "RESOLVED"
    assert response.debug.turn_trace["grounding_status"] == "grounded"
    assert response.debug.turn_trace["missing_slot_type"] is None
    assert response.debug.turn_trace["evidence_status"] == "grounded"
    assert response.debug.turn_trace["evidence_review_result"]["next_action"] == "pass"
    assert response.debug.turn_trace["answer_verify_result"]["status"] == "pass"
    assert response.debug.turn_trace["unsupported_reasons"] == ["none"]
    assert response.debug.turn_trace["unknown_fields"] == ["coupon"]
    assert response.debug.turn_trace["failed_tools"] == ["tool_1"]
    assert response.debug.turn_trace["partial_fields"] == ["distance"]
    assert response.debug.turn_trace["comparison_support_status"] == "supported"
    assert response.debug.turn_trace["ranking_preserved"] is True
    assert response.debug.turn_trace["state_update_plan"]["set_fields"]["current_shop"]["shop_name"] == "海底捞西直门店"
    assert response.debug.turn_trace["conversation_continuity"]["previous_focus"] == "海底捞(牡丹园店)"
    assert response.debug.turn_trace["workflow_candidate_reason"] == "semantic_frame:explicit_shop"


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
            "top_intent_source": "llm",
            "top_intent_router_llm_available": True,
            "top_intent_router_backend": "real_llm",
            "top_intent_router_error_type": "",
            "top_intent_router_error_message": "",
            "semantic_frame": {"top_intent": "local_life", "task_type": "comparison", "primary_task": "comparison"},
            "execution_plan": {"tool_calls": [{"call_id": "a"}, {"call_id": "b"}]},
            "evidence_pack": {"comparison_matrix": {"rows": [{"shop_id": "1"}, {"shop_id": "2"}]}},
            "resolved_target": {"status": "RESOLVED", "reason": "comparison_targets_resolved"},
            "answer_source": "fallback",
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
    assert trace.top_intent_source == "llm"
    assert trace.top_intent_router_llm_available is True
    assert trace.top_intent_router_backend == "real_llm"


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


def test_turn_audit_reports_missing_nodes_and_failed_tools():
    audit = _audit_turn_completeness(
        {
            "top_intent": "local_life",
            "event_log": [
                {"node": "intake_guard_router"},
                {"node": "planning_subgraph"},
                {"node": "response_subgraph"},
            ],
            "tool_result_set": {
                "call_1": {"result_status": "ok"},
                "call_2": {"result_status": "failed"},
            },
            "final_response": "ok",
            "answer_source": "llm_verbalizer",
            "planning_llm_called": True,
        }
    )

    assert audit["llm_called"] is True
    assert audit["tool_call_count"] == 2
    assert audit["failed_tool_calls"] == ["call_2"]
    assert "understanding_subgraph" in audit["missing_nodes"]
    assert "orchestration_router_shadow" in audit["missing_nodes"]
    assert "workflow_runner" in audit["missing_nodes"]
    assert "execution_review_subgraph" in audit["missing_nodes"]


def test_build_turn_trace_marks_planning_and_execution_boundaries():
    trace = build_turn_trace(
        {
            "trace_id": "trace_boundary",
            "session_id": "session_boundary",
            "turn_id": "turn_boundary",
            "raw_text": "川味轩(知春路店)有券吗，顺便看现在营业吗，远不远？",
            "task_type": "single_shop_query",
            "event_log": [
                {"node": "planning_subgraph", "stage": "planning_started", "status": "success", "duration_ms": 1},
                {"node": "planning_subgraph", "stage": "planning_finished", "status": "success", "duration_ms": 2},
                {"node": "execution_review_subgraph", "stage": "execution_started", "status": "success", "duration_ms": 3},
                {"node": "execution_review_subgraph", "stage": "execution_finished", "status": "success", "duration_ms": 4},
            ],
            "execution_plan": {"tool_calls": [{"call_id": "call_coupon"}, {"call_id": "call_open"}]},
            "tool_result_set": {
                "call_coupon": {"result_status": "ok"},
                "call_open": {"result_status": "ok"},
            },
            "target_resolution_status": "RESOLVED",
            "target_resolution": {"status": "RESOLVED"},
            "resolved_target": {"status": "RESOLVED"},
            "evidence_status": "grounded",
            "evidence_review_result": {"status": "ok"},
        },
        user_text="川味轩(知春路店)有券吗，顺便看现在营业吗，远不远？",
        total_duration_ms=10,
    )

    stages = {event.stage for event in trace.events}
    assert {"planning_started", "planning_finished", "execution_started", "execution_finished"} <= stages
    assert trace.tool_call_count == 2
