"""Fallback semantic slot extraction for the local-life domain."""

from __future__ import annotations

import re

from ..domain.enums import Facet, TaskType
from ..input.normalizer import normalize_text
from ..tools.mock_tools import _all_shops

_COUPON_HINTS = (
    "\u6709\u5238",
    "\u4f18\u60e0\u5238",
    "\u4ee3\u91d1\u5238",
    "\u6298\u6263\u5238",
    "\u4f18\u60e0",
    "\u9886\u5238",
    "\u53ef\u7528\u5238",
    "\u56e2\u8d2d",
)
_OPEN_HINTS = (
    "\u8425\u4e1a",
    "\u5f00\u95e8",
    "\u5173\u95e8",
    "\u6253\u70ca",
    "\u505c\u4e1a",
    "\u73b0\u5728\u8425\u4e1a",
    "\u8fd8\u8425\u4e1a",
)
_DISTANCE_HINTS = (
    "\u8ddd\u79bb",
    "\u591a\u8fdc",
    "\u8fd1\u4e0d\u8fd1",
    "\u8fdc\u4e0d\u8fdc",
    "\u51e0\u516c\u91cc",
    "\u8def\u7a0b",
    "\u79bb\u8fd9",
    "\u79bb\u6211",
    "\u9644\u8fd1",
)
_OPTIONAL_HINTS = (
    "\u987a\u4fbf",
    "\u6700\u597d",
    "\u4e5f\u770b",
    "\u4e00\u8d77\u770b",
    "\u518d\u770b",
    "\u9644\u5e26",
)
_RECOMMENDATION_HINTS = (
    "\u63a8\u8350",
    "\u9644\u8fd1",
    "\u5468\u8fb9",
    "\u627e\u51e0\u5bb6",
    "\u60f3\u627e",
    "\u6709\u6ca1\u6709\u9002\u5408",
)
_CATEGORY_HINTS = (
    "\u706b\u9505",
    "\u9910\u5385",
    "\u996d\u9986",
    "\u5496\u5561",
    "\u5976\u8336",
    "\u8336\u996e",
    "\u70e7\u70e4",
    "\u70e7\u8089",
    "\u5feb\u9910",
    "\u4e2d\u9910",
    "\u897f\u9910",
    "\u65e5\u6599",
    "\u751c\u54c1",
)
_SCENE_HINTS = (
    "\u7ea6\u4f1a",
    "\u670b\u53cb\u805a\u9910",
    "\u805a\u9910",
    "\u5bb6\u5ead\u805a\u9910",
    "\u5546\u52a1",
    "\u8bf7\u5ba2",
    "\u591c\u5bb5",
)
_COMPARISON_HINTS = (
    "\u5bf9\u6bd4",
    "\u6bd4\u8f83",
    "\u6bd4\u4e00\u6bd4",
    "\u6bd4\u5462",
    "\u54ea\u4e2a\u66f4",
    "\u54ea\u5bb6\u66f4",
    "\u8c01\u66f4",
    "\u66f4\u597d",
    "\u66f4\u4f18",
    "\u8fd9\u4e09\u5bb6",
    "\u8fd9\u51e0\u5bb6",
)
_ORDINAL_ALIASES = {
    "\u7b2c\u4e00\u5bb6": "\u7b2c\u4e00\u5bb6",
    "\u7b2c\u4e8c\u5bb6": "\u7b2c\u4e8c\u5bb6",
    "\u7b2c\u4e09\u5bb6": "\u7b2c\u4e09\u5bb6",
    "\u7b2c\u4e00\u4e2a": "\u7b2c\u4e00\u5bb6",
    "\u7b2c\u4e8c\u4e2a": "\u7b2c\u4e8c\u5bb6",
    "\u7b2c\u4e09\u4e2a": "\u7b2c\u4e09\u5bb6",
    "\u7b2c\u4e00\u95f4": "\u7b2c\u4e00\u5bb6",
    "\u7b2c\u4e8c\u95f4": "\u7b2c\u4e8c\u5bb6",
    "\u7b2c\u4e09\u95f4": "\u7b2c\u4e09\u5bb6",
}
_DEICTIC_HINTS = (
    "\u8fd9\u5bb6",
    "\u90a3\u5bb6",
    "\u8fd9\u95f4",
    "\u90a3\u95f4",
    "\u8fd9\u4e09\u5bb6",
    "\u8fd9\u51e0\u5bb6",
)
_NOISE_RE = re.compile(r"[\s,\.\?!;:()\[\]{}<>/\\|\"'\u3001\uff0c\u3002\uff01\uff1f\uff1b\uff1a]+")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _brand_prefix(name: str) -> str:
    cleaned = normalize_text(name).strip()
    if "(" in cleaned:
        return cleaned.split("(", 1)[0].strip()
    return cleaned


