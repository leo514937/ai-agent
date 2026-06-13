from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
import re

FollowUpKind = Literal[
    "none",
    "entity_reference",
    "intent_ellipsis",
    "constraint_inheritance",
    "comparison_completion",
]


@dataclass(frozen=True)
class ShopReference:
    name: str | None = None
    shop_id: int | None = None
    source: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class FollowUpContextResult:
    follow_up_kind: FollowUpKind = "none"
    anchor_shop: ShopReference | None = None
    comparison_targets: list[ShopReference] = field(default_factory=list)
    inherited_constraints: dict[str, Any] = field(default_factory=dict)
    promoted_intent: str | None = None
    confidence: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["comparison_targets"] = [asdict(item) for item in self.comparison_targets]
        payload["anchor_shop"] = asdict(self.anchor_shop) if self.anchor_shop is not None else None
        return payload


_PRONOUN_TOKENS = ("这家", "这店", "这间", "它", "刚才那家", "刚才那个", "这商家", "这个商家")
_CHEAP_TOKENS = ("便宜", "再便宜", "便宜一点", "更便宜", "便宜点", "划算", "省钱")
_CATEGORY_HINTS = (
    ("川菜", "川菜"),
    ("火锅", "火锅"),
    ("粤菜", "粤菜"),
    ("日料", "日料"),
    ("烧烤", "烧烤"),
    ("餐厅", "餐厅"),
    ("饭店", "餐厅"),
)
_CITY_HINTS = ("北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "南京", "苏州", "武汉", "西安", "天津")
_SCENE_HINTS = (
    ("家庭聚餐", "family_dinner"),
    ("爸妈", "family_dinner"),
    ("父母", "family_dinner"),
    ("长辈", "family_dinner"),
    ("老人", "family_dinner"),
    ("约会", "date"),
    ("情侣", "date"),
    ("聚餐", "gathering"),
    ("聚会", "gathering"),
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _clean_text(value).replace(" ", "")


def _to_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _current_shop_ref(session_context: dict[str, Any]) -> ShopReference | None:
    anchor = session_context.get("current_shop_anchor")
    if isinstance(anchor, dict):
        name = _clean_text(anchor.get("name") or anchor.get("shop_name"))
        shop_id = _to_int(anchor.get("shop_id") or anchor.get("id"))
        if name or shop_id is not None:
            return ShopReference(name=name or None, shop_id=shop_id, source="current_shop_anchor", confidence=0.9)

    name = _clean_text(
        session_context.get("current_shop")
        or session_context.get("selected_shop_name")
        or session_context.get("shopName")
        or session_context.get("shop_name")
    )
    shop_id = _to_int(
        session_context.get("selected_shop_id")
        or session_context.get("current_shop_id")
        or session_context.get("shopId")
        or session_context.get("shop_id")
    )
    if name or shop_id is not None:
        return ShopReference(name=name or None, shop_id=shop_id, source="session", confidence=0.8)
    return None


def _extract_comparison_target(text: str) -> str | None:
    compact = _norm(text)
    if not compact:
        return None

    match = re.search(r"(?:和|跟|与)(?P<target>.+?)(?:比|比较|对比)", compact)
    if match:
        candidate = match.group("target").strip(" 、,;；?？。.!！")
        if candidate:
            return candidate

    if compact.endswith(("比呢", "比吗", "比吧", "比呀")):
        candidate = compact.split("比", 1)[-1].strip(" 呢吗吧呀?？。.!！，,;；")
        if candidate and len(candidate) <= 20:
            return candidate
    return None


def _extract_constraint_hints(text: str, session_context: dict[str, Any]) -> dict[str, Any]:
    compact = _norm(text)
    hints: dict[str, Any] = {}

    for keyword, category in _CATEGORY_HINTS:
        if keyword in compact:
            hints["category"] = category
            break

    for keyword, scene in _SCENE_HINTS:
        if keyword in compact:
            hints["scene"] = scene
            break

    for city in _CITY_HINTS:
        if city in compact:
            hints["city"] = city
            break

    if any(token in compact for token in _CHEAP_TOKENS):
        hints["price"] = {"kind": "budget", "max": 150}

    current_city = _clean_text(session_context.get("current_city") or session_context.get("city"))
    if current_city and "city" not in hints:
        hints["city"] = current_city

    current_scene = _clean_text(session_context.get("current_scene") or session_context.get("scene"))
    if current_scene and "scene" not in hints:
        hints["scene"] = current_scene

    current_constraints = session_context.get("current_constraints")
    if isinstance(current_constraints, dict):
        for key in ("category", "scene", "city", "price", "location", "preferences", "avoid"):
            value = current_constraints.get(key)
            if value not in (None, "", [], {}, ()):
                hints.setdefault(key, value)

    return hints


def recover_follow_up_context(
    raw_query: str,
    *,
    client_context: dict[str, Any] | None = None,
    session_context: dict[str, Any] | None = None,
) -> FollowUpContextResult:
    client_context = dict(client_context or {})
    session_context = dict(session_context or {})
    query = _clean_text(raw_query)
    compact = _norm(query)
    anchor_shop = _current_shop_ref(session_context)
    comparison_target = _extract_comparison_target(query)
    constraint_hints = _extract_constraint_hints(query, session_context)

    has_followup_marker = any(token in compact for token in ("呢", "吗", "吗", "吧", "呀", "比")) or any(token in compact for token in _PRONOUN_TOKENS)

    follow_up_kind: FollowUpKind = "none"
    promoted_intent: str | None = None
    confidence = 0.0

    if comparison_target:
        follow_up_kind = "comparison_completion"
        promoted_intent = "restaurant_comparison"
        confidence = 0.95
    elif any(token in compact for token in _CHEAP_TOKENS) and has_followup_marker:
        follow_up_kind = "intent_ellipsis"
        promoted_intent = "restaurant_recommendation"
        confidence = 0.88
    elif (
        any(token in compact for token, _ in _CATEGORY_HINTS)
        or any(token in compact for token, _ in _SCENE_HINTS)
        or any(token in compact for token in _CITY_HINTS)
    ) and has_followup_marker:
        follow_up_kind = "constraint_inheritance"
        promoted_intent = "restaurant_recommendation"
        confidence = 0.82
    elif any(token in compact for token in _PRONOUN_TOKENS):
        follow_up_kind = "entity_reference"
        promoted_intent = "restaurant_detail"
        confidence = 0.92

    comparison_targets: list[ShopReference] = []
    if comparison_target:
        comparison_targets.append(ShopReference(name=comparison_target, source="current_query", confidence=0.9))

    if follow_up_kind in {"intent_ellipsis", "constraint_inheritance", "comparison_completion"} and anchor_shop is None:
        anchor_shop = _current_shop_ref(session_context)

    details = {
        "query": query,
        "client_context_keys": sorted(client_context.keys()),
        "session_has_anchor": bool(anchor_shop),
        "explicit_comparison_target": comparison_target,
    }
    if comparison_targets:
        details["comparison_targets"] = [asdict(item) for item in comparison_targets]

    return FollowUpContextResult(
        follow_up_kind=follow_up_kind,
        anchor_shop=anchor_shop,
        comparison_targets=comparison_targets,
        inherited_constraints=constraint_hints,
        promoted_intent=promoted_intent,
        confidence=confidence,
        details=details,
    )
