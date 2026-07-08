"""Top-level intent and semantic frame parsing."""

from __future__ import annotations

import logging
import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import LLM_TIMEOUT_MS, SEMANTIC_FALLBACK_ENABLED
from ..domain.enums import (
    ComparisonStructure,
    Facet,
    GroundingStatus,
    MissingSlotType,
    RefineAction,
    SemanticParseSource,
    TaskType,
    TopIntent,
)
from ..domain.schemas import SemanticFrame
from ..domain.session_context_summary import build_session_context_summary
from ..input.normalizer import normalize_text
from ..llm.client import call_llm, load_prompt
from ..llm.json_parser import LLMJSONParseError, parse_json_response
from ..observability.file_logger import get_python_service_logger, log_kv
from .slot_extractor import extract_slots

_logger = logging.getLogger(__name__)
_SERVICE_LOG = get_python_service_logger()

# Module-level capture of dropped facets from the last _validate_semantic_payload call.
# Reset before each LLM call; consumed by parse_semantic_frame after validation.
_last_dropped_facets: list[str] = []
_LOW_CONFIDENCE_FALLBACK = 0.25


def get_last_dropped_facets() -> list[str]:
    """Return the list of facet names dropped in the most recent validation, then clear."""
    global _last_dropped_facets
    result = list(_last_dropped_facets)
    _last_dropped_facets = []
    return result


class _TopIntentRouterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


class FacetSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Facet
    required: bool = False


class _SemanticFrameRouterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent | None = None
    task_type: TaskType | None = None
    primary_task: str = ""
    workflow_hint: str = ""
    comparison_intent: bool = False
    comparison_facets: list[str] = Field(default_factory=list)
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    category: str = ""
    shop_target: dict[str, Any] | None = None
    reference: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    facets: list[FacetSpecResponse] = Field(default_factory=list)
    merchant_mentions: list[str] = Field(default_factory=list)
    brand_mentions: list[str] = Field(default_factory=list)
    branch_mentions: list[str] = Field(default_factory=list)
    surface_hints: list[str] = Field(default_factory=list)
    alias_hints: list[str] = Field(default_factory=list)
    reference_mentions: list[str] = Field(default_factory=list)
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    ordinal_references: list[str] = Field(default_factory=list)
    deictic_references: list[str] = Field(default_factory=list)
    focused_facets: list[str] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    unsupported_reasons: list[str] = Field(default_factory=list)
    comparison_focus: str = ""
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    ranking_signals: dict[str, Any] = Field(default_factory=dict)
    follow_up: dict[str, Any] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    need_context: bool = False

    # Candidate-resolution fields
    candidate_source: str | None = None
    candidate_category: str = ""
    candidate_limit: int | None = None
    candidate_sort_by: list[dict[str, Any]] = Field(default_factory=list)
    candidate_filters: dict[str, Any] = Field(default_factory=dict)
    candidate_source_origin: str | None = None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _parse_source_for_backend(semantic_source: str) -> SemanticParseSource:
    source = str(semantic_source or "").strip()
    if not source:
        return SemanticParseSource.unknown
    try:
        return SemanticParseSource(source)
    except Exception:
        return SemanticParseSource.unknown


def _normalize_preference_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []

    items = value if isinstance(value, list) else [value]
    normalized: list[dict[str, Any]] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            if "type" not in item and len(item) == 1:
                only_key, only_value = next(iter(item.items()))
                key_text = str(only_key).strip()
                if key_text:
                    normalized.append({"type": key_text, "value": only_value})
                    continue
            payload = {str(key): val for key, val in item.items() if str(key).strip()}
            if payload:
                normalized.append(payload)
            continue
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append({"type": text})
            continue
        normalized.append({"type": str(item).strip() or "unknown"})
    return normalized


def _normalize_ranking_policy(value: Any) -> dict[str, Any] | None:
    if value in (None, "", [], ()):
        return None
    if isinstance(value, dict):
        return dict(value) or None
    return None


def _normalize_candidate_limit(value: Any) -> int | None:
    try:
        limit = int(value)
    except Exception:
        return None
    return limit if limit > 0 else None


