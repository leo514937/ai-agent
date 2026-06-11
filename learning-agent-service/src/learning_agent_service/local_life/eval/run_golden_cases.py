from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text
from learning_agent_service.application.router.trace import (
    build_routing_trace_from_metrics,
    routing_trace_to_dict,
)
from learning_agent_service.local_life.failure_mode_mapping import failure_mode_detector
from learning_agent_service.testing import EvaluationHarness, EvalCaseRecorder, HarnessRunResult, TraceWriter


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
    else:
        items = [value]
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    description: str = ""
    turns: tuple[str, ...] = ()
    query: str = ""
    session_context: dict[str, Any] = field(default_factory=dict)
    client_context: dict[str, Any] = field(default_factory=dict)
    extra_payload: dict[str, Any] = field(default_factory=dict)
    expected_contains: tuple[str, ...] = ()
    expected_not_contains: tuple[str, ...] = ()
    expected_metrics: dict[str, Any] = field(default_factory=dict)
    expected_route_branch: str | None = None
    expected_rag_mode: str | None = None
    expected_graph_runtime: str | None = "langgraph"
    expected_runner_kind: str | None = "langgraph"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "GoldenCase":
        expected = _as_mapping(raw.get("expected"))
        turns = raw.get("turns") or []
        if isinstance(turns, str):
            turns = [turns]
        elif not isinstance(turns, Sequence) or isinstance(turns, (bytes, bytearray)):
            turns = [turns]
        turns_tuple = tuple(_clean_text(item) for item in turns if _clean_text(item))
        query = _clean_text(raw.get("query") or (turns_tuple[-1] if turns_tuple else ""))
        return cls(
            case_id=_clean_text(raw.get("case_id") or raw.get("id") or query or "case"),
            description=_clean_text(raw.get("description")),
            turns=turns_tuple,
            query=query,
            session_context=_as_mapping(raw.get("session_context")),
            client_context=_as_mapping(raw.get("client_context")),
            extra_payload=_as_mapping(raw.get("extra_payload")),
            expected_contains=_string_list(raw.get("expected_contains") or expected.get("contains")),
            expected_not_contains=_string_list(raw.get("expected_not_contains") or expected.get("not_contains")),
            expected_metrics=_as_mapping(raw.get("expected_metrics") or expected.get("metrics")),
            expected_route_branch=_clean_text(raw.get("expected_route_branch") or expected.get("route_branch")) or None,
            expected_rag_mode=_clean_text(raw.get("expected_rag_mode") or expected.get("rag_mode")) or None,
            expected_graph_runtime=_clean_text(raw.get("expected_graph_runtime") or expected.get("graph_runtime")) or "langgraph",
            expected_runner_kind=_clean_text(raw.get("expected_runner_kind") or expected.get("runner_kind")) or "langgraph",
        )


@dataclass(frozen=True)
class GoldenCaseResult:
    case_id: str
    passed: bool
    actual_trace: dict[str, Any] = field(default_factory=dict)
    actual_response_mode: str = "unknown"
    actual_answer: str = ""
    failures: list[str] = field(default_factory=list)
    actual_metrics: dict[str, Any] = field(default_factory=dict)


