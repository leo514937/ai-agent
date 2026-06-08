from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping
from learning_agent_service.application.router.trace import (
    build_routing_trace_from_state,
    routing_trace_to_dict,
)


def _nested_mapping(*sources: Mapping[str, Any], key: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        value = source.get(key)
        if isinstance(value, Mapping):
            merged.update(dict(value))
    return merged


def extract_phase0_trace(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, Mapping):
        turn = _as_mapping(state.get("turn"))
        runtime = _as_mapping(state.get("runtime"))
    else:
        turn = _as_mapping(getattr(state, "turn", None))
        runtime = _as_mapping(getattr(state, "runtime", None))

    turn_extra = _as_mapping(turn.get("extra"))
    runtime_metrics = _as_mapping(runtime.get("metrics"))
    runtime_extra = _as_mapping(runtime.get("extra"))

    phase0_trace = {}
    phase0_trace.update(_nested_mapping(turn_extra, runtime_metrics, runtime_extra, key="phase0_trace"))
    return phase0_trace


def extract_phase3_trace(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, Mapping):
        turn = _as_mapping(state.get("turn"))
        runtime = _as_mapping(state.get("runtime"))
    else:
        turn = _as_mapping(getattr(state, "turn", None))
        runtime = _as_mapping(getattr(state, "runtime", None))

    turn_extra = _as_mapping(turn.get("extra"))
    runtime_metrics = _as_mapping(runtime.get("metrics"))
    runtime_extra = _as_mapping(runtime.get("extra"))

    phase3_trace = {}
    phase3_trace.update(_nested_mapping(turn_extra, runtime_metrics, runtime_extra, key="phase3_trace"))
    return phase3_trace


def extract_phase4_trace(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, Mapping):
        turn = _as_mapping(state.get("turn"))
        runtime = _as_mapping(state.get("runtime"))
    else:
        turn = _as_mapping(getattr(state, "turn", None))
        runtime = _as_mapping(getattr(state, "runtime", None))

    turn_extra = _as_mapping(turn.get("extra"))
    runtime_metrics = _as_mapping(runtime.get("metrics"))
    runtime_extra = _as_mapping(runtime.get("extra"))

    phase4_trace = {}
    phase4_trace.update(_nested_mapping(turn_extra, runtime_metrics, runtime_extra, key="phase4_trace"))
    return phase4_trace


def extract_phase5_trace(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, Mapping):
        turn = _as_mapping(state.get("turn"))
        runtime = _as_mapping(state.get("runtime"))
    else:
        turn = _as_mapping(getattr(state, "turn", None))
        runtime = _as_mapping(getattr(state, "runtime", None))

    turn_extra = _as_mapping(turn.get("extra"))
    runtime_metrics = _as_mapping(runtime.get("metrics"))
    runtime_extra = _as_mapping(runtime.get("extra"))

    phase5_trace = {}
    phase5_trace.update(_nested_mapping(turn_extra, runtime_metrics, runtime_extra, key="phase5_trace"))
    return phase5_trace


def extract_routing_trace(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    trace = build_routing_trace_from_state(state)
    return routing_trace_to_dict(trace)


@dataclass
class HarnessCase:
    case_id: str
    query: str
    session_context: dict[str, Any] = field(default_factory=dict)
    client_context: dict[str, Any] = field(default_factory=dict)
    mock_rag: dict[str, Any] | None = None
    mock_tools: dict[str, Any] | None = None
    expected_trace: dict[str, Any] = field(default_factory=dict)
    expected_response_mode: str | None = None
    forbidden_behaviors: list[str] = field(default_factory=list)


@dataclass
class ToolMockResult:
    tool_name: str
    status: str = "success"
    payload: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None


@dataclass
class GoldenEvidencePack:
    case_id: str
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    covered_facets: list[str] = field(default_factory=list)
    missing_facets: list[str] = field(default_factory=list)
    entity_keys: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessRunResult:
    case_id: str
    passed: bool
    actual_trace: dict[str, Any] = field(default_factory=dict)
    actual_response_mode: str = "unknown"
    actual_answer: str = ""
    failures: list[str] = field(default_factory=list)


@dataclass
class ReplayComparisonResult:
    case_id: str
    passed: bool
    baseline: HarnessRunResult
    candidate: HarnessRunResult
    differences: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


@dataclass
class ReplayComparisonReport:
    total_cases: int
    changed_cases: int
    unchanged_cases: int
    changed_field_counts: dict[str, int] = field(default_factory=dict)
    case_status_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    total_cases: int
    passed_cases: int
    failed_cases: int
    failure_buckets: dict[str, int] = field(default_factory=dict)
    metric_summary: dict[str, Any] = field(default_factory=dict)


class TraceHarnessRecorder:
    def record(self, state: Any, *, case_id: str | None = None) -> dict[str, Any]:
        trace = extract_phase0_trace(state)
        phase3_trace = extract_phase3_trace(state)
        phase5_trace = extract_phase5_trace(state)
        phase4_trace = extract_phase4_trace(state)
        routing_trace = extract_routing_trace(state)
        if isinstance(state, Mapping):
            turn = _as_mapping(state.get("turn"))
            runtime = _as_mapping(state.get("runtime"))
            persistent = _as_mapping(state.get("persistent"))
        else:
            turn = _as_mapping(getattr(state, "turn", None))
            runtime = _as_mapping(getattr(state, "runtime", None))
            persistent = _as_mapping(getattr(state, "persistent", None))
        runtime_metrics = _as_mapping(runtime.get("metrics"))
        turn_extra = _as_mapping(turn.get("extra"))

        recorded = {
            "case_id": case_id,
            "trace_id": runtime.get("trace_id"),
            "session_id": runtime.get("session_id"),
            "turn_id": runtime.get("turn_id"),
            "harness_mode": trace.get("harness_mode", "off"),
            "initial_routing_decision": trace.get("initial_routing_decision"),
            "retrieval_plan_status": trace.get("retrieval_plan_status", "not_attempted"),
            "retrieval_plan_failure_reason": trace.get("retrieval_plan_failure_reason"),
            "tool_plan_status": trace.get("tool_plan_status", "not_attempted"),
            "tool_plan_failure_reason": trace.get("tool_plan_failure_reason"),
            "evidence_quality": trace.get("evidence_quality"),
            "final_response_mode": trace.get("final_response_mode"),
            "response_origin": trace.get("response_origin"),
            "answer_confidence": trace.get("answer_confidence"),
            "stage_timeline": list(turn.get("stage_timeline", []) or []),
            "selected_shop_id": persistent.get("selected_shop_id"),
            "selected_shop_name": persistent.get("selected_shop_name"),
            "graph_runtime": phase5_trace.get("graph_runtime") or phase5_trace.get("runner_backend") or phase5_trace.get("runner_kind"),
            "graph_fallback": runtime_metrics.get("graph_fallback") or persistent.get("extra", {}).get("graph_fallback") or "none",
            "final_answer_audit": turn_extra.get("final_answer_audit") or runtime_metrics.get("final_answer_audit") or phase4_trace.get("final_answer_audit"),
            "final_answer_safety": turn_extra.get("final_answer_safety") or runtime_metrics.get("final_answer_safety") or phase4_trace.get("final_answer_safety"),
            "phase3_trace": phase3_trace,
            "phase5_trace": phase5_trace,
            "phase4_trace": phase4_trace,
            "routing_trace": routing_trace,
        }
        return recorded


class ReplayHarness:
    def run_case(self, case: HarnessCase, executor: Callable[[HarnessCase], HarnessRunResult | Mapping[str, Any]]) -> HarnessRunResult:
        outcome = executor(case)
        if isinstance(outcome, HarnessRunResult):
            return outcome
        if isinstance(outcome, Mapping):
            return HarnessRunResult(
                case_id=str(outcome.get("case_id") or case.case_id),
                passed=bool(outcome.get("passed", False)),
                actual_trace=dict(outcome.get("actual_trace") or {}),
                actual_response_mode=str(outcome.get("actual_response_mode") or "unknown"),
                actual_answer=str(outcome.get("actual_answer") or ""),
                failures=list(outcome.get("failures") or []),
            )
        raise TypeError("executor must return HarnessRunResult or mapping")

    def run_many(self, cases: Sequence[HarnessCase], executor: Callable[[HarnessCase], HarnessRunResult | Mapping[str, Any]]) -> list[HarnessRunResult]:
        return [self.run_case(case, executor) for case in cases]

    @staticmethod
    def _comparison_value(result: HarnessRunResult, field: str) -> Any:
        if field in {"phase0_trace", "phase3_trace", "phase4_trace", "phase5_trace", "routing_trace"}:
            return dict(result.actual_trace or {}).get(field)
        if field.startswith("actual_trace."):
            value: Any = dict(result.actual_trace or {})
            for part in field.split(".")[1:]:
                if not isinstance(value, Mapping):
                    return None
                value = value.get(part)
            return value
        return getattr(result, field, None)

    def compare_case(
        self,
        case: HarnessCase,
        baseline_executor: Callable[[HarnessCase], HarnessRunResult | Mapping[str, Any]],
        candidate_executor: Callable[[HarnessCase], HarnessRunResult | Mapping[str, Any]],
        *,
        comparison_fields: Sequence[str] = ("phase3_trace", "actual_response_mode", "actual_answer"),
    ) -> ReplayComparisonResult:
        baseline = self.run_case(case, baseline_executor)
        candidate = self.run_case(case, candidate_executor)
        differences: dict[str, tuple[Any, Any]] = {}
        for field_name in comparison_fields:
            baseline_value = self._comparison_value(baseline, field_name)
            candidate_value = self._comparison_value(candidate, field_name)
            if baseline_value != candidate_value:
                differences[field_name] = (baseline_value, candidate_value)
        failures: list[str] = []
        if not differences:
            failures.append("no_trace_diff")
        return ReplayComparisonResult(
            case_id=case.case_id,
            passed=bool(differences),
            baseline=baseline,
            candidate=candidate,
            differences=differences,
            failures=failures,
        )

    def compare_many(
        self,
        cases: Sequence[HarnessCase],
        baseline_executor: Callable[[HarnessCase], HarnessRunResult | Mapping[str, Any]],
        candidate_executor: Callable[[HarnessCase], HarnessRunResult | Mapping[str, Any]],
        *,
        comparison_fields: Sequence[str] = ("phase3_trace", "actual_response_mode", "actual_answer"),
    ) -> list[ReplayComparisonResult]:
        return [
            self.compare_case(
                case,
                baseline_executor,
                candidate_executor,
                comparison_fields=comparison_fields,
            )
            for case in cases
        ]


class ToolMockHarness:
    def __init__(self) -> None:
        self._results: dict[str, ToolMockResult] = {}

    def register(self, result: ToolMockResult) -> ToolMockResult:
        self._results[result.tool_name] = result
        return result

    def resolve(self, tool_name: str) -> ToolMockResult | None:
        return self._results.get(tool_name)


class RagGoldenEvidenceHarness:
    def __init__(self) -> None:
        self._packs: dict[str, GoldenEvidencePack] = {}

    def register(self, pack: GoldenEvidencePack) -> GoldenEvidencePack:
        self._packs[pack.case_id] = pack
        return pack

    def resolve(self, case_id: str) -> GoldenEvidencePack | None:
        return self._packs.get(case_id)


class EvaluationHarness:
    def summarize(self, results: Sequence[HarnessRunResult]) -> EvaluationReport:
        total_cases = len(results)
        passed_cases = len([result for result in results if result.passed])
        failed_cases = total_cases - passed_cases
        failure_buckets = Counter()
        response_mode_counts = Counter()
        response_origin_counts = Counter()
        missing_trace_field_counts = Counter()
        runner_kind_counts = Counter()
        graph_runtime_counts = Counter()
        graph_fallback_counts = Counter()
        verifier_status_counts = Counter()
        verifier_issue_counts = Counter()
        verifier_response_mode_counts = Counter()
        final_answer_safety_severity_counts = Counter()
        final_answer_audit_severity_counts = Counter()

        for result in results:
            trace = dict(result.actual_trace or {})
            phase0_trace = dict(trace.get("phase0_trace") or {})
            phase5_trace = dict(trace.get("phase5_trace") or {})
            phase4_trace = dict(trace.get("phase4_trace") or {})
            _ = dict(trace.get("routing_trace") or {})
            for failure in result.failures:
                failure_buckets[str(failure)] += 1
            response_mode = str(
                phase0_trace.get("final_response_mode")
                or result.actual_response_mode
                or "unknown"
            ).strip() or "unknown"
            response_mode_counts[response_mode] += 1
            response_origin = str(phase0_trace.get("response_origin") or "unknown").strip() or "unknown"
            response_origin_counts[response_origin] += 1
            runner_kind = str(phase5_trace.get("runner_kind") or "unknown").strip() or "unknown"
            runner_kind_counts[runner_kind] += 1
            graph_runtime = str(
                phase5_trace.get("graph_runtime")
                or phase5_trace.get("runner_backend")
                or phase5_trace.get("runner_kind")
                or "unknown"
            ).strip() or "unknown"
            graph_runtime_counts[graph_runtime] += 1
            graph_fallback = str(trace.get("graph_fallback") or phase5_trace.get("graph_fallback") or "none").strip() or "none"
            graph_fallback_counts[graph_fallback] += 1
            for field_name in ("initial_routing_decision", "evidence_quality", "final_response_mode"):
                if not phase0_trace.get(field_name):
                    missing_trace_field_counts[field_name] += 1
            if phase4_trace:
                verifier_status = "passed" if phase4_trace.get("verifier_passed") else "failed"
                verifier_status_counts[verifier_status] += 1
                verifier_response_mode = str(phase4_trace.get("suggested_response_mode") or "unknown").strip() or "unknown"
                verifier_response_mode_counts[verifier_response_mode] += 1
                for issue in phase4_trace.get("verifier_issues") or []:
                    verifier_issue_counts[str(issue)] += 1
            final_answer_safety = dict(trace.get("final_answer_safety") or {})
            if final_answer_safety:
                final_answer_safety_severity = str(final_answer_safety.get("severity") or "unknown").strip() or "unknown"
                final_answer_safety_severity_counts[final_answer_safety_severity] += 1
            final_answer_audit = dict(trace.get("final_answer_audit") or {})
            if final_answer_audit:
                final_answer_audit_severity = str(final_answer_audit.get("severity") or "unknown").strip() or "unknown"
                final_answer_audit_severity_counts[final_answer_audit_severity] += 1

        return EvaluationReport(
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            failure_buckets=dict(sorted(failure_buckets.items())),
            metric_summary={
                "response_mode_distribution": dict(sorted(response_mode_counts.items())),
                "response_origin_distribution": dict(sorted(response_origin_counts.items())),
                "runner_kind_distribution": dict(sorted(runner_kind_counts.items())),
                "graph_runtime_distribution": dict(sorted(graph_runtime_counts.items())),
                "graph_fallback_distribution": dict(sorted(graph_fallback_counts.items())),
                "missing_trace_fields": dict(sorted(missing_trace_field_counts.items())),
                "routing_trace_distribution": {
                    "present": sum(1 for result in results if dict(result.actual_trace or {}).get("routing_trace")),
                    "absent": sum(1 for result in results if not dict(result.actual_trace or {}).get("routing_trace")),
                },
                "verifier_status_distribution": dict(sorted(verifier_status_counts.items())),
                "verifier_issue_distribution": dict(sorted(verifier_issue_counts.items())),
                "verifier_response_mode_distribution": dict(sorted(verifier_response_mode_counts.items())),
                "final_answer_safety_severity_distribution": dict(sorted(final_answer_safety_severity_counts.items())),
                "final_answer_audit_severity_distribution": dict(sorted(final_answer_audit_severity_counts.items())),
            },
        )

    def summarize_comparisons(self, results: Sequence[ReplayComparisonResult]) -> ReplayComparisonReport:
        total_cases = len(results)
        changed_cases = len([result for result in results if result.passed and result.differences])
        unchanged_cases = total_cases - changed_cases
        changed_field_counts = Counter()
        case_status_counts = Counter()

        for result in results:
            case_status = "changed" if result.passed and result.differences else "unchanged"
            case_status_counts[case_status] += 1
            for field_name in result.differences:
                changed_field_counts[str(field_name)] += 1

        return ReplayComparisonReport(
            total_cases=total_cases,
            changed_cases=changed_cases,
            unchanged_cases=unchanged_cases,
            changed_field_counts=dict(sorted(changed_field_counts.items())),
            case_status_counts=dict(sorted(case_status_counts.items())),
        )
