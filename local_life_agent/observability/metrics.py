"""Metrics helpers for observability and eval aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from time import time
from typing import Any

from .trace import TurnTrace


@dataclass
class ToolCallMetricRecord:
    tool_name: str
    duration_ms: float
    success: bool
    timestamp_ms: float = field(default_factory=lambda: time() * 1000.0)


@dataclass
class TurnMetricRecord:
    trace_id: str
    total_duration_ms: float
    timestamp_ms: float = field(default_factory=lambda: time() * 1000.0)


_METRIC_LOCK = Lock()
_TOOL_CALL_METRICS: list[ToolCallMetricRecord] = []
_TURN_METRICS: list[TurnMetricRecord] = []


def record_tool_call_metric(tool_name: str, duration_ms: float, success: bool) -> None:
    """Record a single tool call metric."""
    if not tool_name:
        return
    record = ToolCallMetricRecord(
        tool_name=tool_name,
        duration_ms=float(duration_ms),
        success=bool(success),
    )
    with _METRIC_LOCK:
        _TOOL_CALL_METRICS.append(record)


def record_turn_metric(trace_id: str, total_duration_ms: float) -> None:
    """Record per-turn metrics."""
    if not trace_id:
        return
    record = TurnMetricRecord(
        trace_id=trace_id,
        total_duration_ms=float(total_duration_ms),
    )
    with _METRIC_LOCK:
        _TURN_METRICS.append(record)


def get_tool_call_metrics() -> list[ToolCallMetricRecord]:
    with _METRIC_LOCK:
        return list(_TOOL_CALL_METRICS)


def get_turn_metrics() -> list[TurnMetricRecord]:
    with _METRIC_LOCK:
        return list(_TURN_METRICS)


def reset_metrics() -> None:
    with _METRIC_LOCK:
        _TOOL_CALL_METRICS.clear()
        _TURN_METRICS.clear()


def aggregate_turn_trace_metrics(turn_traces: list[TurnTrace]) -> dict[str, Any]:
    total = len(turn_traces)
    if total == 0:
        return {
            "total_cases": 0,
            "top_intent_accuracy": None,
            "task_type_accuracy": None,
            "flow_accuracy": None,
            "semantic_source_real_llm_rate": 0.0,
            "fallback_rules_rate": 0.0,
            "shop_resolve_success_rate": 0.0,
            "ambiguous_rate": 0.0,
            "not_found_rate": 0.0,
            "reference_resolution_semantic_frame_rate": 0.0,
            "raw_text_fallback_rate": 0.0,
            "candidate_decision_generated_rate": 0.0,
            "candidate_count_avg": 0.0,
            "recommendation_success_rate": 0.0,
            "comparison_success_rate": 0.0,
            "llm_verbalizer_rate": 0.0,
            "template_fallback_rate": 0.0,
            "answer_verify_pass_rate": 0.0,
            "rewrite_rate": 0.0,
            "rewrite_success_rate": 0.0,
            "fallback_rate": 0.0,
            "unknown_as_false_violation_count": 0,
            "ranking_changed_violation_count": 0,
            "hallucinated_shop_violation_count": 0,
            "total_duration_ms": 0.0,
            "llm_duration_ms": 0.0,
            "tool_duration_ms": 0.0,
            "verifier_duration_ms": 0.0,
        }

    recommendation_cases = [trace for trace in turn_traces if trace.task_type == "recommendation"]
    comparison_cases = [trace for trace in turn_traces if trace.task_type == "comparison"]
    rewrite_cases = [trace for trace in turn_traces if trace.rewrite_count > 0]

    def _rate(count: int, denominator: int = total) -> float:
        if denominator <= 0:
            return 0.0
        return round(count / denominator, 4)

    violations = [item for trace in turn_traces for item in trace.answer_verify_violations]
    return {
        "total_cases": total,
        "top_intent_accuracy": None,
        "task_type_accuracy": None,
        "flow_accuracy": None,
        "semantic_source_real_llm_rate": _rate(sum(1 for trace in turn_traces if (trace.semantic_source or "").endswith("real_llm") or (trace.semantic_source or "").startswith("spy"))),
        "fallback_rules_rate": _rate(sum(1 for trace in turn_traces if trace.semantic_source == "fallback_rules")),
        "shop_resolve_success_rate": _rate(sum(1 for trace in turn_traces if trace.target_status == "RESOLVED")),
        "ambiguous_rate": _rate(sum(1 for trace in turn_traces if trace.target_status in {"AMBIGUOUS", "LOW_CONFIDENCE"})),
        "not_found_rate": _rate(sum(1 for trace in turn_traces if trace.target_status == "NOT_FOUND")),
        "reference_resolution_semantic_frame_rate": _rate(sum(1 for trace in turn_traces if trace.reference_resolution_source == "semantic_frame")),
        "raw_text_fallback_rate": _rate(sum(1 for trace in turn_traces if trace.reference_resolution_source == "raw_text_fallback")),
        "candidate_decision_generated_rate": _rate(sum(1 for trace in turn_traces if bool(trace.decision_type))),
        "candidate_count_avg": round(sum(trace.candidate_count for trace in turn_traces) / total, 4),
        "recommendation_success_rate": _rate(sum(1 for trace in recommendation_cases if (trace.answer_source or "") != "template_fallback"), len(recommendation_cases)) if recommendation_cases else 0.0,
        "comparison_success_rate": _rate(sum(1 for trace in comparison_cases if (trace.answer_source or "") != "template_fallback"), len(comparison_cases)) if comparison_cases else 0.0,
        "llm_verbalizer_rate": _rate(sum(1 for trace in turn_traces if (trace.answer_source or "").startswith("llm_verbalizer"))),
        "template_fallback_rate": _rate(sum(1 for trace in turn_traces if trace.answer_source == "template_fallback")),
        "answer_verify_pass_rate": _rate(sum(1 for trace in turn_traces if trace.answer_verify_passed is True)),
        "rewrite_rate": _rate(len(rewrite_cases)),
        "rewrite_success_rate": _rate(sum(1 for trace in rewrite_cases if trace.answer_verify_passed is True), len(rewrite_cases)) if rewrite_cases else 0.0,
        "fallback_rate": _rate(sum(1 for trace in turn_traces if trace.final_safety_status == "fallback" or trace.answer_source == "template_fallback")),
        "unknown_as_false_violation_count": sum(1 for item in violations if "unknown_as_false" in item or "unknown_claimed_as_empty_or_available" in item),
        "ranking_changed_violation_count": sum(1 for item in violations if "ranking_changed" in item),
        "hallucinated_shop_violation_count": sum(1 for item in violations if "hallucinated_shop" in item or "shop_mismatch" in item),
        "total_duration_ms": round(sum(trace.total_duration_ms or 0 for trace in turn_traces), 2),
        "llm_duration_ms": round(sum(trace.llm_duration_ms for trace in turn_traces), 2),
        "tool_duration_ms": round(sum(trace.tool_duration_ms for trace in turn_traces), 2),
        "verifier_duration_ms": round(sum(trace.verifier_duration_ms for trace in turn_traces), 2),
    }


def merge_eval_metrics(
    trace_metrics: dict[str, Any],
    *,
    total_cases: int,
    passed: int,
    failed: int,
    skipped: int,
    category_stats: dict[str, dict[str, int]],
) -> dict[str, Any]:
    pass_rate = 0.0 if total_cases - skipped <= 0 else round(passed / max(total_cases - skipped, 1), 4)
    payload = dict(trace_metrics)
    payload.update(
        {
            "total_cases": total_cases,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": pass_rate,
            "category_pass_rate": {
                name: (
                    0.0
                    if stats["total"] - stats["skipped"] <= 0
                    else round(stats["passed"] / max(stats["total"] - stats["skipped"], 1), 4)
                )
                for name, stats in category_stats.items()
            },
        }
    )
    return payload


def metric_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in metrics.items():
        rows.append({"metric": key, "value": value})
    return rows


def turn_metric_to_dict(record: TurnMetricRecord) -> dict[str, Any]:
    return asdict(record)
