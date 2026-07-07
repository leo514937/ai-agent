"""DecisionPlanner — P2 structured decision planning.

Produces a ``DecisionPlan`` based **solely** on ``EvidencePack``.
Runs AFTER ``EvidenceReview`` and BEFORE ``DecisionReview``.

Responsibilities:
  1. Aggregate answerable / unknown / failed facets from EvidencePack.
  2. Build evidence-backed claims for each facet per candidate.
  3. Determine winner ONLY when evidence supports it.
  4. Do NOT judge sufficiency (that's DecisionReview).
  5. Do NOT output natural language (that's AnswerGenerator).
  6. Do NOT add new evidence.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ...domain.candidate import CandidateSet
from ...domain.decision import DecisionPlan, DecisionType
from ...domain.evidence import EvidenceReviewResult
from ...domain.goal import GoalPlan
from ...domain.schemas import EvidencePack
from ...observability.file_logger import get_python_service_logger, log_kv
from ..llm_utils import invoke_structured_llm, model_validate_or_error

_LOGGER = get_python_service_logger()


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


def _get_evidence_dict(pack: EvidencePack | dict[str, Any] | None) -> dict[str, Any]:
    """Normalise EvidencePack to a dict."""
    if pack is None:
        return {}
    if isinstance(pack, EvidencePack):
        return pack.model_dump()
    return _to_dict(pack)


def _classify_facet_status(
    item: dict[str, Any],
) -> str:
    """Classify a single facet result as answerable / unknown / failed."""
    raw = str(item.get("result_status") or item.get("status") or "unknown").lower()
    if raw in ("ok", "partial", "empty"):
        return "answerable"
    if raw in ("unknown",):
        return "unknown"
    if raw in ("failed", "error", "timeout", "unsupported", "circuit_open", "backend_unavailable"):
        return "failed"
    return "unknown"


def _build_claims_from_evidence(
    evidence_dict: dict[str, Any],
    candidates: list[str],
) -> list[dict[str, Any]]:
    """Build evidence-backed claims from EvidencePack.

    A claim is a dict with: shop_id, facet, claim_type, value, evidence_ids.
    """
    claims: list[dict[str, Any]] = []
    evidence_items = list(evidence_dict.get("evidence_items", []) or [])

    for item in evidence_items:
        item_dict = _to_dict(item)
        shop_id = str(item_dict.get("shop_id", "") or "")
        if shop_id and candidates and shop_id not in candidates:
            continue  # Skip items not in our candidate set
        facet = str(item_dict.get("facet", "") or "")
        if not facet:
            continue
        claim = {
            "shop_id": shop_id,
            "facet": facet,
            "claim_type": facet,
            "value": item_dict.get("value"),
            "evidence_ids": [str(item_dict.get("evidence_id", "") or "")],
            "confidence": float(item_dict.get("confidence", 1.0) or 1.0),
        }
        claims.append(claim)

    return claims


def _extract_ranking(
    evidence_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract ranking from EvidencePack's ranking_snapshot.

    Ranking is retained for trace/display compatibility only and must not
    be used as a winner fallback.
    """
    snapshot = evidence_dict.get("ranking_snapshot") or {}
    if isinstance(snapshot, dict):
        ranked = (snapshot.get("ranked") or
                  snapshot.get("ranked_shops") or
                  snapshot.get("shops") or [])
        if isinstance(ranked, list):
            result: list[dict[str, Any]] = []
            for item in ranked:
                item_dict = _to_dict(item)
                if item_dict.get("shop_id") or item_dict.get("shop_name"):
                    result.append(item_dict)
            return result
    return []


