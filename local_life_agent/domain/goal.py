"""Goal domain models for P2 GoalPlanner + GoalReview.

Enhanced from ``domain/candidate.py`` ``LocalLifeGoalDraft`` with P2 fields:
  - GoalSource enum (origin of goal derivation)
  - GoalPlan output from GoalPlanner
  - GoalReviewResult output from GoalReview
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..planning.review_policy import NextAction


class GoalSource(str, Enum):
    """Origin of the goal plan — how was the goal derived?"""
    SEMANTIC_FRAME = "semantic_frame"
    CONTEXT_RECOVERY = "context_recovery"
    CLARIFICATION_REPLY = "clarification_reply"
    REPLAN = "replan"
    FALLBACK = "fallback"


class GoalPlan(BaseModel):
    """Structured goal output from GoalPlanner.

    Replaces old ``task_type`` as the authoritative decision source for
    local-life business-objective reasoning.  The old ``task_type`` is
    kept as a compatibility field only.
    """
    # Goal identity
    goal_type: str = ""               # recommendation | comparison | single_shop_query | refinement | unsupported
    goal_source: GoalSource = GoalSource.SEMANTIC_FRAME
    goal_summary: str = ""            # Natural-language summary of what the user wants

    # Candidate resolution directives
    candidate_source: str = ""        # explicit | context | discovery | mixed
    candidate_category: str | None = None
    candidate_limit: int | None = None
    requested_count: int = 1
    min_required: int = 1
    max_allowed: int = 5

    # Evidence directives
    evidence_needs: list[str] = Field(default_factory=list)
    required_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)

    # Constraints
    constraints: dict[str, Any] = Field(default_factory=dict)

    # Unsupported handling
    unsupported: bool = False
    unsupported_reason: str = ""

    # Trace
    source_origin: str = "goal_planner"
    planner_source: str = ""
    planner_reason: str = ""
    planner_confidence: float = 0.0


class GoalReviewResult(BaseModel):
    """Output from GoalReview — determines whether the goal is actionable.

    Written to ``GraphState.review_results["goal_review"]``.
    """
    stage: str = "goal_review"
    status: str = "enough"            # enough | need_clarification | unsupported
    next_action: NextAction = NextAction.FINISH
    reason: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    trace_payload: dict[str, Any] = Field(default_factory=dict)


# ===================================================================
# Backward-compat mapper: GoalPlan → LocalLifeGoalDraft
# ===================================================================


def goal_plan_to_draft(plan: GoalPlan) -> Any:
    """Convert a P2 GoalPlan to the legacy LocalLifeGoalDraft (for CandidateResolver compat).

    This is the compatibility-shell approach: the new GoalPlanner produces
    GoalPlan, and we map it to LocalLifeGoalDraft until CandidateResolver
    is updated to accept GoalPlan directly.
    """
    from ..domain.candidate import CandidateSource, GoalType, LocalLifeGoalDraft

    # Map goal_type string → GoalType
    gt_map = {
        "recommendation": GoalType.RECOMMENDATION,
        "comparison": GoalType.COMPARISON,
        "single_shop_query": GoalType.SINGLE_SHOP_QUERY,
        "refinement": GoalType.REFINEMENT,
    }
    goal_type = gt_map.get(plan.goal_type, GoalType.UNSUPPORTED)

    # Map candidate_source string → CandidateSource
    cs_map = {
        "explicit": CandidateSource.EXPLICIT,
        "context": CandidateSource.CONTEXT,
        "discovery": CandidateSource.DISCOVERY,
        "mixed": CandidateSource.MIXED,
    }
    candidate_source = cs_map.get(plan.candidate_source, CandidateSource.DISCOVERY)

    return LocalLifeGoalDraft(
        goal_type=goal_type,
        candidate_source=candidate_source,
        candidate_category=plan.candidate_category,
        candidate_limit=plan.candidate_limit,
        evidence_needs=list(plan.evidence_needs),
        required_facets=list(plan.required_facets),
        optional_facets=list(plan.optional_facets),
        requested_count=plan.requested_count,
        min_required=plan.min_required,
        max_allowed=plan.max_allowed,
        max_candidates=5,
        source_origin=plan.source_origin,
    )
