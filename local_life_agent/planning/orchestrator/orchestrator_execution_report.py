from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .worker_result import WorkerResult


@dataclass(frozen=True)
class OrchestratorExecutionReport:
    """Execution metadata for a single complex orchestrator worker."""

    task_id: str
    workflow_name: str
    status: str
    duration_ms: int = 0
    timed_out: bool = False
    skipped: bool = False
    cache_hit: bool = False
    blocked_by: list[str] = field(default_factory=list)
    error_code: str = ""
    started_at: str = ""
    finished_at: str = ""
    trace_summary: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_worker_result(
        cls,
        worker_result: WorkerResult,
        *,
        duration_ms: int = 0,
        timed_out: bool | None = None,
        skipped: bool | None = None,
        blocked_by: list[str] | None = None,
        cache_hit: bool | None = None,
        error_code: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> "OrchestratorExecutionReport":
        return cls(
            task_id=worker_result.task_id,
            workflow_name=worker_result.workflow_name,
            status=worker_result.status,
            duration_ms=max(int(duration_ms or worker_result.duration_ms or 0), 0),
            timed_out=bool(worker_result.timed_out if timed_out is None else timed_out),
            skipped=bool(worker_result.skipped if skipped is None else skipped),
            cache_hit=bool(worker_result.cache_hit if cache_hit is None else cache_hit),
            blocked_by=list(blocked_by if blocked_by is not None else worker_result.blocked_by),
            error_code=str(error_code if error_code is not None else worker_result.error_code or ""),
            started_at=str(started_at or worker_result.trace_summary.get("started_at", "") or ""),
            finished_at=str(finished_at or worker_result.trace_summary.get("finished_at", "") or ""),
            trace_summary=dict(worker_result.trace_summary),
            provenance=dict(worker_result.provenance),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "duration_ms": max(int(self.duration_ms or 0), 0),
            "timed_out": bool(self.timed_out),
            "skipped": bool(self.skipped),
            "cache_hit": bool(self.cache_hit),
            "blocked_by": list(self.blocked_by),
            "error_code": self.error_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "trace_summary": dict(self.trace_summary),
            "provenance": dict(self.provenance),
        }
