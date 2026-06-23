"""Eval helpers for regression runs."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any


def load_cases(cases_path: str | Path) -> list[dict[str, Any]]:
    return import_module("local_life_agent.eval.run_eval").load_cases(cases_path)


def run_eval(cases: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return import_module("local_life_agent.eval.run_eval").run_eval(cases, **kwargs)


def run_eval_file(cases_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return import_module("local_life_agent.eval.run_eval").run_eval_file(cases_path, **kwargs)


__all__ = ["load_cases", "run_eval", "run_eval_file"]
