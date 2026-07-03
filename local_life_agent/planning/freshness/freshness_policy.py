from __future__ import annotations

import hashlib
import json
from enum import Enum
from time import time
from typing import Any

from pydantic import BaseModel, ConfigDict


class FreshnessClass(str, Enum):
    STRONG_DYNAMIC = "strong_dynamic"
    WEAK_DYNAMIC = "weak_dynamic"
    STATIC = "static"
    LOCATION_BOUND = "location_bound"
    SAME_TURN_ONLY = "same_turn_only"


class FreshnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facet: str
    freshness_class: FreshnessClass
    ttl_seconds: int | None = None
    requires_location_fingerprint: bool = False
    same_turn_only: bool = False
    stale_action: str = "refresh_or_unknown"


_POLICY_TABLE: dict[str, FreshnessPolicy] = {
    "open_status": FreshnessPolicy(facet="open_status", freshness_class=FreshnessClass.STRONG_DYNAMIC, ttl_seconds=120),
    "open_now": FreshnessPolicy(facet="open_now", freshness_class=FreshnessClass.STRONG_DYNAMIC, ttl_seconds=120),
    "coupon": FreshnessPolicy(facet="coupon", freshness_class=FreshnessClass.STRONG_DYNAMIC, ttl_seconds=120),
    "queue_status": FreshnessPolicy(facet="queue_status", freshness_class=FreshnessClass.STRONG_DYNAMIC, ttl_seconds=120),
    "reservation_available": FreshnessPolicy(facet="reservation_available", freshness_class=FreshnessClass.STRONG_DYNAMIC, ttl_seconds=180),
    "rating": FreshnessPolicy(facet="rating", freshness_class=FreshnessClass.WEAK_DYNAMIC, ttl_seconds=86400, stale_action="allow_with_disclaimer"),
    "review_tags": FreshnessPolicy(facet="review_tags", freshness_class=FreshnessClass.WEAK_DYNAMIC, ttl_seconds=86400, stale_action="allow_with_disclaimer"),
    "avg_price": FreshnessPolicy(facet="avg_price", freshness_class=FreshnessClass.WEAK_DYNAMIC, ttl_seconds=86400, stale_action="allow_with_disclaimer"),
    "shop_static_info": FreshnessPolicy(facet="shop_static_info", freshness_class=FreshnessClass.WEAK_DYNAMIC, ttl_seconds=86400, stale_action="allow_with_disclaimer"),
    "shop_name": FreshnessPolicy(facet="shop_name", freshness_class=FreshnessClass.STATIC, ttl_seconds=604800, stale_action="allow_with_disclaimer"),
    "address": FreshnessPolicy(facet="address", freshness_class=FreshnessClass.STATIC, ttl_seconds=604800, stale_action="allow_with_disclaimer"),
    "phone": FreshnessPolicy(facet="phone", freshness_class=FreshnessClass.STATIC, ttl_seconds=604800, stale_action="allow_with_disclaimer"),
    "category": FreshnessPolicy(facet="category", freshness_class=FreshnessClass.STATIC, ttl_seconds=604800, stale_action="allow_with_disclaimer"),
    "business_area": FreshnessPolicy(facet="business_area", freshness_class=FreshnessClass.STATIC, ttl_seconds=604800, stale_action="allow_with_disclaimer"),
    "distance": FreshnessPolicy(facet="distance", freshness_class=FreshnessClass.LOCATION_BOUND, ttl_seconds=300, requires_location_fingerprint=True, stale_action="refresh_or_unknown"),
    "travel_time": FreshnessPolicy(facet="travel_time", freshness_class=FreshnessClass.LOCATION_BOUND, ttl_seconds=300, requires_location_fingerprint=True, stale_action="refresh_or_unknown"),
}

_LOCATION_KEYS = ("lat", "lng", "latitude", "longitude", "location_name", "label")


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    return str(value)


def compute_location_fingerprint(location: dict[str, Any] | None) -> str:
    location = location or {}
    compact = {key: location.get(key) for key in _LOCATION_KEYS if str(location.get(key, "") or "").strip()}
    if not compact:
        return ""
    raw = json.dumps(compact, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def freshness_policy_for_facet(facet: str) -> FreshnessPolicy:
    normalized = str(facet or "").strip()
    if not normalized:
        return FreshnessPolicy(facet="", freshness_class=FreshnessClass.SAME_TURN_ONLY, ttl_seconds=0, same_turn_only=True)
    policy = _POLICY_TABLE.get(normalized)
    if policy is not None:
        return policy
    if normalized in {"distance", "travel_time"}:
        return FreshnessPolicy(facet=normalized, freshness_class=FreshnessClass.LOCATION_BOUND, ttl_seconds=300, requires_location_fingerprint=True, stale_action="refresh_or_unknown")
    if normalized in {"open_status", "open_now", "coupon", "queue_status", "reservation_available"}:
        return FreshnessPolicy(facet=normalized, freshness_class=FreshnessClass.STRONG_DYNAMIC, ttl_seconds=120)
    return FreshnessPolicy(facet=normalized, freshness_class=FreshnessClass.SAME_TURN_ONLY, ttl_seconds=0, same_turn_only=True, stale_action="block_claim")


def build_freshness_metadata(
    facet: str,
    *,
    observed_at_ms: int | None = None,
    ttl_seconds: int | None = None,
    freshness_class: FreshnessClass | str | None = None,
    is_stale: bool = False,
    cache_hit: bool = False,
    location_fingerprint: str | None = None,
    budget_context_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = freshness_policy_for_facet(facet)
    freshness_value = freshness_class.value if isinstance(freshness_class, FreshnessClass) else str(freshness_class or policy.freshness_class.value)
    return {
        "observed_at_ms": observed_at_ms if observed_at_ms is not None else int(time() * 1000),
        "ttl_seconds": ttl_seconds if ttl_seconds is not None else policy.ttl_seconds,
        "freshness_class": freshness_value,
        "is_stale": bool(is_stale),
        "cache_hit": bool(cache_hit),
        "location_fingerprint": location_fingerprint or "",
        "budget_context_snapshot": budget_context_snapshot or None,
    }


def is_stale_evidence(
    metadata: dict[str, Any] | None,
    *,
    current_location_fingerprint: str | None = None,
    now_ms: int | None = None,
) -> bool:
    metadata = metadata or {}
    if metadata.get("is_stale") is True:
        return True
    ttl_seconds = metadata.get("ttl_seconds")
    observed_at_ms = metadata.get("observed_at_ms")
    if isinstance(ttl_seconds, int) and ttl_seconds >= 0 and isinstance(observed_at_ms, int):
        now = int(now_ms if now_ms is not None else time() * 1000)
        if now - observed_at_ms > ttl_seconds * 1000:
            return True
    expected_fp = str(metadata.get("location_fingerprint", "") or "")
    if expected_fp and current_location_fingerprint and expected_fp != current_location_fingerprint:
        return True
    return False
