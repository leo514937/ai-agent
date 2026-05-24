from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional
from uuid import uuid4

from learning_agent_service.domain.memory import MemoryTrace


@dataclass
class MemoryTraceRecorder:
    """轻量 trace 记录器，用于收集单轮记忆行为。"""

    session_id: str
    turn_id: str
    trace_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)
    trace: MemoryTrace = field(init=False)

    def __post_init__(self) -> None:
        self.trace = MemoryTrace(
            trace_id=self.trace_id or f"memory-trace:{uuid4().hex}",
            session_id=self.session_id,
            turn_id=self.turn_id,
            extra=dict(self.extra),
        )

    def record_retrieved(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.retrieved, memory_ids)

    def record_injected(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.injected, memory_ids)

    def record_skipped(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.skipped, memory_ids)

    def record_candidates(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.candidates, memory_ids)

    def record_promoted(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.promoted, memory_ids)

    def record_rejected(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.rejected, memory_ids)

    def record_decision_reason(self, candidate_id: str, reason: str) -> None:
        if candidate_id and reason:
            self.trace.decision_reasons[candidate_id] = reason

    def record_conflict_ids(self, memory_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.conflict_ids, memory_ids)

    def record_deletion_job_ids(self, job_ids: Iterable[str]) -> None:
        self._extend_unique(self.trace.deletion_job_ids, job_ids)

    def record_skip_reason(self, candidate_id: str, reason: str) -> None:
        if candidate_id and reason:
            self.trace.skip_reasons[candidate_id] = reason

    def snapshot(self) -> MemoryTrace:
        return self.trace

    def _extend_unique(self, target: List[str], values: Iterable[str]) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)
