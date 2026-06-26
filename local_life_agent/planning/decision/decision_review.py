"""DecisionReview — P2 decision sufficiency gate.

Runs AFTER DecisionPlanner and BEFORE AnswerGenerator.
Evaluates whether the DecisionPlan is sufficient to generate a
truthful answer, and determines the correct next_action.

Possible next_actions:
  - FINISH              → sufficient, proceed to answer generation.
  - REPLAN_EVIDENCE     → missing required evidence, replan.
  - EXPAND_SEARCH       → need more candidates, expand search.
  - DEGRADE_ANSWER      → partial info available, degrade gracefully.
  - UNSUPPORTED_ANSWER  → goal unsupported, explain why.
  - FALLBACK            → cannot answer at all, use fallback.
  - CLARIFY             → need user clarification.

DecisionReview does NOT:
  - Add new evidence.
  - Modify the DecisionPlan.
  - Generate natural language.
  - Call LLM.

LLMs are used upstream for semantic understanding and planning. This stage
remains deterministic so routing decisions stay explainable, testable, and
stable across repeated runs.
"""

from __future__ import annotations

from typing import Any

from ...domain.decision import DecisionPlan, DecisionReviewResult
from ...domain.evidence import EvidenceReviewResult
from ...domain.goal import GoalPlan
from ..policies.review_policy import SufficiencyCheckResult


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


def _evidence_review_violations(
    evidence_review: EvidenceReviewResult | dict[str, Any] | None,
) -> tuple[bool, str]:
    """Check if EvidenceReview detected unknown_as_false or failed_as_empty."""
    if evidence_review is None:
        return False, ""
    if isinstance(evidence_review, EvidenceReviewResult):
        uaf = evidence_review.unknown_as_false_detected
        fae = evidence_review.failed_as_empty_detected
    else:
        uaf = bool(evidence_review.get("unknown_as_false_detected", False))
        fae = bool(evidence_review.get("failed_as_empty_detected", False))

    if uaf:
        return True, "unknown_as_false_detected_by_evidence_review"
    if fae:
        return True, "failed_as_empty_detected_by_evidence_review"
    return False, ""


def _can_determine_winner(
    decision_plan: DecisionPlan,
) -> bool:
    """Check if the DecisionPlan has enough info for a deterministic winner.

    A deterministic winner requires:
      1. At least one answerable facet.
      2. No unknown or failed facets on the winner candidate.
      3. Ranking is evidence-based, not forced.
    """
    if not decision_plan.answerable_facets:
        return False
    if decision_plan.winner_shop_id is None:
        return False
    if decision_plan.ranking_source == "forbidden":
        return False
    # If there are unknown/failed facets, winner is conditional
    if decision_plan.unknown_facets or decision_plan.failed_facets:
        return False
    if not decision_plan.winner_evidence_refs:
        return False
    return True


def _validate_claim_bindings(decision_plan: DecisionPlan) -> tuple[bool, str]:
    if not decision_plan.claims:
        return True, ""
    bindings = decision_plan.claim_bindings or []
    binding_map: dict[str, list[str]] = {}
    for item in bindings:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id", "") or "").strip()
        evidence_ids = [str(ev).strip() for ev in (item.get("evidence_ids") or []) if str(ev).strip()]
        if claim_id:
            binding_map[claim_id] = evidence_ids
    for idx, claim in enumerate(decision_plan.claims, start=1):
        claim_dict = _to_dict(claim)
        claim_id = str(claim_dict.get("claim_id", "") or f"claim_{idx}")
        evidence_ids = [str(ev).strip() for ev in (claim_dict.get("evidence_ids") or []) if str(ev).strip()]
        if not evidence_ids:
            evidence_ids = binding_map.get(claim_id, [])
        if not evidence_ids:
            return False, f"claim_missing_evidence_refs:{claim_id}"
    return True, ""


def _has_core_coverage(
    decision_plan: DecisionPlan,
    goal_plan: GoalPlan | None,
) -> tuple[bool, list[str]]:
    """Check if required facets from the goal are covered.

    Returns (covered, missing_facets).
    """
    missing: list[str] = []

    if goal_plan is None:
        return True, []

    required = list(goal_plan.required_facets or [])
    if not required:
        return True, []

    answerable = set(decision_plan.answerable_facets)
    unknown = set(decision_plan.unknown_facets)
    failed = set(decision_plan.failed_facets)

    for f in required:
        if f not in answerable and f not in unknown and f not in failed:
            missing.append(f)

    return len(missing) == 0, missing