def _find_winner_from_evidence(
    evidence_dict: dict[str, Any],
    candidates: list[str],
    ranking: list[dict[str, Any]] | None = None,
) -> tuple[str | None, list[dict[str, Any]], list[str], str, str, bool]:
    """Pick a winner from evidence coverage only.

    Returns:
        winner_shop_id, evidence_ranking, missing_fields, next_action,
        reason, insufficient_evidence
    """
    if not candidates:
        return None, [], ["candidate_set"], "clarify", "no candidates available", True

    support_count: dict[str, int] = {sid: 0 for sid in candidates}
    evidence_refs: dict[str, list[str]] = {sid: [] for sid in candidates}

    for item in evidence_dict.get("evidence_items", []) or []:
        item_dict = _to_dict(item)
        shop_id = str(item_dict.get("shop_id", "") or "").strip()
        if shop_id not in support_count:
            continue
        if _classify_facet_status(item_dict) != "answerable":
            continue
        support_count[shop_id] += 1
        evidence_id = str(item_dict.get("evidence_id", "") or "").strip()
        if evidence_id and evidence_id not in evidence_refs[shop_id]:
            evidence_refs[shop_id].append(evidence_id)

    comparison_matrix = evidence_dict.get("comparison_matrix") or {}
    if isinstance(comparison_matrix, dict):
        dimension_winners = comparison_matrix.get("dimension_winners") or {}
        if isinstance(dimension_winners, dict):
            for dimension, winners in dimension_winners.items():
                if not isinstance(winners, list):
                    continue
                unique_winner_ids: list[str] = []
                for winner in winners:
                    winner_dict = _to_dict(winner)
                    shop_id = str(winner_dict.get("shop_id", "") or "").strip()
                    if shop_id not in support_count:
                        continue
                    unique_winner_ids.append(shop_id)
                    evidence_ref = f"comparison_matrix.dimension_winners.{dimension}"
                    if evidence_ref not in evidence_refs[shop_id]:
                        evidence_refs[shop_id].append(evidence_ref)
                if len(unique_winner_ids) == 1:
                    support_count[unique_winner_ids[0]] += 1

    winner_shop_id = None
    winner_score = 0
    tied = False
    for shop_id, score in support_count.items():
        if score > winner_score:
            winner_shop_id = shop_id
            winner_score = score
            tied = False
        elif score == winner_score and score > 0 and shop_id != winner_shop_id:
            tied = True

    if winner_score <= 0:
        missing_fields = ["claim_refs"]
        if not evidence_dict.get("evidence_items"):
            missing_fields.append("evidence_items")
        return None, [], missing_fields, "insufficient_evidence", "insufficient evidence to choose a winner", True

    if tied:
        return None, [], ["tie_break_evidence"], "present_tie", "tie or insufficient differentiating evidence", True

    evidence_ranking = [
        {
            "shop_id": shop_id,
            "evidence_count": score,
            "evidence_ids": evidence_refs[shop_id],
        }
        for shop_id, score in support_count.items()
        if score > 0
    ]
    evidence_ranking.sort(key=lambda item: (-int(item.get("evidence_count", 0) or 0), str(item.get("shop_id", ""))))
    return winner_shop_id, evidence_ranking, [], "finish", "", False


def _determine_decision_type(goal: GoalPlan | None) -> DecisionType:
    """Map GoalPlan.goal_type to DecisionType."""
    if goal is None:
        return DecisionType.UNSUPPORTED
    mapping = {
        "recommendation": DecisionType.RECOMMENDATION,
        "comparison": DecisionType.COMPARISON,
        "single_shop_query": DecisionType.SINGLE_SHOP_QUERY,
        "refinement": DecisionType.REFINEMENT if hasattr(DecisionType, "REFINEMENT") else DecisionType.RECOMMENDATION,
    }
    return mapping.get(goal.goal_type, DecisionType.UNSUPPORTED)


