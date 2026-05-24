from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .enums import IntentType
from .memory import MemoryRecord, MemoryStatus


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class ClarificationDecision:
    should_clarify: bool
    reason: str


def evaluate_clarification(
    *,
    intent_confidence: float,
    reference_confidence: Optional[float],
    intent: Optional[IntentType],
    intent_threshold: float = 0.5,
    reference_threshold: float = 0.5,
) -> ClarificationDecision:
    if intent_confidence < intent_threshold:
        return ClarificationDecision(True, "low_intent_confidence")
    if intent == IntentType.FOLLOW_UP and (reference_confidence is None or reference_confidence < reference_threshold):
        return ClarificationDecision(True, "low_reference_confidence")
    return ClarificationDecision(False, "no_clarification_needed")


def allow_memory_injection_status(status: MemoryStatus) -> bool:
    return status in {MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED, MemoryStatus.INFERRED}


def validate_memory_write_boundary(
    *,
    user_id: str,
    runtime_user_id: str,
    session_id: Optional[str],
    turn_id: Optional[str],
) -> GuardDecision:
    if not user_id or not runtime_user_id or runtime_user_id != user_id:
        return GuardDecision(False, "reject_cross_user_write")
    if not session_id or not turn_id:
        return GuardDecision(False, "reject_incomplete_runtime")
    return GuardDecision(True, "boundary_ok")


def validate_memory_record_mutation(record: MemoryRecord) -> GuardDecision:
    if record.status in {
        MemoryStatus.DELETED,
        MemoryStatus.EXPIRED,
        MemoryStatus.SUPERSEDED,
        MemoryStatus.INACTIVE,
        MemoryStatus.OBSERVED,
        MemoryStatus.EPHEMERAL,
        MemoryStatus.ACTIVE_SESSION,
    }:
        return GuardDecision(False, f"reject_{record.status.value}_record")
    return GuardDecision(True, "mutation_allowed")

