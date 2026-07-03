from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

import pytest

from ..observability.metrics import aggregate_quality_metrics, build_turn_metrics
from ..observability.trace import build_turn_trace, record_span, reset_trace_store
from ..streaming.events import (
    StreamEventType,
    make_evidence_update,
    make_fallback,
    make_final,
    make_preview,
    make_status,
)


def _sample_final_state() -> dict[str, object]:
    return {
        "trace_id": "trace_p11_001",
        "session_id": "session_p11",
        "turn_id": "turn_p11",
        "raw_text": "附近推荐火锅",
        "workflow_name": "deterministic_tool_workflow",
        "route_task": "recommendation",
        "response_mode": "final",
        "task_type": "recommendation",
        "facets": ["口味", "距离"],
        "semantic_frame": {
            "task_type": "recommendation",
            "facets": [{"name": "口味"}],
        },
        "execution_plan": {
            "tool_calls": [{"call_id": "call_1"}, {"call_id": "call_2", "blocked": True}],
            "facet_candidates": [{"name": "口味"}, {"name": "距离"}],
            "facet_validation_result": {
                "accepted_facets": ["口味"],
                "rejected_facets": ["随机项"],
                "unsupported_facets": ["current_shop"],
            },
            "blocked_tool_calls": [{"call_id": "call_2", "reason": "budget"}],
            "unsupported_facets": ["current_shop"],
            "facet_budget_plan": {"budget_exceeded": True},
            "stages": [
                {"stage_id": "stage_1", "max_parallelism": 2},
                {"stage_id": "stage_2", "max_parallelism": 3},
            ],
        },
        "answer_plan": {"facets": ["口味", "距离"]},
        "evidence_pack": {
            "evidence_items": [{"evidence_id": "e1"}, {"evidence_id": "e2"}],
            "answerable_facets": ["口味"],
            "unknown_facets": ["距离"],
            "failed_facets": ["current_shop"],
            "evidence_cache_hit": True,
        },
        "review_results": {"evidence_review": {"next_action": "retry"}},
        "state_update_plan": {
            "set_fields": {"comparison_targets": [{"shop_id": "shop_1"}]},
            "clear_fields": ["pending_clarification"],
        },
        "answer_verify_passed": True,
        "fallback_reason": "",
        "final_safety_status": "safe",
        "event_log": [],
    }


def test_p11_one_turn_has_single_trace():
    reset_trace_store()
    trace_id = "trace_p11_single"
    record_span(trace_id, "workflow_runner", {"workflow_name": "deterministic_tool_workflow", "stage": "router"})
    record_span(trace_id, "planning_subgraph", {"workflow_name": "deterministic_tool_workflow", "stage": "planning"})
    record_span(trace_id, "evidence_review", {"workflow_name": "deterministic_tool_workflow", "stage": "evidence_review"})
    record_span(trace_id, "answer_verify", {"workflow_name": "deterministic_tool_workflow", "stage": "answer_verify"})
    record_span(trace_id, "state_update_plan", {"workflow_name": "deterministic_tool_workflow", "stage": "state_update"})
    record_span(trace_id, "emit_response", {"workflow_name": "deterministic_tool_workflow", "stage": "streaming"})

    final_state = _sample_final_state()
    final_state["trace_id"] = trace_id
    trace = build_turn_trace(final_state, user_text="附近推荐火锅", total_duration_ms=123)

    assert trace.trace_id == trace_id
    assert trace.workflow_name == "recommendation_flow"
    assert trace.route_task == "recommendation"
    assert trace.response_mode == "recommendation_flow"
    assert len({span.trace_id for span in trace.spans}) == 1
    assert {span.span_name for span in trace.spans} >= {"router", "planning", "evidence_review", "answer_verify", "state_update", "streaming"}
    assert trace.metrics["workflow_name"] == "deterministic_tool_workflow"
    assert trace.metrics["route_task"] == "recommendation"
    assert trace.errors == []


