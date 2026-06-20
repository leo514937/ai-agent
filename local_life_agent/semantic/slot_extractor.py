"""Typed slot extraction for the local-life semantic layer.

The stage-11 implementation expands the single-shop flow to allow
multiple facets on the same shop while keeping the extractor conservative:
- no shop IDs
- no tool names
- no fabricated facts
"""

from __future__ import annotations

import re

from ..domain.enums import Facet, TaskType
from ..input.normalizer import normalize_text
from ..tools.mock_tools import _all_shops

_COUPON_HINTS = (
    "有券",
    "优惠券",
    "代金券",
    "折扣券",
    "券",
    "优惠",
    "领券",
    "可用券",
)
_FACET_HINTS: dict[Facet, tuple[str, ...]] = {
    Facet.coupon: _COUPON_HINTS,
    Facet.open_status: (
        "营业",
        "开门",
        "关门",
        "打烊",
        "歇业",
        "营业吗",
        "现在营业",
    ),
    Facet.distance: (
        "距离",
        "多远",
        "远不远",
        "几公里",
        "路程",
        "离这",
        "离我",
    ),
}
_OPTIONAL_HINTS = ("顺便", "最好", "也看", "一起看", "再看", "顺带", "附带")

_NOISE_RE = re.compile(r"[\s\.,，。！？!？:：、`'\"_\-+=\(\)\[\]{}<>/\\|·～]+")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _shop_tokens() -> list[tuple[str, str]]:
    """Return ``(token, canonical_name)`` pairs for exact matching."""
    tokens: list[tuple[str, str]] = []
    for shop in _all_shops():
        shop_name = normalize_text(shop.get("shop_name", "")).strip()
        if shop_name:
            tokens.append((shop_name, shop_name))

        alias = normalize_text(shop.get("alias", "")).strip()
        if alias:
            tokens.append((alias, shop_name or alias))

        for alias_item in shop.get("aliases", []) or []:
            alias_item = normalize_text(alias_item).strip()
            if alias_item:
                tokens.append((alias_item, shop_name or alias_item))

    tokens.sort(key=lambda item: len(item[0]), reverse=True)
    return tokens


def _brand_prefix(name: str) -> str:
    name = normalize_text(name).strip()
    if "(" in name:
        return name.split("(", 1)[0].strip()
    return name


def _extract_merchant_mentions(text: str) -> list[str]:
    text = normalize_text(text)
    exact_matches: list[str] = []
    brand_matches: list[str] = []

    for token, canonical_name in _shop_tokens():
        if token and token in text:
            exact_matches.append(canonical_name)

    if exact_matches:
        return _dedupe(exact_matches)

    for shop in _all_shops():
        brand = _brand_prefix(shop.get("shop_name", ""))
        if brand and brand in text:
            brand_matches.append(brand)

    return _dedupe(brand_matches)


def _looks_like_coupon_query(text: str) -> bool:
    return any(hint in text for hint in _COUPON_HINTS)


def _facet_positions(text: str) -> list[tuple[int, Facet]]:
    positions: list[tuple[int, Facet]] = []
    seen: set[Facet] = set()
    for facet, hints in _FACET_HINTS.items():
        for hint in hints:
            idx = text.find(hint)
            if idx >= 0:
                positions.append((idx, facet))
                seen.add(facet)
                break
    positions.sort(key=lambda item: item[0])
    return positions


def _build_facet_specs(text: str) -> list[dict[str, object]]:
    ordered = _facet_positions(text)

    optional = any(hint in text for hint in _OPTIONAL_HINTS)
    specs: list[dict[str, object]] = []
    for idx, (_pos, facet) in enumerate(ordered):
        required = True
        if optional and (len(ordered) == 1 or idx > 0):
            required = False
        specs.append({"name": facet, "required": required})
    return specs


def extract_slots(text: str, top_intent: str) -> dict:
    """Extract typed slots from the user's utterance."""
    normalised = normalize_text(text)
    mentions = _extract_merchant_mentions(normalised)
    facets = _build_facet_specs(normalised)
    has_multi_facet = len(facets) > 1

    task_type: TaskType | None = None
    primary_task = ""
    need_context = False

    if top_intent == "local_life":
        if facets:
            task_type = TaskType.single_shop_query if has_multi_facet or any(
                isinstance(spec, dict) and spec.get("name") in {Facet.open_status, Facet.distance}
                for spec in facets
            ) else TaskType.coupon_query
            primary_task = "multi_facet_query" if len(facets) > 1 or task_type == TaskType.single_shop_query else "coupon_query"
            need_context = not bool(mentions)
        elif mentions:
            task_type = TaskType.single_shop_query
            primary_task = "single_shop_query"

    return {
        "top_intent": top_intent,
        "task_type": task_type,
        "primary_task": primary_task,
        "facets": facets,
        "merchant_mentions": mentions,
        "reference_mentions": [],
        "hard_constraints": {},
        "soft_preferences": {},
        "ranking_signals": {},
        "follow_up": None,
        "confidence": 0.9 if mentions else 0.6,
        "need_context": need_context,
    }
