"""Decision domain models for P2 DecisionPlanner + DecisionReview.

Defines the structured DecisionPlan output (replaces the legacy DecisionPlan
in ``domain/schemas.py`` for P2 flows) and DecisionReviewResult.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..planning.review_policy import NextAction
from .facets import ConflictingFacet, FacetSet, QueryFacet, RankingPolicy, TargetResolutionResult

# Re-export DomainGoalDraft for assignment in graph_builder
try:
    from .schemas import DomainGoalDraft
except ImportError:
    DomainGoalDraft = None  # type: ignore


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


def _coerce_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _coerce_facets(value: Any) -> list[dict[str, Any]]:
    from .facets import QueryFacet

    raw = value
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, dict):
        raw = raw.get("facets", [])
    facets: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, QueryFacet):
            payload = item.model_dump()
        elif hasattr(item, "model_dump"):
            payload = item.model_dump()
        elif isinstance(item, dict):
            payload = dict(item)
        else:
            payload = {"name": str(item or ""), "group": ""}
        if not str(payload.get("name", "") or "").strip():
            continue
        facets.append(payload)
    return facets


def _coerce_target_resolution(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return _to_dict(value) or None


def _coerce_conflicting_facets(value: Any) -> list[dict[str, Any]]:
    raw = value
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, dict):
        raw = raw.get("conflicting_facets", raw.get("items", []))
    items: list[dict[str, Any]] = []
    for item in raw or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if isinstance(item, dict):
            items.append(dict(item))
    return items


def _coerce_ranking_policy(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return _to_dict(value) or None


def _coerce_dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    try:
        return dict(value)
    except Exception:
        return {}


def decision_to_answer_plan(decision_plan: DecisionPlan, evidence_pack: Any = None) -> dict:
    """Convert a P2 DecisionPlan to an AnswerPlan-compatible dict.

    This bridges the P2 DecisionPlan (produced by DecisionPlanner) into the
    AnswerPlan format consumed by AnswerGenerator / answer_plan_build.

    ``evidence_pack`` may be a dict or an EvidencePack Pydantic model.
    """
    from .schemas import AnswerPlan

    decision_type = decision_plan.decision_type
    target_shop_ids: list[str] = []
    if decision_plan.winner_shop_id:
        target_shop_ids = [decision_plan.winner_shop_id]
    elif decision_plan.candidates:
        target_shop_ids = decision_plan.candidates[:]

    # Build response sections based on decision plan
    response_sections: list[dict[str, Any]] = [
        {
            "section_id": "summary",
            "section_type": "summary",
            "target_shop_ids": target_shop_ids,
            "status": "ok" if decision_plan.winner_shop_id else "unknown",
        },
    ]

    # Facet sections from answerable facets
    for facet in decision_plan.answerable_facets:
        response_sections.append({
            "section_id": f"facet_{facet}",
            "section_type": facet,
            "required": True,
            "status": "ok",
        })

    # Unknown facets
    for facet in decision_plan.unknown_facets:
        response_sections.append({
            "section_id": f"facet_{facet}",
            "section_type": facet,
            "required": True,
            "status": "unknown",
        })

    # Failed facets
    for facet in decision_plan.failed_facets:
        response_sections.append({
            "section_id": f"facet_{facet}",
            "section_type": facet,
            "required": False,
            "status": "failed",
        })

    # Map claims to allowed_claims
    allowed_claims: list[dict[str, Any]] = []
    claims = decision_plan.claims or []
    for idx, claim in enumerate(claims, start=1):
        claim_id = claim.get("claim_id", f"claim_{idx}")
        allowed_claims.append({
            "claim_id": claim_id,
            "shop_id": claim.get("shop_id", decision_plan.winner_shop_id or ""),
            "facet": claim.get("facet", "unknown"),
            "evidence_ids": claim.get("evidence_ids", []),
            "claim_type": claim.get("claim_type", "factual"),
            "value": claim.get("value", ""),
            "verbalization_hint": claim.get("verbalization_hint", ""),
        })

    required_disclaimers: list[str] = []
    if decision_plan.unknown_facets:
        required_disclaimers.append(f"部分信息暂无法确认: {', '.join(decision_plan.unknown_facets)}")
    if decision_plan.failed_facets:
        required_disclaimers.append(f"部分工具结果失败: {', '.join(decision_plan.failed_facets)}")

    # Normalize evidence_pack: accept both dict and Pydantic model
    evidence: dict[str, Any] = {}
    if evidence_pack is not None:
        if isinstance(evidence_pack, dict):
            evidence = evidence_pack
        elif hasattr(evidence_pack, "model_dump"):
            evidence = evidence_pack.model_dump()
        elif hasattr(evidence_pack, "dict"):
            evidence = evidence_pack.dict()
        else:
            try:
                evidence = dict(evidence_pack)
            except (TypeError, ValueError):
                evidence = {}

    snapshot = evidence.get("ranking_snapshot") or {}
    comparison_matrix = evidence.get("comparison_matrix") or {}

    return {
        "answer_type": _map_decision_type_to_answer_type(decision_type),
        "facets": _coerce_facets(decision_plan.facets if hasattr(decision_plan, "facets") else evidence.get("facets", [])),
        "target_resolution": _coerce_target_resolution(decision_plan.target_resolution if hasattr(decision_plan, "target_resolution") else evidence.get("target_resolution")),
        "conflicting_facets": _coerce_conflicting_facets(decision_plan.conflicting_facets if hasattr(decision_plan, "conflicting_facets") else evidence.get("conflicting_facets", [])),
        "ranking_policy": _coerce_ranking_policy(decision_plan.ranking_policy if hasattr(decision_plan, "ranking_policy") else evidence.get("ranking_policy")),
        "answerable_facets": list(decision_plan.answerable_facets or []),
        "unknown_facets": list(decision_plan.unknown_facets or []),
        "failed_facets": list(decision_plan.failed_facets or []),
        "required_disclaimers": required_disclaimers,
        "target_shop_ids": target_shop_ids,
        "response_sections": response_sections,
        "allowed_claims": allowed_claims,
        "required_claims": [],
        "must_mention_unknowns": decision_plan.must_mention_unknowns or decision_plan.unknown_facets[:],
        "forbidden_claims": decision_plan.forbidden_claims or evidence.get("forbidden_claims", []),
        "ranking_snapshot_id": snapshot.get("snapshot_id", ""),
        "comparison_matrix_id": comparison_matrix.get("matrix_id", ""),
        "tone": decision_plan.decision_context.get("tone", "neutral") if isinstance(decision_plan.decision_context, dict) else "neutral",
        "facet_statuses": dict(getattr(decision_plan, "facet_statuses", {}) or {}),
        "grounded_facts": dict(getattr(decision_plan, "grounded_facts", {}) or {}),
        "facet_reasons": dict(getattr(decision_plan, "facet_reasons", {}) or {}),
        "fallback_template_type": _map_fallback_template(decision_plan, evidence),
    }


def _map_decision_type_to_answer_type(dt: DecisionType) -> str:
    mapping: dict[DecisionType, str] = {
        DecisionType.RECOMMENDATION: "recommendation",
        DecisionType.COMPARISON: "comparison",
        DecisionType.SINGLE_SHOP_QUERY: "single_shop_query",
        DecisionType.COUPON_QUERY: "single_shop_query",
        DecisionType.OPEN_STATUS_QUERY: "single_shop_query",
        DecisionType.DISTANCE_QUERY: "single_shop_query",
        DecisionType.UNSUPPORTED: "error",
        DecisionType.DEGRADED: "single_shop_query",
    }
    return mapping.get(dt, "single_shop_query")


def _map_fallback_template(decision_plan: DecisionPlan, evidence: dict) -> str:
    """Map decision plan state to fallback template type."""
    if decision_plan.winner_shop_id:
        if decision_plan.unknown_facets or decision_plan.failed_facets:
            return "multi_facet_partial"
        return "multi_facet_ok"
    if decision_plan.failed_facets and not decision_plan.answerable_facets:
        return "multi_facet_failed"
    if decision_plan.unknown_facets and not decision_plan.answerable_facets:
        return "multi_facet_empty"
    if decision_plan.decision_type == DecisionType.UNSUPPORTED:
        return "unsupported"
    return "multi_facet_partial"


class DecisionType(str, Enum):
    """Type of decision being made."""
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SINGLE_SHOP_QUERY = "single_shop_query"
    COUPON_QUERY = "coupon_query"
    OPEN_STATUS_QUERY = "open_status_query"
    DISTANCE_QUERY = "distance_query"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"


class DecisionPlan(BaseModel):
    """Structured decision plan produced by DecisionPlanner.

    This is the authoritative plan consumed by AnswerGenerator.
    It is based solely on EvidencePack — no new facts, no LLM winner changes.

    All claims must be bindable to EvidencePack entries.
    """
    decision_type: DecisionType = DecisionType.UNSUPPORTED
    goal_id: str = ""                    # Ties back to the goal that spawned this decision
    facets: list[QueryFacet] = Field(default_factory=list)
    target_resolution: TargetResolutionResult | None = None
    conflicting_facets: list[ConflictingFacet] = Field(default_factory=list)
    ranking_policy: RankingPolicy | None = None
    candidates: list[str] = Field(default_factory=list)  # shop_ids considered
    answerable_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_facets: list[str] = Field(default_factory=list)

    # Ranking / winner — must be evidence-backed
    winner_shop_id: str | None = None
    ranking: list[dict[str, Any]] = Field(default_factory=list)
    ranking_source: str = ""             # evidence | forbidden

    # Per-facet claims bound to evidence
    claims: list[dict[str, Any]] = Field(default_factory=list)

    # Caveats about missing/unreliable data
    caveats: list[str] = Field(default_factory=list)

    # Optional next goal for multi-goal flows
    next_goal: dict[str, Any] | None = None

    # Decision context
    decision_context: dict[str, Any] = Field(default_factory=dict)
    style_hints: list[str] = Field(default_factory=list)

    # Phase 6 semantic sidecar fields
    semantic_frame: dict[str, Any] = Field(default_factory=dict)
    semantic_parse_source: str = ""
    grounding_status: str = ""
    missing_slot_type: str = ""
    router_policy_decision: dict[str, Any] = Field(default_factory=dict)
    router_policy_conflicts: list[str] = Field(default_factory=list)
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    facet_statuses: dict[str, str] = Field(default_factory=dict)
    grounded_facts: dict[str, Any] = Field(default_factory=dict)
    facet_reasons: dict[str, str] = Field(default_factory=dict)
    evidence_status: str = ""
    comparison_support_status: str = ""
    ranking_preserved: bool = True
    unsupported_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    partial_fields: list[str] = Field(default_factory=list)
    evidence_review_result: dict[str, Any] = Field(default_factory=dict)
    answer_verify_result: dict[str, Any] = Field(default_factory=dict)

    # For AnswerGenerator: forbidden claims, unknowns to mention
    forbidden_claims: list[str] = Field(default_factory=list)
    must_mention_unknowns: list[str] = Field(default_factory=list)
    decision_source: str = ""
    decision_confidence: float = 0.0
    decision_mode: str = ""
    fallback_used: bool = False
    candidate_count_before_decision: int = 0
    candidate_count_after_decision: int = 0
    evidence_preserved: bool = True
    decision_reason: str = ""
    claim_bindings: list[dict[str, Any]] = Field(default_factory=list)
    winner_evidence_refs: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    next_action: str = ""
    reason: str = ""
    decision_reason: str = ""
    insufficient_evidence: bool = False

    @field_validator(
        "facets",
        "conflicting_facets",
        "candidates",
        "answerable_facets",
        "unknown_facets",
        "failed_facets",
        "ranking",
        "claims",
        "caveats",
        "style_hints",
        "forbidden_claims",
        "must_mention_unknowns",
        "claim_bindings",
        "winner_evidence_refs",
        "missing_fields",
        "router_policy_conflicts",
        "stage_queries",
        "stage_statuses",
        "unsupported_reasons",
        "unknown_fields",
        "failed_tools",
        "partial_fields",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

    @field_validator("location", "facet_statuses", "grounded_facts", "facet_reasons", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, value: Any) -> dict[str, Any]:
        return _coerce_dict_value(value)


class DecisionReviewResult(BaseModel):
    """Output from DecisionReview — evaluates DecisionPlan sufficiency.

    Written to ``GraphState.review_results["decision_review"]``.
    """
    stage: str = "decision_review"
    status: str = "sufficient"     # sufficient | insufficient | partial | unsupported
    next_action: NextAction = NextAction.FINISH
    reason: str = ""
    can_degrade: bool = False
    missing_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_facets: list[str] = Field(default_factory=list)
    is_deterministic_winner: bool = False
    trace_payload: dict[str, Any] = Field(default_factory=dict)
