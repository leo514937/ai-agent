from __future__ import annotations

from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    shop_id: Optional[int] = None
    claim: str
    confidence: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_type: Optional[str] = None

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
    has_coupon: Optional[bool] = None
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
    shop_id: Optional[int] = None
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
    shop_id: Optional[int] = None
    query: Optional[str] = None

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
    slots: Dict[str, Any] = Field(default_factory=dict)
    ranked_candidates: list[CandidateEvidenceSummary] = Field(default_factory=list)
    items: list[EvidenceItem] = Field(default_factory=list)
    shop_evidence_map: Dict[str, list[str]] = Field(default_factory=dict)
    source_summary: Dict[str, Any] = Field(default_factory=dict)
    safety_result: Dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    truncated: bool = False

    @property
    def candidate_summaries(self) -> list[CandidateEvidenceSummary]:
        return list(self.ranked_candidates)

    @model_validator(mode="before")
    @classmethod
    def _repair_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        next_data = dict(data)
        next_data["slots"] = _as_mapping(next_data.get("slots"))
        next_data["source_summary"] = _as_mapping(next_data.get("source_summary"))
        next_data["safety_result"] = _as_mapping(next_data.get("safety_result"))
        next_data["notes"] = _string_list(next_data.get("notes"))
        next_data["ranked_candidates"] = [item for item in next_data.get("ranked_candidates") or []]
        next_data["items"] = [item for item in next_data.get("items") or []]
        next_data["shop_evidence_map"] = {
            str(key): _string_list(value)
            for key, value in _as_mapping(next_data.get("shop_evidence_map")).items()
        }
        return next_data


class LocalLifeAnswerPlan(LocalLifeModel):
    answer_text: str = ""
    decision_type: str = "fallback"
    recommendation_summary: str = ""
    top_choice: Optional[CandidateEvidenceSummary] = None
    candidate_reasons: list[CandidateEvidenceSummary] = Field(default_factory=list)
    scene_fit_summary: SceneFitSummary = Field(default_factory=SceneFitSummary)
    coupon_advice: CouponAdvice = Field(default_factory=CouponAdvice)
    risk_points: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    suggested_replies: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    source_mode: Optional[str] = None
    degraded_reason: Optional[str] = None
    knowledge_freshness: Dict[str, Any] = Field(default_factory=dict)

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
    degraded_reason: Optional[str] = None
    normalized_plan: Dict[str, Any] = Field(default_factory=dict)
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
    safety_result: Mapping[str, Any] | Any,
    source_mode: str | None = None,
    degraded_reason: str | None = None,
    knowledge_freshness: Mapping[str, Any] | Any | None = None,
    route_decision: str | None = None,
    route_reason: str | None = None,
    clarification: Mapping[str, Any] | Any | None = None,
    approval_required: bool = False,
) -> dict[str, Any]:
    prompt = {
        "stage": "answer_planning",
        "raw_query": raw_query,
        "slots": _as_mapping(slots),
        "ranked_candidates": [
            _as_mapping(item)
            for item in ranked_candidates
        ],
        "evidence_pack": _as_mapping(evidence_pack) if evidence_pack is not None else {},
        "safety_result": _as_mapping(safety_result),
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
        "knowledge_freshness": _as_mapping(knowledge_freshness),
        "route_decision": route_decision,
        "route_reason": route_reason,
        "clarification": _as_mapping(clarification),
        "approval_required": approval_required,
        "instructions": {
            "must_use_only": ["evidence_pack", "ranked_candidates", "slots", "safety_result"],
            "do_not_invent": [
                "coupon",
                "score",
                "distance",
                "open_hours",
                "queue_time",
            ],
            "output_must_be_json": True,
        },
    }
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
