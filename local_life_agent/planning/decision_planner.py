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

from typing import Any

from ..domain.candidate import CandidateSet
from ..domain.decision import DecisionPlan, DecisionType
from ..domain.evidence import EvidenceReviewResult
from ..domain.goal import GoalPlan
from ..domain.schemas import EvidencePack


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
    """Extract ranking from EvidencePack's ranking_snapshot."""
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


def _find_winner_from_ranking(
    ranking: list[dict[str, Any]],
) -> str | None:
    """Find the top-ranked shop from evidence ranking."""
    if ranking and isinstance(ranking[0], dict):
        return str(ranking[0].get("shop_id", "") or "") or None
    return None


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
    winner_shop_id = _find_winner_from_ranking(ranking)

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
    }

    return DecisionPlan(
        decision_type=decision_type,
        goal_id=goal_id,
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
    )
