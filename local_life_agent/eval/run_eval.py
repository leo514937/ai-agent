from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from ..agent import AgentResponse, run_agent_graph
from ..llm.client import clear_llm_backend, set_llm_backend
from ..observability.metrics import aggregate_turn_trace_metrics, merge_eval_metrics
from ..observability.trace import TurnTrace, build_turn_trace
from ..session.store import reset_session_store
from .eval_case_schema import EvalCase


_REPORT_DIR = Path(__file__).resolve().parent / "reports"


class EvalSpyBackend:
    """轻量 deterministic backend，用于阶段 16 的离线 eval。"""

    llm_backend = "spy_real_llm"

    def __call__(
        self,
        prompt: str = "",
        system_prompt: str = "",
        timeout_ms: int = 3000,
        **_: Any,
    ) -> str:
        if "## DecisionPlan" in prompt:
            return self._decision_plan_response(prompt)
        from ..llm.client import _default_llm_backend

        return _default_llm_backend(prompt, system_prompt, 0.0, timeout_ms)

    def _decision_plan_response(self, prompt: str) -> str:
        selected = re.findall(r'"shop_name":\s*"([^"]+)"', prompt)
        ranking_match = re.search(r'- 综合排序:\s*(.*)', prompt)
        ranked = re.findall(r'"shop_name":\s*"([^"]+)"', ranking_match.group(1)) if ranking_match else []
        if "意图类型: comparison" in prompt:
            names = ranked[:2] or selected[:2]
            if len(names) >= 2:
                text = f"这两家里，{names[0]}整体更占优，{names[1]}也可以作为备选。"
            else:
                text = "这两家各有侧重，需要结合你的关注点来选。"
        elif "意图类型: recommendation" in prompt:
            names = ranked[:3] or selected[:3]
            text = "我优先推荐：" + "、".join(names) if names else "我先按你当前条件给出保守推荐。"
        else:
            text = f"{selected[0]}可以重点看当前已查到的信息。" if selected else "我先基于已查到的信息回答。"
        return json.dumps({"natural_response": text}, ensure_ascii=False)


@contextmanager
def _backend_scope(backend: str) -> Iterator[dict[str, Any]]:
    clear_llm_backend()
    meta = {"backend": backend, "skipped": False, "skip_reason": ""}
    if backend == "rule_based":
        try:
            yield meta
        finally:
            clear_llm_backend()
        return
    if backend == "spy":
        set_llm_backend(EvalSpyBackend())
        try:
            yield meta
        finally:
            clear_llm_backend()
        return
    if backend == "real_llm":
        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            meta["skipped"] = True
            meta["skip_reason"] = "missing_api_key"
            yield meta
            return
        from ..llm.openai_backend import OpenAICompatibleBackend

        set_llm_backend(OpenAICompatibleBackend())
        try:
            yield meta
        finally:
            clear_llm_backend()
        return
    raise ValueError(f"Unsupported backend: {backend}")


class EvalCaseValidationError(ValueError):
    """Raised when a JSONL line fails Pydantic schema validation.

    Carries the file path, line number, and the underlying
    ``pydantic.ValidationError`` for diagnostics.
    """

    def __init__(self, file_path: str, line_number: int, cause: ValidationError):
        self.file_path = file_path
        self.line_number = line_number
        self.cause = cause
        messages = "; ".join(str(e) for e in cause.errors())
        super().__init__(
            f"{file_path}:{line_number}: eval case schema validation failed: {messages}"
        )


def load_cases(cases_path: str | Path) -> list[dict[str, Any]]:
    path = Path(cases_path)
    cases: list[dict[str, Any]] = []
    errors: list[EvalCaseValidationError] = []

    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = EvalCase.model_validate_json(line)
            cases.append(parsed.to_dict())
        except ValidationError as exc:
            errors.append(EvalCaseValidationError(str(path), lineno, exc))

    if errors and not cases:
        # All lines failed — raise immediately
        raise errors[0]

    if errors:
        # Some lines failed: emit warnings but keep the valid cases
        import logging
        _logger = logging.getLogger(__name__)
        for err in errors:
            _logger.warning("Skipping invalid eval case: %s", err)

    return cases


def _response_debug_dict(response: AgentResponse) -> dict[str, Any]:
    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return payload.get("debug", {}) if isinstance(payload, dict) else {}
    debug = getattr(response, "debug", None)
    if debug is None:
        return {}
    if isinstance(debug, dict):
        return debug
    return {
        key: value
        for key, value in vars(debug).items()
        if not str(key).startswith("_")
    }


