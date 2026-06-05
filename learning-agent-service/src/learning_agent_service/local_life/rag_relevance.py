from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")

FACET_COMPATIBILITY: dict[str, set[str]] = {
    "environment": {"environment", "scene_fit", "crowd", "noise", "seat", "parking"},
    "scene_fit": {"scene_fit", "environment", "crowd", "noise", "service", "price", "recommendation_reason"},
    "coupon": {"coupon", "deal", "package"},
    "open_status": {"open_status", "business_hours"},
    "taste": {"taste", "dish", "product"},
    "service": {"service", "queue"},
    "recommendation": {"scene_fit", "environment", "taste", "price", "location", "category", "recommendation_reason"},
    "recommendation_reason": {"scene_fit", "environment", "taste", "price", "location", "category", "recommendation"},
    "price": {"price", "scene_fit", "recommendation_reason"},
}

_FACET_ALIASES: dict[str, str] = {
    "deal": "coupon",
    "package": "coupon",
    "package_description": "coupon",
    "business_hours": "open_status",
    "distance": "distance_eta",
    "shop_detail": "environment",
    "general_review": "environment",
    "location": "recommendation_reason",
    "merchant_profile": "environment",
    "merchant_review_summary": "environment",
    "merchant_scene_fit": "scene_fit",
    "review_summary": "environment",
    "dish_recommendation": "taste",
    "merchant_service": "service",
}


def normalize_facet(value: Any) -> str | None:
    if value in (None, ""):
        return None
    facet = str(value).strip().lower()
    if not facet:
        return None
    return _FACET_ALIASES.get(facet, facet)


def extract_facet(item: Any) -> str | None:
    item_map = _as_mapping(item)
    metadata = _as_mapping(item_map.get("metadata"))
    for key in ("facet", "chunk_type", "source_type", "chunk_role", "scene_kind"):
        facet = normalize_facet(item_map.get(key))
        if facet:
            return facet
        facet = normalize_facet(metadata.get(key))
        if facet:
            return facet
    return None


def compatible_facets(allowed_facets: Sequence[str]) -> set[str]:
    normalized_allowed: set[str] = set()
    for facet in allowed_facets:
        norm = normalize_facet(facet)
        if norm is not None:
            normalized_allowed.add(norm)
    compatible: set[str] = set(normalized_allowed)
    for facet in normalized_allowed:
        compatible.update(FACET_COMPATIBILITY.get(facet, {facet}))
    return compatible


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in _TOKEN_PATTERN.findall(text or ""))


def lexical_overlap(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    text_tokens = set(tokenize(text))
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / float(len(query_tokens | text_tokens) or 1)


def metadata_match_score(*, target_shop_id: int | None, item_shop_id: int | None, facet_match: bool) -> float:
    score = 0.0
    if target_shop_id is None:
        score += 0.5
    elif item_shop_id == target_shop_id:
        score += 1.0
    if facet_match:
        score += 0.5
    return min(score, 1.0)


def final_relevance_score(
    *,
    confidence: float,
    lexical: float,
    facet_match: bool,
    metadata_score: float,
) -> float:
    facet_score = 1.0 if facet_match else 0.0
    return (
        0.45 * max(0.0, min(float(confidence), 1.0))
        + 0.25 * lexical
        + 0.20 * facet_score
        + 0.10 * metadata_score
    )


def support_level(score: float) -> str:
    if score >= 0.70:
        return "strong"
    if score >= 0.50:
        return "medium"
    if score >= 0.35:
        return "weak"
    return "irrelevant"