def review_decision(
    decision_plan: DecisionPlan | None = None,
    goal_plan: GoalPlan | dict[str, Any] | None = None,
    evidence_review: EvidenceReviewResult | dict[str, Any] | None = None,
    candidate_review: SufficiencyCheckResult | dict[str, Any] | None = None,
    expand_search_count: int = 0,
    replan_evidence_count: int = 0,
) -> DecisionReviewResult:
    """Review the DecisionPlan and determine next_action.

    Args:
        decision_plan: The DecisionPlan to review (may be None if planning failed).
        goal_plan: The originating GoalPlan.
        evidence_review: EvidenceReview result (for violation detection).
        candidate_review: CandidateReview result (for need_more_candidates).
        expand_search_count: Current expand_search round count.
        replan_evidence_count: Current replan_evidence round count.

    Returns:
        A ``DecisionReviewResult`` with next_action and supporting detail.
    """
    trace: dict[str, Any] = {}
    missing_facets: list[str] = []
    unknown_facets: list[str] = []
    failed_facets: list[str] = []

    # --- 1. No DecisionPlan at all → FALLBACK ---
    if decision_plan is None:
        return DecisionReviewResult(
            stage="decision_review",
            status="insufficient",
            next_action="FALLBACK",
            reason="no decision plan produced",
            missing_facets=[],
            trace_payload={"error": "decision_plan_is_none"},
        )

    # --- 2. Check for unsupported goal ---
    if goal_plan is not None:
        gp = goal_plan if isinstance(goal_plan, GoalPlan) else GoalPlan.model_validate(goal_plan)
        if gp.unsupported:
            return DecisionReviewResult(
                stage="decision_review",
                status="unsupported",
                next_action="UNSUPPORTED_ANSWER",
                reason=gp.unsupported_reason or "unsupported_goal",
                trace_payload={"unsupported_reason": gp.unsupported_reason},
            )

    # --- 3. Check for evidence_review violations ---
    has_violation, violation_reason = _evidence_review_violations(evidence_review)
    if has_violation:
        return DecisionReviewResult(
            stage="decision_review",
            status="insufficient",
            next_action="FALLBACK",
            reason=violation_reason,
            trace_payload={"evidence_review_violation": violation_reason},
        )

    claim_bindings_ok, binding_reason = _validate_claim_bindings(decision_plan)
    if not claim_bindings_ok:
        return DecisionReviewResult(
            stage="decision_review",
            status="insufficient",
            next_action="FALLBACK",
            reason=binding_reason,
            trace_payload={"binding_reason": binding_reason},
        )

    # --- 4. Check candidate_review for need_more_candidates ---
    if candidate_review is not None:
        crn = None
        if isinstance(candidate_review, SufficiencyCheckResult):
            crn = candidate_review.next_action
        elif isinstance(candidate_review, dict):
            crn = candidate_review.get("next_action")
        if crn in ("EXPAND_SEARCH",):
            return DecisionReviewResult(
                stage="decision_review",
                status="insufficient",
                next_action="EXPAND_SEARCH",
                reason="candidate_review_requires_more_candidates",
                trace_payload={"candidate_review_action": str(crn)},
            )

    # --- 5. Check if the plan has any answerable facets ---
    if not decision_plan.answerable_facets:
        # All facets are unknown/failed → FALLBACK
        if decision_plan.unknown_facets or decision_plan.failed_facets:
            return DecisionReviewResult(
                stage="decision_review",
                status="insufficient",
                next_action="FALLBACK",
                reason="no_answerable_facets_all_unknown_or_failed",
                unknown_facets=list(decision_plan.unknown_facets),
                failed_facets=list(decision_plan.failed_facets),
                trace_payload={
                    "unknown_facets": list(decision_plan.unknown_facets),
                    "failed_facets": list(decision_plan.failed_facets),
                },
            )
        return DecisionReviewResult(
            stage="decision_review",
            status="insufficient",
            next_action="FALLBACK",
            reason="no_answerable_facets",
            trace_payload={"reason": "empty_decision_plan"},
        )

    # --- 6. Check core coverage ---
    goal_obj = goal_plan if isinstance(goal_plan, GoalPlan) else None
    core_covered, missing = _has_core_coverage(decision_plan, goal_obj)
    if not core_covered:
        missing_facets.extend(missing)
        trace["missing_required_facets"] = missing
        # Can we replan evidence?
        from ... import config as _cfg
        if replan_evidence_count < _cfg.MAX_REPLAN_EVIDENCE_ROUNDS:
            return DecisionReviewResult(
                stage="decision_review",
                status="insufficient",
                next_action="REPLAN_EVIDENCE",
                reason=f"missing_required_facets: {missing}",
                missing_facets=missing,
                trace_payload=trace,
            )
        # Replan exhausted → degrade or fallback
        if decision_plan.unknown_facets or decision_plan.failed_facets:
            return DecisionReviewResult(
                stage="decision_review",
                status="partial",
                next_action="DEGRADE_ANSWER",
                can_degrade=True,
                reason=f"missing_required_facets_after_replan_exhausted: {missing}",
                missing_facets=missing,
                unknown_facets=list(decision_plan.unknown_facets),
                failed_facets=list(decision_plan.failed_facets),
                trace_payload=trace,
            )
        return DecisionReviewResult(
            stage="decision_review",
            status="insufficient",
            next_action="FALLBACK",
            reason=f"missing_required_facets_no_replan_left: {missing}",
            missing_facets=missing,
            trace_payload=trace,
        )

    # --- 7. Check deterministic winner ---
    can_determine = _can_determine_winner(decision_plan)
    trace["can_determine_winner"] = can_determine
    trace["has_winner"] = decision_plan.winner_shop_id is not None

    if decision_plan.winner_shop_id is not None and not can_determine:
        # Winner claimed but evidence doesn't fully support it
        return DecisionReviewResult(
            stage="decision_review",
            status="partial",
            next_action="DEGRADE_ANSWER",
            can_degrade=True,
            is_deterministic_winner=False,
            reason="winner_claimed_but_evidence_insufficient_for_deterministic_verdict",
            unknown_facets=list(decision_plan.unknown_facets),
            failed_facets=list(decision_plan.failed_facets),
            trace_payload={**trace, "warning": "non_deterministic_winner"},
        )

    # --- 8. Check for candidate_review need_more_candidates with expand_search available ---
    if candidate_review is not None:
        cr_status = None
        if isinstance(candidate_review, SufficiencyCheckResult):
            cr_status = candidate_review.status
        elif isinstance(candidate_review, dict):
            cr_status = candidate_review.get("status")

        if cr_status in ("need_more_candidates", "need_clarification"):
            from ... import config as _cfg
            if expand_search_count < _cfg.MAX_EXPAND_SEARCH_ROUNDS:
                return DecisionReviewResult(
                    stage="decision_review",
                    status="insufficient",
                    next_action="EXPAND_SEARCH",
                    reason="candidate_review_needs_more_candidates",
                    trace_payload={"candidate_review_status": str(cr_status)},
                )

    # --- 9. Check if we have any unknown or failed facets (but core is covered) ---
    if decision_plan.unknown_facets or decision_plan.failed_facets:
        # Some info missing but core is covered → can degrade
        return DecisionReviewResult(
            stage="decision_review",
            status="partial",
            next_action="DEGRADE_ANSWER",
            can_degrade=True,
            reason=f"partial_information: unknown={decision_plan.unknown_facets}, failed={decision_plan.failed_facets}",
            unknown_facets=list(decision_plan.unknown_facets),
            failed_facets=list(decision_plan.failed_facets),
            trace_payload=trace,
        )

    # --- 10. All good → FINISH ---
    trace["decision"] = "sufficient"
    trace["answerable_facets"] = list(decision_plan.answerable_facets)
    trace["winner"] = decision_plan.winner_shop_id

    return DecisionReviewResult(
        stage="decision_review",
        status="sufficient",
        next_action="FINISH",
        reason="decision_plan_sufficient_for_answer",
        is_deterministic_winner=can_determine and decision_plan.winner_shop_id is not None,
        trace_payload=trace,
    )