def test_p11_trace_records_core_spans():
    reset_trace_store()
    trace_id = "trace_p11_spans"
    for span_name, stage in [
        ("workflow_runner", "router"),
        ("planning_subgraph", "planning"),
        ("evidence_review", "evidence_review"),
        ("answer_verify", "answer_verify"),
        ("state_update_plan", "state_update"),
        ("emit_response", "streaming"),
    ]:
        record_span(trace_id, span_name, {"workflow_name": "comparison_flow", "stage": stage})

    trace = build_turn_trace({"trace_id": trace_id, "workflow_name": "comparison_flow", "task_type": "comparison", "event_log": []})

    span_names = {span.span_name for span in trace.spans}
    assert {"router", "planning", "evidence_review", "answer_verify", "state_update", "streaming"}.issubset(span_names)
    assert len(trace.spans) == 6


def test_p11_turn_metrics_derived_without_changing_state():
    final_state = _sample_final_state()
    before = deepcopy(final_state)
    stream_events = [
        make_status("trace_p11_001", "session_p11", "turn_p11", "running", stage="planning"),
        make_preview("trace_p11_001", "session_p11", "turn_p11", "先给你一个预览", workflow_name="deterministic_tool_workflow"),
        make_evidence_update("trace_p11_001", "session_p11", "turn_p11", summary="补充了 2 条证据"),
    ]

    metrics = build_turn_metrics(final_state, total_duration_ms=456, stream_events=stream_events)

    assert final_state == before
    assert metrics.workflow_name == "deterministic_tool_workflow"
    assert metrics.route_task == "recommendation"
    assert metrics.facet_count == 3
    assert metrics.facet_candidates_count == 2
    assert metrics.accepted_facets_count == 1
    assert metrics.rejected_facets_count == 1
    assert metrics.unsupported_facets_count == 1
    assert metrics.tool_call_count == 2
    assert metrics.evidence_count == 2
    assert metrics.answerable_facets_count == 1
    assert metrics.unknown_facets_count == 1
    assert metrics.failed_facets_count == 1
    assert metrics.verification_status == "pass"
    assert metrics.state_write_count == 1
    assert metrics.blocked_state_write_count == 1
    assert metrics.preview_event_count == 1
    assert metrics.preview_block_count == 0
    assert metrics.stream_event_count == 3
    assert metrics.planner_selected_tool_call_count == 1
    assert metrics.planner_blocked_tool_call_count == 1
    assert metrics.planner_dropped_facet_count == 1
    assert metrics.budget_exceeded_count == 1
    assert metrics.cache_hit_count == 1
    assert metrics.cache_miss_count == 0
    assert metrics.batch_size == 2
    assert metrics.parallelism == 3


def test_p11_stream_events_carry_trace_id_and_single_final():
    trace_id = "trace_p11_events"
    status = make_status(trace_id, "session_p11", "turn_p11", "running", stage="planning", workflow_name="comparison_flow", span_id="span_status")
    preview = make_preview(trace_id, "session_p11", "turn_p11", "这是预览", workflow_name="comparison_flow", span_id="span_preview")
    evidence_update = make_evidence_update(trace_id, "session_p11", "turn_p11", summary="证据更新", workflow_name="comparison_flow", span_id="span_evidence")
    final = make_final(trace_id, "session_p11", "turn_p11", "这是最终答案", workflow_name="comparison_flow", span_id="span_final")
    fallback = make_fallback(trace_id, "session_p11", "turn_p11", "timeout", message="降级处理", workflow_name="comparison_flow", span_id="span_fallback")

    assert status.trace_id == trace_id
    assert status.partial is True
    assert preview.trace_id == trace_id
    assert preview.partial is True
    assert preview.verified is False
    assert evidence_update.partial is True
    assert final.partial is False
    assert final.verified is True
    assert fallback.partial is False
    assert fallback.verified is False
    assert final.event_type == StreamEventType.FINAL
    assert final.type == StreamEventType.FINAL
    assert final.payload["answer_text"] == "这是最终答案"
    assert final.span_id == "span_final"
    assert preview.span_id == "span_preview"


