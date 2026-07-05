from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import contextmanager
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from .. import config
from ..agent import AgentResponse, run_agent_graph
from ..llm.client import clear_llm_backend, set_llm_backend
from ..observability.metrics import aggregate_turn_trace_metrics, merge_eval_metrics
from ..observability.trace import TraceSpanRecord, TurnTrace, build_turn_trace
from ..session.store import reset_session_store
from .eval_case_schema import EvalCase


_REPORT_DIR = Path(__file__).resolve().parent / "reports"
_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"


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
                if "不确定项/无法确认项" in prompt and "[]" not in prompt.split("不确定项/无法确认项:", 1)[1].splitlines()[0]:
                    text = f"这两家目前信息还不够完整，我暂时无法确认谁更好，先参考{names[0]}和{names[1]}的已知信息。"
                else:
                    text = f"综合当前已知信息，我会优先推荐{names[0]}，其次是{names[1]}。"
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
        api_key = config.load_llm_api_key()
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
        debug_payload = payload.get("debug", {}) if isinstance(payload, dict) else {}
        if isinstance(debug_payload, dict):
            debug_payload.setdefault("answer_text", getattr(response, "answer_text", ""))
            debug_payload.setdefault("clarification", getattr(response, "clarification", None))
        return debug_payload
    debug = getattr(response, "debug", None)
    if debug is None:
        return {}
    if isinstance(debug, dict):
        debug.setdefault("answer_text", getattr(response, "answer_text", ""))
        debug.setdefault("clarification", getattr(response, "clarification", None))
        return debug
    payload = {
        key: value
        for key, value in vars(debug).items()
        if not str(key).startswith("_")
    }
    payload.setdefault("answer_text", getattr(response, "answer_text", ""))
    payload.setdefault("clarification", getattr(response, "clarification", None))
    return payload


def _turn_trace_from_response(response: AgentResponse, user_text: str) -> TurnTrace:
    debug = _response_debug_dict(response)
    turn_trace_seed = debug.get("turn_trace") if isinstance(debug.get("turn_trace"), dict) else {}
    final_state = {
        "trace_id": response.trace_id,
        "session_id": response.session_id,
        "raw_text": user_text,
        "event_log": debug.get("execution_trace", []),
        "semantic_frame": {**turn_trace_seed, **(debug.get("semantic_frame", {}) or {})},
        "execution_plan": debug.get("execution_plan", {}),
        "evidence_pack": debug.get("evidence_pack", {}),
        "answer_source": debug.get("answer_source", ""),
        "fallback_reason": debug.get("fallback_reason", ""),
        "answer_verify_passed": debug.get("answer_verify_passed"),
        "answer_verify_violations": debug.get("answer_verify_violations", []),
        "rewrite_count": debug.get("rewrite_count", 0),
        "final_safety_status": debug.get("final_safety_status", ""),
        "resolved_target": debug.get("resolved_target", {}),
        "resolve_shop_result": debug.get("resolve_shop_result", {}),
        "comparison_result": debug.get("comparison_result", {}),
        "tool_results": debug.get("tool_results", {}),
        "tool_result_set": debug.get("tool_result_set", {}),
        "session_state_before": debug.get("session_state_before", {}),
        "session_state_after": debug.get("session_state_after", {}),
        "target_status": debug.get("target_status", turn_trace_seed.get("target_status", "")),
        "llm_backend": debug.get("llm_backend", turn_trace_seed.get("llm_backend", "")),
        "semantic_source": debug.get("semantic_source", turn_trace_seed.get("semantic_source", "")),
        "llm_called": debug.get("llm_called", turn_trace_seed.get("llm_called", False)),
        "task_type": debug.get("task_type", turn_trace_seed.get("task_type", "")),
        "decision_type": debug.get("decision_type", turn_trace_seed.get("decision_type", "")),
        "top_intent": debug.get("top_intent", turn_trace_seed.get("top_intent", "")),
        "primary_task": debug.get("primary_task", turn_trace_seed.get("primary_task", "")),
        "selected_flow": debug.get("selected_flow", turn_trace_seed.get("selected_flow", "")),
    }
    built_trace = build_turn_trace(final_state, user_text=user_text)
    turn_trace_dict = debug.get("turn_trace")
    if isinstance(turn_trace_dict, dict) and turn_trace_dict.get("trace_id"):
        merged = built_trace.to_dict()
        for key, value in turn_trace_dict.items():
            if key == "events":
                continue
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            merged[key] = value
        events = merged.get("events") or []
        if isinstance(events, list):
            merged["events"] = [TraceSpanRecord(**event) if isinstance(event, dict) else event for event in events]
        allowed_fields = {field.name for field in dataclass_fields(TurnTrace)}
        filtered = {key: value for key, value in merged.items() if key in allowed_fields}
        return TurnTrace(**filtered)
    return built_trace


