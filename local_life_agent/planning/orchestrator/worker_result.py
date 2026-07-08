from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


def _dump(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return value


@dataclass
class WorkerResult:
    """Isolated output of one subtask worker."""

    task_id: str
    workflow_name: str
    status: str = "completed"
    state_patch: dict[str, Any] = field(default_factory=dict)
    evidence_pack: Any = None
    decision_plan: Any = None
    response_directive: Any = None
    provenance: dict[str, Any] = field(default_factory=dict)
    trace_summary: dict[str, Any] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    duration_ms: int = 0
    timed_out: bool = False
    skipped: bool = False
    blocked_by: list[str] = field(default_factory=list)
    cache_hit: bool = False
    error_code: str = ""
    deadline_ms: int = 0

    @classmethod
    def from_patch(
        cls,
        *,
        task_id: str,
        workflow_name: str,
        patch: dict[str, Any],
        provenance: dict[str, Any] | None = None,
        trace_summary: dict[str, Any] | None = None,
    ) -> "WorkerResult":
        patch_copy = deepcopy(dict(patch or {}))
        return cls(
            task_id=task_id,
            workflow_name=workflow_name,
            status=str(patch_copy.get("workflow_run_status") or patch_copy.get("status") or "completed"),
            state_patch=patch_copy,
            evidence_pack=patch_copy.get("evidence_pack"),
            decision_plan=patch_copy.get("decision_plan") or patch_copy.get("answer_plan"),
            response_directive=patch_copy.get("response_directive"),
            provenance=dict(provenance or {}),
            trace_summary=dict(trace_summary or {}),
            conflicts=[str(item).strip() for item in (patch_copy.get("conflicts") or []) if str(item).strip()],
            duration_ms=max(int(patch_copy.get("duration_ms", 0) or 0), 0),
            timed_out=bool(patch_copy.get("timed_out", False)),
            skipped=bool(patch_copy.get("skipped", False)),
            blocked_by=[str(item).strip() for item in (patch_copy.get("blocked_by") or []) if str(item).strip()],
            cache_hit=bool(patch_copy.get("cache_hit", False)),
            error_code=str(patch_copy.get("error_code", "") or "").strip(),
            deadline_ms=max(int(patch_copy.get("deadline_ms", 0) or 0), 0),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "WorkerResult":
        data = dict(value or {})
        state_patch = dict(data.get("state_patch") or {})
        evidence_pack = data.get("evidence_pack")
        decision_plan = data.get("decision_plan")
        response_directive = data.get("response_directive")
        return cls(
            task_id=str(data.get("task_id", "") or "").strip(),
            workflow_name=str(data.get("workflow_name", "") or "").strip(),
            status=str(data.get("status", "completed") or "completed"),
            state_patch=state_patch,
            evidence_pack=evidence_pack,
            decision_plan=decision_plan,
            response_directive=response_directive,
            provenance=dict(data.get("provenance") or {}),
            trace_summary=dict(data.get("trace_summary") or {}),
            conflicts=[str(item).strip() for item in (data.get("conflicts") or []) if str(item).strip()],
            duration_ms=max(int(data.get("duration_ms", 0) or 0), 0),
            timed_out=bool(data.get("timed_out", False)),
            skipped=bool(data.get("skipped", False)),
            blocked_by=[str(item).strip() for item in (data.get("blocked_by") or []) if str(item).strip()],
            cache_hit=bool(data.get("cache_hit", False)),
            error_code=str(data.get("error_code", "") or "").strip(),
            deadline_ms=max(int(data.get("deadline_ms", 0) or 0), 0),
        )

    def clone_state_patch(self) -> dict[str, Any]:
        return deepcopy(self.state_patch)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "state_patch": deepcopy(self.state_patch),
            "evidence_pack": deepcopy(_dump(self.evidence_pack)),
            "decision_plan": deepcopy(_dump(self.decision_plan)),
            "response_directive": deepcopy(_dump(self.response_directive)),
            "provenance": deepcopy(self.provenance),
            "trace_summary": deepcopy(self.trace_summary),
            "conflicts": list(self.conflicts),
            "duration_ms": max(int(self.duration_ms or 0), 0),
            "timed_out": bool(self.timed_out),
            "skipped": bool(self.skipped),
            "blocked_by": list(self.blocked_by),
            "cache_hit": bool(self.cache_hit),
            "error_code": self.error_code,
            "deadline_ms": max(int(self.deadline_ms or 0), 0),
        }
