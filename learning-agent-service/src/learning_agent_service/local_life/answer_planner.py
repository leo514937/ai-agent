from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .answer_depth_policy import build_answer_structure_requirements, derive_answer_depth_policy
from .answer_linter import prune_context_for_contract

_DECISION_TYPES = {
    "recommend",
    "compare",
    "shop_detail",
    "coupon_advice",
    "environment_check",
    "avoid_pit",
    "booking",
    "order",
    "clarification",
    "fallback",
}

_CONFIDENCE_LEVELS = {"high", "medium", "low"}
_FIT_LEVELS = {"high", "medium", "low", "unknown"}
_WORTH_LEVELS = {"high", "medium", "low", "unknown"}


class LocalLifeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _reply_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, Mapping):
            text = _clean_text(item.get("label") or item.get("prompt") or item.get("value"))
        else:
            text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_choice(value: Any, *, allowed: set[str], default: str) -> str:
    text = _clean_text(value)
    if not text:
        return default
    lowered = text.lower()
    return lowered if lowered in allowed else default


def _normalize_scene_fit(value: Any) -> str:
    return _normalize_choice(value, allowed=_FIT_LEVELS, default="unknown")


def _normalize_worth_it(value: Any) -> str:
    return _normalize_choice(value, allowed=_WORTH_LEVELS, default="unknown")


def _normalize_decision_type(value: Any) -> str:
    return _normalize_choice(value, allowed=_DECISION_TYPES, default="fallback")


def _normalize_confidence(value: Any) -> str:
    return _normalize_choice(value, allowed=_CONFIDENCE_LEVELS, default="medium")


class EvidenceItem(LocalLifeModel):
    evidence_id: str
    chunk_id: str
    source_type: str
    shop_id: int | None = None
    claim: str
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_type: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data.setdefault("evidence_id", next_data.get("chunk_id"))
        next_data.setdefault("chunk_id", next_data.get("evidence_id"))
        next_data.setdefault("source_type", next_data.get("chunk_type") or "unknown")
        next_data["claim"] = _clean_text(next_data.get("claim") or next_data.get("support_text") or next_data.get("text")) or ""
        next_data["metadata"] = _as_mapping(next_data.get("metadata"))
        if next_data.get("shop_id") in ("", None):
            metadata_shop_id = next_data["metadata"].get("shop_id")
            if metadata_shop_id not in (None, ""):
                next_data["shop_id"] = metadata_shop_id
        return next_data


class SceneFitSummary(LocalLifeModel):
    scene: str = "unknown"
    fit: str = "unknown"
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["scene"] = _clean_text(next_data.get("scene")) or "unknown"
        next_data["fit"] = _normalize_scene_fit(next_data.get("fit"))
        next_data["reason"] = _clean_text(next_data.get("reason")) or ""
        return next_data


class CouponAdvice(LocalLifeModel):
    has_coupon: bool | None = None
    worth_it: str = "unknown"
    reason: str = ""
    risk: str = ""

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        if isinstance(next_data.get("has_coupon"), str):
            lowered = next_data["has_coupon"].strip().lower()
            if lowered in {"true", "yes", "1"}:
                next_data["has_coupon"] = True
            elif lowered in {"false", "no", "0"}:
                next_data["has_coupon"] = False
        next_data["worth_it"] = _normalize_worth_it(next_data.get("worth_it"))
        next_data["reason"] = _clean_text(next_data.get("reason")) or ""
        next_data["risk"] = _clean_text(next_data.get("risk")) or ""
        return next_data


class CandidateEvidenceSummary(LocalLifeModel):
    shop_id: int | None = None
    name: str
    rank: int = 0
    fit_score: float = 0.0
    why: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    coupon_summary: str = ""
    scene_fit: SceneFitSummary = Field(default_factory=SceneFitSummary)
    evidence_used: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["why"] = _string_list(next_data.get("why") or next_data.get("reasons") or next_data.get("reason"))
        next_data["risks"] = _string_list(next_data.get("risks") or next_data.get("risk_flags"))
        next_data["coupon_summary"] = _clean_text(next_data.get("coupon_summary") or next_data.get("coupon")) or ""
        next_data["evidence_used"] = _string_list(next_data.get("evidence_used") or next_data.get("evidence_ids"))
        scene_fit = next_data.get("scene_fit")
        if scene_fit is None:
            next_data["scene_fit"] = {
                "scene": "unknown",
                "fit": "unknown",
                "reason": "",
            }
        elif isinstance(scene_fit, Mapping):
            next_data["scene_fit"] = dict(scene_fit)
        else:
            next_data["scene_fit"] = _as_mapping(scene_fit)
        if next_data.get("name") is None:
            next_data["name"] = ""
        return next_data


