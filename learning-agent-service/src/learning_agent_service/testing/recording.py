from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .harness import TraceHarnessRecorder


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            return {}
    return {}


def _read_field(result: Any, *names: str, default: Any = None) -> Any:
    if isinstance(result, Mapping):
        for name in names:
            if name in result:
                value = result.get(name)
                if value is not None:
                    return value
        return default
    for name in names:
        value = getattr(result, name, None)
        if value is not None:
            return value
    return default


@dataclass
class TraceWriter:
    path: str | Path
    append: bool = True

    def write(self, record: Mapping[str, Any]) -> Path:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append else "w"
        with path.open(mode, encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path

    def write_many(self, records: list[Mapping[str, Any]]) -> Path:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append else "w"
        with path.open(mode, encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return path


@dataclass
class EvalCaseRecorder:
    trace_writer: TraceWriter | None = None
    trace_harness: TraceHarnessRecorder = field(default_factory=TraceHarnessRecorder)

    def build_record(self, case_id: str, result: Any, *, case: Any | None = None, state: Any | None = None) -> dict[str, Any]:
        actual_trace = _as_dict(_read_field(result, "actual_trace", default={}))
        actual_metrics = _as_dict(_read_field(result, "actual_metrics", default={}))
        if not actual_metrics:
            actual_metrics = _as_dict(actual_trace.get("metrics"))
        trace_snapshot = self.trace_harness.record(state, case_id=case_id) if state is not None else {}
        if trace_snapshot:
            actual_trace = {**trace_snapshot, **actual_trace}

        record = {
            "case_id": case_id,
            "passed": bool(_read_field(result, "passed", default=False)),
            "actual_response_mode": str(_read_field(result, "actual_response_mode", default="unknown") or "unknown"),
            "actual_answer": str(_read_field(result, "actual_answer", default="") or ""),
            "failures": list(_read_field(result, "failures", default=[]) or []),
            "actual_trace": actual_trace,
            "actual_metrics": actual_metrics,
            "final_answer_audit": _as_dict(actual_trace.get("final_answer_audit") or actual_metrics.get("final_answer_audit")),
            "final_answer_safety": _as_dict(actual_trace.get("final_answer_safety") or actual_metrics.get("final_answer_safety")),
            "answer_lint": _as_dict(actual_trace.get("answer_lint") or actual_metrics.get("answer_lint")),
        }
        if case is not None:
            record["case"] = _as_dict(case)
            if not record["case"] and hasattr(case, "__dict__"):
                record["case"] = dict(case.__dict__)
        return record

    def record_case(
        self,
        case_id: str,
        result: Any,
        *,
        case: Any | None = None,
        state: Any | None = None,
        write: bool = True,
    ) -> dict[str, Any]:
        record = self.build_record(case_id, result, case=case, state=state)
        if write and self.trace_writer is not None:
            self.trace_writer.write(record)
        return record


__all__ = ["EvalCaseRecorder", "TraceWriter"]