def load_golden_cases(path: str | Path) -> tuple[GoldenCase, ...]:
    path = Path(path)
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, Mapping):
            raw_cases = data.get("cases") or []
        else:
            raw_cases = data
        return tuple(GoldenCase.from_mapping(item) for item in raw_cases or [])

    cases: list[GoldenCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            cases.append(GoldenCase.from_mapping(json.loads(line)))
    return tuple(cases)


def _build_case_payload(case: GoldenCase) -> dict[str, Any]:
    payload = dict(case.extra_payload or {})
    payload.update(case.client_context or {})
    if case.session_context:
        payload.setdefault("session_context", dict(case.session_context))
    return payload


def evaluate_golden_case(case: GoldenCase, result: Mapping[str, Any] | HarnessRunResult) -> GoldenCaseResult:
    if isinstance(result, HarnessRunResult):
        actual_answer = result.actual_answer
        actual_trace = dict(result.actual_trace or {})
        actual_response_mode = result.actual_response_mode
        failures = list(result.failures or [])
    else:
        actual_answer = _clean_text(result.get("actual_answer") or result.get("answer_text"))
        actual_trace = dict(result.get("actual_trace") or {})
        actual_response_mode = _clean_text(result.get("actual_response_mode") or "unknown") or "unknown"
        failures = list(result.get("failures") or [])
    metrics = dict(actual_trace.get("metrics") or {})
    if not metrics and isinstance(result, Mapping):
        metrics = dict(result.get("metrics") or {})

    for expected in case.expected_contains:
        if expected not in actual_answer:
            failures.append(f"missing:{expected}")
    for forbidden in case.expected_not_contains:
        if forbidden in actual_answer:
            failures.append(f"forbidden:{forbidden}")
    if case.expected_route_branch:
        route_branch = _clean_text((metrics.get("route_gate") or {}).get("branch"))
        if route_branch != case.expected_route_branch:
            failures.append(f"route_branch:{route_branch or 'missing'}")
    if case.expected_rag_mode:
        rag_mode = _clean_text(metrics.get("rag_mode"))
        if rag_mode != case.expected_rag_mode:
            failures.append(f"rag_mode:{rag_mode or 'missing'}")
    if case.expected_graph_runtime:
        graph_runtime = _clean_text(metrics.get("graph_runtime") or actual_trace.get("graph_runtime"))
        if graph_runtime != case.expected_graph_runtime:
            failures.append(f"graph_runtime:{graph_runtime or 'missing'}")
    if case.expected_runner_kind:
        phase5_trace = dict(metrics.get("phase5_trace") or actual_trace.get("phase5_trace") or {})
        runner_kind = _clean_text(phase5_trace.get("runner_kind"))
        if runner_kind != case.expected_runner_kind:
            failures.append(f"runner_kind:{runner_kind or 'missing'}")
    for metric_key, expected_value in case.expected_metrics.items():
        observed = metrics.get(metric_key)
        if observed is None:
            observed = metrics
            for part in str(metric_key).split("."):
                if isinstance(observed, Mapping):
                    observed = observed.get(part)
                else:
                    observed = None
                    break
        if observed != expected_value:
            failures.append(f"metric:{metric_key}")

    target_shop_id_str = _clean_text((case.session_context or {}).get("shop_id"))
    try:
        target_shop_id = int(target_shop_id_str) if target_shop_id_str else None
    except Exception:
        target_shop_id = None

    answer_shop_ids = []
    for shop in (actual_trace.get("shops") or []):
        try:
            answer_shop_ids.append(int(shop.get("id")))
        except Exception:
            pass

    answer_contract = metrics.get("answer_contract") or {}
    allowed_facets = answer_contract.get("allowed_facets") or []
    forbidden_facets = answer_contract.get("forbidden_facets") or []
    realtime_facets = answer_contract.get("realtime_facets") or []
    route_branch = _clean_text((metrics.get("route_gate") or {}).get("branch")) or "unknown"
    tool_called = route_branch in ("tool_call", "rag_plus_tool")
    evidence_count = int(metrics.get("evidence_count") or 0)

    detected = failure_mode_detector.detect_failure_modes(
        query=case.query,
        answer=actual_answer,
        route=route_branch,
        tool_called=tool_called,
        evidence_count=evidence_count,
        target_shop_id=target_shop_id,
        answer_shop_ids=answer_shop_ids,
        allowed_facets=allowed_facets,
        forbidden_facets=forbidden_facets,
        realtime_facets=realtime_facets,
    )
    actual_trace["detected_failures"] = [m.mode_id for m in detected]

    return GoldenCaseResult(
        case_id=case.case_id,
        passed=not failures,
        actual_trace=actual_trace,
        actual_response_mode=actual_response_mode,
        actual_answer=actual_answer,
        failures=failures,
        actual_metrics=metrics,
    )


def run_golden_cases(
    cases: Sequence[GoldenCase],
    executor: Callable[[GoldenCase], HarnessRunResult | Mapping[str, Any]],
) -> list[GoldenCaseResult]:
    results: list[GoldenCaseResult] = []
    for case in cases:
        outcome = executor(case)
        results.append(evaluate_golden_case(case, outcome))
    return results


class _HttpChatExecutor:
    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False)
        self._base_url = base_url
        self._token = token

    def _payload_for_turn(self, case: GoldenCase, turn: str, *, turn_index: int, is_first_turn: bool) -> dict[str, Any]:
        context_payload = dict(case.client_context or {})
        context_payload.update(dict(case.extra_payload or {}))
        payload = {
            "message": turn,
            "user_id": f"golden-{case.case_id}",
            "session_id": f"golden-{case.case_id}",
            "turn_id": f"{case.case_id}-turn-{turn_index}",
            "trace_id": f"{case.case_id}-trace",
            "page": case.extra_payload.get("page", "assistant"),
            "context": context_payload,
            "client_context": dict(context_payload),
        }
        if is_first_turn and case.session_context:
            payload["context"].update(case.session_context)
            payload["client_context"].update(case.session_context)
        return payload

    def run_case(self, case: GoldenCase) -> HarnessRunResult:
        last_result: dict[str, Any] = {}
        turns = case.turns or (case.query,)
        for index, turn in enumerate(turns, start=1):
            payload = self._payload_for_turn(case, turn, turn_index=index, is_first_turn=index == 1)
            with self._client.stream(
                "POST",
                self._base_url,
                json=payload,
                headers={"Accept": "text/event-stream", "X-Internal-Token": self._token},
            ) as response:
                response.raise_for_status()
                raw_text = "".join(chunk for chunk in response.iter_text() if chunk)
            last_result = _parse_sse(raw_text)
        metrics = dict(last_result.get("metrics") or {})
        phase5_trace = dict(metrics.get("phase5_trace") or {})
        routing_trace = routing_trace_to_dict(
            build_routing_trace_from_metrics(
                query=turns[-1] if turns else case.query,
                session_id=f"golden-{case.case_id}",
                turn_id=f"{case.case_id}-turn-{len(turns)}",
                trace_id=f"{case.case_id}-trace",
                metrics=metrics,
                final_decision=dict(last_result.get("route_gate") or metrics.get("route_gate") or {}),
            )
        )
        actual_trace = {
            "phase5_trace": phase5_trace,
            "graph_runtime": metrics.get("graph_runtime") or phase5_trace.get("graph_runtime"),
            "graph_fallback": metrics.get("graph_fallback") or phase5_trace.get("graph_fallback") or "none",
            "route_gate": metrics.get("route_gate") or {},
            "metrics": metrics,
            "routing_trace": routing_trace,
            "shops": last_result.get("shops") or [],
        }
        return HarnessRunResult(
            case_id=case.case_id,
            passed=True,
            actual_trace=actual_trace,
            actual_response_mode=str(last_result.get("mode") or metrics.get("final_response_mode") or "unknown"),
            actual_answer=str(last_result.get("answer_text") or ""),
            failures=[],
        )


