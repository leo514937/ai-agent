from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class StageTrace:
    input: Any = None
    output: Any = None
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class RoutingTrace:
    query: str
    session_id: str
    turn_id: str
    timestamp: str
    trace_id: str | None = None
    stages: dict[str, StageTrace] = field(default_factory=dict)
    final_decision: dict[str, Any] = field(default_factory=dict)
    ground_truth: dict[str, Any] | None = None
    is_correct: bool | None = None


def _stage_trace_from_value(value: Any) -> StageTrace:
    if isinstance(value, StageTrace):
        return value
    if isinstance(value, Mapping):
        if any(key in value for key in ("input", "output", "duration_ms", "error")):
            return StageTrace(
                input=value.get("input"),
                output=value.get("output"),
                duration_ms=float(value.get("duration_ms") or 0.0),
                error=str(value.get("error")) if value.get("error") not in (None, "") else None,
            )
        return StageTrace(output=dict(value))
    return StageTrace(output=value)


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
        except Exception:
            dumped = value.model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return None


def build_routing_trace(
    *,
    query: str,
    session_id: str,
    turn_id: str,
    trace_id: str | None = None,
    stages: Mapping[str, Any] | None = None,
    final_decision: Mapping[str, Any] | None = None,
    ground_truth: Mapping[str, Any] | None = None,
    is_correct: bool | None = None,
    timestamp: str | None = None,
) -> RoutingTrace:
    return RoutingTrace(
        query=str(query or ""),
        session_id=str(session_id or ""),
        turn_id=str(turn_id or ""),
        trace_id=(str(trace_id).strip() or None) if trace_id is not None else None,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        stages={str(key): _stage_trace_from_value(value) for key, value in dict(stages or {}).items()},
        final_decision=dict(final_decision or {}),
        ground_truth=_mapping_or_none(ground_truth),
        is_correct=is_correct,
    )


def routing_trace_to_dict(trace: RoutingTrace) -> dict[str, Any]:
    return asdict(trace)


def build_routing_trace_from_state(
    state: Any,
    *,
    trace_id: str | None = None,
    ground_truth: Mapping[str, Any] | None = None,
    is_correct: bool | None = None,
) -> RoutingTrace:
    if isinstance(state, Mapping):
        turn = state.get("turn")
        runtime = state.get("runtime")
    else:
        turn = getattr(state, "turn", None)
        runtime = getattr(state, "runtime", None)

    turn_extra = getattr(turn, "extra", {}) if turn is not None else {}
    runtime_metrics = getattr(runtime, "metrics", {}) if runtime is not None else {}

    routing = getattr(turn, "routing_decision", None) if turn is not None else None
    return build_routing_trace(
        query=str(getattr(turn, "raw_query", "") or ""),
        session_id=str(getattr(runtime, "session_id", "") or ""),
        turn_id=str(getattr(runtime, "turn_id", "") or ""),
        trace_id=str(trace_id or getattr(runtime, "trace_id", "") or "").strip() or None,
        stages={
            "phase0_trace": dict(turn_extra.get("phase0_trace") or runtime_metrics.get("phase0_trace") or {}),
            "phase1_trace": dict(turn_extra.get("phase1_trace") or runtime_metrics.get("phase1_trace") or {}),
            "phase2_trace": dict(turn_extra.get("phase2_trace") or runtime_metrics.get("phase2_trace") or {}),
            "phase3_trace": dict(turn_extra.get("phase3_trace") or runtime_metrics.get("phase3_trace") or {}),
            "phase4_trace": dict(turn_extra.get("phase4_trace") or runtime_metrics.get("phase4_trace") or {}),
            "phase5_trace": dict(turn_extra.get("phase5_trace") or runtime_metrics.get("phase5_trace") or {}),
        },
        final_decision=_mapping_or_none(routing) or {},
        ground_truth=ground_truth,
        is_correct=is_correct,
    )


def build_routing_trace_from_metrics(
    *,
    query: str,
    session_id: str,
    turn_id: str,
    trace_id: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    final_decision: Mapping[str, Any] | None = None,
    ground_truth: Mapping[str, Any] | None = None,
    is_correct: bool | None = None,
    timestamp: str | None = None,
) -> RoutingTrace:
    metrics_map = dict(metrics or {})
    return build_routing_trace(
        query=query,
        session_id=session_id,
        turn_id=turn_id,
        trace_id=trace_id,
        stages={
            "phase0_trace": dict(metrics_map.get("phase0_trace") or {}),
            "phase1_trace": dict(metrics_map.get("phase1_trace") or {}),
            "phase2_trace": dict(metrics_map.get("phase2_trace") or {}),
            "phase3_trace": dict(metrics_map.get("phase3_trace") or {}),
            "phase4_trace": dict(metrics_map.get("phase4_trace") or {}),
            "phase5_trace": dict(metrics_map.get("phase5_trace") or {}),
        },
        final_decision=final_decision or dict(metrics_map.get("route_gate") or {}),
        ground_truth=ground_truth,
        is_correct=is_correct,
        timestamp=timestamp,
    )
