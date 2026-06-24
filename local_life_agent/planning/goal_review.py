"""GoalReview — P2 goal sufficiency gate.

Runs AFTER GoalPlanner and BEFORE CandidateResolver.
Checks whether the goal is clear, executable, and within tool capability.

Typical scenarios:
  - ``帮我订座`` → unsupported (no booking tool)
  - ``对比两家KTV`` without names or default strategy → need_clarification
  - ``附近评分最高的两家KTV谁优惠券多`` → enough
"""

from __future__ import annotations

from typing import Any

from ..domain.goal import GoalPlan, GoalReviewResult
from ..domain.state import SessionState


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


# Set of known unsupported intent patterns (no tool available)
_UNSUPPORTED_INTENT_MARKERS: list[str] = [
    "booking", "reservation", "订座", "订位", "预约", "预订",
]


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

    # Candidate source is required
    if not goal.candidate_source or goal.candidate_source == "":
        missing.append("candidate_source")
        return False, "no candidate_source specified", missing

    # For explicit / mixed sources, we need at least some mention context
    # (checked at CandidateReview level, not here)

    return True, "", []


def _check_tool_capability(goal: GoalPlan) -> tuple[bool, str]:
    """Check if the goal can be handled by current tool capabilities.

    Returns (is_supported, reason).
    """
    summary_lower = (goal.goal_summary or "").lower()

    for marker in _UNSUPPORTED_INTENT_MARKERS:
        if marker in summary_lower or marker in goal.goal_type.lower():
            return False, f"unsupported_intent: '{marker}' not in current tool capability"

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