class NextAction(LocalLifeModel):
    label: str
    action: str
    shop_id: int | None = None
    query: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["label"] = _clean_text(next_data.get("label") or next_data.get("title")) or ""
        next_data["action"] = _clean_text(next_data.get("action") or next_data.get("type")) or ""
        next_data["query"] = _clean_text(next_data.get("query"))
        return next_data


class EvidencePack(LocalLifeModel):
    raw_query: str = ""
    slots: dict[str, Any] = Field(default_factory=dict)
    rag_mode: str = "single_shop_rag"
    target_shop_id: int | None = None
    ranked_candidates: list[CandidateEvidenceSummary] = Field(default_factory=list)
    items: list[EvidenceItem] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    shop_evidence_map: dict[str, list[str]] = Field(default_factory=dict)
    grouped_by_shop: dict[str, list[EvidenceItem]] = Field(default_factory=dict)
    dropped_cross_shop_evidence: list[EvidenceItem] = Field(default_factory=list)
    discard_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_status: str = "unknown"
    source_summary: dict[str, Any] = Field(default_factory=dict)
    safety_result: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    empty_reason: str | None = None
    truncated: bool = False

    @property
    def candidate_summaries(self) -> list[CandidateEvidenceSummary]:
        return list(self.ranked_candidates)

    @property
    def evidence_items(self) -> list[EvidenceItem]:
        return list(self.items)

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["slots"] = _as_mapping(next_data.get("slots"))
        next_data["rag_mode"] = _clean_text(next_data.get("rag_mode")) or "single_shop_rag"
        if next_data.get("target_shop_id") in ("", None):
            next_data["target_shop_id"] = None
        else:
            try:
                next_data["target_shop_id"] = int(next_data.get("target_shop_id"))
            except Exception:
                next_data["target_shop_id"] = None
        next_data["source_summary"] = _as_mapping(next_data.get("source_summary"))
        next_data["safety_result"] = _as_mapping(next_data.get("safety_result"))
        next_data["notes"] = _string_list(next_data.get("notes"))
        next_data["ranked_candidates"] = [item for item in next_data.get("ranked_candidates") or []]
        next_data["items"] = [item for item in next_data.get("items") or []]
        next_data["citations"] = _string_list(next_data.get("citations"))
        next_data["shop_evidence_map"] = {
            str(key): _string_list(value)
            for key, value in _as_mapping(next_data.get("shop_evidence_map")).items()
        }
        next_data["grouped_by_shop"] = {
            str(key): [item for item in value or []]
            for key, value in _as_mapping(next_data.get("grouped_by_shop")).items()
        }
        next_data["dropped_cross_shop_evidence"] = [item for item in next_data.get("dropped_cross_shop_evidence") or []]
        next_data["discard_summary"] = _as_mapping(next_data.get("discard_summary"))
        next_data["evidence_status"] = _clean_text(next_data.get("evidence_status")) or "unknown"
        next_data["empty_reason"] = _clean_text(next_data.get("empty_reason"))
        return next_data


