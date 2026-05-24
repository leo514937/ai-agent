from __future__ import annotations

from enum import Enum


class StrValueEnum(str, Enum):
    """String enum base with stable serialized values."""

    def __str__(self) -> str:
        return str(self.value)


class TurnDecision(StrValueEnum):
    CLARIFY = "clarify"
    DIRECT_ANSWER = "direct_answer"
    RETRIEVE_THEN_ANSWER = "retrieve_then_answer"
    TOOL_THEN_ANSWER = "tool_then_answer"


class RagStatus(StrValueEnum):
    OK = "ok"
    DEGRADED = "degraded"
    EMPTY = "empty"


class ToolExecutionStatus(StrValueEnum):
    SKIPPED = "skipped"
    PENDING_APPROVAL = "pending_approval"
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    REJECTED = "rejected"


class OutputStyle(StrValueEnum):
    BRIEF = "brief"
    DETAILED = "detailed"
    COMPARISON = "comparison"
    GUIDED = "guided"


class IntentType(StrValueEnum):
    EXPLAIN = "explain"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    SUMMARY = "summary"
    FOLLOW_UP = "follow_up"
