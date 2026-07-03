from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...domain.facets import LOCAL_LIFE_FACET_TAXONOMY, FacetSet, QueryFacet, normalize_query_facets
from .tool_capabilities import TOOL_CAPABILITY_REGISTRY, tool_supports_facet


_VALID_FACETS: set[str] = {
    facet for facets in LOCAL_LIFE_FACET_TAXONOMY.values() for facet in facets
}
_VALID_FACETS.update(
    {
        "detail",
        "deal",
        "open_status",
        "review_summary",
        "scene_fit",
        "price",
        "rating",
    }
)

_SYNONYM_MAP: dict[str, str] = {
    "open_status": "open_now",
    "review_summary": "review_tags",
    "scene_fit": "family_with_kids",
    "price": "avg_price",
    "deal": "group_buy",
}

_REFERENCE_FACETS = {"current_shop", "ordinal_reference", "comparison_targets", "previous_recommendation"}
_DECISION_FACETS = {"price_compare", "avg_price", "budget", "budget_around_x", "rating"}
_SAFETY_FACETS = {"open_now", "distance", "travel_time", "coupon"}


class FacetCandidate(BaseModel):
    facet: str
    source: str = "llm"
    confidence: float | None = None
    priority_group: str | None = None
    reason: str | None = None


class FacetValidationResult(BaseModel):
    accepted_facets: list[str] = Field(default_factory=list)
    rejected_facets: list[str] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    normalized_facets: list[str] = Field(default_factory=list)
    rejection_reasons: dict[str, str] = Field(default_factory=dict)


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


def _normalize_facet_name(name: Any) -> str:
    raw = str(getattr(name, "value", name) or "").strip()
    return _SYNONYM_MAP.get(raw, raw)


def _priority_group_for_candidate(candidate: FacetCandidate) -> str:
    facet = _normalize_facet_name(candidate.facet)
    if facet in _REFERENCE_FACETS:
        return "reference_required"
    if facet in _DECISION_FACETS:
        return "decision_required"
    if facet in _SAFETY_FACETS:
        return "safety_required"
    if candidate.source in {"text", "user", "current_shop", "session_state"}:
        return "user_explicit"
    if candidate.source in {"required", "rule"}:
        return "reference_required" if facet in _REFERENCE_FACETS else "decision_required"
    return candidate.priority_group or "experience"


def _facet_from_item(item: Any, *, source: str) -> FacetCandidate | None:
    if item is None:
        return None
    if isinstance(item, FacetCandidate):
        facet = _normalize_facet_name(item.facet)
        return item.model_copy(update={"facet": facet, "priority_group": item.priority_group or _priority_group_for_candidate(item)})
    if isinstance(item, QueryFacet):
        facet = _normalize_facet_name(item.name)
        return FacetCandidate(
            facet=facet,
            source=str(item.source or source or "rule"),
            confidence=item.confidence,
            priority_group="reference_required" if item.required and facet in _REFERENCE_FACETS else None,
            reason=item.resolution_reason,
        )
    if isinstance(item, str):
        facet = _normalize_facet_name(item)
        return FacetCandidate(facet=facet, source=source)
    if isinstance(item, dict):
        raw = dict(item)
        facet = _normalize_facet_name(raw.get("facet", raw.get("facet_name", raw.get("name", ""))))
        if not facet:
            return None
        return FacetCandidate(
            facet=facet,
            source=str(raw.get("source", source) or source),
            confidence=raw.get("confidence"),
            priority_group=raw.get("priority_group"),
            reason=raw.get("reason") or raw.get("resolution_reason"),
        )
    if hasattr(item, "name") or hasattr(item, "facet"):
        return _facet_from_item(_to_dict(item), source=source)
    facet = _normalize_facet_name(item)
    if not facet:
        return None
    return FacetCandidate(facet=facet, source=source)


def build_facet_candidates(
    proposed_facets: list[Any] | None = None,
    *,
    semantic_frame: dict[str, Any] | Any | None = None,
    session_state: dict[str, Any] | Any | None = None,
    raw_text: str = "",
) -> list[FacetCandidate]:
    frame = _to_dict(semantic_frame)
    facet_set = normalize_query_facets(frame, session_state=session_state, raw_text=raw_text)
    lowered = str(raw_text or "").strip()

    candidates: list[FacetCandidate] = []
    for item in proposed_facets or []:
        candidate = _facet_from_item(item, source="llm")
        if candidate is not None:
            candidate.priority_group = candidate.priority_group or _priority_group_for_candidate(candidate)
            candidates.append(candidate)

    for item in facet_set.facets:
        candidate = _facet_from_item(item, source=str(getattr(item, "source", "") or "rule"))
        if candidate is not None:
            candidate.priority_group = candidate.priority_group or _priority_group_for_candidate(candidate)
            candidates.append(candidate)

    if facet_set.target_resolution and not facet_set.target_resolution.resolved:
        unresolved = str(facet_set.target_resolution.unresolved_reason or facet_set.target_resolution.resolution_reason or "")
        if unresolved and "comparison" in unresolved:
            candidates.append(FacetCandidate(facet="comparison_targets", source="required", confidence=1.0, priority_group="reference_required", reason=unresolved))

    has_deictic_cue = any(token in lowered for token in ("这家", "那家", "这间", "那间", "它", "第一家", "第二家"))
    if has_deictic_cue and not any(_normalize_facet_name(item.facet) == "current_shop" for item in candidates):
        candidates.append(
            FacetCandidate(
                facet="current_shop",
                source="required",
                confidence=0.0,
                priority_group="reference_required",
                reason="missing_current_shop",
            )
        )

    has_comparison_cue = any(token in lowered for token in ("哪家", "哪间", "哪一个", "哪款")) or ("第一家" in lowered and "第二家" in lowered)
    if has_comparison_cue and not any(_normalize_facet_name(item.facet) == "comparison_targets" for item in candidates):
        candidates.append(
            FacetCandidate(
                facet="comparison_targets",
                source="required",
                confidence=0.0,
                priority_group="reference_required",
                reason="missing_comparison_targets",
            )
        )

    # Deduplicate while keeping the first/highest-priority occurrence.
    ordered: list[FacetCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        facet = _normalize_facet_name(candidate.facet)
        if not facet or facet in seen:
            continue
        seen.add(facet)
        ordered.append(
            candidate.model_copy(update={
                "facet": facet,
                "priority_group": candidate.priority_group or _priority_group_for_candidate(candidate),
            })
        )
    return ordered


def validate_facet_candidates(
    candidates: list[FacetCandidate] | list[Any],
    *,
    capability_registry: dict[str, Any] | None = None,
) -> FacetValidationResult:
    registry = capability_registry or TOOL_CAPABILITY_REGISTRY
    result = FacetValidationResult()
    accepted: list[str] = []
    normalized: list[str] = []
    seen: set[str] = set()

    for item in candidates or []:
        candidate = _facet_from_item(item, source="llm")
        if candidate is None:
            continue
        facet = _normalize_facet_name(candidate.facet)
        if not facet:
            continue
        if facet in seen:
            continue
        seen.add(facet)
        normalized.append(facet)
        if facet not in _VALID_FACETS:
            result.rejected_facets.append(facet)
            result.rejection_reasons[facet] = "unknown_facet"
            continue
        supported = any(tool_supports_facet(tool_name, facet) for tool_name in registry)
        if not supported:
            result.unsupported_facets.append(facet)
            result.rejection_reasons[facet] = "unsupported_facet"
            continue
        accepted.append(facet)

    result.accepted_facets = accepted
    result.normalized_facets = normalized
    return result