def _field_map(turn_trace: TurnTrace, debug: dict[str, Any]) -> dict[str, Any]:
    payload = turn_trace.to_dict()
    payload["reference_resolution_source"] = payload.get("reference_resolution_source")
    payload["final_debug_info"] = debug
    payload["tool_result_count"] = _tool_result_count(debug)
    payload["tool_results_present"] = payload["tool_result_count"] > 0
    payload["candidate_status"] = payload.get("candidate_status") or payload.get("target_status") or payload.get("target_resolve_status")
    payload["pending_clarification"] = _pending_clarification(debug)
    payload["clarify_reason"] = _clarify_reason(debug, turn_trace)
    payload["terminal"] = _infer_terminal(debug, turn_trace)
    payload["fake_success_risk"] = _has_fake_success_risk(debug, turn_trace)
    payload["evidence_complete"] = bool(payload.get("evidence_complete", not bool(payload.get("evidence_incomplete", False))))
    payload["verifier_result"] = payload.get("verifier_result") or ("pass" if payload.get("answer_verify_passed") else "fail" if payload.get("answer_verify_passed") is not None else "")
    payload["verifier_failure_code"] = payload.get("verifier_failure_code") or (payload.get("answer_verify_violations", [""]) or [""])[0]
    payload["verifier_unknown_fields"] = payload.get("verifier_unknown_fields") or []
    payload["verifier_unsupported_claims"] = payload.get("verifier_unsupported_claims") or []
    payload["template_fallback_used"] = bool(payload.get("template_fallback_used") or str(payload.get("answer_source") or "") == "template_fallback")
    payload["raw_text_fallback_source"] = payload.get("raw_text_fallback_source") or payload.get("fallback_reason") or ""
    return payload