def _turn_trace_from_response(response: AgentResponse, user_text: str) -> TurnTrace:
    debug = _response_debug_dict(response)
    turn_trace_dict = debug.get("turn_trace")
    if isinstance(turn_trace_dict, dict) and turn_trace_dict.get("trace_id"):
        events = turn_trace_dict.get("events", [])
        return TurnTrace(
            **{
                **{k: v for k, v in turn_trace_dict.items() if k != "events"},
                "events": [],
            }
        )
    final_state = {
        "trace_id": response.trace_id,
        "session_id": response.session_id,
        "raw_text": user_text,
        "event_log": debug.get("execution_trace", []),
        "semantic_frame": debug.get("semantic_frame", {}),
        "execution_plan": debug.get("execution_plan", {}),
        "evidence_pack": debug.get("evidence_pack", {}),
        "answer_source": debug.get("answer_source", ""),
        "fallback_reason": debug.get("fallback_reason", ""),
        "answer_verify_passed": debug.get("answer_verify_passed"),
        "answer_verify_violations": debug.get("answer_verify_violations", []),
        "rewrite_count": debug.get("rewrite_count", 0),
        "final_safety_status": debug.get("final_safety_status", ""),
    }
    return build_turn_trace(final_state, user_text=user_text)


def _field_map(turn_trace: TurnTrace, debug: dict[str, Any]) -> dict[str, Any]:
    payload = turn_trace.to_dict()
    payload["reference_resolution_source"] = payload.get("reference_resolution_source")
    payload["final_debug_info"] = debug
    return payload


