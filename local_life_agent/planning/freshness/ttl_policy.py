from __future__ import annotations

from .freshness_policy import FreshnessClass, freshness_policy_for_facet


def ttl_seconds_for_facet(facet: str) -> int | None:
    return freshness_policy_for_facet(facet).ttl_seconds


def ttl_seconds_for_class(freshness_class: FreshnessClass) -> int | None:
    return {
        FreshnessClass.STRONG_DYNAMIC: 120,
        FreshnessClass.WEAK_DYNAMIC: 86400,
        FreshnessClass.STATIC: 604800,
        FreshnessClass.LOCATION_BOUND: 300,
        FreshnessClass.SAME_TURN_ONLY: 0,
    }.get(freshness_class)

