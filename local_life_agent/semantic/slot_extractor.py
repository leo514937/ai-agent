"""Typed slot extraction for the local-life semantic layer.

The extractor stays conservative:
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
    "优惠",
    "领券",
    "可用券",
    "团购",
)

_FACET_HINTS: dict[Facet, tuple[str, ...]] = {
    Facet.coupon: _COUPON_HINTS,
    Facet.open_status: (
        "营业",
        "开门",
        "关门",
        "打烊",
        "歇业",
        "营业中",
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
        "附近",
    ),
}

_OPTIONAL_HINTS = ("顺便", "最好", "也看", "一起看", "再看", "顺带", "附带", "更好")
_RECOMMENDATION_HINTS = (
    "推荐",
    "附近",
    "周边",
    "找几家",
    "推荐几家",
    "给我推荐",
    "想找",
    "有没有适合",
)
_CATEGORY_HINTS = (
    "火锅",
    "餐厅",
    "餐馆",
    "快餐",
    "咖啡",
    "茶饮",
    "奶茶",
    "甜品",
    "烘焙",
    "烧烤",
    "饺子",
    "中餐",
    "西餐",
    "日料",
)
_SCENE_HINTS = (
    "约会",
    "朋友聚餐",
    "聚餐",
    "家庭聚餐",
    "商务",
    "请客",
    "夜宵",
)

_NOISE_RE = re.compile(r"[\s\.,，。！？；;:、\"_\-+=\(\)\[\]{}<>/\\|]+")


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


def _facet_positions(text: str) -> list[tuple[int, Facet]]:
    positions: list[tuple[int, Facet]] = []
    for facet, hints in _FACET_HINTS.items():
        for hint in hints:
            idx = text.find(hint)
            if idx >= 0:
                positions.append((idx, facet))
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


def _looks_like_recommendation(text: str) -> bool:
    return any(hint in text for hint in _RECOMMENDATION_HINTS)


_COMPARISON_HINTS = (
    "对比",
    "比较",
    "比一比",
    "比一比看",
    "哪个好",
    "哪个更",
    "哪家更",
    "哪家更好",
    "谁更",
    "横向",
)
_COMPARISON_REFERENCE_HINTS = (
    "第一家",
    "第二家",
    "第三家",
    "第一间",
    "第二间",
    "第三间",
    "这家",
    "那家",
    "这间",
    "那间",
    "这家店",
)


def _looks_like_comparison(text: str) -> bool:
    return any(hint in text for hint in _COMPARISON_HINTS)


def _recommendation_query_terms(text: str) -> list[str]:
    return _dedupe([hint for hint in _CATEGORY_HINTS if hint in text])


def _recommendation_scene_terms(text: str) -> list[str]:
    return _dedupe([hint for hint in _SCENE_HINTS if hint in text])


def _has_coupon_preference(text: str) -> bool:
    return any(hint in text for hint in ("最好有券", "有券更好", "有优惠更好", "有团购更好", * _COUPON_HINTS))


def _has_open_preference(text: str) -> bool:
    return any(hint in text for hint in ("现在营业", "营业中", "还营业", "开着", "开门"))


def _has_nearby_preference(text: str) -> bool:
    return any(hint in text for hint in ("附近", "周边", "别太远", "近一点", "离我近", "远不远"))


def extract_slots(text: str, top_intent: str) -> dict:
    """Extract typed slots from the user's utterance."""
    normalized_raw = normalize_text(text)
    normalised = _NOISE_RE.sub(" ", normalized_raw)
    mentions = _extract_merchant_mentions(normalized_raw)
    facets = _build_facet_specs(normalised)
    recommendation = _looks_like_recommendation(normalised)
    comparison = _looks_like_comparison(normalised)
    query_terms = _recommendation_query_terms(normalised)
    scene_terms = _recommendation_scene_terms(normalised)
    has_multi_facet = len(facets) > 1
    coupon_preferred = _has_coupon_preference(normalised)
    open_preferred = _has_open_preference(normalised)
    nearby_preferred = _has_nearby_preference(normalised)

    task_type: TaskType | None = None
    primary_task = ""
    need_context = False
    reference_mentions: list[str] = []

    if top_intent == "local_life":
        if recommendation:
            task_type = TaskType.recommendation
            primary_task = "recommendation"
            need_context = False
        elif comparison:
            task_type = TaskType.comparison
            primary_task = "comparison"
            reference_mentions = [hint for hint in _COMPARISON_REFERENCE_HINTS if hint in normalised]
            need_context = len(mentions) < 2 and not reference_mentions
        elif facets:
            task_type = TaskType.single_shop_query if has_multi_facet or any(
                isinstance(spec, dict) and spec.get("name") in {Facet.open_status, Facet.distance}
                for spec in facets
            ) else TaskType.coupon_query
            primary_task = "multi_facet_query" if len(facets) > 1 or task_type == TaskType.single_shop_query else "coupon_query"
            need_context = not bool(mentions)
        elif mentions:
            task_type = TaskType.single_shop_query
            primary_task = "single_shop_query"

    soft_preferences: dict[str, object] = {}
    ranking_signals: dict[str, object] = {}
    if recommendation:
        if scene_terms:
            soft_preferences["scene_terms"] = scene_terms
            ranking_signals["scene_terms"] = scene_terms
        if query_terms:
            ranking_signals["query_terms"] = query_terms
            ranking_signals["category"] = query_terms[0]
        if open_preferred:
            soft_preferences["open_now_preferred"] = True
            ranking_signals["open_now_preferred"] = True
        if coupon_preferred:
            soft_preferences["coupon_preferred"] = True
            ranking_signals["coupon_preferred"] = True
        if nearby_preferred:
            soft_preferences["nearby_preferred"] = True
            ranking_signals["nearby_preferred"] = True
    if comparison and not reference_mentions:
        reference_mentions = [hint for hint in _COMPARISON_REFERENCE_HINTS if hint in normalised]

    return {
        "top_intent": top_intent,
        "task_type": task_type,
        "primary_task": primary_task,
        "facets": facets,
        "merchant_mentions": mentions,
        "reference_mentions": reference_mentions if comparison else [],
        "hard_constraints": {},
        "soft_preferences": soft_preferences,
        "ranking_signals": ranking_signals,
        "follow_up": None,
        "confidence": 0.9 if mentions else 0.6,
        "need_context": need_context,
    }
