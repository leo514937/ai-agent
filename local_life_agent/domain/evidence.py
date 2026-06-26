"""Evidence domain schemas for the P1 EvidencePlanner + EvidenceReview flow.

Defines the standardised ToolStatus enum (ok / empty / unknown / failed / timeout / unsupported),
FacetEvidence for per-facet result tracking, and EvidenceReviewResult for the sufficiency
check output written to GraphState.review_results.evidence_review.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..planning.review_policy import NextAction


class ToolStatus(str, Enum):
    """Standardised tool execution status — P1 required set."""
    OK = "ok"
    EMPTY = "empty"
    UNKNOWN = "unknown"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"


FINAL_STATUSES = frozenset({"ok", "empty"})
FAILURE_STATUSES = frozenset({"unknown", "failed", "timeout", "unsupported"})


class FacetEvidence(BaseModel):
    """Per-facet evidence result for a single shop candidate."""
    shop_id: str = ""
    shop_name: str = ""
    facet: str = ""
    tool_name: str = ""
    status: ToolStatus = ToolStatus.UNKNOWN
    required: bool = False
    can_degrade: bool = False
    retriable: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceReviewResult(BaseModel):
    """Sufficiency check result for the EvidenceReview stage.

    Written to ``GraphState.review_results["evidence_review"]``.
    """
    stage: str = "evidence_review"
    next_action: NextAction = NextAction.FINISH
    can_degrade: bool = False
    status: str = "sufficient"
    reason: str = ""
    required_ok: list[str] = Field(default_factory=list)
    required_empty: list[str] = Field(default_factory=list)
    required_unknown: list[str] = Field(default_factory=list)
    required_failed: list[str] = Field(default_factory=list)
    optional_ok: list[str] = Field(default_factory=list)
    optional_empty: list[str] = Field(default_factory=list)
    optional_unknown: list[str] = Field(default_factory=list)
    optional_failed: list[str] = Field(default_factory=list)
    unknown_as_false_detected: bool = False
    failed_as_empty_detected: bool = False
    evidence_incomplete: bool = False
    trace_payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_sufficient(self) -> bool:
        return self.next_action in (NextAction.FINISH, NextAction.DEGRADE_ANSWER)