def test_p11_preview_never_counts_as_final():
    preview = make_preview("trace_preview", "session_preview", "turn_preview", "这里只是预览", verified=False)

    assert preview.event_type == StreamEventType.PREVIEW
    assert preview.partial is True
    assert preview.verified is False


def test_p11_no_multi_workflow_stream_merge():
    files = [
        Path("local_life_agent/engine/workflow_runner.py"),
        Path("local_life_agent/engine/graph_builder.py"),
        Path("local_life_agent/app.py"),
    ]
    forbidden = ["trace_A", "trace_B", "trace_merge", "workflow_names", "final_responses", "state_update_plans"]

    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert re.search(rf"\\b{token}\\b", text) is None, f"{token} should not appear in {path.as_posix()}"


@pytest.mark.parametrize("action", ["retry", "degrade", "fallback", "clarify", "expand_search"])
def test_p11_metrics_record_evidence_review_actions(action: str):
    final_state = _sample_final_state()
    final_state["review_results"] = {"evidence_review": {"next_action": action}}
    metrics = build_turn_metrics(final_state)

    assert metrics.evidence_review_action == action
    assert metrics.accepted_facets_count == 1
    assert metrics.rejected_facets_count == 1
    assert metrics.unsupported_facets_count == 1


def test_p11_metrics_record_planner_budget_and_capability():
    final_state = _sample_final_state()
    metrics = build_turn_metrics(final_state)

    assert metrics.facet_candidates_count == 2
    assert metrics.accepted_facets_count == 1
    assert metrics.rejected_facets_count == 1
    assert metrics.unsupported_facets_count == 1
    assert metrics.planner_selected_tool_call_count == 1
    assert metrics.planner_blocked_tool_call_count == 1
    assert metrics.planner_dropped_facet_count == 1
    assert metrics.budget_exceeded_count == 1


def test_p11_metrics_record_stream_preview_batch_and_cache():
    final_state = _sample_final_state()
    stream_events = [
        make_status("trace_metrics", "session_p11", "turn_p11", "running"),
        make_preview("trace_metrics", "session_p11", "turn_p11", "预览一"),
        make_preview("trace_metrics", "session_p11", "turn_p11", "预览二"),
        make_evidence_update("trace_metrics", "session_p11", "turn_p11", summary="证据刷新"),
    ]
    metrics = build_turn_metrics(final_state, stream_events=stream_events)

    assert metrics.stream_event_count == 4
    assert metrics.preview_event_count == 2
    assert metrics.preview_block_count == 0
    assert metrics.batch_size == 2
    assert metrics.parallelism == 3
    assert metrics.cache_hit_count == 1
    assert metrics.cache_miss_count == 0


def test_p11_observability_failure_does_not_break_main_flow(monkeypatch: pytest.MonkeyPatch):
    final_state = _sample_final_state()

    def broken_build_turn_metrics(*args, **kwargs):
        raise RuntimeError("metrics boom")

    monkeypatch.setattr("local_life_agent.observability.metrics.build_turn_metrics", broken_build_turn_metrics)

    trace = build_turn_trace(final_state)

    assert trace.trace_id == final_state["trace_id"]
    assert trace.metrics["error"] == "metrics boom"
    assert trace.errors == []


def test_p11_quality_metrics_aggregate_helper():
    good = build_turn_metrics(_sample_final_state())
    fallback_state = _sample_final_state()
    fallback_state["response_mode"] = "fallback"
    fallback_state["fallback_reason"] = "timeout"
    fallback_state["answer_verify_passed"] = False
    fallback_state["review_results"] = {"evidence_review": {"next_action": "expand_search"}}
    fallback = build_turn_metrics(fallback_state)

    summary = aggregate_quality_metrics([good, fallback])

    assert summary["answer_verify_pass_rate"] == 0.5
    assert summary["fallback_rate"] == 0.5
    assert summary["degrade_rate"] == 0.5
    assert summary["expand_search_action_rate"] == 0.5
