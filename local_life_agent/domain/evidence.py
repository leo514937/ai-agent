"""Evidence domain schemas for the P1 EvidencePlanner + EvidenceReview flow.

Defines the standardised ToolStatus enum (ok / empty / unknown / failed / timeout / unsupported),
FacetEvidence for per-facet result tracking, and EvidenceReviewResult for the sufficiency
check output written to GraphState.review_results.evidence_review.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

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


class EvidenceReviewAction(str, Enum):
    """P8 review action for evidence sufficiency and iteration."""

    PROCEED = "proceed"
    RETRY = "retry"
    REPLAN_MISSING_FACETS = "replan_missing_facets"
    EXPAND_SEARCH = "expand_search"
    CLARIFY = "clarify"
    DEGRADE = "degrade"
    FALLBACK = "fallback"


class ToolFailureType(str, Enum):
    """Minimal P8 tool failure classification."""

    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    BACKEND_ERROR = "backend_error"
    INVALID_RESPONSE = "invalid_response"
    UNSUPPORTED_FACET = "unsupported_facet"
    MISSING_INPUT = "missing_input"
    EMPTY_RESULT = "empty_result"
    UNKNOWN = "unknown"


class ToolFailure(BaseModel):
    tool_name: str | None = None
    facet: str | None = None
    target_shop_id: str | None = None
    failure_type: ToolFailureType = ToolFailureType.UNKNOWN
    retryable: bool = False
    message: str | None = None
    evidence_ref: str | None = None


def _coerce_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _coerce_dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    try:
        return dict(value)
    except Exception:
        return {}


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
    action: EvidenceReviewAction = EvidenceReviewAction.PROCEED
    next_action: NextAction = NextAction.FINISH
    can_degrade: bool = False
    status: str = "sufficient"
    reason: str = ""
    retryable_facets: list[str] = Field(default_factory=list)
    missing_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_facets: list[str] = Field(default_factory=list)
    answerable_facets: list[str] = Field(default_factory=list)
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
    review_source: str = ""
    review_confidence: float = 0.0
    missing_evidence: list[str] = Field(default_factory=list)
    unsafe_answer_risks: list[str] = Field(default_factory=list)
    recommended_next_action: str = ""
    tool_failures: list[ToolFailure] = Field(default_factory=list)
    retry_budget_remaining: int | None = None
    expand_search_budget_remaining: int | None = None
    replan_budget_remaining: int | None = None
    rewrite_budget_remaining: int | None = None
    tool_round_budget_remaining: int | None = None
    facet_enrich_budget_remaining: int | None = None
    deadline_remaining_ms: int | None = None
    budget_context_snapshot: dict[str, Any] = Field(default_factory=dict)
    budget_exhausted_reasons: list[str] = Field(default_factory=list)
    stale_facets: list[str] = Field(default_factory=list)
    expired_facets: list[str] = Field(default_factory=list)
    disclaimer_facets: list[str] = Field(default_factory=list)
    degrade_reason: str = ""
    fallback_reason: str = ""
    clarification_reason: str = ""
    next_step: str = ""
    semantic_frame: dict[str, Any] = Field(default_factory=dict)
    semantic_parse_source: str = ""
    grounding_status: str = ""
    missing_slot_type: str = ""
    router_policy_decision: dict[str, Any] = Field(default_factory=dict)
    router_policy_conflicts: list[str] = Field(default_factory=list)
    conversation_continuity: dict[str, Any] = Field(default_factory=dict)
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    facet_statuses: dict[str, str] = Field(default_factory=dict)
    grounded_facts: dict[str, Any] = Field(default_factory=dict)
    facet_reasons: dict[str, str] = Field(default_factory=dict)
    evidence_status: str = ""
    comparison_support_status: str = ""
    ranking_preserved: bool = True
    unsupported_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    partial_fields: list[str] = Field(default_factory=list)

    @field_validator(
        "retryable_facets",
        "missing_facets",
        "unknown_facets",
        "failed_facets",
        "answerable_facets",
        "required_ok",
        "required_empty",
        "required_unknown",
        "required_failed",
        "optional_ok",
        "optional_empty",
        "optional_unknown",
        "optional_failed",
        "missing_evidence",
        "unsafe_answer_risks",
        "budget_exhausted_reasons",
        "stale_facets",
        "expired_facets",
        "disclaimer_facets",
        "router_policy_conflicts",
        "stage_queries",
        "stage_statuses",
        "unsupported_reasons",
        "unknown_fields",
        "failed_tools",
        "partial_fields",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

    @field_validator("location", "facet_statuses", "grounded_facts", "facet_reasons", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, value: Any) -> dict[str, Any]:
        return _coerce_dict_value(value)

    @property
    def is_sufficient(self) -> bool:
        return self.action in (
            EvidenceReviewAction.PROCEED,
            EvidenceReviewAction.DEGRADE,
        ) or self.next_action in (NextAction.FINISH, NextAction.DEGRADE_ANSWER)
