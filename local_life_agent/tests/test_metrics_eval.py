from __future__ import annotations

from local_life_agent.observability.metrics import aggregate_turn_trace_metrics, merge_eval_metrics
from local_life_agent.observability.trace import TurnTrace


def test_aggregate_turn_trace_metrics_counts_core_rates():
    traces = [
        TurnTrace(
            trace_id="t1",
            task_type="recommendation",
            semantic_source="fallback_rules",
            reference_resolution_source="raw_text_fallback",
            candidate_count=3,
            decision_type="recommendation",
            answer_source="llm_verbalizer",
            answer_verify_passed=True,
            rewrite_count=0,
            final_safety_status="safe",
            tool_call_count=2,
        ),
        TurnTrace(
            trace_id="t2",
            task_type="comparison",
            semantic_source="spy_real_llm",
            target_status="RESOLVED",
            reference_resolution_source="semantic_frame",
            candidate_count=2,
            decision_type="comparison",
            answer_source="fallback",
            answer_verify_passed=False,
            answer_verify_violations=["ranking_changed"],
            rewrite_count=1,
            final_safety_status="fallback",
            tool_call_count=3,
        ),
    ]

    metrics = aggregate_turn_trace_metrics(traces)

    assert metrics["fallback_rate"] == 0.5
    assert metrics["rewrite_rate"] == 0.5
    assert metrics["answer_verify_pass_rate"] == 0.5
    assert metrics["raw_text_fallback_rate"] == 0.5
    assert metrics["llm_verbalizer_rate"] == 0.5
    assert metrics["ranking_changed_violation_count"] == 1


def test_aggregate_turn_trace_metrics_handles_empty_input():
    metrics = aggregate_turn_trace_metrics([])
    assert metrics["total_cases"] == 0
    assert metrics["fallback_rate"] == 0.0


def test_merge_eval_metrics_excludes_skipped_from_pass_rate():
    merged = merge_eval_metrics(
        {"fallback_rate": 0.5, "rewrite_rate": 0.5, "template_fallback_rate": 0.0, "raw_text_fallback_rate": 0.0},
        total_cases=3,
        passed=1,
        failed=1,
        skipped=1,
        category_stats={"core": {"total": 3, "passed": 1, "failed": 1, "skipped": 1}},
    )
    assert merged["pass_rate"] == 0.5
    assert merged["category_pass_rate"]["core"] == 0.5
