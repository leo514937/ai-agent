from __future__ import annotations

from types import SimpleNamespace

import pytest

from ..agent import run_agent_graph
from ..observability.eval_runner import run_eval
from ..observability.metrics import get_tool_call_metrics, get_turn_metrics, reset_metrics
from ..observability.trace import get_trace_spans, new_trace_id, record_span, reset_trace_store
from ..tools.gateway import dispatch_tool_call


def test_trace_store_records_and_resets_spans():
    reset_trace_store()

    trace_id = new_trace_id()
    record_span(trace_id, "node_a", {"step": 1})
    record_span(trace_id, "node_b", {"step": 2})

    spans = get_trace_spans(trace_id)
    assert [span.span_name for span in spans] == ["node_a", "node_b"]
    assert spans[0].metadata["step"] == 1

    reset_trace_store()
    assert get_trace_spans(trace_id) == []


def test_dispatch_tool_call_records_tool_metric():
    reset_metrics()

    result = dispatch_tool_call("get_shop_detail", {"shop_id": "shop_sc_05"})

    assert result["success"] is True
    metrics = get_tool_call_metrics()
    assert metrics, "expected at least one tool metric"
    latest = metrics[-1]
    assert latest.tool_name == "get_shop_detail"
    assert latest.success is True
    assert latest.duration_ms >= 0


def test_run_agent_graph_records_turn_metric(monkeypatch: pytest.MonkeyPatch):
    reset_metrics()

    class FakeGraph:
        def invoke(self, initial, config=None):
            return {
                "final_response": "ok",
                "trace_id": initial["trace_id"],
                "session_id": initial["session_id"],
                "event_log": [],
                "semantic_frame": {},
                "execution_plan": {},
                "tool_result_set": {},
                "evidence_pack": {},
                "session_state_before": {},
                "session_state_after": {},
                "state_update_plan": {},
                "answer_source": "template",
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

    response = run_agent_graph("hello", session_id="session_metric")

    assert response.trace_id
    metrics = get_turn_metrics()
    assert metrics, "expected at least one turn metric"
    latest = metrics[-1]
    assert latest.trace_id == response.trace_id
    assert latest.total_duration_ms >= 0


def test_run_eval_reports_case_status(monkeypatch: pytest.MonkeyPatch):
    class FakeDebug:
        semantic_frame = {
            "task_type": "recommendation",
            "facets": [{"name": "口味"}],
            "shop_id": "shop_sc_05",
        }
        evidence_pack = {
            "ranking_snapshot": {"ranked": [{"shop_id": "shop_sc_05"}]},
            "requested_facets": ["口味"],
        }
        session_state_before = {"current_shop": {"shop_id": "shop_sc_05"}}
        session_state_after = {"current_shop": {"shop_id": "shop_sc_05"}}
        answer_source = "template"

    class FakeResponse:
        answer_text = "川味轩"
        trace_id = "trace_eval"
        session_id = "case_eval"
        debug = FakeDebug()

    monkeypatch.setattr("local_life_agent.observability.eval_runner.run_agent_graph", lambda *args, **kwargs: FakeResponse())

    report = run_eval(
        [
            {
                "case_id": "case_1",
                "query": "附近推荐火锅",
                "turns": ["附近推荐火锅"],
                "expected_route": "recommendation",
                "expected_rag_mode": "recommendation_rag",
                "expected_shop_id": "shop_sc_05",
                "expected_facets": ["口味"],
                "expected_keywords": ["川味轩"],
            }
        ]
    )

    assert report["summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert report["cases"][0]["passed"] is True