def _shop_tokens() -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for shop in _all_shops():
        canonical = normalize_text(shop.get("shop_name", "")).strip()
        if canonical:
            tokens.append((canonical, canonical))
            brand = _brand_prefix(canonical)
            if brand and brand != canonical:
                tokens.append((brand, brand))
        alias = normalize_text(shop.get("alias", "")).strip()
        if alias:
            tokens.append((alias, canonical or alias))
        for alias_item in shop.get("aliases", []) or []:
            cleaned = normalize_text(alias_item).strip()
            if cleaned:
                tokens.append((cleaned, canonical or cleaned))
    tokens.sort(key=lambda item: len(item[0]), reverse=True)
    return tokens


def _extract_merchant_mentions(text: str) -> list[str]:
    normalized = normalize_text(text)
    mentions: list[str] = []
    for token, canonical in _shop_tokens():
        if token and token in normalized:
            mentions.append(canonical)
    return _dedupe(mentions)


def _extract_ordinals(text: str) -> list[str]:
    hits = [canonical for token, canonical in _ORDINAL_ALIASES.items() if token in text]
    digits = []
    if "1" in text:
        digits.append("\u7b2c\u4e00\u5bb6")
    if "2" in text:
        digits.append("\u7b2c\u4e8c\u5bb6")
    if "3" in text:
        digits.append("\u7b2c\u4e09\u5bb6")
    return _dedupe(hits + digits)


def _extract_deictic(text: str) -> list[str]:
    return _dedupe([hint for hint in _DEICTIC_HINTS if hint in text])


def _facet_positions(text: str) -> list[tuple[int, str]]:
    positions: list[tuple[int, str]] = []
    for facet_name, hints in (
        (Facet.coupon.value, _COUPON_HINTS),
        (Facet.open_status.value, _OPEN_HINTS),
        (Facet.distance.value, _DISTANCE_HINTS),
    ):
        indexes = [text.find(hint) for hint in hints if hint in text]
        if indexes:
            positions.append((min(indexes), facet_name))
    positions.sort(key=lambda item: item[0])
    return positions


def _build_facets(text: str) -> list[dict[str, object]]:
    ordered = _facet_positions(text)
    optional_mode = any(hint in text for hint in _OPTIONAL_HINTS)
    facets: list[dict[str, object]] = []
    for index, (_pos, facet_name) in enumerate(ordered):
        required = not optional_mode or index == 0
        facets.append({"name": facet_name, "required": required})
    return facets


def _extract_hints(text: str, hints: tuple[str, ...]) -> list[str]:
    return _dedupe([hint for hint in hints if hint in text])


def _comparison_focus(text: str) -> str:
    for facet_name, hints in (
        ("coupon", _COUPON_HINTS),
        ("open_status", _OPEN_HINTS),
        ("distance", _DISTANCE_HINTS),
        ("rating", ("\u8bc4\u5206", "\u53e3\u7891", "\u8bc4\u4ef7")),
        ("overall", ("\u54ea\u4e2a\u66f4\u597d", "\u54ea\u5bb6\u66f4\u597d", "\u8c01\u66f4\u597d")),
    ):
        if any(hint in text for hint in hints):
            return facet_name
    return ""


def _comparison_focused_facets(text: str) -> list[str]:
    facets: list[str] = []
    for facet_name, hints in (
        ("coupon", _COUPON_HINTS),
        ("open_status", _OPEN_HINTS),
        ("distance", _DISTANCE_HINTS),
        ("rating", ("\u8bc4\u5206", "\u53e3\u7891", "\u8bc4\u4ef7")),
    ):
        if any(hint in text for hint in hints):
            facets.append(facet_name)
    if not facets and any(hint in text for hint in ("\u66f4\u597d", "\u66f4\u4f18", "\u54ea\u4e2a\u597d", "\u54ea\u5bb6\u597d")):
        facets.append("overall")
    return _dedupe(facets)


def _looks_like_comparison(
    text: str,
    mentions: list[str],
    ordinal_references: list[str],
    deictic_references: list[str],
) -> bool:
    if any(hint in text for hint in _COMPARISON_HINTS):
        return True
    if "\u548c" in text and "\u6bd4" in text and (mentions or ordinal_references or deictic_references):
        return True
    if "\u6bd4" in text and len(mentions) + len(ordinal_references) + len(deictic_references) >= 2:
        return True
    return False