def _assert_expected(expected: dict[str, Any], turn_trace: TurnTrace, debug: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    fields = _field_map(turn_trace, debug)
    for key, value in expected.items():
        if key in {"forbid_answer_source", "min_candidate_count", "max_rewrite_count", "must_include_violation", "must_not_include_violation", "allow_skipped_if_no_api_key", "turn_assertions"}:
            continue
        if key == "expected_route":
            expected_flow = {
                "recommendation": "recommendation_flow",
                "comparison": "comparison_flow",
            }.get(str(value), str(value))
            if fields.get("selected_flow") != expected_flow and fields.get("task_type") != value:
                failures.append(f"expected_route:{value} observed={fields.get('selected_flow')}")
            continue
        observed = fields.get(key)
        if observed != value:
            failures.append(f"{key}: expected={value!r} observed={observed!r}")

    forbidden_sources = [str(item) for item in expected.get("forbid_answer_source", []) or []]
    if forbidden_sources and str(fields.get("answer_source", "")) in forbidden_sources:
        failures.append(f"forbid_answer_source:{fields.get('answer_source')}")

    min_candidate_count = expected.get("min_candidate_count")
    if min_candidate_count is not None and int(fields.get("candidate_count", 0) or 0) < int(min_candidate_count):
        failures.append(f"min_candidate_count:{min_candidate_count}")

    max_rewrite_count = expected.get("max_rewrite_count")
    if max_rewrite_count is not None and int(fields.get("rewrite_count", 0) or 0) > int(max_rewrite_count):
        failures.append(f"max_rewrite_count:{max_rewrite_count}")

    violations = [str(item) for item in fields.get("answer_verify_violations", []) or []]
    for item in expected.get("must_include_violation", []) or []:
        if not any(str(item) in violation for violation in violations):
            failures.append(f"must_include_violation:{item}")
    for item in expected.get("must_not_include_violation", []) or []:
        if any(str(item) in violation for violation in violations):
            failures.append(f"must_not_include_violation:{item}")

    return failures


def _run_case(case: dict[str, Any], *, backend: str, backend_meta: dict[str, Any]) -> dict[str, Any]:
    session_id = str(case.get("session_id") or case.get("case_id") or "eval_case")
    category = str(case.get("category", "uncategorized") or "uncategorized")
    turns = case.get("turns") or []
    if not isinstance(turns, list):
        turns = []
    if backend_meta.get("skipped") and case.get("expected", {}).get("allow_skipped_if_no_api_key"):
        return {
            "case_id": case.get("case_id", ""),
            "category": category,
            "status": "skipped",
            "reason": backend_meta.get("skip_reason", ""),
            "backend": backend,
        }

    responses: list[AgentResponse] = []
    turn_traces: list[TurnTrace] = []
    for turn in turns:
        text = str((turn or {}).get("user", "") if isinstance(turn, dict) else turn).strip()
        response = run_agent_graph(text, session_id=session_id)
        responses.append(response)
        turn_traces.append(_turn_trace_from_response(response, text))

    response = responses[-1]
    debug = _response_debug_dict(response)
    expected = dict(case.get("expected") or {})
    failures = _assert_expected(expected, turn_traces[-1], debug)

    turn_assertions = expected.get("turn_assertions") or []
    for index, assertion in enumerate(turn_assertions):
        if index >= len(turn_traces):
            failures.append(f"missing_turn_trace:{index}")
            continue
        failures.extend([f"turn_{index}:{item}" for item in _assert_expected(assertion, turn_traces[index], debug)])

    status = "passed" if not failures else "failed"
    return {
        "case_id": case.get("case_id", ""),
        "category": category,
        "status": status,
        "backend": backend,
        "query": str(turns[-1].get("user", "") if turns and isinstance(turns[-1], dict) else (turns[-1] if turns else "")),
        "failures": failures,
        "trace_summary": turn_traces[-1].to_dict(),
        "final_debug_info": debug,
        "turn_traces": [trace.to_dict() for trace in turn_traces],
    }


def _write_reports(report: dict[str, Any], output_dir: str | Path | None = None) -> dict[str, str]:
    target_dir = Path(output_dir) if output_dir else _REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "latest_eval_report.json"
    md_path = target_dir / "latest_eval_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_report_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _report_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    metrics = report.get("metrics", {})
    lines = [
        "# Eval Report",
        "",
        f"- total_cases: {summary.get('total_cases', 0)}",
        f"- passed: {summary.get('passed', 0)}",
        f"- failed: {summary.get('failed', 0)}",
        f"- skipped: {summary.get('skipped', 0)}",
        f"- pass_rate: {metrics.get('pass_rate', 0.0)}",
        f"- fallback_rate: {metrics.get('fallback_rate', 0.0)}",
        f"- rewrite_rate: {metrics.get('rewrite_rate', 0.0)}",
        f"- template_fallback_rate: {metrics.get('template_fallback_rate', 0.0)}",
        f"- raw_text_fallback_rate: {metrics.get('raw_text_fallback_rate', 0.0)}",
        "",
        "## Cases",
    ]
    for item in report.get("cases", []):
        lines.append(f"- {item.get('case_id')}: {item.get('status')}")
        if item.get("failures"):
            lines.append(f"  failures: {', '.join(item.get('failures', []))}")
    return "\n".join(lines) + "\n"


def run_eval(
    cases: list[dict[str, Any]],
    *,
    backend: str = "rule_based",
    output_dir: str | Path | None = None,
    write_reports: bool = True,
) -> dict[str, Any]:
    reset_session_store()
    results: list[dict[str, Any]] = []

    with _backend_scope(backend) as backend_meta:
        for case in cases:
            if not isinstance(case, dict):
                continue
            results.append(_run_case(case, backend=backend, backend_meta=backend_meta))

    total_cases = len(results)
    passed = sum(1 for item in results if item.get("status") == "passed")
    failed = sum(1 for item in results if item.get("status") == "failed")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    category_stats: dict[str, dict[str, int]] = {}
    turn_traces: list[TurnTrace] = []
    for item in results:
        category = str(item.get("category", "uncategorized"))
        stats = category_stats.setdefault(category, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        stats["total"] += 1
        stats[str(item.get("status"))] += 1
        if item.get("status") != "skipped":
            turn_traces.append(TurnTrace(**{k: v for k, v in item.get("trace_summary", {}).items() if k != "events"}, events=[]))

    metrics = merge_eval_metrics(
        aggregate_turn_trace_metrics(turn_traces),
        total_cases=total_cases,
        passed=passed,
        failed=failed,
        skipped=skipped,
        category_stats=category_stats,
    )
    report = {
        "summary": {
            "total_cases": total_cases,
            "total": total_cases,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "metrics": metrics,
        "cases": results,
    }
    if write_reports:
        report["report_paths"] = _write_reports(report, output_dir=output_dir)
    return report


def run_eval_file(
    cases_path: str | Path,
    *,
    backend: str = "rule_based",
    output_dir: str | Path | None = None,
    write_reports: bool = True,
) -> dict[str, Any]:
    return run_eval(load_cases(cases_path), backend=backend, output_dir=output_dir, write_reports=write_reports)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local life eval cases.")
    parser.add_argument("--cases", required=True, help="JSONL cases path")
    parser.add_argument("--backend", default="rule_based", choices=["rule_based", "spy", "real_llm"])
    parser.add_argument("--output-dir", default=str(_REPORT_DIR))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = run_eval_file(args.cases, backend=args.backend, output_dir=args.output_dir, write_reports=True)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(json.dumps({k: report["metrics"][k] for k in ("pass_rate", "fallback_rate", "rewrite_rate", "template_fallback_rate", "raw_text_fallback_rate")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
