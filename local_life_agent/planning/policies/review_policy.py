"""Review policy — structured sufficiency gates for the P0 candidate flow.

Defines enums and DTOs used by all review stages.  P0 only uses
CANDIDATE_REVIEW with FINISH / CLARIFY / FALLBACK next actions.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..budget.budget_context import BudgetContext, budget_context_from_state


# ===================================================================
# Enumerations
# ===================================================================


class ReviewStage(str, Enum):
    """Which stage of the review pipeline this check belongs to."""
    GOAL_REVIEW = "goal_review"
    CANDIDATE_REVIEW = "candidate_review"
    EVIDENCE_REVIEW = "evidence_review"
    DECISION_REVIEW = "decision_review"
    ANSWER_REVIEW = "answer_review"


class ReviewStatus(str, Enum):
    """Outcome of a sufficiency check."""
    ENOUGH = "enough"
    NEED_MORE_CANDIDATES = "need_more_candidates"
    NEED_MORE_EVIDENCE = "need_more_evidence"
    NEED_CLARIFICATION = "need_clarification"
    CAN_DEGRADE = "can_degrade"
    UNSUPPORTED = "unsupported"
    FALLBACK = "fallback"


class NextAction(str, Enum):
    """The action the graph should take after a review check.

    P0 only allows FINISH, CLARIFY, FALLBACK.  The other values
    are reserved for P1/P2 and MUST NOT be returned by P0 code.
    """
    FINISH = "FINISH"
    EXPAND_SEARCH = "EXPAND_SEARCH"          # P1/P2 only
    REPLAN_EVIDENCE = "REPLAN_EVIDENCE"      # P1/P2 only
    CLARIFY = "CLARIFY"
    DEGRADE_ANSWER = "DEGRADE_ANSWER"        # P1/P2 only
    UNSUPPORTED_ANSWER = "UNSUPPORTED_ANSWER"
    FALLBACK = "FALLBACK"


# ===================================================================
# ReviewPolicy
# ===================================================================


class ReviewPolicy(BaseModel):
    """Minimal review policy used to cap review and rewrite loops."""

    model_config = ConfigDict(extra="forbid")

    max_review_rounds: int = 2
    max_rewrite_rounds: int = 1
    allow_fallback: bool = True
    allow_clarify: bool = True

    @field_validator("max_review_rounds", "max_rewrite_rounds", mode="before")
    @classmethod
    def _coerce_non_negative_int(cls, value: Any) -> int:
        try:
            return max(int(value), 0)
        except Exception:
            return 0

    @field_validator("allow_fallback", "allow_clarify", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"0", "false", "no", "off", "n"}:
                return False
            if normalized in {"1", "true", "yes", "on", "y"}:
                return True
        return bool(value)

    @classmethod
    def from_budget_context(cls, budget_context: BudgetContext | dict[str, Any] | None = None) -> ReviewPolicy:
        if budget_context is None:
            return cls()
        if isinstance(budget_context, dict):
            try:
                budget_context = BudgetContext.model_validate(budget_context)
            except Exception:
                budget_context = BudgetContext()
        if not isinstance(budget_context, BudgetContext):
            return cls()
        return cls(
            max_review_rounds=max(int(budget_context.retry_budget or 0) + 1, 1),
            max_rewrite_rounds=max(int(budget_context.rewrite_budget or 0), 1),
        )

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> ReviewPolicy:
        state = state or {}
        value = state.get("review_policy")
        if isinstance(value, ReviewPolicy):
            return value
        if isinstance(value, dict):
            try:
                return cls.model_validate(value)
            except Exception:
                pass

        execution_budget = state.get("execution_budget")
        if execution_budget is not None:
            from ..budget.execution_budget import ExecutionBudget

            if isinstance(execution_budget, ExecutionBudget):
                return cls(
                    max_review_rounds=max(int(execution_budget.max_review_rounds or 0), 1),
                    max_rewrite_rounds=max(int(execution_budget.max_rewrite_rounds or 0), 1),
                )
            if isinstance(execution_budget, dict):
                try:
                    budget = ExecutionBudget.model_validate(execution_budget)
                except Exception:
                    budget = None
                if budget is not None:
                    return cls(
                        max_review_rounds=max(int(budget.max_review_rounds or 0), 1),
                        max_rewrite_rounds=max(int(budget.max_rewrite_rounds or 0), 1),
                    )

        return cls.from_budget_context(budget_context_from_state(state))


# P0 allowed next actions — test must fail if any other action is returned.
P0_ALLOWED_NEXT_ACTIONS: frozenset[str] = frozenset({
    NextAction.FINISH,
    NextAction.CLARIFY,
    NextAction.FALLBACK,
})


# ===================================================================
# SufficiencyCheckResult
# ===================================================================


class SufficiencyCheckResult(BaseModel):
    """Structured output of a single sufficiency gate check.

    Every review stage (candidate, evidence, decision) produces one
    of these.  The graph reads ``next_action`` to decide routing.
    """
    stage: ReviewStage = ReviewStage.CANDIDATE_REVIEW
    status: ReviewStatus = ReviewStatus.ENOUGH
    next_action: NextAction = NextAction.FINISH
    missing_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    affected_candidates: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    trace_payload: dict[str, Any] = Field(default_factory=dict)


# ===================================================================
# P0 Assertion Helper
# ===================================================================


def assert_p0_next_action_allowed(result: SufficiencyCheckResult) -> None:
    """Raise ValueError if *result* contains a next_action forbidden in P0.

    This is called from tests to guard against accidental use of
    EXPAND_SEARCH / REPLAN_EVIDENCE / DEGRADE_ANSWER before P1.
    """
    action = result.next_action
    if action.value not in P0_ALLOWED_NEXT_ACTIONS:
        raise ValueError(
            f"P0 forbids next_action={action.value!r}. "
            f"Allowed: {', '.join(sorted(P0_ALLOWED_NEXT_ACTIONS))}. "
            f"Stage={result.stage.value}, status={result.status.value}."
        )


def review_policy_from_state(state: dict[str, Any] | None) -> ReviewPolicy:
    return ReviewPolicy.from_state(state)
