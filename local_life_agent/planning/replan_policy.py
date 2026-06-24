"""ReplanPolicy — P2 replan loop guard and suggestions.

Manages replan limits (expand_search, replan_evidence, rewrite) via
``SessionState.replan_counters``, provides helpers for checking
whether a replan action is allowed, and generates suggestions for
what to do on each replan type.
"""

from __future__ import annotations

from typing import Any

from .. import config
from ..domain.evidence import EvidenceReviewResult
from ..domain.goal import GoalPlan
from ..domain.state import SessionState


# ===================================================================
# Counter helpers
# ===================================================================


def _get_counters(state: SessionState | dict[str, Any] | None) -> dict[str, int]:
    """Extract replan_counters from session state."""
    if state is None:
        return {"expand_search": 0, "replan_evidence": 0, "rewrite": 0}
    if isinstance(state, SessionState):
        return dict(state.replan_counters)
    if isinstance(state, dict):
        raw = state.get("replan_counters", {}) or {}
        if isinstance(raw, dict):
            return {
                "expand_search": int(raw.get("expand_search", 0)),
                "replan_evidence": int(raw.get("replan_evidence", 0)),
                "rewrite": int(raw.get("rewrite", 0)),
            }
    return {"expand_search": 0, "replan_evidence": 0, "rewrite": 0}


def _set_counter(
    state: SessionState | dict[str, Any] | None,
    key: str,
    value: int,
) -> None:
    """Set a replan counter on the session state."""
    if state is None:
        return
    if isinstance(state, SessionState):
        state.replan_counters[key] = value
    elif isinstance(state, dict):
        counters = state.get("replan_counters", {})
        if isinstance(counters, dict):
            counters[key] = value


# ===================================================================
# Allowance checks
# ===================================================================


def check_expand_search_allowed(
    session_state: SessionState | dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Check whether expand_search is allowed (within max rounds).

    Args:
        session_state: Current session state with replan_counters.

    Returns:
        (allowed: bool, reason: str)
    """
    counters = _get_counters(session_state)
    current = counters.get("expand_search", 0)
    max_rounds = config.MAX_EXPAND_SEARCH_ROUNDS

    if current >= max_rounds:
        return False, f"expand_search limit reached ({current}/{max_rounds})"
    return True, f"expand_search allowed ({current + 1}/{max_rounds})"


def check_replan_evidence_allowed(
    session_state: SessionState | dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Check whether replan_evidence is allowed (within max rounds).

    Args:
        session_state: Current session state with replan_counters.

    Returns:
        (allowed: bool, reason: str)
    """
    counters = _get_counters(session_state)
    current = counters.get("replan_evidence", 0)
    max_rounds = config.MAX_REPLAN_EVIDENCE_ROUNDS

    if current >= max_rounds:
        return False, f"replan_evidence limit reached ({current}/{max_rounds})"
    return True, f"replan_evidence allowed ({current + 1}/{max_rounds})"


def check_rewrite_allowed(
    session_state: SessionState | dict[str, Any] | None = None,
    current_count: int | None = None,
) -> tuple[bool, str]:
    """Check whether rewrite is allowed (within max attempts).

    Args:
        session_state: Current session state (used if current_count not given).
        current_count: Explicit rewrite count (overrides session state).

    Returns:
        (allowed: bool, reason: str)
    """
    if current_count is not None:
        current = current_count
    else:
        counters = _get_counters(session_state)
        current = counters.get("rewrite", 0)

    max_rewrites = max(1, config.MAX_REWRITE_ATTEMPTS - 1)

    if current >= max_rewrites:
        return False, f"rewrite limit reached ({current}/{max_rewrites})"
    return True, f"rewrite allowed ({current + 1}/{max_rewrites})"


# ===================================================================
# Counter increments
# ===================================================================


def increment_expand_search(
    session_state: SessionState | dict[str, Any] | None = None,
) -> None:
    """Increment the expand_search counter."""
    counters = _get_counters(session_state)
    current = counters.get("expand_search", 0)
    _set_counter(session_state, "expand_search", current + 1)


def increment_replan_evidence(
    session_state: SessionState | dict[str, Any] | None = None,
) -> None:
    """Increment the replan_evidence counter."""
    counters = _get_counters(session_state)
    current = counters.get("replan_evidence", 0)
    _set_counter(session_state, "replan_evidence", current + 1)


def increment_rewrite(
    session_state: SessionState | dict[str, Any] | None = None,
) -> None:
    """Increment the rewrite counter."""
    counters = _get_counters(session_state)
    current = counters.get("rewrite", 0)
    _set_counter(session_state, "rewrite", current + 1)


# ===================================================================
# Suggestions
# ===================================================================


def get_expand_search_suggestions(
    goal_plan: GoalPlan | dict[str, Any] | None = None,
) -> list[str]:
    """Generate suggestions for how to expand the search.

    Args:
        goal_plan: The current goal plan (for context-aware suggestions).

    Returns:
        List of suggestion strings.
    """
    suggestions: list[str] = []

    suggestions.append("broaden category or remove category filter")
    suggestions.append("increase candidate limit")
    suggestions.append("relax location or distance constraints")

    if goal_plan is not None:
        if isinstance(goal_plan, GoalPlan):
            cat = goal_plan.candidate_category
        elif isinstance(goal_plan, dict):
            cat = goal_plan.get("candidate_category")
        else:
            cat = None

        if cat:
            suggestions.append(f"try related categories similar to '{cat}'")

    return suggestions


def get_replan_evidence_suggestions(
    evidence_review: EvidenceReviewResult | dict[str, Any] | None = None,
) -> list[str]:
    """Generate suggestions for which evidence to replan.

    Args:
        evidence_review: The EvidenceReviewResult with failure details.

    Returns:
        List of suggestion strings.
    """
    suggestions: list[str] = []

    if evidence_review is not None:
        if isinstance(evidence_review, EvidenceReviewResult):
            failed = list(evidence_review.required_failed)
            unknown = list(evidence_review.required_unknown)
        elif isinstance(evidence_review, dict):
            failed = list(evidence_review.get("required_failed", []) or [])
            unknown = list(evidence_review.get("required_unknown", []) or [])
        else:
            failed, unknown = [], []

        if failed:
            suggestions.append(f"retry failed facets: {', '.join(failed)}")
            suggestions.append("try alternative tools for failed facets")
        if unknown:
            suggestions.append(f"re-query unknown facets: {', '.join(unknown)}")

    suggestions.append("retry transient failures with backoff")
    suggestions.append("downgrade optional facets if still failing")

    return suggestions
