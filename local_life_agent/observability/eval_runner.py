"""Backward-compatible eval runner shim."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ..agent import run_agent_graph
from ..eval.run_eval import load_cases, run_eval_file


def run_eval(
    test_cases: list[dict[str, Any]],
    *,
    backend: str = "rule_based",
    write_reports: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    _run_eval_module = import_module("local_life_agent.eval.run_eval")
    original = _run_eval_module.run_agent_graph
    _run_eval_module.run_agent_graph = run_agent_graph
    try:
        report = _run_eval_module.run_eval(
            test_cases,
            backend=backend,
            write_reports=write_reports,
            output_dir=output_dir,
        )
        summary = report.get("summary", {})
        report["summary"] = {
            "total": summary.get("total_cases", summary.get("total", 0)),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
        }
        legacy_cases = []
        for item in report.get("cases", []):
            legacy_cases.append({**item, "passed": item.get("status") == "passed"})
        report["cases"] = legacy_cases
        return report
    finally:
        _run_eval_module.run_agent_graph = original


def run_eval_cases(test_cases: list[dict[str, Any]], *, backend: str = "rule_based") -> dict[str, Any]:
    return run_eval(test_cases, backend=backend, write_reports=False)


__all__ = ["load_cases", "run_eval", "run_eval_file", "run_eval_cases", "run_agent_graph"]