def _parse_sse(raw_text: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for block in raw_text.replace("\r\n", "\n").strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        data_raw = "\n".join(data_lines).strip()
        data: Any = None
        if data_raw:
            try:
                data = json.loads(data_raw)
            except Exception:
                data = data_raw
        events.append({"event_type": event_type, "data": data})
    for event in events:
        if event.get("event_type") == "final":
            payload = event.get("data") or {}
            if isinstance(payload, Mapping):
                return dict(payload.get("payload") or payload)
    return {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run golden case replay for local life chat.")
    parser.add_argument("--cases", required=True, help="Path to eval/local_life/golden_cases.jsonl or yaml.")
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write a JSON report.",
    )
    parser.add_argument(
        "--trace-output",
        default=None,
        help="Optional JSONL path for per-case trace replay records.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000/internal/v1/chat/stream",
        help="Chat stream endpoint.",
    )
    parser.add_argument(
        "--token",
        default="local-learning-agent-token",
        help="Internal token for the chat endpoint.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases = load_golden_cases(args.cases)
    executor = _HttpChatExecutor(args.base_url, args.token)
    results = run_golden_cases(cases, executor.run_case)
    trace_records: list[dict[str, Any]] = []
    if args.trace_output:
        recorder = EvalCaseRecorder(trace_writer=TraceWriter(args.trace_output))
        trace_records = [
            recorder.record_case(case.case_id, result, case=case, write=True)
            for case, result in zip(cases, results)
        ]
    report = EvaluationHarness().summarize(
        [
            HarnessRunResult(
                case_id=result.case_id,
                passed=result.passed,
                actual_trace=result.actual_trace,
                actual_response_mode=result.actual_response_mode,
                actual_answer=result.actual_answer,
                failures=list(result.failures),
            )
            for result in results
        ]
    )
    from collections import Counter
    detected_counter = Counter()
    for res in results:
        for mode_id in res.actual_trace.get("detected_failures", []):
            detected_counter[mode_id] += 1

    output = {
        "report": {
            "total_cases": report.total_cases,
            "passed_cases": report.passed_cases,
            "failed_cases": report.failed_cases,
            "failure_buckets": report.failure_buckets,
            "metric_summary": report.metric_summary,
            "business_metrics": dict(detected_counter),
        },
        "results": [asdict(result) for result in results],
    }
    if trace_records:
        output["trace_records"] = trace_records
        output["trace_output"] = str(Path(args.trace_output).resolve())
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["report"], ensure_ascii=False, indent=2))
    return 0


def run_evaluation() -> dict[str, Any]:
    """Run evaluation and return results in CI-friendly format."""
    from pathlib import Path
    
    cases_path = Path(__file__).parent.parent.parent.parent.parent / "eval" / "local_life" / "golden_cases.jsonl"
    if not cases_path.exists():
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "failures": [],
            "error": f"Golden cases file not found: {cases_path}",
        }
    
    cases = load_golden_cases(cases_path)
    if not cases:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "failures": [],
            "error": "No golden cases found",
        }
    
    executor = _HttpChatExecutor(
        base_url="http://127.0.0.1:8000/internal/v1/chat/stream",
        token="local-learning-agent-token",
    )
    
    results = run_golden_cases(cases, executor.run_case)
    
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    pass_rate = passed / total if total > 0 else 0.0
    
    failures = []
    for result in results:
        if not result.passed:
            failures.append({
                "case_id": result.case_id,
                "reason": "; ".join(result.failures) if result.failures else "unknown",
            })
    
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "failures": failures,
    }


if __name__ == "__main__":
    raise SystemExit(main())
