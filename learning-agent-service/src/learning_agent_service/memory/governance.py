from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable, List

from learning_agent_service.domain.memory import (
    MemoryCandidate,
    MemoryDeletionStatus,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)


@dataclass(frozen=True)
class MemoryGovernancePolicyConfig:
    low_confidence_threshold: float = 0.35
    low_stability_threshold: float = 0.45
    confirmation_sensitivity_levels: tuple[MemorySensitivity, ...] = (
        MemorySensitivity.CONFIDENTIAL,
        MemorySensitivity.RESTRICTED,
    )
    default_ttl_seconds: int = 7 * 24 * 60 * 60


@dataclass
class MemoryGovernancePolicy:
    """统一处理候选记忆的审批、拒绝和确认要求。"""

    config: MemoryGovernancePolicyConfig = field(default_factory=MemoryGovernancePolicyConfig)

    def evaluate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        notes: List[str] = list(candidate.approval_notes)
        should_promote = bool(candidate.should_promote)
        action = "approve"
        require_confirmation = False

        sensitivity = candidate.record.sensitivity if candidate.record is not None else MemorySensitivity.PUBLIC
        if sensitivity in self.config.confirmation_sensitivity_levels:
            action = "require_confirmation"
            require_confirmation = True
            should_promote = False
            notes.append(f"sensitivity:{sensitivity.value}")
        elif candidate.confidence < self.config.low_confidence_threshold or candidate.importance <= 0.1:
            action = "reject"
            should_promote = False
            notes.append("confidence_too_low")
        elif candidate.stability < self.config.low_stability_threshold:
            action = "defer"
            should_promote = False
            notes.append("stability_too_low")
        else:
            notes.append("approved")

        record_update = candidate.record
        if record_update is not None and record_update.ttl_seconds is None and action == "approve":
            if record_update.scope in {MemoryScope.TURN, MemoryScope.SESSION}:
                record_update = record_update.model_copy(update={"ttl_seconds": self.config.default_ttl_seconds})
        if record_update is not None and record_update.ttl_seconds is not None and record_update.valid_until is None:
            record_update = record_update.model_copy(
                update={
                    "valid_until": record_update.created_at + timedelta(seconds=record_update.ttl_seconds),
                }
            )

        return candidate.model_copy(
            update={
                "should_promote": should_promote,
                "governance_action": action,
                "require_confirmation": require_confirmation,
                "approval_notes": notes,
                "record": record_update,
                "decision_reason": action,
                "skip_reason": None if should_promote else action,
                "extra": {
                    **dict(candidate.extra),
                    "decision_reason": action,
                    "require_confirmation": require_confirmation,
                    "approval_notes": notes,
                },
            }
        )

    def evaluate_many(self, candidates: Iterable[MemoryCandidate]) -> List[MemoryCandidate]:
        return [self.evaluate(candidate) for candidate in candidates]
