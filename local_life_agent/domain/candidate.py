"""Candidate domain schemas for the P0 CandidateSet + CandidateReview flow.

Defines enumerations and structured DTOs used across the candidate
resolution and review pipeline:

  - CandidateStatus, CandidateSource, GoalType  (enums)
  - LocalLifeGoalDraft, CandidateSpec, ResolvedCandidate, CandidateSet  (DTOs)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ===================================================================
# Enumerations
# ===================================================================


class CandidateStatus(str, Enum):
    """Status of a resolved candidate set."""
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    PARTIAL = "partial"
    TOO_MANY = "too_many"
    NEED_CLARIFICATION = "need_clarification"


class CandidateSource(str, Enum):
    """Origin of candidate shops."""
    EXPLICIT = "explicit"
    CONTEXT = "context"
    DISCOVERY = "discovery"
    MIXED = "mixed"


class GoalType(str, Enum):
    """High-level goal type derived from the semantic frame."""
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SINGLE_SHOP_QUERY = "single_shop_query"
    REFINEMENT = "refinement"
    UNSUPPORTED = "unsupported"


# ===================================================================
# Core DTOs
# ===================================================================


class LocalLifeGoalDraft(BaseModel):
    """Structured goal derived from SemanticFrame for the candidate flow.

    This replaces the old monolithic ``task_type`` as the primary
    decision source for candidate resolution.  ``task_type`` is kept
    downstream solely as a compatibility field.
    """
    goal_type: GoalType = GoalType.UNSUPPORTED
    candidate_source: CandidateSource = CandidateSource.DISCOVERY
    candidate_category: str | None = None
    candidate_limit: int | None = None
    evidence_needs: list[str] = Field(default_factory=list)
    required_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    requested_count: int = 1
    min_required: int = 1
    max_allowed: int = 5
    max_candidates: int = 5
    source_origin: str = "llm"  # llm | llm+fallback | fallback


class CandidateSpec(BaseModel):
    """Specification driving the candidate resolution strategy."""
    source: CandidateSource = CandidateSource.DISCOVERY
    category: str = ""
    query: str = ""
    location_scope: dict[str, Any] | None = None
    sort_by: list[dict[str, Any]] = Field(default_factory=list)
    limit: int | None = None
    explicit_mentions: list[str] = Field(default_factory=list)
    context_ref: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    ranking_signals: dict[str, Any] = Field(default_factory=dict)


class ResolvedCandidate(BaseModel):
    """A single candidate shop resolved by CandidateResolver."""
    shop_id: str = ""
    shop_name: str = ""
    source: CandidateSource = CandidateSource.DISCOVERY
    rank: int = 0
    confidence: float = 1.0
    rating: float | None = None
    distance_km: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CandidateSet(BaseModel):
    """The resolved set of candidates for a single turn."""
    status: CandidateStatus = CandidateStatus.NOT_FOUND
    source: CandidateSource = CandidateSource.DISCOVERY
    candidates: list[ResolvedCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    original_spec: CandidateSpec | None = None
    requested_count: int = 1
    min_required: int = 2
    max_allowed: int = 5