def _assert_expected(expected: dict[str, Any], turn_trace: TurnTrace, debug: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    fields = _field_map(turn_trace, debug)
    for key, value in expected.items():
        if key in {
            "forbid_answer_source",
            "min_candidate_count",
            "max_rewrite_count",
            "must_include_violation",
            "must_not_include_violation",
            "allow_skipped_if_no_api_key",
            "turn_assertions",
            "expect_llm_backend",
            "expect_llm_backend_kind",
            "expect_llm_backend_family",
            "forbid_llm_backend_kinds",
            "forbid_llm_backend_families",
            "forbid_semantic_sources",
            "forbid_tool_backends",
            "expect_answer_source",
            "forbid_answer_sources",
            "expect_legacy_used",
            "expect_fallback_used",
            "expect_evidence_incomplete",
            "expect_terminal",
            "forbid_fake_success",
            "require_tool_results",
            "require_clarify_on_ambiguous_candidates",
            "require_trusted_failure_on_empty_tools",
        }:
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

    expect_llm_backend = expected.get("expect_llm_backend")
    if expect_llm_backend is not None and str(fields.get("llm_backend") or "") != str(expect_llm_backend):
        failures.append(f"expect_llm_backend: expected={expect_llm_backend!r} observed={fields.get('llm_backend')!r}")

    expect_llm_backend_kind = expected.get("expect_llm_backend_kind")
    if expect_llm_backend_kind is not None and str(fields.get("llm_backend_kind") or "") != str(expect_llm_backend_kind):
        failures.append(f"expect_llm_backend_kind: expected={expect_llm_backend_kind!r} observed={fields.get('llm_backend_kind')!r}")

    expect_llm_backend_family = expected.get("expect_llm_backend_family")
    if expect_llm_backend_family is not None and str(fields.get("llm_backend_family") or "") != str(expect_llm_backend_family):
        failures.append(f"expect_llm_backend_family: expected={expect_llm_backend_family!r} observed={fields.get('llm_backend_family')!r}")

    forbidden_llm_backend_kinds = [str(item) for item in expected.get("forbid_llm_backend_kinds", []) or []]
    if forbidden_llm_backend_kinds and str(fields.get("llm_backend_kind") or "") in forbidden_llm_backend_kinds:
        failures.append(f"forbid_llm_backend_kinds:{fields.get('llm_backend_kind')}")

    forbidden_llm_backend_families = [str(item) for item in expected.get("forbid_llm_backend_families", []) or []]
    if forbidden_llm_backend_families and str(fields.get("llm_backend_family") or "") in forbidden_llm_backend_families:
        failures.append(f"forbid_llm_backend_families:{fields.get('llm_backend_family')}")

    forbidden_semantic_sources = [str(item) for item in expected.get("forbid_semantic_sources", []) or []]
    if forbidden_semantic_sources and str(fields.get("semantic_source") or "") in forbidden_semantic_sources:
        failures.append(f"forbid_semantic_sources:{fields.get('semantic_source')}")

    forbidden_tool_backends = [str(item) for item in expected.get("forbid_tool_backends", []) or []]
    if forbidden_tool_backends and str(fields.get("tool_backend") or "") in forbidden_tool_backends:
        failures.append(f"forbid_tool_backends:{fields.get('tool_backend')}")

    expect_answer_source = expected.get("expect_answer_source")
    if expect_answer_source is not None and str(fields.get("answer_source") or "") != str(expect_answer_source):
        failures.append(f"expect_answer_source: expected={expect_answer_source!r} observed={fields.get('answer_source')!r}")

    forbidden_answer_sources = [str(item) for item in expected.get("forbid_answer_sources", []) or []]
    if forbidden_answer_sources and str(fields.get("answer_source") or "") in forbidden_answer_sources:
        failures.append(f"forbid_answer_sources:{fields.get('answer_source')}")

    for key in ("expect_legacy_used", "expect_fallback_used", "expect_evidence_incomplete"):
        if key in expected and expected.get(key) is not None:
            field_name = key.removeprefix("expect_")
            observed = fields.get(field_name)
            if bool(observed) != bool(expected.get(key)):
                failures.append(f"{key}: expected={bool(expected.get(key))!r} observed={bool(observed)!r}")

    expect_terminal = expected.get("expect_terminal")
    if expect_terminal is not None and str(fields.get("terminal") or "") != str(expect_terminal):
        failures.append(f"expect_terminal: expected={expect_terminal!r} observed={fields.get('terminal')!r}")

    if expected.get("forbid_fake_success") and fields.get("fake_success_risk"):
        failures.append("forbid_fake_success: fake_success_risk_detected")

    require_tool_results = expected.get("require_tool_results")
    if require_tool_results is True and not fields.get("tool_results_present"):
        failures.append("require_tool_results: no_real_tool_results")
    if require_tool_results is False and fields.get("tool_result_count", 0) not in (0, None):
        failures.append(f"require_tool_results: expected_no_tool_results observed={fields.get('tool_result_count')}")

    if expected.get("require_clarify_on_ambiguous_candidates"):
        if fields.get("terminal") != "clarify":
            failures.append(f"require_clarify_on_ambiguous_candidates: terminal={fields.get('terminal')}")
        clarify_reason = str(fields.get("clarify_reason") or "")
        if "ambiguous" not in clarify_reason:
            failures.append(f"require_clarify_on_ambiguous_candidates: clarify_reason={clarify_reason!r}")

    if expected.get("require_trusted_failure_on_empty_tools"):
        if fields.get("terminal") not in {"clarify", "trusted_failure"}:
            failures.append(f"require_trusted_failure_on_empty_tools: terminal={fields.get('terminal')}")
        if fields.get("tool_results_present"):
            failures.append("require_trusted_failure_on_empty_tools: unexpected_tool_results_present")
        if str(fields.get("answer_source") or "") in {"template", "template_fallback"}:
            failures.append(f"require_trusted_failure_on_empty_tools: answer_source={fields.get('answer_source')}")

    return failures


def _tool_result_count(debug: dict[str, Any]) -> int:
    tool_results = debug.get("tool_results") or debug.get("final_debug_info", {}).get("tool_results") or {}
    if isinstance(tool_results, dict):
        return len(tool_results)
    return 0


def _pending_clarification(debug: dict[str, Any]) -> dict[str, Any]:
    for key in ("session_state_after", "session_state_before"):
        state = debug.get(key) or {}
        if isinstance(state, dict):
            pending = state.get("pending_clarification")
            if isinstance(pending, dict):
                return pending
    return {}


def _clarify_reason(debug: dict[str, Any], turn_trace: TurnTrace) -> str:
    pending = _pending_clarification(debug)
    reason = pending.get("reason") if isinstance(pending, dict) else None
    if reason:
        return str(reason)
    if turn_trace.target_status in {"AMBIGUOUS", "LOW_CONFIDENCE"}:
        return "ambiguous_candidates"
    if turn_trace.target_status == "NOT_FOUND":
        return "tool_empty_or_not_found"
    return ""


def _infer_terminal(debug: dict[str, Any], turn_trace: TurnTrace) -> str:
    if debug.get("clarification") or _pending_clarification(debug):
        return "clarify"
    if turn_trace.target_status == "NOT_FOUND" and _tool_result_count(debug) == 0:
        return "trusted_failure"
    return "final_answer"


def _has_fake_success_risk(debug: dict[str, Any], turn_trace: TurnTrace) -> bool:
    if (turn_trace.answer_source or "") in {"template", "template_fallback"} and (turn_trace.final_safety_status or "") == "safe":
        return True
    if not _tool_result_count(debug) and turn_trace.target_status == "RESOLVED" and (turn_trace.answer_source or "").startswith("llm_verbalizer"):
        text = str(debug.get("answer_text", "") or "")
        if text:
            return True
    return False


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
        try:
            response = run_agent_graph(text, session_id=session_id)
        except Exception as exc:
            error_name = type(exc).__name__
            error_message = str(exc)
            failure_trace = {
                "trace_id": f"trace_{case.get('case_id', 'eval_case')}_runtime_error",
                "session_id": session_id,
                "turn_id": "",
                "user_text": text,
                "top_intent": None,
                "top_intent_source": None,
                "top_intent_router_llm_available": None,
                "top_intent_router_backend": None,
                "top_intent_router_error_type": error_name,
                "top_intent_router_error_message": error_message,
                "semantic_source": None,
                "llm_backend": None,
                "tool_backend": None,
                "answer_source": None,
                "fallback_reason": error_message,
                "answer_verify_passed": False,
                "answer_verify_violations": [f"runtime_exception:{error_name}"],
                "rewrite_count": 0,
                "final_safety_status": "fallback",
                "target_status": "NOT_FOUND",
                "candidate_status": "NOT_FOUND",
                "reference_resolution_source": "runtime_exception",
                "candidate_count": 0,
                "candidate_source": None,
                "resolver_tool_called": False,
                "resolver_tool_name": None,
                "resolver_tool_backend": None,
                "resolver_tool_result_count": 0,
                "resolver_error_type": error_name,
                "resolver_error_message": error_message,
                "fallback_used": False,
                "template_fallback_used": False,
                "legacy_used": False,
                "evidence_incomplete": False,
                "verifier_result": "fail",
                "verifier_failure_code": f"runtime_exception:{error_name}",
                "verifier_unknown_fields": [],
                "verifier_unsupported_claims": [],
                "raw_text_fallback_source": "runtime_exception",
                "events": [],
            }
            return {
                "case_id": case.get("case_id", ""),
                "category": category,
                "status": "failed",
                "backend": backend,
                "profile": str(case.get("profile", "") or ""),
                "query": text,
                "failures": [f"runtime_exception:{error_name}:{error_message}"],
                "trace_summary": failure_trace,
                "final_debug_info": {"runtime_exception": error_message},
                "turn_traces": [failure_trace],
            }
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
        "profile": str(case.get("profile", "") or ""),
        "query": str(turns[-1].get("user", "") if turns and isinstance(turns[-1], dict) else (turns[-1] if turns else "")),
        "failures": failures,
        "trace_summary": _field_map(turn_traces[-1], debug),
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
        f"- real_e2e_veto_count: {metrics.get('real_e2e_veto_count', 0)}",
        "",
        "## Cases",
    ]
    for item in report.get("cases", []):
        trace_summary = item.get("trace_summary", {}) or {}
        lines.append(f"- {item.get('case_id')}: {item.get('status')} terminal={trace_summary.get('terminal', '')} llm={trace_summary.get('llm_backend', '')} tool={trace_summary.get('tool_backend', '')}")
        if item.get("failures"):
            lines.append(f"  failures: {', '.join(item.get('failures', []))}")
    return "\n".join(lines) + "\n"