def _normalize_semantic_payload(payload: Any, *, top_intent: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        wrapped_content = payload.get("content")
        if isinstance(wrapped_content, dict) and (
            "ok" in payload
            or "raw" in payload
            or "provider" in payload
            or "model" in payload
            or "transport" in payload
            or "llm_backend" in payload
        ):
            payload = wrapped_content
    if not isinstance(payload, dict):
        payload = {}

    normalized = dict(payload)
    if "top_intent" not in normalized or normalized.get("top_intent") is None:
        normalized["top_intent"] = top_intent
    if "intent" not in normalized or normalized.get("intent") is None:
        normalized["intent"] = normalized.get("top_intent")

    if "semantic_source" in normalized:
        semantic_source = str(normalized.get("semantic_source") or "").strip()
        if semantic_source:
            normalized.setdefault("parse_source", semantic_source)
            normalized.setdefault("semantic_parse_source", semantic_source)

    if "parse_source" not in normalized or not str(normalized.get("parse_source") or "").strip():
        normalized["parse_source"] = normalized.get("semantic_parse_source") or normalized.get("semantic_source") or ""
    if "semantic_parse_source" not in normalized or not str(normalized.get("semantic_parse_source") or "").strip():
        normalized["semantic_parse_source"] = normalized.get("parse_source") or normalized.get("semantic_source") or ""

    if "exploration_stages" in normalized and isinstance(normalized["exploration_stages"], list):
        stages: list[Any] = []
        for index, item in enumerate(normalized["exploration_stages"], start=1):
            if isinstance(item, str):
                stages.append({"stage_id": f"stage_{index}", "stage_type": item, "candidate_query": item, "order": index, "required": True})
                continue
            if isinstance(item, dict):
                payload = dict(item)
                payload.setdefault("stage_id", f"stage_{index}")
                payload.setdefault("order", index)
                if "candidate_query" not in payload and "query" in payload:
                    payload["candidate_query"] = payload.get("query", "")
                if "query" not in payload and payload.get("candidate_query"):
                    payload["query"] = payload.get("candidate_query", "")
                if "stage_type" not in payload:
                    payload["stage_type"] = str(payload.get("kind", payload.get("category", payload.get("name", ""))) or "")
                payload.setdefault("required", True)
                stages.append(payload)
                continue
            stages.append(item)
        normalized["exploration_stages"] = stages
        if str(normalized.get("workflow_hint") or "").strip() != "exploration_planning":
            normalized["workflow_hint"] = "exploration_planning"
        if not str(normalized.get("primary_task") or "").strip():
            normalized["primary_task"] = "exploration"
        if not str(normalized.get("missing_slot_type") or "").strip() and not normalized.get("location"):
            normalized["missing_slot_type"] = MissingSlotType.missing_exploration_location.value

    normalized["preferences"] = _normalize_preference_items(normalized.get("preferences"))
    if "soft_preferences" not in normalized or not isinstance(normalized.get("soft_preferences"), dict):
        normalized["soft_preferences"] = dict(normalized.get("soft_preferences") or {})
    if "ranking_signals" not in normalized or not isinstance(normalized.get("ranking_signals"), dict):
        normalized["ranking_signals"] = dict(normalized.get("ranking_signals") or {})
    normalized["ranking_policy"] = _normalize_ranking_policy(normalized.get("ranking_policy"))

    if not normalized.get("location_reference") and isinstance(normalized.get("location"), dict):
        location = normalized.get("location") or {}
        if location:
            normalized["location_reference"] = {
                "reference_type": "location_reference",
                "text": str(location.get("text") or location.get("location_name") or location.get("name") or ""),
                "value": dict(location),
                "location_name": str(location.get("location_name") or location.get("name") or ""),
                "resolved": bool(location),
            }
    if not normalized.get("shop_reference") and isinstance(normalized.get("shop_target"), dict):
        shop_target = normalized.get("shop_target") or {}
        if shop_target:
            normalized["shop_reference"] = {
                "reference_type": "shop_reference",
                "text": str(shop_target.get("text") or shop_target.get("shop_name") or shop_target.get("name") or ""),
                "value": dict(shop_target),
                "shop_id": str(shop_target.get("shop_id") or ""),
                "shop_name": str(shop_target.get("shop_name") or shop_target.get("name") or ""),
                "resolved": bool(shop_target.get("shop_id")),
            }

    comparison_targets = normalized.get("comparison_targets") or []
    ordinal_references = normalized.get("ordinal_references") or []
    deictic_references = normalized.get("deictic_references") or []
    has_comparison_signals = bool(
        normalized.get("comparison_intent")
        or comparison_targets
        or ordinal_references
        or deictic_references
        or normalized.get("comparison_facets")
        or normalized.get("comparison_focus")
    )
    if has_comparison_signals:
        if not normalized.get("comparison_intent"):
            normalized["comparison_intent"] = True
        if not normalized.get("task_type") or str(normalized.get("task_type") or "").strip() in {
            "",
            TopIntent.out_of_scope.value,
            TopIntent.invalid.value,
        }:
            normalized["task_type"] = TaskType.comparison
        if not normalized.get("primary_task"):
            normalized["primary_task"] = "comparison"
        if not normalized.get("workflow_hint"):
            normalized["workflow_hint"] = "comparison"
        if not normalized.get("comparison_structure"):
            if len(comparison_targets) >= 2:
                normalized["comparison_structure"] = ComparisonStructure.multi_target.value
            elif ordinal_references:
                normalized["comparison_structure"] = ComparisonStructure.ordinal.value
            elif deictic_references:
                normalized["comparison_structure"] = ComparisonStructure.deictic.value
            else:
                normalized["comparison_structure"] = ComparisonStructure.explicit.value

    if normalized.get("comparison_intent") and not normalized.get("comparison_structure"):
        if len(comparison_targets) >= 2:
            normalized["comparison_structure"] = ComparisonStructure.multi_target.value
        elif ordinal_references:
            normalized["comparison_structure"] = ComparisonStructure.ordinal.value
        elif deictic_references:
            normalized["comparison_structure"] = ComparisonStructure.deictic.value
        elif normalized.get("merchant_mentions"):
            normalized["comparison_structure"] = ComparisonStructure.explicit.value

    if normalized.get("missing_slot_type") in (None, "") and normalized.get("missing_slots"):
        normalized["missing_slot_type"] = str(normalized["missing_slots"][0])
    if normalized.get("missing_slot_type") in {"missing_location", "missing_shop", "missing_shop_target", "missing_comparison_targets", "missing_exploration_location"}:
        normalized["missing_slots"] = [str(normalized["missing_slot_type"])]

    if normalized.get("confidence") is None:
        normalized["confidence"] = 0.0

    return normalized


def _schema_validation_result(
    *,
    status: str,
    source: str,
    confidence: float,
    payload_preview: dict[str, Any] | None = None,
    error_code: str = "",
    error_message: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "confidence": confidence,
        "error_code": error_code,
        "error_message": error_message,
        "payload_preview": payload_preview or {},
    }


_SemanticFrameRouterResponse.model_rebuild()


class TopIntentRouter:
    """Small wrapper to keep the router easy to inject in tests."""

    def __init__(self, llm_call: Callable[..., dict[str, Any]] | None = None):
        self._llm_call = llm_call or call_llm

    def route(self, text: str) -> dict[str, Any]:
        return parse_top_intent(text, llm_call=self._llm_call)


def _validate_router_payload(payload: Any) -> dict[str, Any]:
    try:
        model = _TopIntentRouterResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return model.model_dump()


def _validate_semantic_payload(payload: Any) -> dict[str, Any]:
    global _last_dropped_facets
    normalized = _normalize_semantic_payload(payload, top_intent=TopIntent.out_of_scope.value)

    if "facets" in normalized and isinstance(normalized["facets"], list):
        valid_facet_values = {f.value for f in Facet}
        original_facets = list(normalized["facets"])
        normalized["facets"] = [
            f for f in normalized["facets"]
            if isinstance(f, dict) and f.get("name") in valid_facet_values
        ]
        dropped = [
            f for f in original_facets
            if isinstance(f, dict) and f.get("name") not in valid_facet_values
        ]
        _last_dropped_facets = [str(f.get("name", "")) for f in dropped if f.get("name")]
        if _last_dropped_facets:
            _logger.warning(
                "Dropped %d facet(s) not in Facet enum: %s",
                len(_last_dropped_facets),
                _last_dropped_facets,
            )

    fu = normalized.get("follow_up")
    if isinstance(fu, dict) and fu.get("is_follow_up"):
        ra = fu.get("refine_action")
        if ra is not None and isinstance(ra, str):
            fu["refine_action"] = _normalize_refine_action(ra)

    try:
        model = SemanticFrame.model_validate(normalized)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    dumped = model.model_dump(mode="python", exclude_none=False)
    dumped["semantic_source"] = model.semantic_source
    dumped["parse_source"] = _enum_value(model.parse_source)
    dumped["semantic_parse_source"] = _enum_value(model.semantic_parse_source)
    dumped["grounding_status"] = _enum_value(model.grounding_status)
    dumped["missing_slot_type"] = _enum_value(model.missing_slot_type)
    return dumped


def _normalize_refine_action(action: str) -> str:
    """Normalise a free-form refine_action string to the RefineAction enum."""
    normalized = action.strip().lower().replace(" ", "_").replace("-", "_")
    # Direct match
    try:
        return RefineAction(normalized).value
    except ValueError:
        pass

    # Synonym mapping
    SYNONYMS: dict[str, str] = {
        # cheaper
        "lower_price": "cheaper",
        "more_affordable": "cheaper",
        "cheap": "cheaper",
        "price_down": "cheaper",
        "affordable": "cheaper",
        "budget": "cheaper",
        "less_expensive": "cheaper",
        # closer
        "nearer": "closer",
        "nearby": "closer",
        "shorter_distance": "closer",
        "near": "closer",
        "close": "closer",
        "less_far": "closer",
        "near_by": "closer",
        # higher_rating
        "rating_higher": "higher_rating",
        "better_score": "higher_rating",
        "better_rating": "higher_rating",
        "high_score": "higher_rating",
        # better_environment
        "nicer_environment": "better_environment",
        "better_ambiance": "better_environment",
        # better_taste
        "better_flavor": "better_taste",
        "yummier": "better_taste",
        "tastier": "better_taste",
        # coupon_lookup
        "coupon": "coupon_lookup",
        "check_coupon": "coupon_lookup",
        "any_coupon": "coupon_lookup",
        "discount": "coupon_lookup",
        # open_status_lookup
        "open_status": "open_status_lookup",
        "is_open": "open_status_lookup",
        "opening_hours": "open_status_lookup",
        # distance_lookup
        "distance": "distance_lookup",
        "how_far": "distance_lookup",
        "eta": "distance_lookup",
        # comparison
        "compare": "comparison",
        "which_better": "comparison",
        # select_candidate
        "select": "select_candidate",
        "pick_one": "select_candidate",
        "which_one": "select_candidate",
        "first_one": "select_candidate",
        "ordinal": "select_candidate",
        "this_one": "select_candidate",
        # restart
        "fresh": "restart",
        "new_search": "restart",
        "start_over": "restart",
        "reset": "restart",
    }
    if normalized in SYNONYMS:
        return SYNONYMS[normalized]

    return RefineAction.other.value


_CAPABILITY_HINTS = (
    "你能帮我做什么",
    "能帮我做什么",
    "你可以帮我做什么",
    "可以帮我做什么",
    "你会什么",
    "能做什么",
    "有什么作用",
    "怎么帮我",
    "帮我做什么",
)

_UNSAFE_HINTS = (
    "下单",
    "支付",
    "付款",
    "代付",
    "代买",
    "订座",
    "订餐",
    "帮我买",
    "直接下单",
    "直接支付",
)


def _looks_like_capability_query(text: str) -> bool:
    compact = str(text or "").strip()
    return any(hint in compact for hint in _CAPABILITY_HINTS)


def _looks_like_unsafe_query(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return False
    if any(hint in compact for hint in _UNSAFE_HINTS):
        return True
    return any(token in compact for token in ("代下单", "代支付", "代订座", "代订餐", "帮我付款"))


def _fallback_intent(normalised_text: str, error_code: str = "") -> TopIntent:
    compact = normalised_text.strip()
    if not compact:
        return TopIntent.invalid
    if error_code:
        # When LLM fails, still classify based on content rather than
        # blindly returning out_of_scope.  Check business keywords and
        # CJK characters before giving up.
        if _looks_like_capability_query(compact):
            return TopIntent.capability
        if _looks_like_unsafe_query(compact):
            return TopIntent.unsafe
        if any(
            hint in compact
            for hint in (
                "对比",
                "比较",
                "比一比",
                "比呢",
                "哪个好",
                "哪个更好",
                "比好",
                "这三家",
                "这几家",
                "第一家",
                "第二家",
                "第三家",
                "哪个更",
                "哪家更",
                "谁更",
            )
        ):
            return TopIntent.local_life
        if any("\u4e00" <= ch <= "\u9fff" for ch in compact):
            return TopIntent.local_life
        return TopIntent.out_of_scope
    if _looks_like_capability_query(compact):
        return TopIntent.capability
    if _looks_like_unsafe_query(compact):
        return TopIntent.unsafe
    if any(
        hint in compact
        for hint in (
            "瀵规瘮",
            "姣旇緝",
            "姣斾竴姣?",
            "姣斿憿",
            "杩欎笁瀹?",
            "杩欏嚑瀹?",
            "绗竴瀹?",
            "绗簩瀹?",
            "绗笁瀹?",
            "鍝釜鏇?",
            "鍝鏇?",
            "璋佹洿",
        )
    ):
        return TopIntent.local_life
    if any("\u4e00" <= ch <= "\u9fff" for ch in compact):
        return TopIntent.local_life
    return TopIntent.out_of_scope


def _annotate_frame(
    frame: SemanticFrame,
    *,
    semantic_source: str,
    parse_source: SemanticParseSource | None = None,
    llm_backend: str = "",
    fallback_reason: str = "",
    llm_called: bool,
) -> SemanticFrame:
    frame.semantic_source = semantic_source
    frame.llm_backend = llm_backend
    frame.fallback_reason = fallback_reason
    frame.llm_called = llm_called
    resolved_parse_source = parse_source or _parse_source_for_backend(semantic_source)
    frame.parse_source = resolved_parse_source
    frame.semantic_parse_source = resolved_parse_source
    return frame


def _merge_semantic_mentions(payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload)
    merchant_mentions = [str(item).strip() for item in (merged.get("merchant_mentions") or []) if str(item).strip()]
    brand_mentions = [str(item).strip() for item in (merged.get("brand_mentions") or []) if str(item).strip()]
    branch_mentions = [str(item).strip() for item in (merged.get("branch_mentions") or []) if str(item).strip()]

    combined: list[str] = []
    for item in [*merchant_mentions, *brand_mentions, *branch_mentions]:
        if item and item not in combined:
            combined.append(item)
    merged["merchant_mentions"] = combined
    merged["brand_mentions"] = brand_mentions
    merged["branch_mentions"] = branch_mentions
    return merged


def _merge_slot_hints(payload: dict[str, Any], slot_hints: dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload)
    hinted_limit = _normalize_candidate_limit(slot_hints.get("candidate_limit"))
    current_limit = _normalize_candidate_limit(merged.get("candidate_limit"))
    if current_limit is None and hinted_limit is not None:
        merged["candidate_limit"] = hinted_limit

    ranking_signals = merged.get("ranking_signals")
    if not isinstance(ranking_signals, dict):
        ranking_signals = {}
    if hinted_limit is not None and not _normalize_candidate_limit(ranking_signals.get("requested_count")):
        ranking_signals["requested_count"] = hinted_limit
    merged["ranking_signals"] = ranking_signals
    return merged


def _fallback_semantic_frame(
    text: str,
    top_intent: str,
    *,
    fallback_reason: str,
    llm_called: bool,
    llm_backend: str = "",
    semantic_source: str = "diagnostic_rules",
) -> SemanticFrame:
    normalized_top_intent = str(top_intent or "").strip()
    if normalized_top_intent not in {item.value for item in TopIntent}:
        normalized_top_intent = TopIntent.out_of_scope.value
    payload = _safe_extract_slots(text, normalized_top_intent)
    if not str(payload.get("top_intent", "") or "").strip():
        payload["top_intent"] = normalized_top_intent
    frame = SemanticFrame.model_validate(payload)
    structured_signals = any(
        bool(payload.get(key))
        for key in (
            "task_type",
            "workflow_hint",
            "comparison_intent",
            "comparison_targets",
            "ordinal_references",
            "deictic_references",
            "exploration_stages",
            "merchant_mentions",
            "brand_mentions",
            "branch_mentions",
            "location",
            "location_reference",
            "shop_reference",
            "category",
            "filters",
            "soft_preferences",
            "ranking_signals",
            "unsupported_facets",
        )
    )
    if structured_signals:
        frame.confidence = max(float(frame.confidence or 0.0), 0.85)
    else:
        frame.confidence = min(float(frame.confidence or 0.0), _LOW_CONFIDENCE_FALLBACK)
    frame.grounding_status = GroundingStatus.unknown
    return _annotate_frame(
        frame,
        semantic_source=semantic_source,
        parse_source=SemanticParseSource.fallback_rules,
        llm_backend=llm_backend,
        fallback_reason=fallback_reason,
        llm_called=llm_called,
    )


def _build_recovery_frame(
    text: str,
    top_intent: str,
    payload: Any,
    *,
    llm_called: bool,
    llm_backend: str,
    source: str,
    fallback_reason: str = "",
) -> tuple[SemanticFrame | None, dict[str, Any] | None, str]:
    normalized_top_intent = str(top_intent or "").strip()
    if normalized_top_intent not in {item.value for item in TopIntent}:
        normalized_top_intent = TopIntent.out_of_scope.value
    raw_payload = payload
    if isinstance(raw_payload, str):
        try:
            raw_payload = parse_json_response(raw_payload)
        except LLMJSONParseError:
            return None, None, "raw_json_parse_failed"
    if not isinstance(raw_payload, dict):
        return None, None, "raw_payload_not_dict"

    normalized = _normalize_semantic_payload(raw_payload, top_intent=normalized_top_intent)
    recovery_hints = _safe_extract_slots(text, normalized_top_intent)
    for key in ("comparison_targets", "ordinal_references", "deictic_references", "merchant_mentions", "brand_mentions", "branch_mentions"):
        if not normalized.get(key) and recovery_hints.get(key):
            normalized[key] = recovery_hints.get(key)
    for key in ("comparison_intent", "workflow_hint", "task_type", "primary_task", "comparison_facets", "comparison_focus", "need_context", "missing_slots", "soft_preferences", "ranking_signals", "location", "category", "reference", "exploration_stages", "scene", "time", "unsupported_facets", "unsupported_reasons"):
        if not normalized.get(key) and recovery_hints.get(key) not in (None, [], {}, ""):
            normalized[key] = recovery_hints.get(key)
    if recovery_hints.get("location_reference") and not normalized.get("location_reference"):
        normalized["location_reference"] = recovery_hints["location_reference"]
    if recovery_hints.get("shop_reference") and not normalized.get("shop_reference"):
        normalized["shop_reference"] = recovery_hints["shop_reference"]

    try:
        frame = SemanticFrame.model_validate(normalized)
    except ValidationError:
        return None, normalized, "structured_recovery_failed"

    frame.confidence = min(float(frame.confidence or 0.0), 0.5)
    semantic_source = "diagnostic_rules" if fallback_reason else source
    frame = _annotate_frame(
        frame,
        semantic_source=semantic_source,
        parse_source=SemanticParseSource.real_llm if semantic_source in {"real_llm", "fake_llm", "spy_real_llm"} else SemanticParseSource.fallback_rules,
        llm_backend=llm_backend,
        fallback_reason=fallback_reason,
        llm_called=llm_called,
    )
    frame.grounding_status = frame.grounding_status if frame.grounding_status != GroundingStatus.unknown else GroundingStatus.partially_grounded
    return frame, normalized, ""


def _apply_session_follow_up_context(frame: SemanticFrame, text: str, summary: Any) -> None:
    """补齐会话续问的轻量语义，不改写明确的新任务。"""
    normalized = normalize_text(text)
    if not normalized:
        return

    # 只在明确有推荐上下文、且没有明显的商家/对比/序数引用时，
    # 才把“便宜一点”类表达收敛为推荐续问。
    has_recommendation_context = bool(
        getattr(summary, "last_recommendation_present", False)
        or getattr(summary, "last_recommendation_count", 0)
        or getattr(summary, "active_constraints", None)
    )
    if not has_recommendation_context:
        return

    has_explicit_target = bool(
        (frame.merchant_mentions or [])
        or (frame.brand_mentions or [])
        or (frame.branch_mentions or [])
        or (frame.reference_mentions or [])
        or (frame.comparison_targets or [])
        or (frame.ordinal_references or [])
        or (frame.deictic_references or [])
    )
    if has_explicit_target:
        return

    cheaper_cues = ("便宜一点", "便宜点", "更便宜", "更便宜点", "便宜些", "比较便宜", "便宜一点的呢")
    if not any(token in normalized for token in cheaper_cues):
        return

    task_type_value = _enum_value(frame.task_type)
    if task_type_value and task_type_value not in {"recommendation", "single_shop_query", "invalid", "out_of_scope"}:
        return

    frame.task_type = TaskType.recommendation
    frame.primary_task = "recommendation_refine"
    if not _enum_value(frame.workflow_hint) or _enum_value(frame.workflow_hint) in {"follow_up", "single_shop_query"}:
        frame.workflow_hint = "recommendation"
    follow_up = dict(frame.follow_up or {})
    follow_up.update({"is_follow_up": True, "refine_action": "cheaper"})
    frame.follow_up = follow_up

    soft_preferences = dict(frame.soft_preferences or {})
    soft_preferences.setdefault("price_preference", "lower_price")
    frame.soft_preferences = soft_preferences

    ranking_signals = dict(frame.ranking_signals or {})
    ranking_signals.setdefault("price_preference", "lower_price")
    frame.ranking_signals = ranking_signals

    if not frame.focused_facets:
        frame.focused_facets = ["price"]
    frame.need_context = True
    frame.confidence = max(float(frame.confidence or 0.0), 0.85)


def _safe_extract_slots(text: str, top_intent: str) -> dict[str, Any]:
    try:
        payload = extract_slots(text, top_intent)
    except ModuleNotFoundError:
        normalized = normalize_text(text)
        focused_facets: list[str] = []
        ordinal_references: list[str] = []
        deictic_references: list[str] = []
        reference_mentions: list[str] = []
        comparison_targets: list[dict[str, Any]] = []
        merchant_mentions: list[str] = []

        if "券" in normalized or "优惠" in normalized:
            focused_facets.append("coupon")
        if "营业" in normalized or "开门" in normalized or "打烊" in normalized:
            focused_facets.append("open_status")
        if "距离" in normalized or "多远" in normalized or "公里" in normalized or "几分钟" in normalized or "多久能到" in normalized or "多久到" in normalized:
            focused_facets.append("distance")

        unsupported_facets: list[str] = []
        unsupported_reasons: list[str] = []
        service_cues = ("有没有", "是否", "能不能", "能否", "可不可以", "提供", "支持", "服务", "设施")
        unsupported_keywords = ("寄存", "宠物", "停车", "包间", "包厢", "充电", "无障碍", "儿童椅", "洗手间")
        if any(cue in normalized for cue in service_cues) and any(keyword in normalized for keyword in unsupported_keywords):
            unsupported_facets.append("service_feature")
            unsupported_reasons.extend([f"unsupported_service:{keyword}" for keyword in unsupported_keywords if keyword in normalized])

        for ref in ("第一家", "第二家", "第三家", "第一个", "第二个", "第三个"):
            if ref in normalized:
                ordinal_references.append(ref)
                reference_mentions.append(ref)

        for ref in ("这家", "那家", "这几家", "这三家"):
            if ref in normalized:
                deictic_references.append(ref)
                reference_mentions.append(ref)
                comparison_targets.append(
                    {"shop_name": ref, "reference": "deictic", "source_text": ref}
                )

        task_type = "recommendation" if top_intent == "local_life" else None
        primary_task = "recommendation"
        if any(token in normalized for token in ("对比", "比较", "哪个好", "谁更", "哪家更")):
            task_type = "comparison"
            primary_task = "comparison"
        elif focused_facets or ordinal_references or deictic_references:
            task_type = "single_shop_query" if top_intent == "local_life" else None
            primary_task = "single_shop_query"

        payload = {
            "top_intent": top_intent,
            "task_type": task_type,
            "primary_task": primary_task,
            "facets": [{"name": facet, "required": True} for facet in focused_facets],
            "merchant_mentions": merchant_mentions,
            "brand_mentions": [],
            "branch_mentions": [],
            "reference_mentions": reference_mentions,
            "comparison_targets": comparison_targets,
            "ordinal_references": ordinal_references,
            "deictic_references": deictic_references,
            "focused_facets": focused_facets,
            "unsupported_facets": unsupported_facets,
            "unsupported_reasons": unsupported_reasons,
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "follow_up": None,
            "confidence": 0.0,
            "need_context": False,
        }
    return payload


def _semantic_full_timeout_ms() -> int:
    return max(LLM_TIMEOUT_MS, 30000)


def _semantic_repair_timeout_ms() -> int:
    return max(8000, min(_semantic_full_timeout_ms() // 2, 12000))


def _build_semantic_repair_prompt(
    normalised_text: str,
    top_intent: str,
    *,
    session_summary_json: str,
    repair_hints: dict[str, Any],
) -> str:
    compact_hints = {
        key: value
        for key, value in repair_hints.items()
        if key
        in {
            "task_type",
            "primary_task",
            "workflow_hint",
            "comparison_intent",
            "comparison_facets",
            "comparison_targets",
            "merchant_mentions",
            "brand_mentions",
            "branch_mentions",
            "reference_mentions",
            "ordinal_references",
            "deictic_references",
            "focused_facets",
            "location",
            "location_reference",
            "shop_reference",
            "category",
            "hard_constraints",
            "soft_preferences",
            "ranking_signals",
            "need_context",
            "comparison_focus",
        }
        and value not in (None, [], {}, "")
    }
    payload = {
        "top_intent": top_intent,
        "text": normalised_text,
        "session_context": json.loads(session_summary_json) if session_summary_json else {},
        "hints": compact_hints,
    }
    return (
        "你是本地生活语义修复器。只输出 JSON，不要解释，不要重复题外内容。\n"
        "目标：基于用户原文和已有提示，修复一个尽量完整但最小化的 semantic frame。\n"
        "优先保证 top_intent、task_type、primary_task、facets、merchant_mentions、location、reference、preferences 的结构合法。\n"
        "如果不确定，请保守填写空数组/空对象，不要编造店名、坐标或候选。\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)}"
    )


def _semantic_llm_attempt(
    llm_call: Callable[..., dict[str, Any]],
    *,
    prompt: str,
    timeout_ms: int,
) -> dict[str, Any]:
    return llm_call(
        prompt,
        system_prompt="",
        timeout_ms=timeout_ms,
        temperature=0.0,
        max_retries=0,
        response_validator=_validate_semantic_payload,
    )


def parse_top_intent(text: str, llm_call: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    normalised_text = normalize_text(text)
    log_kv(
        _SERVICE_LOG,
        logging.INFO,
        "[TOP_INTENT_START]",
        tone="route",
        text_preview=normalised_text,
    )
    if not normalised_text.strip():
        log_kv(
            _SERVICE_LOG,
            logging.WARNING,
            "[TOP_INTENT_RESULT]",
            tone="warn",
            top_intent=TopIntent.invalid.value,
            error_code="EMPTY_INPUT",
            source="empty_input",
        )
        return {
            "top_intent": TopIntent.invalid,
            "confidence": 0.0,
            "reason": "empty_input",
            "raw": "",
            "error_code": "EMPTY_INPUT",
            "error_message": "input is empty after normalisation",
        }

    prompt_template = load_prompt("top_intent_router")
    rendered_prompt = prompt_template.replace("{{TEXT}}", normalised_text)

    router = TopIntentRouter(llm_call=llm_call)
    result = router._llm_call(
        rendered_prompt,
        system_prompt="",
        timeout_ms=LLM_TIMEOUT_MS,
        temperature=0.0,
        max_retries=1,
        response_validator=_validate_router_payload,
    )

    if result.get("ok"):
        payload = result["content"] or {}
        if not isinstance(payload, dict):
            if isinstance(payload, str):
                try:
                    payload = parse_json_response(payload)
                except LLMJSONParseError:
                    payload = {}
            else:
                payload = {}
        top_intent = payload.get("top_intent", TopIntent.out_of_scope)
        if not isinstance(top_intent, TopIntent):
            try:
                top_intent = TopIntent(top_intent)
            except Exception:
                fallback = TopIntent.invalid if not normalised_text.strip() else TopIntent.out_of_scope
                return {
                    "top_intent": fallback,
                    "confidence": 0.0,
                    "reason": "llm_failed",
                    "raw": result.get("raw", ""),
                    "error_code": "LLM_ENUM_OUT_OF_RANGE",
                    "error_message": "top_intent is outside the allowed enum range",
                }
        if top_intent in {TopIntent.out_of_scope, TopIntent.invalid}:
            fallback = _fallback_intent(normalised_text, str(result.get("error_code", "") or ""))
            if fallback not in {TopIntent.out_of_scope, TopIntent.invalid}:
                top_intent = fallback
        confidence = float(payload.get('confidence', result.get('confidence', 0.0)))
        confidence = max(0.0, min(1.0, confidence))
        response = {
            "top_intent": top_intent,
            "confidence": confidence,
            "reason": payload.get("reason", ""),
            "raw": result.get("raw", ""),
            "error_code": "",
            "error_message": "",
        }
        log_kv(
            _SERVICE_LOG,
            logging.INFO,
            "[TOP_INTENT_RESULT]",
            tone="route",
            top_intent=getattr(top_intent, "value", top_intent),
            confidence=confidence,
            reason=payload.get("reason", ""),
            llm_backend=result.get("llm_backend", ""),
            llm_payload=payload,
            raw_preview=result.get("raw", ""),
            source="llm",
        )
        return response

    fallback = _fallback_intent(normalised_text, str(result.get("error_code", "") or ""))
    response = {
        "top_intent": fallback,
        "confidence": 0.0,
        "reason": "llm_failed",
        "raw": result.get("raw", ""),
        "error_code": result.get("error_code", ""),
        "error_message": result.get("error_message", ""),
    }
    log_kv(
        _SERVICE_LOG,
        logging.WARNING,
        "[TOP_INTENT_RESULT]",
        tone="warn",
        top_intent=getattr(fallback, "value", fallback),
        confidence=0.0,
        error_code=result.get("error_code", ""),
        error_message=result.get("error_message", ""),
        raw_preview=result.get("raw", ""),
        source="fallback",
    )
    return response


def parse_semantic_frame(
    text: str,
    top_intent: str,
    llm_call: Callable[..., dict[str, Any]] | None = None,
    *,
    allow_fallback: bool = SEMANTIC_FALLBACK_ENABLED,
    session_state: Any = None,
) -> dict[str, Any]:
    """Parse a semantic frame for the local-life flow.

    When *session_state* is provided, a compressed ``{{SESSION_CONTEXT}}``
    is injected into the LLM prompt so the parser can better understand
    follow-ups, references, and task continuity.
    """
    normalised_text = normalize_text(text)
    log_kv(
        _SERVICE_LOG,
        logging.INFO,
        "[SEMANTIC_PARSE_START]",
        tone="route",
        text_preview=normalised_text,
        top_intent=top_intent,
    )
    if not normalised_text.strip():
        frame = _annotate_frame(
            SemanticFrame(),
            semantic_source="diagnostic_rules",
            parse_source=SemanticParseSource.fallback_rules,
            llm_backend="",
            fallback_reason="empty_input",
            llm_called=False,
        )
        response = {
            "semantic_frame": frame,
            "error_code": "EMPTY_INPUT",
            "error_message": "input is empty after normalisation",
            "raw": "",
            "semantic_source": frame.semantic_source,
            "parse_source": _enum_value(frame.parse_source),
            "semantic_parse_source": _enum_value(frame.semantic_parse_source),
            "llm_backend": frame.llm_backend,
            "fallback_reason": frame.fallback_reason,
            "llm_called": frame.llm_called,
            "semantic_parse_status": "fallback",
            "semantic_parse_mode": "rules",
            "semantic_parse_retry_count": 0,
            "semantic_parse_attempts": 0,
            "semantic_parse_reason": "empty_input",
            "schema_validation_result": _schema_validation_result(
                status="fallback",
                source="empty_input",
                confidence=frame.confidence,
            ),
        }
        log_kv(
            _SERVICE_LOG,
            logging.WARNING,
            "[SEMANTIC_PARSE_RESULT]",
            tone="warn",
            source="empty_input",
            error_code="EMPTY_INPUT",
            semantic_source=frame.semantic_source,
        )
        return response

    if llm_call is None:
        if not allow_fallback:
            response = {
                "semantic_frame": None,
                "error_code": "SEMANTIC_LLM_UNAVAILABLE",
                "error_message": "semantic llm backend is unavailable",
                "raw": "",
                "semantic_source": "",
                "parse_source": "",
                "semantic_parse_source": "",
                "llm_backend": "",
                "fallback_reason": "llm_call_unavailable",
                "llm_called": False,
                "semantic_parse_status": "failed",
                "semantic_parse_mode": "rules",
                "semantic_parse_retry_count": 0,
                "semantic_parse_attempts": 0,
                "semantic_parse_reason": "llm_call_unavailable",
                "semantic_repair_hints": _safe_extract_slots(normalised_text, top_intent),
                "schema_validation_result": _schema_validation_result(
                    status="failed",
                    source="llm_unavailable",
                    confidence=0.0,
                    error_code="SEMANTIC_LLM_UNAVAILABLE",
                    error_message="semantic llm backend is unavailable",
                ),
            }
            log_kv(
                _SERVICE_LOG,
                logging.ERROR,
                "[SEMANTIC_PARSE_RESULT]",
                tone="error",
                source="llm_unavailable",
                error_code="SEMANTIC_LLM_UNAVAILABLE",
                repair_hints=response.get("semantic_repair_hints"),
            )
            return response
        frame = _fallback_semantic_frame(
            normalised_text,
            top_intent,
            fallback_reason="llm_call_unavailable",
            llm_called=False,
        )
        response = {
            "semantic_frame": frame,
            "error_code": "",
            "error_message": "",
            "raw": "",
            "semantic_source": frame.semantic_source,
            "parse_source": _enum_value(frame.parse_source),
            "semantic_parse_source": _enum_value(frame.semantic_parse_source),
            "llm_backend": frame.llm_backend,
            "fallback_reason": frame.fallback_reason,
            "llm_called": frame.llm_called,
            "semantic_parse_status": "fallback",
            "semantic_parse_mode": "rules",
            "semantic_parse_retry_count": 0,
            "semantic_parse_attempts": 0,
            "semantic_parse_reason": "llm_call_unavailable",
            "semantic_repair_hints": _safe_extract_slots(normalised_text, top_intent),
            "schema_validation_result": _schema_validation_result(
                status="fallback",
                source="llm_unavailable",
                confidence=frame.confidence,
            ),
        }
        log_kv(
            _SERVICE_LOG,
            logging.WARNING,
            "[SEMANTIC_PARSE_RESULT]",
            tone="warn",
            source="diagnostic_rules",
            semantic_source=frame.semantic_source,
            fallback_reason=frame.fallback_reason,
            semantic_frame=frame,
        )
        return response

    prompt_template = load_prompt("local_life_parser")

    # Build session context summary -----------------------------------
    from ..domain.state import SessionState
    ss = session_state
    if ss is not None and not isinstance(ss, (SessionState, dict)):
        ss = None
    summary = build_session_context_summary(ss)
    summary_json = summary.model_dump_json()
    repair_hints = _safe_extract_slots(normalised_text, top_intent)

    full_prompt = (
        prompt_template
        .replace("{{TEXT}}", normalised_text)
        .replace("{{TOP_INTENT}}", top_intent)
        .replace("{{SESSION_CONTEXT}}", summary_json)
    )
    repair_prompt = _build_semantic_repair_prompt(
        normalised_text,
        top_intent,
        session_summary_json=summary_json,
        repair_hints=repair_hints,
    )

    parse_retry_count = 0
    parse_attempts = 0
    parse_mode = "full_prompt"
    parse_status = "pending"
    parse_reason = ""

    result = _semantic_llm_attempt(
        llm_call,
        prompt=full_prompt,
        timeout_ms=_semantic_full_timeout_ms(),
    )
    parse_attempts += 1
    if not result.get("ok"):
        parse_reason = str(result.get("error_code", "") or result.get("error_message", "") or "semantic_parse_failed")
        parse_retry_count = 1
        parse_mode = "repair_prompt"
        repair_result = _semantic_llm_attempt(
            llm_call,
            prompt=repair_prompt,
            timeout_ms=_semantic_repair_timeout_ms(),
        )
        parse_attempts += 1
        result = repair_result
        if repair_result.get("ok"):
            parse_status = "repaired"
            parse_reason = parse_reason or str(result.get("error_code", "") or result.get("error_message", "") or "semantic_parse_failed")
        else:
            parse_status = "failed"
            parse_reason = str(repair_result.get("error_code", "") or repair_result.get("error_message", "") or parse_reason or "semantic_parse_failed")
    else:
        parse_status = "validated"

    if result.get("ok"):
        payload = result["content"] or {}
        if not isinstance(payload, dict):
            if isinstance(payload, str):
                try:
                    payload = parse_json_response(payload)
                except LLMJSONParseError:
                    payload = {}
            else:
                payload = {}
        slot_hints = _safe_extract_slots(normalised_text, top_intent)
        payload = _merge_slot_hints(_merge_semantic_mentions(payload), slot_hints)
        normalized_payload = _normalize_semantic_payload(payload, top_intent=top_intent)
        if normalized_payload.get("task_type") == TaskType.recommendation:
            hinted_limit = _normalize_candidate_limit(slot_hints.get("candidate_limit"))
            current_limit = _normalize_candidate_limit(normalized_payload.get("candidate_limit"))
            if current_limit is None and hinted_limit is not None:
                normalized_payload["candidate_limit"] = hinted_limit
            ranking_signals = normalized_payload.get("ranking_signals")
            if not isinstance(ranking_signals, dict):
                ranking_signals = {}
            if hinted_limit is not None and not _normalize_candidate_limit(ranking_signals.get("requested_count")):
                ranking_signals["requested_count"] = hinted_limit
            normalized_payload["ranking_signals"] = ranking_signals
        llm_backend = str(result.get("llm_backend", "real_llm") or "real_llm")
        # Map backend kinds to semantic source taxonomy.
        #   rule_based → rule_based (pure offline rules, no LLM)
        #   fake_llm   → fake_llm   (test-injected fake)
        #   fake       → fake_llm   (legacy compat)
        #   real_llm   → real_llm   (real LLM provider)
        #   real       → real_llm   (legacy compat)
        #   other      → passthrough
        _source_map = {
            "rule_based": "rule_based",
            "fake_llm": "fake_llm",
            "fake": "fake_llm",
            "spy_real_llm": "spy_real_llm",
            "real_llm": "real_llm",
            "real": "real_llm",
        }
        semantic_source = _source_map.get(llm_backend, "real_llm")
        try:
            frame = SemanticFrame.model_validate(normalized_payload)
            frame = _annotate_frame(
                frame,
                semantic_source=semantic_source,
                parse_source=_parse_source_for_backend(semantic_source),
                llm_backend=llm_backend,
                fallback_reason="",
                llm_called=True,
            )
            frame.semantic_parse_status = parse_status
            frame.semantic_parse_mode = parse_mode
            frame.semantic_parse_retry_count = parse_retry_count
            frame.semantic_parse_attempts = parse_attempts
            frame.semantic_parse_reason = parse_reason
            _apply_session_follow_up_context(frame, normalised_text, summary)
            schema_validation_result = _schema_validation_result(
                status=parse_status,
                source="llm",
                confidence=float(frame.confidence or 0.0),
                payload_preview={"top_intent": normalized_payload.get("top_intent"), "task_type": normalized_payload.get("task_type"), "workflow_hint": normalized_payload.get("workflow_hint")},
            )
            schema_validation_result.update(
                {
                    "parse_status": parse_status,
                    "parse_mode": parse_mode,
                    "parse_retry_count": parse_retry_count,
                    "parse_attempts": parse_attempts,
                    "parse_reason": parse_reason,
                }
            )
            if parse_status != "validated":
                frame.semantic_source = "diagnostic_rules"
                frame.parse_source = SemanticParseSource.fallback_rules
                frame.semantic_parse_source = SemanticParseSource.fallback_rules
                frame.fallback_reason = parse_reason or frame.fallback_reason or "semantic_parse_repaired"
        except ValidationError as exc:
            recovery_frame, recovery_preview, recovery_error = _build_recovery_frame(
                normalised_text,
                top_intent,
                result.get("raw") or normalized_payload,
                llm_called=True,
                llm_backend=llm_backend,
                source=semantic_source,
                fallback_reason="SEMANTIC_SCHEMA_VALIDATION_FAILED",
            )
            if recovery_frame is not None:
                frame = recovery_frame
                frame.semantic_parse_status = "recovered"
                frame.semantic_parse_mode = parse_mode
                frame.semantic_parse_retry_count = parse_retry_count
                frame.semantic_parse_attempts = parse_attempts
                frame.semantic_parse_reason = parse_reason or "SEMANTIC_SCHEMA_VALIDATION_FAILED"
                schema_validation_result = _schema_validation_result(
                    status="recovered",
                    source="llm_raw_recovery",
                    confidence=float(frame.confidence or 0.0),
                    payload_preview=recovery_preview or normalized_payload,
                    error_code="SEMANTIC_SCHEMA_REPAIRED",
                    error_message=str(exc),
                )
                schema_validation_result.update(
                    {
                        "parse_status": "recovered",
                        "parse_mode": parse_mode,
                        "parse_retry_count": parse_retry_count,
                        "parse_attempts": parse_attempts,
                        "parse_reason": frame.semantic_parse_reason,
                    }
                )
            elif allow_fallback:
                frame = _fallback_semantic_frame(
                    normalised_text,
                    top_intent,
                    fallback_reason="SEMANTIC_SCHEMA_VALIDATION_FAILED",
                    llm_called=True,
                    llm_backend=llm_backend,
                    semantic_source="diagnostic_rules",
                )
                frame.semantic_parse_status = "fallback"
                frame.semantic_parse_mode = parse_mode
                frame.semantic_parse_retry_count = parse_retry_count
                frame.semantic_parse_attempts = parse_attempts
                frame.semantic_parse_reason = parse_reason or "SEMANTIC_SCHEMA_VALIDATION_FAILED"
                schema_validation_result = _schema_validation_result(
                    status="fallback",
                    source="slot_extractor_recovery",
                    confidence=frame.confidence,
                    payload_preview=recovery_preview or normalized_payload,
                    error_code="SEMANTIC_SCHEMA_VALIDATION_FAILED",
                    error_message=str(exc),
                )
                schema_validation_result.update(
                    {
                        "parse_status": "fallback",
                        "parse_mode": parse_mode,
                        "parse_retry_count": parse_retry_count,
                        "parse_attempts": parse_attempts,
                        "parse_reason": frame.semantic_parse_reason,
                    }
                )
            else:
                response = {
                    "semantic_frame": None,
                    "error_code": "SEMANTIC_SCHEMA_VALIDATION_FAILED",
                    "error_message": str(exc),
                    "raw": result.get("raw", ""),
                    "semantic_source": semantic_source,
                    "parse_source": semantic_source,
                    "semantic_parse_source": semantic_source,
                    "llm_backend": llm_backend,
                    "fallback_reason": "SEMANTIC_SCHEMA_VALIDATION_FAILED",
                    "llm_called": True,
                    "semantic_parse_status": "failed",
                    "semantic_parse_mode": parse_mode,
                    "semantic_parse_retry_count": parse_retry_count,
                    "semantic_parse_attempts": parse_attempts,
                    "semantic_parse_reason": parse_reason or "SEMANTIC_SCHEMA_VALIDATION_FAILED",
                    "schema_validation_result": _schema_validation_result(
                        status="failed",
                        source="llm_validation",
                        confidence=float(normalized_payload.get("confidence", 0.0) or 0.0),
                        payload_preview=normalized_payload,
                        error_code="SEMANTIC_SCHEMA_VALIDATION_FAILED",
                        error_message=str(exc),
                    ),
                }
                log_kv(
                    _SERVICE_LOG,
                    logging.ERROR,
                    "[SEMANTIC_PARSE_RESULT]",
                    tone="error",
                    source="schema_validation_failed",
                    error_code="SEMANTIC_SCHEMA_VALIDATION_FAILED",
                    error_message=str(exc),
                    llm_backend=llm_backend,
                    raw_preview=result.get("raw", ""),
                    parse_mode=parse_mode,
                    parse_retry_count=parse_retry_count,
                    parse_attempts=parse_attempts,
                )
                return response
    if not result.get("ok"):
        error_code = result.get("error_code", "") or parse_reason or "SEMANTIC_PARSE_FAILED"
        error_message = result.get("error_message", "") or "semantic parse failed"
        if not allow_fallback:
            response = {
                "semantic_frame": None,
                "error_code": error_code,
                "error_message": error_message,
                "raw": result.get("raw", ""),
                "semantic_source": "",
                "parse_source": "",
                "semantic_parse_source": "",
                "llm_backend": str(result.get("llm_backend", "") or ""),
                "fallback_reason": error_code,
                "llm_called": True,
                "semantic_parse_status": "failed",
                "semantic_parse_mode": parse_mode,
                "semantic_parse_retry_count": parse_retry_count,
                "semantic_parse_attempts": parse_attempts,
                "semantic_parse_reason": parse_reason or error_code,
                "semantic_repair_hints": _safe_extract_slots(normalised_text, top_intent),
                "schema_validation_result": _schema_validation_result(
                    status="failed",
                    source="llm_failure",
                    confidence=0.0,
                    error_code=error_code,
                    error_message=error_message,
                ),
            }
            return response
        frame = _fallback_semantic_frame(
            normalised_text,
            top_intent,
            fallback_reason=error_code,
            llm_called=True,
            llm_backend=str(result.get("llm_backend", "") or ""),
            semantic_source="diagnostic_rules",
        )
        frame.semantic_parse_status = "fallback"
        frame.semantic_parse_mode = parse_mode
        frame.semantic_parse_retry_count = parse_retry_count
        frame.semantic_parse_attempts = parse_attempts
        frame.semantic_parse_reason = parse_reason or error_code
        response = {
            "semantic_frame": frame,
            "error_code": "",
            "error_message": "",
            "raw": result.get("raw", ""),
            "semantic_source": frame.semantic_source,
            "parse_source": _enum_value(frame.parse_source),
            "semantic_parse_source": _enum_value(frame.semantic_parse_source),
            "llm_backend": frame.llm_backend,
            "fallback_reason": frame.fallback_reason,
            "llm_called": True,
            "semantic_parse_status": frame.semantic_parse_status,
            "semantic_parse_mode": frame.semantic_parse_mode,
            "semantic_parse_retry_count": frame.semantic_parse_retry_count,
            "semantic_parse_attempts": frame.semantic_parse_attempts,
            "semantic_parse_reason": frame.semantic_parse_reason,
            "semantic_repair_hints": _safe_extract_slots(normalised_text, top_intent),
            "schema_validation_result": _schema_validation_result(
                status="fallback",
                source="slot_extractor_fallback",
                confidence=frame.confidence,
                payload_preview={},
                error_code=error_code,
                error_message=error_message,
            ),
        }
        log_kv(
            _SERVICE_LOG,
            logging.WARNING,
            "[SEMANTIC_PARSE_RESULT]",
            tone="warn",
            source="fallback",
            semantic_source=frame.semantic_source,
            llm_backend=frame.llm_backend,
            fallback_reason=frame.fallback_reason,
            raw_preview=result.get("raw", ""),
            semantic_frame=frame,
            parse_status=response["semantic_parse_status"],
            parse_mode=response["semantic_parse_mode"],
            parse_retry_count=response["semantic_parse_retry_count"],
            parse_attempts=response["semantic_parse_attempts"],
            parse_reason=response["semantic_parse_reason"],
        )
        return response

    if frame.top_intent is None and top_intent in {item.value for item in TopIntent}:
        frame.top_intent = TopIntent(top_intent)
        frame.intent = frame.top_intent
    dropped_facets = get_last_dropped_facets()
    if frame.semantic_parse_status in {"fallback", "failed", "recovered"} or str(frame.fallback_reason or ""):
        frame.semantic_source = "diagnostic_rules"
        frame.parse_source = SemanticParseSource.fallback_rules
        frame.semantic_parse_source = SemanticParseSource.fallback_rules
    response = {
        "semantic_frame": frame,
        "error_code": "",
        "error_message": "",
        "raw": result.get("raw", ""),
        "semantic_source": frame.semantic_source,
        "parse_source": _enum_value(frame.parse_source),
        "semantic_parse_source": _enum_value(frame.semantic_parse_source),
        "llm_backend": frame.llm_backend,
        "fallback_reason": frame.fallback_reason,
        "llm_called": frame.llm_called,
        "semantic_parse_status": frame.semantic_parse_status or parse_status,
        "semantic_parse_mode": frame.semantic_parse_mode or parse_mode,
        "semantic_parse_retry_count": frame.semantic_parse_retry_count or parse_retry_count,
        "semantic_parse_attempts": frame.semantic_parse_attempts or parse_attempts,
        "semantic_parse_reason": frame.semantic_parse_reason or parse_reason,
        "schema_validation_result": schema_validation_result,
        "dropped_facets": dropped_facets,
    }
    log_kv(
        _SERVICE_LOG,
        logging.INFO,
        "[SEMANTIC_PARSE_RESULT]",
        tone="route",
        source="llm",
        semantic_source=frame.semantic_source,
        llm_backend=frame.llm_backend,
        task_type=frame.task_type,
        primary_task=frame.primary_task,
        focused_facets=frame.focused_facets,
        merchant_mentions=frame.merchant_mentions,
        dropped_facets=dropped_facets,
        llm_payload=payload,
        raw_preview=result.get("raw", ""),
        parse_status=response["semantic_parse_status"],
        parse_mode=response["semantic_parse_mode"],
        parse_retry_count=response["semantic_parse_retry_count"],
        parse_attempts=response["semantic_parse_attempts"],
        parse_reason=response["semantic_parse_reason"],
    )
    return response

    if not result.get("ok"):
        error_code = result.get("error_code", "") or "SEMANTIC_PARSE_FAILED"
        error_message = result.get("error_message", "") or "semantic parse failed"
        if not allow_fallback:
            response = {
                "semantic_frame": None,
                "error_code": error_code,
                "error_message": error_message,
                "raw": result.get("raw", ""),
                "semantic_source": "",
                "parse_source": "",
                "semantic_parse_source": "",
                "llm_backend": str(result.get("llm_backend", "") or ""),
                "fallback_reason": error_code,
                "llm_called": True,
                "semantic_parse_status": "failed",
                "semantic_parse_mode": parse_mode,
                "semantic_parse_retry_count": parse_retry_count,
                "semantic_parse_attempts": parse_attempts,
                "semantic_parse_reason": parse_reason or error_code,
                "semantic_repair_hints": _safe_extract_slots(normalised_text, top_intent),
                "schema_validation_result": _schema_validation_result(
                    status="failed",
                    source="llm_failure",
                    confidence=0.0,
                    error_code=error_code,
                    error_message=error_message,
                ),
            }
            log_kv(
                _SERVICE_LOG,
                logging.ERROR,
                "[SEMANTIC_PARSE_RESULT]",
                tone="error",
                source="llm_failed",
                error_code=error_code,
                error_message=error_message,
                llm_backend=result.get("llm_backend", ""),
                raw_preview=result.get("raw", ""),
                repair_hints=response.get("semantic_repair_hints"),
                parse_mode=parse_mode,
                parse_retry_count=parse_retry_count,
                parse_attempts=parse_attempts,
            )
            return response

        frame = _fallback_semantic_frame(
            normalised_text,
            top_intent,
            fallback_reason=error_code,
            llm_called=True,
            llm_backend=str(result.get("llm_backend", "") or ""),
            semantic_source="diagnostic_rules",
        )
        frame.semantic_parse_status = "fallback"
        frame.semantic_parse_mode = parse_mode
        frame.semantic_parse_retry_count = parse_retry_count
        frame.semantic_parse_attempts = parse_attempts
        frame.semantic_parse_reason = parse_reason or error_code
        if frame.top_intent is None and top_intent in {item.value for item in TopIntent}:
            frame.top_intent = TopIntent(top_intent)
            frame.intent = frame.top_intent
        response = {
            "semantic_frame": frame,
            "error_code": "",
            "error_message": "",
            "raw": result.get("raw", ""),
            "semantic_source": frame.semantic_source,
            "parse_source": _enum_value(frame.parse_source),
            "semantic_parse_source": _enum_value(frame.semantic_parse_source),
            "llm_backend": frame.llm_backend,
            "fallback_reason": frame.fallback_reason,
            "llm_called": True,
            "semantic_parse_status": frame.semantic_parse_status,
            "semantic_parse_mode": frame.semantic_parse_mode,
            "semantic_parse_retry_count": frame.semantic_parse_retry_count,
            "semantic_parse_attempts": frame.semantic_parse_attempts,
            "semantic_parse_reason": frame.semantic_parse_reason,
            "semantic_repair_hints": _safe_extract_slots(normalised_text, top_intent),
            "schema_validation_result": _schema_validation_result(
                status="fallback",
                source="slot_extractor_fallback",
                confidence=frame.confidence,
                payload_preview={},
                error_code=error_code,
                error_message=error_message,
            ),
        }
        log_kv(
            _SERVICE_LOG,
            logging.WARNING,
            "[SEMANTIC_PARSE_RESULT]",
            tone="warn",
            source="fallback",
            semantic_source=frame.semantic_source,
            llm_backend=frame.llm_backend,
            fallback_reason=frame.fallback_reason,
            raw_preview=result.get("raw", ""),
            semantic_frame=frame,
            parse_status=response["semantic_parse_status"],
            parse_mode=response["semantic_parse_mode"],
            parse_retry_count=response["semantic_parse_retry_count"],
            parse_attempts=response["semantic_parse_attempts"],
            parse_reason=response["semantic_parse_reason"],
        )
        return response


