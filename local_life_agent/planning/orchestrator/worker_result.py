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
        }