def _looks_like_recommendation(text: str, query_terms: list[str], scene_terms: list[str]) -> bool:
    if any(hint in text for hint in _RECOMMENDATION_HINTS):
        return True
    return bool(query_terms and ("\u9644\u8fd1" in text or "\u63a8\u8350" in text or scene_terms))


def _recommendation_query_terms(text: str) -> list[str]:
    return _extract_hints(text, _CATEGORY_HINTS)


def _recommendation_scene_terms(text: str) -> list[str]:
    return _extract_hints(text, _SCENE_HINTS)


def _has_coupon_preference(text: str) -> bool:
    return any(hint in text for hint in _COUPON_HINTS)


def _has_open_preference(text: str) -> bool:
    return any(hint in text for hint in _OPEN_HINTS)


def _has_nearby_preference(text: str) -> bool:
    return any(hint in text for hint in ("\u9644\u8fd1", "\u5468\u8fb9", "\u8fd1\u4e00\u70b9", "\u522b\u592a\u8fdc", "\u79bb\u6211\u8fd1"))


def _build_comparison_targets(
    mentions: list[str],
    ordinal_references: list[str],
    deictic_references: list[str],
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for mention in mentions:
        targets.append({"shop_name": mention, "reference": "explicit", "source_text": mention})
    for token in ordinal_references:
        targets.append({"shop_name": token, "reference": "ordinal", "source_text": token})
    for token in deictic_references:
        targets.append({"shop_name": token, "reference": "deictic", "source_text": token})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in targets:
        key = f"{item.get('reference', '')}|{item.get('shop_name', '')}|{item.get('source_text', '')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def extract_slots(text: str, top_intent: str) -> dict:
    normalized = normalize_text(text)
    simplified = _NOISE_RE.sub(" ", normalized)
    mentions = _extract_merchant_mentions(normalized)
    ordinal_references = _extract_ordinals(normalized)
    deictic_references = _extract_deictic(normalized)
    facets = _build_facets(simplified)
    query_terms = _recommendation_query_terms(simplified)
    scene_terms = _recommendation_scene_terms(simplified)
    comparison = _looks_like_comparison(simplified, mentions, ordinal_references, deictic_references)
    recommendation = _looks_like_recommendation(simplified, query_terms, scene_terms) and not comparison

    task_type: TaskType | None = None
    primary_task = ""
    need_context = False
    reference_mentions: list[str] = []
    comparison_targets: list[dict[str, str]] = []
    focused_facets: list[str] = []
    comparison_focus = ""

    if top_intent == "local_life":
        if comparison:
            task_type = TaskType.comparison
            primary_task = "comparison"
            reference_mentions = _dedupe(ordinal_references + deictic_references)
            comparison_targets = _build_comparison_targets(mentions, ordinal_references, deictic_references)
            focused_facets = _comparison_focused_facets(simplified)
            comparison_focus = _comparison_focus(simplified)
            need_context = not bool(mentions or ordinal_references or deictic_references)
        elif recommendation:
            task_type = TaskType.recommendation
            primary_task = "recommendation"
        elif facets:
            task_type = (
                TaskType.coupon_query
                if len(facets) == 1 and facets[0]["name"] == Facet.coupon.value
                else TaskType.single_shop_query
            )
            primary_task = "coupon_query" if task_type == TaskType.coupon_query else "single_shop_query"
            need_context = not bool(mentions or ordinal_references or deictic_references)
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
        if _has_open_preference(simplified):
            soft_preferences["open_now_preferred"] = True
            ranking_signals["open_now_preferred"] = True
        if _has_coupon_preference(simplified):
            soft_preferences["coupon_preferred"] = True
            ranking_signals["coupon_preferred"] = True
        if _has_nearby_preference(simplified):
            soft_preferences["nearby_preferred"] = True
            ranking_signals["nearby_preferred"] = True

    confidence = 0.9 if task_type is not None else 0.6
    if mentions or ordinal_references or deictic_references:
        confidence = max(confidence, 0.85)

    return {
        "top_intent": top_intent,
        "task_type": task_type,
        "primary_task": primary_task,
        "facets": facets,
        "merchant_mentions": mentions,
        "reference_mentions": reference_mentions,
        "comparison_targets": comparison_targets,
        "ordinal_references": ordinal_references,
        "deictic_references": deictic_references,
        "focused_facets": focused_facets,
        "comparison_focus": comparison_focus,
        "hard_constraints": {},
        "soft_preferences": soft_preferences,
        "ranking_signals": ranking_signals,
        "follow_up": None,
        "confidence": confidence,
        "need_context": need_context,
    }