def plan_decision(
    goal_plan: GoalPlan | dict[str, Any] | None = None,
    candidate_set: CandidateSet | dict[str, Any] | None = None,
    evidence_pack: EvidencePack | dict[str, Any] | None = None,
    evidence_review: EvidenceReviewResult | dict[str, Any] | None = None,
) -> DecisionPlan:
    """Plan a structured decision based solely on evidence.

    Args:
        goal_plan: The GoalPlan (for goal_id and context).
        candidate_set: The resolved candidate set.
        evidence_pack: The evidence pack from tool execution.
        evidence_review: The evidence review result (for auxiliary info).

    Returns:
        A ``DecisionPlan`` ready for DecisionReview and AnswerGenerator.
    """
    evidence_dict = _get_evidence_dict(evidence_pack)
    facet_statuses = dict(evidence_dict.get("facet_statuses") or {})
    grounded_facts = dict(evidence_dict.get("grounded_facts") or {})
    facet_reasons = dict(evidence_dict.get("facet_reasons") or {})
    evidence_status = str(evidence_dict.get("evidence_status") or "").strip()
    comparison_support_status = str(evidence_dict.get("comparison_support_status") or "").strip()
    ranking_preserved = bool(evidence_dict.get("ranking_preserved", True))
    unsupported_reasons = list(evidence_dict.get("unsupported_reasons", []) or [])
    unknown_fields = list(evidence_dict.get("unknown_fields", []) or [])
    failed_tools = list(evidence_dict.get("failed_tools", []) or [])
    partial_fields = list(evidence_dict.get("partial_fields", []) or [])
    evidence_review_result = _to_dict(evidence_review) if evidence_review is not None else _to_dict(evidence_dict.get("evidence_review_result"))
    answer_verify_result = _to_dict(evidence_dict.get("answer_verify_result"))

    # --- 1. Extract candidates ---
    candidates: list[str] = []
    if candidate_set is not None:
        cs_dict = _to_dict(candidate_set) if not isinstance(candidate_set, dict) else candidate_set
        for c in cs_dict.get("candidates", []) or []:
            c_dict = _to_dict(c)
            sid = str(c_dict.get("shop_id", "") or "").strip()
            if sid and sid not in candidates:
                candidates.append(sid)

    # Fallback: extract from evidence target_shop_ids
    if not candidates:
        candidates = list(evidence_dict.get("target_shop_ids", []) or [])

    # --- 2. Classify facets ---
    facet_results = list(evidence_dict.get("facet_results", []) or [])
    answerable_facets: list[str] = []
    unknown_facets: list[str] = []
    failed_facets: list[str] = []

    for item in facet_results:
        item_dict = _to_dict(item)
        facet = str(item_dict.get("facet", "") or "")
        if not facet:
            continue
        status = _classify_facet_status(item_dict)
        if status == "answerable":
            if facet not in answerable_facets:
                answerable_facets.append(facet)
        elif status == "unknown":
            if facet not in unknown_facets:
                unknown_facets.append(facet)
        elif status == "failed":
            if facet not in failed_facets:
                failed_facets.append(facet)

    # --- 3. Build ranking ---
    ranking = _extract_ranking(evidence_dict)
    winner_shop_id, evidence_ranking, missing_fields, next_action, reason, insufficient_evidence = _find_winner_from_evidence(
        evidence_dict,
        candidates,
        ranking=ranking,
    )

    # --- 4. Build claims ---
    claims = _build_claims_from_evidence(evidence_dict, candidates)

    # --- 5. Build caveats ---
    caveats: list[str] = []
    if unknown_facets:
        caveats.append(f"cannot confirm: {', '.join(unknown_facets)}")
    if failed_facets:
        caveats.append(f"failed to retrieve: {', '.join(failed_facets)}")

    # --- 6. Forbidden claims and unknowns from evidence ---
    forbidden_claims = list(evidence_dict.get("forbidden_claims", []) or [])
    must_mention_unknowns: list[str] = []
    for item in evidence_dict.get("unknown_items", []) or []:
        item_dict = _to_dict(item)
        name = str(item_dict.get("shop_name", "") or "").strip()
        if name and name not in must_mention_unknowns:
            must_mention_unknowns.append(name)

    # --- 7. Determine decision_type ---
    decision_type = DecisionType.UNSUPPORTED
    goal = None
    if isinstance(goal_plan, GoalPlan):
        goal = goal_plan
        decision_type = _determine_decision_type(goal)
    elif isinstance(goal_plan, dict):
        gt = str(goal_plan.get("goal_type", "") or "")
        mapping = {
            "recommendation": DecisionType.RECOMMENDATION,
            "comparison": DecisionType.COMPARISON,
            "single_shop_query": DecisionType.SINGLE_SHOP_QUERY,
        }
        decision_type = mapping.get(gt, DecisionType.UNSUPPORTED)

    # --- 8. Goal ID ---
    goal_id = ""
    if goal is not None:
        goal_id = goal.goal_summary or ""
    elif isinstance(goal_plan, dict):
        goal_id = str(goal_plan.get("goal_summary", "") or "")

    # --- 9. Decision context ---
    decision_context: dict[str, Any] = {
        "candidate_count": len(candidates),
        "answerable_facet_count": len(answerable_facets),
        "unknown_facet_count": len(unknown_facets),
        "failed_facet_count": len(failed_facets),
        "has_winner": winner_shop_id is not None,
        "missing_fields": list(missing_fields),
        "next_action": next_action,
        "reason": reason,
        "insufficient_evidence": insufficient_evidence,
    }

    winner_evidence_refs: list[str] = []
    if winner_shop_id is not None:
        winner_claim_refs = []
        for claim in claims:
            if str(claim.get("shop_id", "") or "") == str(winner_shop_id):
                winner_claim_refs.extend([str(ev).strip() for ev in (claim.get("evidence_ids") or []) if str(ev).strip()])
        winner_evidence_refs = winner_claim_refs
        if not winner_evidence_refs and evidence_ranking:
            for row in evidence_ranking:
                if str(row.get("shop_id", "") or "") == str(winner_shop_id):
                    winner_evidence_refs.extend([str(ev).strip() for ev in (row.get("evidence_ids") or []) if str(ev).strip()])

    decision_reason = reason or ("winner selected from evidence" if winner_shop_id else "insufficient evidence to choose a winner")

    return DecisionPlan(
        decision_type=decision_type,
        goal_id=goal_id,
        facets=(goal.facets if goal is not None and hasattr(goal, "facets") else evidence_dict.get("facets", [])),
        target_resolution=(goal.target_resolution if goal is not None and hasattr(goal, "target_resolution") else evidence_dict.get("target_resolution")),
        conflicting_facets=(goal.conflicting_facets if goal is not None and hasattr(goal, "conflicting_facets") else evidence_dict.get("conflicting_facets", [])),
        ranking_policy=(goal.ranking_policy if goal is not None and hasattr(goal, "ranking_policy") else evidence_dict.get("ranking_policy")),
        candidates=candidates,
        answerable_facets=answerable_facets,
        unknown_facets=unknown_facets,
        failed_facets=failed_facets,
        winner_shop_id=winner_shop_id,
        ranking=ranking,
        ranking_source="evidence",
        claims=claims,
        caveats=caveats,
        forbidden_claims=forbidden_claims,
        must_mention_unknowns=must_mention_unknowns,
        decision_context=decision_context,
        facet_statuses=facet_statuses,
        grounded_facts=grounded_facts,
        facet_reasons=facet_reasons,
        evidence_status=evidence_status,
        comparison_support_status=comparison_support_status,
        ranking_preserved=ranking_preserved,
        unsupported_reasons=unsupported_reasons,
        unknown_fields=unknown_fields,
        failed_tools=failed_tools,
        partial_fields=partial_fields,
        evidence_review_result=evidence_review_result,
        answer_verify_result=answer_verify_result,
        decision_source="deterministic_decision_planner",
        decision_confidence=1.0 if winner_shop_id is not None else 0.0,
        decision_mode="deterministic",
        fallback_used=False,
        candidate_count_before_decision=len(candidates),
        candidate_count_after_decision=len(candidates),
        evidence_preserved=True,
        decision_reason=decision_reason,
        claim_bindings=[
            {"claim_id": f"claim_{idx+1}", "evidence_ids": claim.get("evidence_ids", [])}
            for idx, claim in enumerate(claims)
        ],
        winner_evidence_refs=winner_evidence_refs,
        missing_fields=list(missing_fields),
        next_action=next_action,
        reason=reason,
        insufficient_evidence=insufficient_evidence,
    )