class LocalLifeAnswerPlan(LocalLifeModel):
    answer_text: str = ""
    decision_type: str = "fallback"
    recommendation_summary: str = ""
    top_choice: CandidateEvidenceSummary | None = None
    candidate_reasons: list[CandidateEvidenceSummary] = Field(default_factory=list)
    scene_fit_summary: SceneFitSummary = Field(default_factory=SceneFitSummary)
    coupon_advice: CouponAdvice = Field(default_factory=CouponAdvice)
    risk_points: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    suggested_replies: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    source_mode: str | None = None
    degraded_reason: str | None = None
    knowledge_freshness: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["answer_text"] = _clean_text(next_data.get("answer_text") or next_data.get("answer") or next_data.get("final_answer")) or ""
        next_data["decision_type"] = _normalize_decision_type(
            next_data.get("decision_type") or next_data.get("decision") or next_data.get("intent")
        )
        next_data["recommendation_summary"] = _clean_text(
            next_data.get("recommendation_summary") or next_data.get("summary") or next_data.get("route_reason")
        ) or ""
        next_data["scene_fit_summary"] = next_data.get("scene_fit_summary") or next_data.get("scene_fit") or {
            "scene": "unknown",
            "fit": "unknown",
            "reason": "",
        }
        next_data["coupon_advice"] = next_data.get("coupon_advice") or {
            "has_coupon": None,
            "worth_it": "unknown",
            "reason": "",
            "risk": "",
        }
        next_data["risk_points"] = _string_list(next_data.get("risk_points") or next_data.get("risks"))
        next_data["missing_info"] = _string_list(next_data.get("missing_info") or next_data.get("missing_slots"))
        next_data["next_actions"] = [item for item in next_data.get("next_actions") or []]
        next_data["suggested_replies"] = _reply_strings(next_data.get("suggested_replies"))
        next_data["evidence_used"] = _string_list(next_data.get("evidence_used"))
        next_data["confidence"] = _normalize_confidence(next_data.get("confidence"))
        next_data["source_mode"] = _clean_text(next_data.get("source_mode"))
        next_data["degraded_reason"] = _clean_text(next_data.get("degraded_reason"))
        next_data["knowledge_freshness"] = _as_mapping(next_data.get("knowledge_freshness"))
        if next_data.get("top_choice") is None and next_data.get("candidate_reasons"):
            next_data["top_choice"] = next_data["candidate_reasons"][0]
        if not next_data.get("answer_text") and next_data.get("recommendation_summary"):
            next_data["answer_text"] = next_data["recommendation_summary"]
        return next_data


class GroundedVerificationResult(LocalLifeModel):
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_response_mode: str = "grounded"
    degraded_reason: str | None = None
    normalized_plan: dict[str, Any] = Field(default_factory=dict)
    evidence_pack_item_count: int = 0
    confidence: str = "medium"

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["issues"] = _string_list(next_data.get("issues"))
        next_data["warnings"] = _string_list(next_data.get("warnings"))
        next_data["suggested_response_mode"] = _clean_text(next_data.get("suggested_response_mode")) or "grounded"
        next_data["degraded_reason"] = _clean_text(next_data.get("degraded_reason"))
        next_data["normalized_plan"] = _as_mapping(next_data.get("normalized_plan"))
        try:
            next_data["evidence_pack_item_count"] = int(next_data.get("evidence_pack_item_count") or 0)
        except Exception:
            next_data["evidence_pack_item_count"] = 0
        next_data["confidence"] = _normalize_confidence(next_data.get("confidence"))
        return next_data


