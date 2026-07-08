"""Metrics helpers for observability and eval aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from time import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class TurnMetrics(BaseModel):
    """P11 turn-level observability metrics."""

    model_config = ConfigDict(extra="forbid")

    workflow_name: str | None = None
    route_task: str | None = None
    response_mode: str | None = None
    facet_count: int = 0
    facets: list[str] = Field(default_factory=list)
    facet_candidates_count: int = 0
    accepted_facets_count: int = 0
    rejected_facets_count: int = 0
    unsupported_facets_count: int = 0
    tool_call_count: int = 0
    evidence_count: int = 0
    answerable_facets_count: int = 0
    unknown_facets_count: int = 0
    failed_facets_count: int = 0
    verification_status: str | None = None
    fallback_reason: str | None = None
    final_latency_ms: int | None = None
    state_write_count: int = 0
    blocked_state_write_count: int = 0
    preview_event_count: int = 0
    preview_block_count: int = 0
    stream_event_count: int = 0
    evidence_review_action: str | None = None
    planner_selected_tool_call_count: int = 0
    planner_blocked_tool_call_count: int = 0
    planner_dropped_facet_count: int = 0
    budget_exceeded_count: int = 0
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    tool_round_budget_remaining: int | None = None
    retry_budget_remaining: int | None = None
    expand_search_budget_remaining: int | None = None
    rewrite_budget_remaining: int | None = None
    facet_enrich_budget_remaining: int | None = None
    deadline_remaining_ms: int | None = None
    stale_evidence_count: int = 0
    cache_stale_count: int = 0
    cache_refresh_count: int = 0
    location_fingerprint_mismatch_count: int = 0
    freshness_unknown_count: int = 0
    batch_size: int = 0
    parallelism: int = 1

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


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


def build_turn_metrics(
    final_state: dict[str, Any],
    *,
    total_duration_ms: int | None = None,
    stream_events: list[dict[str, Any]] | list[Any] | None = None,
    trace: TurnTrace | None = None,
) -> TurnMetrics:
    """Derive P11 turn metrics without changing business state."""
    final_state = final_state or {}
    semantic_frame = _coerce_dict(final_state.get("semantic_frame"))
    evidence_pack = _coerce_dict(final_state.get("evidence_pack"))
    budget_context = _coerce_dict(final_state.get("budget_context"))
    execution_plan = _coerce_dict(final_state.get("execution_plan") or final_state.get("validated_plan"))
    answer_plan = _coerce_dict(final_state.get("answer_plan"))
    state_update_plan = _coerce_dict(final_state.get("state_update_plan"))
    tool_results = _coerce_dict(final_state.get("tool_result_set") or final_state.get("tool_results"))
    stream_events = list(stream_events or [])
    facets = _derive_facets(final_state, evidence_pack, answer_plan, semantic_frame)
    facet_validation_result = execution_plan.get("facet_validation_result") or {}
    answerable = _len_list(evidence_pack, "answerable_facets")
    unknown = _len_list(evidence_pack, "unknown_facets")
    failed = _len_list(evidence_pack, "failed_facets")
    preview_event_count = _count_preview_events(final_state, stream_events)
    preview_block_count = 0 if preview_event_count else (1 if _preview_blocked(final_state) else 0)
    stream_event_count = len(stream_events) or len(final_state.get("event_log", []) or [])
    state_write_count, blocked_state_write_count = _state_write_counts(state_update_plan, final_state)
    tool_call_count = _tool_call_count(execution_plan, tool_results)
    evidence_count = _evidence_count(evidence_pack)
    verification_status = _verification_status(final_state, trace)
    return TurnMetrics(
        workflow_name=_first_nonempty(
            final_state.get("workflow_name"),
            trace.workflow_name if trace is not None else "",
        ) or None,
        route_task=_first_nonempty(
            final_state.get("route_task"),
            final_state.get("task_type"),
            trace.route_task if trace is not None else "",
        ) or None,
        response_mode=_first_nonempty(
            final_state.get("response_mode"),
            trace.response_mode if trace is not None else "",
        ) or None,
        facet_count=len(facets),
        facets=facets,
        facet_candidates_count=_len_list(execution_plan, "facet_candidates"),
        accepted_facets_count=_len_list(facet_validation_result, "accepted_facets"),
        rejected_facets_count=_len_list(facet_validation_result, "rejected_facets"),
        unsupported_facets_count=_len_list(facet_validation_result, "unsupported_facets"),
        tool_call_count=tool_call_count,
        evidence_count=evidence_count,
        answerable_facets_count=answerable,
        unknown_facets_count=unknown,
        failed_facets_count=failed,
        verification_status=verification_status,
        fallback_reason=_first_nonempty(
            final_state.get("fallback_reason"),
            final_state.get("answer_fallback_reason"),
            trace.fallback_reason if trace is not None else "",
        ) or None,
        final_latency_ms=total_duration_ms,
        state_write_count=state_write_count,
        blocked_state_write_count=blocked_state_write_count,
        preview_event_count=preview_event_count,
        preview_block_count=preview_block_count,
        stream_event_count=stream_event_count,
        evidence_review_action=_evidence_review_action(final_state),
        planner_selected_tool_call_count=_planner_selected_tool_call_count(execution_plan),
        planner_blocked_tool_call_count=_planner_blocked_tool_call_count(execution_plan),
        planner_dropped_facet_count=_planner_dropped_facet_count(execution_plan),
        budget_exceeded_count=_bool_int(
            execution_plan.get("budget_exceeded")
            or (
                isinstance(execution_plan.get("facet_budget_plan"), dict)
                and (
                    execution_plan["facet_budget_plan"].get("budget_exceeded")
                    or execution_plan["facet_budget_plan"].get("exceeded")
                )
            )
        ),
        cache_hit_count=_bool_int(evidence_pack.get("evidence_cache_hit")),
        cache_miss_count=0 if evidence_pack.get("evidence_cache_hit") else (1 if evidence_pack else 0),
        tool_round_budget_remaining=_budget_remaining(budget_context, "tool_round_budget", evidence_pack, "tool_round_budget_remaining"),
        retry_budget_remaining=_budget_remaining(budget_context, "retry_budget", evidence_pack, "retry_budget_remaining"),
        expand_search_budget_remaining=_budget_remaining(budget_context, "expand_search_budget", evidence_pack, "expand_search_budget_remaining"),
        rewrite_budget_remaining=_budget_remaining(budget_context, "rewrite_budget", evidence_pack, "rewrite_budget_remaining"),
        facet_enrich_budget_remaining=_budget_remaining(budget_context, "facet_enrich_budget", evidence_pack, "facet_enrich_budget_remaining"),
        deadline_remaining_ms=_deadline_remaining_ms(budget_context, evidence_pack),
        stale_evidence_count=_count_metadata_flags(evidence_pack, "is_stale"),
        cache_stale_count=_count_metadata_flags(evidence_pack, "is_stale"),
        cache_refresh_count=_bool_int(evidence_pack.get("cache_refresh_count")),
        location_fingerprint_mismatch_count=_bool_int(evidence_pack.get("location_fingerprint_mismatch_count")),
        freshness_unknown_count=_bool_int(evidence_pack.get("freshness_unknown_count")),
        batch_size=_batch_size(execution_plan),
        parallelism=_parallelism(execution_plan),
    )


def aggregate_quality_metrics(turn_metrics: list[TurnMetrics]) -> dict[str, Any]:
    """Aggregate business quality rates across turns."""
    total = len(turn_metrics)
    if total == 0:
        return {
            "answer_verify_pass_rate": 0.0,
            "clarification_rate": 0.0,
            "tool_failure_rate": 0.0,
            "avg_facets_per_query": 0.0,
            "evidence_sufficiency_rate": 0.0,
            "state_write_block_rate": 0.0,
            "preview_block_rate": 0.0,
            "fallback_rate": 0.0,
            "degrade_rate": 0.0,
            "retry_action_rate": 0.0,
            "expand_search_action_rate": 0.0,
        }
    def _rate(count: int) -> float:
        return round(count / total, 4)
    return {
        "answer_verify_pass_rate": _rate(sum(1 for item in turn_metrics if item.verification_status == "pass")),
        "clarification_rate": _rate(sum(1 for item in turn_metrics if (item.response_mode or "") == "clarify")),
        "tool_failure_rate": _rate(sum(1 for item in turn_metrics if item.failed_facets_count > 0)),
        "avg_facets_per_query": round(sum(item.facet_count for item in turn_metrics) / total, 4),
        "evidence_sufficiency_rate": _rate(sum(1 for item in turn_metrics if item.answerable_facets_count > 0 and item.failed_facets_count == 0)),
        "state_write_block_rate": _rate(sum(1 for item in turn_metrics if item.blocked_state_write_count > 0)),
        "preview_block_rate": _rate(sum(1 for item in turn_metrics if item.preview_block_count > 0)),
        "fallback_rate": _rate(sum(1 for item in turn_metrics if bool(item.fallback_reason))),
        "degrade_rate": _rate(sum(1 for item in turn_metrics if (item.response_mode or "") == "fallback")),
        "retry_action_rate": _rate(sum(1 for item in turn_metrics if (item.evidence_review_action or "").lower() == "retry")),
        "expand_search_action_rate": _rate(sum(1 for item in turn_metrics if (item.evidence_review_action or "").lower() == "expand_search")),
    }


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
        "state_write_block_rate": 0.0,
        "preview_block_rate": 0.0,
        "tool_failure_rate": 0.0,
        "avg_facets_per_query": 0.0,
        "evidence_sufficiency_rate": 0.0,
        "degrade_rate": 0.0,
        "retry_action_rate": 0.0,
        "expand_search_action_rate": 0.0,
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
        "state_write_block_rate": _rate(sum(1 for trace in turn_traces if bool(trace.errors))),
        "preview_block_rate": _rate(sum(1 for trace in turn_traces if not bool(trace.answer_verify_passed) and (trace.answer_source or "") != "template_fallback")),
        "tool_failure_rate": _rate(sum(1 for trace in turn_traces if trace.evidence_incomplete)),
        "avg_facets_per_query": round(sum(len(trace.merchant_mentions or []) for trace in turn_traces) / total, 4),
        "evidence_sufficiency_rate": _rate(sum(1 for trace in turn_traces if trace.answer_verify_passed is True)),
        "degrade_rate": _rate(sum(1 for trace in turn_traces if trace.fallback_used or trace.template_fallback_used)),
        "retry_action_rate": _rate(sum(1 for trace in turn_traces if trace.rewrite_count > 0)),
        "expand_search_action_rate": _rate(sum(1 for trace in turn_traces if trace.ambiguous_candidate_count > 0)),
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


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _budget_remaining(
    budget_context: dict[str, Any],
    field: str,
    evidence_pack: dict[str, Any],
    legacy_field: str,
) -> int | None:
    if isinstance(budget_context, dict):
        value = budget_context.get(field)
        if isinstance(value, int):
            return value
    value = evidence_pack.get(legacy_field)
    if isinstance(value, int):
        return value
    return None


def _deadline_remaining_ms(budget_context: dict[str, Any], evidence_pack: dict[str, Any]) -> int | None:
    if isinstance(budget_context, dict):
        value = budget_context.get("deadline_remaining_ms")
        if isinstance(value, int):
            return value
    value = evidence_pack.get("deadline_remaining_ms")
    if isinstance(value, int):
        return value
    return None


def _count_metadata_flags(evidence_pack: dict[str, Any], key: str) -> int:
    count = 0
    for item in evidence_pack.get("evidence_items") or []:
        if isinstance(item, dict) and bool(item.get(key, False)):
            count += 1
    return count


def _count_preview_events(final_state: dict[str, Any], stream_events: list[Any]) -> int:
    count = 0
    for item in stream_events:
        if isinstance(item, dict):
            event_type = str(item.get("event_type") or item.get("type") or "").lower()
            stage = str(item.get("stage") or "").lower()
            if event_type == "preview" or stage == "preview":
                count += 1
        else:
            event_type = str(getattr(item, "event_type", "") or getattr(item, "type", "") or "").lower()
            stage = str(getattr(item, "stage", "") or "").lower()
            if event_type == "preview" or stage == "preview":
                count += 1
    if count == 0:
        for item in final_state.get("event_log", []) or []:
            if not isinstance(item, dict):
                continue
            event_type = str(item.get("event_type") or item.get("type") or "").lower()
            stage = str(item.get("stage") or item.get("node") or "").lower()
            if event_type == "preview" or stage == "preview":
                count += 1
    return count


def _state_write_counts(state_update_plan: dict[str, Any], final_state: dict[str, Any]) -> tuple[int, int]:
    if not isinstance(state_update_plan, dict):
        return 0, 0
    set_fields = state_update_plan.get("set_fields") or state_update_plan.get("writes") or []
    clear_fields = state_update_plan.get("clear_fields") or state_update_plan.get("blocked_writes") or []
    state_write_count = len(set_fields) if isinstance(set_fields, list) else len(set_fields or {})
    blocked_count = len(clear_fields) if isinstance(clear_fields, list) else len(clear_fields or {})
    if state_update_plan.get("blocked") or final_state.get("state_write_blocked"):
        blocked_count = max(blocked_count, 1)
    return state_write_count, blocked_count


def _len_list(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, list):
        return len(value)
    return 0


def _derive_facets(final_state: dict[str, Any], evidence_pack: dict[str, Any], answer_plan: dict[str, Any], semantic_frame: dict[str, Any]) -> list[str]:
    facets: list[str] = []
    for source in (
        final_state.get("facets"),
        semantic_frame.get("facets"),
        evidence_pack.get("answerable_facets"),
        evidence_pack.get("unknown_facets"),
        evidence_pack.get("failed_facets"),
        answer_plan.get("answerable_facets"),
        answer_plan.get("unknown_facets"),
        answer_plan.get("failed_facets"),
    ):
        if not isinstance(source, list):
            continue
        for item in source:
            text = str(item.get("name") if isinstance(item, dict) else item).strip()
            if text and text not in facets:
                facets.append(text)
    return facets


def _tool_call_count(execution_plan: dict[str, Any], tool_results: dict[str, Any]) -> int:
    tool_calls = execution_plan.get("tool_calls") or []
    if isinstance(tool_calls, list) and tool_calls:
        return len(tool_calls)
    if isinstance(tool_results, dict):
        return len(tool_results)
    return 0


def _evidence_count(evidence_pack: dict[str, Any]) -> int:
    evidence_items = evidence_pack.get("evidence_items") or []
    return len(evidence_items) if isinstance(evidence_items, list) else 0


def _verification_status(final_state: dict[str, Any], trace: TurnTrace | None) -> str | None:
    if str(final_state.get("verify_result", "") or "").strip():
        return str(final_state.get("verify_result", "") or "").strip()
    if final_state.get("answer_verify_passed") is True:
        return "pass"
    if final_state.get("answer_verify_passed") is False:
        return "fail"
    if trace is not None and trace.answer_verify_passed is not None:
        return "pass" if trace.answer_verify_passed else "fail"
    return None


def _evidence_review_action(final_state: dict[str, Any]) -> str | None:
    review_results = final_state.get("review_results") or {}
    if isinstance(review_results, dict):
        review = review_results.get("evidence_review")
        if isinstance(review, dict):
            action = str(review.get("next_action", "") or "").strip()
            return action or None
        action = getattr(review, "next_action", "")
        if action:
            return str(action)
    return None


def _planner_selected_tool_call_count(execution_plan: dict[str, Any]) -> int:
    tool_calls = execution_plan.get("tool_calls") or []
    if isinstance(tool_calls, list):
        return len([item for item in tool_calls if isinstance(item, dict) and not item.get("blocked")])
    return 0


def _planner_blocked_tool_call_count(execution_plan: dict[str, Any]) -> int:
    blocked = execution_plan.get("blocked_tool_calls") or []
    return len(blocked) if isinstance(blocked, list) else 0


def _planner_dropped_facet_count(execution_plan: dict[str, Any]) -> int:
    dropped = execution_plan.get("unsupported_facets") or []
    return len(dropped) if isinstance(dropped, list) else 0


def _bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _batch_size(execution_plan: dict[str, Any]) -> int:
    stages = execution_plan.get("stages") or []
    return len(stages) if isinstance(stages, list) else 0


def _parallelism(execution_plan: dict[str, Any]) -> int:
    max_parallelism = 1
    for stage in execution_plan.get("stages") or []:
        if isinstance(stage, dict):
            max_parallelism = max(max_parallelism, int(stage.get("max_parallelism", 1) or 1))
    return max_parallelism


def _preview_blocked(final_state: dict[str, Any]) -> bool:
    preview_text = str(final_state.get("preview_text", "") or "")
    if preview_text:
        return False
    if final_state.get("answer_verify_passed") is False:
        return True
    return False
