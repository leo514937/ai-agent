"""CandidateReview — structured sufficiency gate for the P0 CandidateSet flow.

CandidateReview is a **deterministic** gate, NOT an LLM reflection step.
It evaluates ``CandidateSet`` against ``LocalLifeGoalDraft`` to decide:

  - FINISH  — sufficient candidates, proceed to planning
  - CLARIFY — insufficient / ambiguous, ask the user
  - FALLBACK — cannot proceed, explain why
"""

from __future__ import annotations

from ..domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
)
from ..planning.review_policy import (
    NextAction,
    ReviewStage,
    ReviewStatus,
    SufficiencyCheckResult,
)


# ===================================================================
# Helpers
# ===================================================================


def dedupe_candidates(candidates: list[ResolvedCandidate]) -> list[ResolvedCandidate]:
    """Remove duplicate candidates by ``shop_id``, preserving order.

    Candidates with empty shop_id are kept as-is (they may represent
    unresolved references).
    """
    seen: set[str] = set()
    deduped: list[ResolvedCandidate] = []
    for c in candidates:
        key = c.shop_id.strip()
        if not key:
            deduped.append(c)
        elif key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def min_required_for_goal(goal: LocalLifeGoalDraft) -> int:
    """Return the minimum number of candidates required for the goal type.

    Rules:
      - COMPARISON: at least 2 candidates
      - SINGLE_SHOP_QUERY: exactly 1 candidate
      - RECOMMENDATION: at least 1 (ideally 3, but 1 is acceptable)
      - REFINEMENT: at least 1
      - UNSUPPORTED: 0 (no candidate needed)
    """
    if goal.goal_type == GoalType.COMPARISON:
        return max(2, goal.min_required or 2)
    if goal.goal_type == GoalType.SINGLE_SHOP_QUERY:
        return 1
    if goal.goal_type == GoalType.RECOMMENDATION:
        return 1
    if goal.goal_type == GoalType.REFINEMENT:
        return 1
    return 0


def default_limit_for_goal(goal: LocalLifeGoalDraft) -> int:
    """Return the default max-allowed limit for the goal type."""
    if goal.goal_type == GoalType.COMPARISON:
        return 5
    if goal.goal_type == GoalType.RECOMMENDATION:
        return 5
    return 5


# ===================================================================
# Review function
# ===================================================================


def review_candidate_set(
    goal: LocalLifeGoalDraft,
    candidate_set: CandidateSet,
) -> SufficiencyCheckResult:
    """Evaluate whether the candidate set is sufficient to proceed.

    This is a **deterministic** gate.  It does NOT call the LLM.

    Args:
        goal: The goal draft driving the request.
        candidate_set: The resolved candidate set to evaluate.

    Returns:
        A SufficiencyCheckResult with the review outcome.
    """
    # ── 1. Handle fundamental status failures ──────────────────────
    if candidate_set.status == CandidateStatus.NOT_FOUND:
        return SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_CANDIDATES,
            next_action=NextAction.CLARIFY,
            reason="CandidateResolver returned NOT_FOUND: no candidates found",
            confidence="high",
        )

    if candidate_set.status == CandidateStatus.AMBIGUOUS:
        return SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_CLARIFICATION,
            next_action=NextAction.CLARIFY,
            reason="CandidateResolver returned AMBIGUOUS: multiple matches for a reference",
            confidence="high",
        )

    if candidate_set.status == CandidateStatus.TOO_MANY:
        return SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_CLARIFICATION,
            next_action=NextAction.CLARIFY,
            reason="CandidateResolver returned TOO_MANY: too many candidates available",
            confidence="high",
        )

    # ── 2. Deduplicate ─────────────────────────────────────────────
    original_count = len(candidate_set.candidates)
    deduped = dedupe_candidates(candidate_set.candidates)
    deduped_count = len(deduped)

    if deduped_count == 0:
        return SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_CANDIDATES,
            next_action=NextAction.CLARIFY,
            reason="No valid candidates after deduplication",
            confidence="high",
        )

    # ── 3. Check min_required ──────────────────────────────────────
    effective_min = max(1, goal.min_required or candidate_set.min_required or min_required_for_goal(goal))

    if deduped_count < effective_min:
        reason_parts: list[str] = []
        if original_count != deduped_count:
            reason_parts.append(f"{original_count} candidates deduplicated to {deduped_count}")
        if goal.goal_type == GoalType.COMPARISON and candidate_set.source == CandidateSource.DISCOVERY:
            reason_parts.append(f"discovery comparison needs at least {effective_min} candidates, found {deduped_count}")
        else:
            reason_parts.append(f"need at least {effective_min} candidates, found {deduped_count}")
        return SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_CANDIDATES,
            next_action=NextAction.CLARIFY,
            reason="; ".join(reason_parts) or f"insufficient candidates ({deduped_count} < {effective_min})",
            affected_candidates=[c.shop_id for c in deduped],
            trace_payload={"original_count": original_count, "deduped_count": deduped_count, "min_required": effective_min},
            confidence="high",
        )

    # ── 4. Check single_shop_query uniqueness ──────────────────────
    if goal.goal_type == GoalType.SINGLE_SHOP_QUERY:
        if deduped_count > 1:
            return SufficiencyCheckResult(
                stage=ReviewStage.CANDIDATE_REVIEW,
                status=ReviewStatus.NEED_CLARIFICATION,
                next_action=NextAction.CLARIFY,
                reason=f"single_shop_query resolved {deduped_count} candidates; expected exactly 1",
                affected_candidates=[c.shop_id for c in deduped],
                confidence="high",
            )

    # ── 5. Check max_allowed and auto-trim ─────────────────────────
    effective_max = min(goal.max_allowed or candidate_set.max_allowed or 5, default_limit_for_goal(goal))

    if deduped_count > effective_max:
        # Auto-trim: keep first effective_max candidates
        trimmed = deduped[:effective_max]
        trace = {
            "trimmed": True,
            "original_count": deduped_count,
            "kept_count": len(trimmed),
            "max_allowed": effective_max,
            "requested_count": goal.requested_count,
            "min_required": effective_min,
        }
        # Build a candidate_set-like representation for downstream
        return SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.ENOUGH,
            next_action=NextAction.FINISH,
            reason=f"trimmed from {deduped_count} to {effective_max} candidates (max_allowed={effective_max})",
            affected_candidates=[c.shop_id for c in trimmed],
            trace_payload=trace,
            confidence="high",
        )

    # ── 6. Everything looks good ───────────────────────────────────
    return SufficiencyCheckResult(
        stage=ReviewStage.CANDIDATE_REVIEW,
        status=ReviewStatus.ENOUGH,
        next_action=NextAction.FINISH,
        reason=f"{deduped_count} candidate(s) resolved and sufficient for {goal.goal_type.value}",
        affected_candidates=[c.shop_id for c in deduped],
        trace_payload={
            "deduped_count": deduped_count,
            "requested_count": goal.requested_count,
            "min_required": effective_min,
            "max_allowed": effective_max,
        },
        confidence="high",
    )