def build_answer_planner_request(
    *,
    raw_query: str,
    slots: Mapping[str, Any] | Any,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_pack: EvidencePack | Mapping[str, Any] | None,
    evidence_claims: Sequence[Mapping[str, Any] | Any] | None = None,
    safety_result: Mapping[str, Any] | Any,
    source_mode: str | None = None,
    degraded_reason: str | None = None,
    knowledge_freshness: Mapping[str, Any] | Any | None = None,
    route_decision: str | None = None,
    route_reason: str | None = None,
    clarification: Mapping[str, Any] | Any | None = None,
    approval_required: bool = False,
    answer_contract: Any | None = None,
    context_recovery: Mapping[str, Any] | Any | None = None,
) -> dict[str, Any]:
    pruned_context = prune_context_for_contract(
        answer_contract,
        ranked_candidates=ranked_candidates,
        evidence_pack=evidence_pack,
        evidence_claims=None,
    )
    pruned_claims: list[dict[str, Any]] = []
    if evidence_claims:
        pruned_claims = prune_context_for_contract(
            answer_contract,
            ranked_candidates=ranked_candidates,
            evidence_pack=evidence_pack,
            evidence_claims=evidence_claims,
        )["evidence_claims"]
    clean_evidence_count = len(pruned_context["evidence_pack"].get("items") or pruned_claims)
    strong_evidence_count = sum(
        1
        for item in pruned_claims
        if float((item or {}).get("confidence") or 0.0) >= 0.7
    )
    medium_evidence_count = sum(
        1
        for item in pruned_claims
        if 0.4 <= float((item or {}).get("confidence") or 0.0) < 0.7
    )
    answer_depth_policy = derive_answer_depth_policy(
        answer_contract,
        clean_evidence_count=clean_evidence_count,
        strong_evidence_count=strong_evidence_count,
        medium_evidence_count=medium_evidence_count,
    )
    answer_structure_requirements = {
        answer_depth_policy.answer_style: build_answer_structure_requirements(answer_contract, answer_depth_policy)
    }
    prompt = {
        "stage": "answer_planning",
        "raw_query": raw_query,
        "slots": _as_mapping(slots),
        "ranked_candidates": pruned_context["ranked_candidates"],
        "evidence_pack": pruned_context["evidence_pack"],
        "safety_result": _as_mapping(safety_result),
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
        "knowledge_freshness": _as_mapping(knowledge_freshness),
        "route_decision": route_decision,
        "route_reason": route_reason,
        "clarification": _as_mapping(clarification),
        "approval_required": approval_required,
        "answer_contract": _as_mapping(answer_contract) if answer_contract is not None else {},
        "context_recovery": _as_mapping(context_recovery),
        "answer_depth_policy": {
            "answer_style": answer_depth_policy.answer_style,
            "depth_level": answer_depth_policy.depth_level,
            "min_sections": answer_depth_policy.min_sections,
            "max_sections": answer_depth_policy.max_sections,
            "min_bullets_per_section": answer_depth_policy.min_bullets_per_section,
            "min_chars": answer_depth_policy.min_chars,
            "require_summary": answer_depth_policy.require_summary,
            "require_evidence_reasoning": answer_depth_policy.require_evidence_reasoning,
            "require_risk_or_caveat": answer_depth_policy.require_risk_or_caveat,
            "require_next_step": answer_depth_policy.require_next_step,
            "depth_limited_by_evidence": answer_depth_policy.depth_limited_by_evidence,
            "clean_evidence_count": answer_depth_policy.clean_evidence_count,
            "strong_evidence_count": answer_depth_policy.strong_evidence_count,
            "medium_evidence_count": answer_depth_policy.medium_evidence_count,
            "reason": answer_depth_policy.reason,
        },
        "answer_structure_requirements": answer_structure_requirements,
        "context_pruning": pruned_context["summary"],
        "instructions": {
            "must_use_only": ["evidence_pack", "ranked_candidates", "slots", "safety_result", "context_pruning"],
            "do_not_invent": [
                "coupon",
                "score",
                "distance",
                "open_hours",
                "queue_time",
            ],
            "output_must_be_json": True,
            "answer_contract_constraints": _as_mapping(answer_contract) if answer_contract is not None else {},
            "answer_structure_requirements": answer_structure_requirements,
        },
    }
    if pruned_claims:
        prompt["evidence_claims"] = pruned_claims
    return prompt


def parse_answer_plan_payload(payload: Any) -> LocalLifeAnswerPlan | None:
    if not isinstance(payload, Mapping):
        return None
    if not any(payload.get(key) for key in ("answer_text", "decision_type", "recommendation_summary")) and not payload.get("candidate_reasons") and not payload.get("evidence_used") and not payload.get("next_actions") and not payload.get("suggested_replies"):
        return None
    try:
        return LocalLifeAnswerPlan.model_validate(payload)
    except Exception:
        return None


__all__ = [
    "CandidateEvidenceSummary",
    "CouponAdvice",
    "EvidenceItem",
    "EvidencePack",
    "GroundedVerificationResult",
    "LocalLifeAnswerPlan",
    "NextAction",
    "SceneFitSummary",
    "build_answer_planner_request",
    "parse_answer_plan_payload",
]
