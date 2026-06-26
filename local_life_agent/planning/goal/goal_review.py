"""GoalReview — P2 goal sufficiency gate.

Runs AFTER GoalPlanner and BEFORE CandidateResolver.
Checks whether the goal is clear, executable, and within tool capability.
This stage is intentionally deterministic: the planner/semantic layers may
use LLMs, but GoalReview is the stable validator that decides routing and
capability gating before execution starts.

Typical scenarios:
  - ``帮我订座`` → unsupported (no booking tool)
  - ``对比两家KTV`` without names or default strategy → need_clarification
  - ``附近评分最高的两家KTV谁优惠券多`` → enough
"""

from __future__ import annotations

from typing import Any

from ...domain.goal import GoalPlan, GoalReviewResult
from ...domain.state import SessionState
from .unsupported_intent import (
    build_booking_unsupported_reason,
    detect_booking_unsupported,
)


_ALLOWED_GOAL_TYPES = {"recommendation", "comparison", "single_shop_query", "refinement", "unsupported"}
_ALLOWED_CANDIDATE_SOURCES = {"explicit", "context", "discovery", "mixed"}


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _check_unsupported(goal: GoalPlan) -> tuple[bool, str]:
    """Check if the goal is fundamentally unsupported.

    Returns (is_unsupported, reason).
    """
    if goal.unsupported:
        return True, goal.unsupported_reason or "goal_marked_unsupported"

    return False, ""


def _check_clarity_and_executability(goal: GoalPlan) -> tuple[bool, str, list[str]]:
    """Check if the goal is clear and executable.

    Returns (is_clear, reason, missing_fields).
    """
    missing: list[str] = []

    # Goal type must be meaningful
    if not goal.goal_type or goal.goal_type in ("unsupported", ""):
        missing.append("goal_type")
        return False, "goal_type is empty or unsupported", missing
    if goal.goal_type not in _ALLOWED_GOAL_TYPES:
        missing.append("goal_type")
        return False, f"goal_type '{goal.goal_type}' is not allowed", missing

    # Candidate source is required
    if not goal.candidate_source or goal.candidate_source == "":
        missing.append("candidate_source")
        return False, "no candidate_source specified", missing
    if goal.candidate_source not in _ALLOWED_CANDIDATE_SOURCES:
        missing.append("candidate_source")
        return False, f"candidate_source '{goal.candidate_source}' is not allowed", missing
    if goal.requested_count <= 0 or goal.min_required <= 0 or goal.max_allowed <= 0:
        missing.append("quantity_bounds")
        return False, "requested_count/min_required/max_allowed must be positive", missing
    if goal.min_required > goal.requested_count or goal.requested_count > goal.max_allowed:
        missing.append("quantity_bounds")
        return False, "goal quantity bounds are inconsistent", missing

    # For explicit / mixed sources, we need at least some mention context
    # (checked at CandidateReview level, not here)

    return True, "", []


def _check_tool_capability(goal: GoalPlan) -> tuple[bool, str]:
    """Check if the goal can be handled by current tool capabilities.

    Returns (is_supported, reason).
    """
    is_booking_intent, marker = detect_booking_unsupported(
        goal.goal_summary,
        goal.goal_type,
        goal.unsupported_reason,
    )
    if is_booking_intent:
        return False, build_booking_unsupported_reason(marker)

    return True, ""


def review_goal(
    goal_plan: GoalPlan,
    raw_text: str = "",
    session_state: SessionState | dict[str, Any] | None = None,
) -> GoalReviewResult:
    """Review whether a goal is clear, executable, and supported.

    Args:
        goal_plan: The ``GoalPlan`` produced by ``GoalPlanner``.
        raw_text: The original user input (for context-sensitive checks).
        session_state: Optional session state for context.

    Returns:
        A ``GoalReviewResult`` with next_action:
            - FINISH → goal is good, proceed to CandidateResolver.
            - CLARIFY → goal needs more information from the user.
            - UNSUPPORTED_ANSWER → goal cannot be handled.
            - FALLBACK → cannot proceed.
    """
    # Guard: None goal_plan → unsupported
    if goal_plan is None:
        return GoalReviewResult(
            stage="goal_review",
            status="unsupported",
            next_action="UNSUPPORTED_ANSWER",
            reason="no_goal_plan_produced",
            trace_payload={"error": "goal_plan_is_none"},
        )

    trace: dict[str, Any] = {}
    missing_fields: list[str] = []

    # --- 1. Check unsupported ---
    is_unsupported, reason = _check_unsupported(goal_plan)
    if is_unsupported:
        trace["unsupported_reason"] = reason
        return GoalReviewResult(
            stage="goal_review",
            status="unsupported",
            next_action="UNSUPPORTED_ANSWER",
            reason=reason,
            missing_fields=missing_fields,
            trace_payload=trace,
        )

    # --- 2. Check tool capability ---
    is_supported, capability_reason = _check_tool_capability(goal_plan)
    if not is_supported:
        trace["capability_reason"] = capability_reason
        return GoalReviewResult(
            stage="goal_review",
            status="unsupported",
            next_action="UNSUPPORTED_ANSWER",
            reason=capability_reason,
            missing_fields=missing_fields,
            trace_payload=trace,
        )

    # --- 3. Check clarity and executability ---
    is_clear, clarity_reason, missing = _check_clarity_and_executability(goal_plan)
    if not is_clear:
        missing_fields.extend(missing)
        trace["clarity_reason"] = clarity_reason
        return GoalReviewResult(
            stage="goal_review",
            status="need_clarification",
            next_action="CLARIFY",
            reason=clarity_reason,
            missing_fields=missing_fields,
            trace_payload=trace,
        )

    # --- 4. Additional checks ---

    # For comparison type, need at least indication of what to compare
    if goal_plan.goal_type == "comparison":
        if not goal_plan.candidate_category and not goal_plan.candidate_source:
            trace["comparison_missing_context"] = True
            return GoalReviewResult(
                stage="goal_review",
                status="need_clarification",
                next_action="CLARIFY",
                reason="comparison request missing comparison targets or category",
                missing_fields=["comparison_targets"],
                trace_payload=trace,
            )

    # --- 5. All checks passed ---
    trace["goal_type"] = goal_plan.goal_type
    trace["candidate_source"] = goal_plan.candidate_source
    trace["review_decision"] = "proceed"

    return GoalReviewResult(
        stage="goal_review",
        status="enough",
        next_action="FINISH",
        reason="goal is clear, executable, and supported",
        missing_fields=[],
        trace_payload=trace,
    )