def plan_decision_with_llm(
    goal_plan: GoalPlan | dict[str, Any] | None = None,
    candidate_set: CandidateSet | dict[str, Any] | None = None,
    evidence_pack: EvidencePack | dict[str, Any] | None = None,
    evidence_review: EvidenceReviewResult | dict[str, Any] | None = None,
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    strict: bool = False,
) -> tuple[DecisionPlan | None, dict[str, Any]]:
    log_kv(
        _LOGGER,
        logging.INFO,
        "[DECISION_PLANNER_START]",
        tone="llm",
        goal_plan=goal_plan,
        candidate_set=candidate_set,
        evidence_pack=evidence_pack,
        evidence_review=evidence_review,
        strict=strict,
    )
    evidence_dict = _get_evidence_dict(evidence_pack)
    replacements = {
        "{{GOAL_PLAN}}": _to_dict(goal_plan) if goal_plan is not None else {},
        "{{CANDIDATE_SET}}": _to_dict(candidate_set) if candidate_set is not None else {},
        "{{EVIDENCE_PACK}}": evidence_dict,
        "{{EVIDENCE_REVIEW}}": _to_dict(evidence_review) if evidence_review is not None else {},
    }
    try:
        llm_result = invoke_structured_llm(
            prompt_name="decision_planner",
            replacements=replacements,
            response_validator=DecisionPlan.model_validate,
            llm_call=llm_call,
        )
    except Exception as exc:
        error = {"error_code": "DECISION_PLANNER_PROMPT_ERROR", "error_message": str(exc), "llm_backend": "", "raw": ""}
        log_kv(_LOGGER, logging.ERROR, "[DECISION_PLANNER_ERROR]", tone="error", error=error)
        if strict:
            return None, error
        plan = plan_decision(goal_plan, candidate_set, evidence_pack, evidence_review)
        plan.decision_mode = "deterministic_fallback"
        plan.fallback_used = True
        plan.candidate_count_before_decision = len([c for c in (getattr(plan, "candidates", []) or []) if str(c).strip()]) if hasattr(plan, "candidates") else len(_to_dict(candidate_set).get("candidates", []) or [])
        plan.candidate_count_after_decision = len(list(plan.candidates or []))
        plan.evidence_preserved = True
        plan.decision_reason = plan.decision_reason or "llm_prompt_error_fallback"
        log_kv(_LOGGER, logging.WARNING, "[DECISION_PLANNER_FALLBACK]", tone="warn", decision_plan=plan, error=error)
        return plan, error

    if not llm_result.get("ok"):
        error = {
            "error_code": llm_result.get("error_code") or "DECISION_PLANNER_LLM_FAILED",
            "error_message": llm_result.get("error_message") or "decision planner llm failed",
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_LOGGER, logging.WARNING, "[DECISION_PLANNER_LLM_FAILED]", tone="warn", error=error)
        if strict:
            return None, error
        plan = plan_decision(goal_plan, candidate_set, evidence_pack, evidence_review)
        plan.decision_mode = "deterministic_fallback"
        plan.fallback_used = True
        plan.candidate_count_before_decision = len([c for c in (getattr(plan, "candidates", []) or []) if str(c).strip()]) if hasattr(plan, "candidates") else len(_to_dict(candidate_set).get("candidates", []) or [])
        plan.candidate_count_after_decision = len(list(plan.candidates or []))
        plan.evidence_preserved = True
        plan.decision_reason = plan.decision_reason or "llm_failed_fallback"
        log_kv(_LOGGER, logging.WARNING, "[DECISION_PLANNER_FALLBACK]", tone="warn", decision_plan=plan, error=error)
        return plan, error

    model, validation_error = model_validate_or_error(DecisionPlan, llm_result.get("payload") or {})
    if model is None:
        error = {
            "error_code": "DECISION_PLAN_SCHEMA_INVALID",
            "error_message": validation_error,
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        log_kv(_LOGGER, logging.WARNING, "[DECISION_PLANNER_SCHEMA_INVALID]", tone="warn", error=error)
        if strict:
            return None, error
        plan = plan_decision(goal_plan, candidate_set, evidence_pack, evidence_review)
        plan.decision_mode = "deterministic_fallback"
        plan.fallback_used = True
        plan.candidate_count_before_decision = len([c for c in (getattr(plan, "candidates", []) or []) if str(c).strip()]) if hasattr(plan, "candidates") else len(_to_dict(candidate_set).get("candidates", []) or [])
        plan.candidate_count_after_decision = len(list(plan.candidates or []))
        plan.evidence_preserved = True
        plan.decision_reason = plan.decision_reason or "schema_invalid_fallback"
        log_kv(_LOGGER, logging.WARNING, "[DECISION_PLANNER_FALLBACK]", tone="warn", decision_plan=plan, error=error)
        return plan, error

    plan = model
    decision_reason = str(plan.decision_reason or evidence_dict.get("decision_reason") or "").strip()
    plan.decision_source = plan.decision_source or "llm_decision_planner"
    plan.decision_mode = "llm"
    plan.candidate_count_before_decision = len(list(plan.candidates or []))
    plan.candidate_count_after_decision = len(list(plan.candidates or []))
    plan.fallback_used = False
    plan.evidence_preserved = True
    plan.decision_reason = plan.decision_reason or decision_reason
    needs_fallback = (
        plan.decision_type == DecisionType.UNSUPPORTED
        or not list(plan.candidates or [])
        or (plan.winner_shop_id is None and not list(plan.answerable_facets or []))
    )
    if needs_fallback:
        deterministic_plan = plan_decision(goal_plan, candidate_set, evidence_pack, evidence_review)
        if deterministic_plan is not None:
            deterministic_has_signal = bool(deterministic_plan.candidates or deterministic_plan.winner_shop_id or deterministic_plan.answerable_facets)
            if deterministic_has_signal and (
                deterministic_plan.decision_type != DecisionType.UNSUPPORTED
                or deterministic_plan.candidates
                or deterministic_plan.winner_shop_id
            ):
                deterministic_plan.decision_source = deterministic_plan.decision_source or "deterministic_decision_planner_fallback"
                deterministic_plan.decision_mode = "deterministic_fallback"
                deterministic_plan.fallback_used = True
                deterministic_plan.candidate_count_before_decision = len(list(deterministic_plan.candidates or []))
                deterministic_plan.candidate_count_after_decision = len(list(deterministic_plan.candidates or []))
                deterministic_plan.evidence_preserved = True
                deterministic_plan.decision_reason = deterministic_plan.decision_reason or decision_reason
                error = {
                    "error_code": "DECISION_PLANNER_UNSUPPORTED_FALLBACK",
                    "error_message": "llm decision was unsupported or empty; fell back to deterministic plan",
                    "llm_backend": llm_result.get("llm_backend", ""),
                    "raw": llm_result.get("raw", ""),
                }
                log_kv(_LOGGER, logging.WARNING, "[DECISION_PLANNER_FALLBACK]", tone="warn", decision_plan=deterministic_plan, error=error)
                return deterministic_plan, error
    log_kv(
        _LOGGER,
        logging.INFO,
        "[DECISION_PLANNER_RESULT]",
        tone="llm",
        llm_backend=llm_result.get("llm_backend", ""),
        decision_plan=plan,
        candidate_count_before_decision=plan.candidate_count_before_decision,
        candidate_count_after_decision=plan.candidate_count_after_decision,
        decision_mode=plan.decision_mode,
        fallback_used=plan.fallback_used,
        evidence_preserved=plan.evidence_preserved,
    )
    return plan, {
        "error_code": "",
        "error_message": "",
        "llm_backend": llm_result.get("llm_backend", ""),
        "raw": llm_result.get("raw", ""),
    }