def _load_profile(profile_path: str | Path) -> dict[str, Any]:
    path = Path(profile_path)
    if not path.exists() and not path.is_absolute():
        path = (_PROFILE_DIR / path).resolve()
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to load eval profiles") from exc
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Profile must be a mapping: {path}")
    data["_profile_path"] = str(path)
    return data


def run_eval(
    cases: list[dict[str, Any]],
    *,
    backend: str = "spy",
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
    real_e2e_veto_count = 0
    for item in results:
        category = str(item.get("category", "uncategorized"))
        stats = category_stats.setdefault(category, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        stats["total"] += 1
        stats[str(item.get("status"))] += 1
        if item.get("status") == "failed" and category == "real_e2e_acceptance":
            real_e2e_veto_count += len(item.get("failures", []))
        if item.get("status") != "skipped":
            trace_payload = item.get("trace_summary", {}) or {}
            allowed = set(TurnTrace.__dataclass_fields__.keys())
            turn_traces.append(TurnTrace(**{k: v for k, v in trace_payload.items() if k in allowed and k != "events"}, events=[]))

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
        "metrics": {**metrics, "real_e2e_veto_count": real_e2e_veto_count},
        "cases": results,
    }
    if write_reports:
        report["report_paths"] = _write_reports(report, output_dir=output_dir)
    return report


def run_eval_file(
    cases_path: str | Path,
    *,
    backend: str = "spy",
    output_dir: str | Path | None = None,
    write_reports: bool = True,
) -> dict[str, Any]:
    return run_eval(load_cases(cases_path), backend=backend, output_dir=output_dir, write_reports=write_reports)


def run_eval_profile(
    profile_path: str | Path,
    *,
    cases_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    write_reports: bool = True,
) -> dict[str, Any]:
    profile = _load_profile(profile_path)
    resolved_cases_path = cases_path or profile.get("cases")
    if not resolved_cases_path:
        raise ValueError(f"profile missing cases: {profile_path}")
    profile_file = Path(str(profile.get("_profile_path", profile_path)))
    resolved_cases_path = Path(str(resolved_cases_path))
    if not resolved_cases_path.is_absolute():
        resolved_cases_path = (profile_file.parent / resolved_cases_path).resolve()
    backend = str(profile.get("backend", "spy"))
    if str(profile.get("name", "")) == "real_e2e":
        from .. import config

        if backend != "real_llm":
            raise ValueError("real_e2e profile must use backend=real_llm")
        if str(config.TOOL_BACKEND) not in {"db", "java_api"}:
            raise ValueError(f"real_e2e requires TOOL_BACKEND in {{'db','java_api'}}, got {config.TOOL_BACKEND!r}")
        if not config.load_llm_api_key():
            raise RuntimeError("real_e2e requires a real LLM API key")
    cases = load_cases(resolved_cases_path)
    for case in cases:
        if isinstance(case, dict):
            case["profile"] = str(profile.get("name", ""))
    report = run_eval(cases, backend=backend, output_dir=output_dir, write_reports=write_reports)
    report["profile"] = {
        "name": profile.get("name", ""),
        "mode": profile.get("mode", ""),
        "backend": backend,
        "tool_backend": profile.get("tool_backend"),
        "cases": str(resolved_cases_path),
        "description": profile.get("description", ""),
        "acceptance": profile.get("acceptance", {}),
    }
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local life eval cases.")
    parser.add_argument("--cases", help="JSONL cases path")
    parser.add_argument("--profile", help="YAML profile path")
    parser.add_argument("--backend", default="spy", choices=["spy", "real_llm", "rule_based"])
    parser.add_argument("--output-dir", default=str(_REPORT_DIR))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.profile:
        report = run_eval_profile(
            args.profile,
            cases_path=args.cases,
            output_dir=args.output_dir,
            write_reports=True,
        )
    else:
        if not args.cases:
            raise SystemExit("--cases or --profile is required")
        report = run_eval_file(args.cases, backend=args.backend, output_dir=args.output_dir, write_reports=True)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(json.dumps({k: report["metrics"][k] for k in ("pass_rate", "fallback_rate", "rewrite_rate", "template_fallback_rate", "raw_text_fallback_rate", "real_e2e_veto_count")}, ensure_ascii=False, indent=2))
    return 0 if report["summary"].get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
