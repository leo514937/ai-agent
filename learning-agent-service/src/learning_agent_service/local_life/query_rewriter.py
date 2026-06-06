from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text, coerce_float as _coerce_float

from .schemas import LocationNorm, QueryUnderstandingResult, TimeNorm

_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("家常菜", "家常菜"),
    ("私房菜", "家常菜"),
    ("火锅", "火锅"),
    ("粤菜", "粤菜"),
    ("川菜", "川菜"),
    ("烧烤", "烧烤"),
    ("烤肉", "烧烤"),
    ("日料", "日料"),
    ("餐厅", "餐厅"),
    ("饭店", "餐厅"),
)

_CITY_NAMES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "重庆",
    "南京",
    "苏州",
    "武汉",
    "西安",
    "天津",
    "长沙",
    "厦门",
    "青岛",
    "宁波",
    "郑州",
)

_SHOP_QUERY_KEYS = ("selected_shop_name", "shop_name", "current_shop")

def _merge_text_values(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        items = value if isinstance(value, (list, tuple, set)) else (value,)
        for item in items:
            text = _clean_text(item)
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _extract_category(text: str, client_context: Mapping[str, Any], session_context: Mapping[str, Any]) -> str | None:
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword in text:
            return category
    for key in ("current_category", "category"):
        value = client_context.get(key) or session_context.get(key)
        if value:
            return str(value)
    return None


def _extract_shop_query(client_context: Mapping[str, Any], session_context: Mapping[str, Any]) -> str | None:
    for key in _SHOP_QUERY_KEYS:
        value = client_context.get(key) or session_context.get(key)
        if value:
            return str(value)
    return None


def _now_from_context(client_context: Mapping[str, Any], session_context: Mapping[str, Any]) -> datetime:
    for candidate in (
        client_context.get("timestamp"),
        client_context.get("current_time"),
        session_context.get("timestamp"),
        session_context.get("current_time"),
    ):
        parsed = _parse_timestamp(candidate)
        if parsed is not None:
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _extract_city(text: str, client_context: Mapping[str, Any], session_context: Mapping[str, Any]) -> str | None:
    for key in ("city", "current_city", "location_city"):
        value = client_context.get(key) or session_context.get(key)
        if value:
            return str(value)
    for city in _CITY_NAMES:
        if city in text:
            return city
    return None


def _extract_location(text: str, client_context: Mapping[str, Any], session_context: Mapping[str, Any]) -> LocationNorm:
    location_data = {}
    for key in ("location", "current_location", "user_location"):
        candidate = client_context.get(key) or session_context.get(key)
        if isinstance(candidate, Mapping):
            location_data = dict(candidate)
            break
    radius_km = 3.0
    if any(keyword in text for keyword in ("很近", "近一点", "更近", "附近", "离我近")):
        radius_km = 3.0
    if "步行" in text or "地铁口" in text:
        radius_km = 2.0
    if "周边" in text:
        radius_km = 5.0
    return LocationNorm(
        type="near_user",
        city=location_data.get("city") or client_context.get("city") or session_context.get("current_city") or session_context.get("city"),
        lat=_coerce_float(location_data.get("lat") or location_data.get("latitude") or client_context.get("lat")),
        lng=_coerce_float(location_data.get("lng") or location_data.get("longitude") or client_context.get("lng")),
        radius_km=radius_km,
    )

def _extract_time(text: str, now: datetime) -> TimeNorm:
    lowered = text.replace(" ", "")
    if any(token in lowered for token in ("今晚", "今天晚上", "今晚吃饭")):
        return TimeNorm(type="tonight", date=now.date().isoformat(), meal_period="dinner")
    if any(token in lowered for token in ("明晚", "明天晚上")):
        return TimeNorm(type="tomorrow_night", date=(now + timedelta(days=1)).date().isoformat(), meal_period="dinner")
    if any(token in lowered for token in ("午饭", "午餐", "中午")):
        return TimeNorm(type="lunch", date=now.date().isoformat(), meal_period="lunch")
    if any(token in lowered for token in ("晚饭", "晚餐", "吃饭")):
        return TimeNorm(type="dinner", date=now.date().isoformat(), meal_period="dinner")
    return TimeNorm()


def _meal_period_label(time_norm: TimeNorm) -> str | None:
    if time_norm.type == "tonight":
        return "今晚"
    if time_norm.type == "tomorrow_night":
        return "明晚"
    if time_norm.meal_period == "lunch":
        return "午餐"
    if time_norm.meal_period == "dinner":
        return "晚餐"
    return None


def _scene_label(scene: str | None) -> str | None:
    if scene == "family_dinner":
        return "家庭聚餐"
    if scene == "date":
        return "约会"
    if scene == "gathering":
        return "聚餐"
    return None


def _extract_price(text: str) -> tuple[float | None, float | None, float | None, list[str]]:
    normalized = text.replace(" ", "")
    rewritten: list[str] = []
    target = None
    min_price = None
    max_price = None
    match = re.search(r"人均(\d{2,4})(?:左右|上下|附近)?", normalized)
    if match:
        target = float(match.group(1))
        min_price = max(0.0, target - 50.0)
        max_price = target + 50.0
        rewritten.append(f"人均约{int(target)}元")
    range_match = re.search(r"(\d{2,4})[-~到](\d{2,4})", normalized)
    if range_match:
        min_price = float(min(range_match.groups(), key=lambda item: float(item)))
        max_price = float(max(range_match.groups(), key=lambda item: float(item)))
        target = (min_price + max_price) / 2
        rewritten.append(f"人均范围{int(min_price)}-{int(max_price)}元")
    if "100以内" in normalized or "100块以内" in normalized:
        min_price = 0.0
        max_price = 100.0
        target = 90.0
        rewritten.append("人均100以内")
    if "150以内" in normalized:
        min_price = 0.0
        max_price = 150.0
        target = 130.0
        rewritten.append("人均150以内")
    if "200以内" in normalized:
        min_price = 0.0
        max_price = 200.0
        target = 180.0
        rewritten.append("人均200以内")
    if "便宜" in normalized:
        min_price = 0.0 if min_price is None else min_price
        max_price = 150.0 if max_price is None else min(max_price, 150.0)
        target = target or 120.0
        rewritten.append("价格偏友好")
    return min_price, max_price, target, rewritten


def _extract_preferences(text: str) -> tuple[list[str], list[str], list[str]]:
    lowered = text.replace(" ", "")
    preferences: list[str] = []
    avoid: list[str] = []
    rewritten: list[str] = []
    if any(token in lowered for token in ("别太吵", "安静", "安静点")):
        preferences.append("quiet")
        rewritten.append("环境安静")
    if any(token in lowered for token in ("有停车", "能停车", "停车")):
        preferences.append("parking_available")
        rewritten.append("有停车")
    if any(token in lowered for token in ("适合爸妈", "带爸妈", "长辈", "父母", "老人")):
        preferences.append("elder_friendly")
        preferences.append("family_dinner")
        rewritten.append("适合长辈")
    if any(token in lowered for token in ("包间", "小包间")):
        preferences.append("private_room")
        rewritten.append("有包间")
    if any(token in lowered for token in ("清淡", "少油", "少辣")):
        preferences.append("light_taste")
        rewritten.append("口味清淡")
    if any(token in lowered for token in ("不要网红店", "别太网红", "不要热门", "不要排队", "少排队")):
        avoid.append("queue_risk")
        avoid.append("busy")
        rewritten.append("避开网红排队店")
    if "辣" in lowered and "火锅" not in lowered:
        preferences.append("spicy_friendly")
    return preferences, avoid, rewritten


def _extract_scene(text: str) -> str | None:
    lowered = text.replace(" ", "")
    if any(token in lowered for token in ("爸妈", "父母", "长辈", "老人")):
        return "family_dinner"
    if any(token in lowered for token in ("约会", "情侣")):
        return "date"
    if any(token in lowered for token in ("聚餐", "团建", "聚会")):
        return "gathering"
    return None


def normalize_query(
    raw_query: str,
    *,
    client_context: Mapping[str, Any] | None = None,
    session_context: Mapping[str, Any] | None = None,
    model_hint: Mapping[str, Any] | None = None,
) -> QueryUnderstandingResult:
    client_context = _as_mapping(client_context)
    session_context = _as_mapping(session_context)
    model_hint = _as_mapping(model_hint)
    model_location = _as_mapping(model_hint.get("location"))
    model_time = _as_mapping(model_hint.get("time"))
    model_price = _as_mapping(model_hint.get("price"))
    text = (raw_query or "").strip()
    compact = re.sub(r"\s+", "", text)
    now = _now_from_context(client_context, session_context)
    city = _extract_city(compact, client_context, session_context)
    category = _extract_category(compact, client_context, session_context)
    shop_query = _extract_shop_query(client_context, session_context)
    location_norm = _extract_location(compact, client_context, session_context)
    if city and not location_norm.city:
        location_norm.city = city
    time_norm = _extract_time(compact, now)
    min_price, max_price, target_price, price_rewrite = _extract_price(compact)
    preferences, avoid, preference_rewrite = _extract_preferences(compact)
    scene = _extract_scene(compact)

    model_city = _clean_text(model_hint.get("city")) or _clean_text(model_location.get("city"))
    model_category = _clean_text(model_hint.get("category"))
    model_shop_query = _clean_text(model_hint.get("shop_query"))
    model_scene = _clean_text(model_hint.get("scene"))
    model_normalized_query = _clean_text(model_hint.get("normalized_query"))
    model_semantic_query = _clean_text(model_hint.get("semantic_query"))
    model_keyword_query = _clean_text(model_hint.get("keyword_query"))
    model_constraints = _merge_text_values(model_hint.get("rewritten_constraints"))
    model_preferences = _merge_text_values(model_hint.get("preferences"))
    model_avoid = _merge_text_values(model_hint.get("avoid"))
    model_route_reason = _clean_text(model_hint.get("route_reason"))
    model_confidence = 0.0
    try:
        model_confidence = float(model_hint.get("confidence", 0.0) or 0.0)
    except Exception:
        model_confidence = 0.0

    if model_city:
        city = model_city
    if model_category:
        category = model_category
    if model_shop_query:
        shop_query = model_shop_query
    if model_scene:
        scene = model_scene

    if model_location:
        location_norm = location_norm.model_copy(
            update={
                "city": _clean_text(model_location.get("city")) or location_norm.city or city,
                "lat": _coerce_float(model_location.get("lat") or model_location.get("latitude")) or location_norm.lat,
                "lng": _coerce_float(model_location.get("lng") or model_location.get("longitude")) or location_norm.lng,
                "radius_km": _coerce_float(model_location.get("radius_km") or model_location.get("radiusKm")) or location_norm.radius_km,
            }
        )
    if city and not location_norm.city:
        location_norm.city = city
    if model_time:
        time_norm = time_norm.model_copy(
            update={
                "type": _clean_text(model_time.get("type")) or time_norm.type,
                "date": _clean_text(model_time.get("date")) or time_norm.date,
                "meal_period": _clean_text(model_time.get("meal_period") or model_time.get("mealPeriod")) or time_norm.meal_period,
                "preferred_time": _clean_text(model_time.get("preferred_time") or model_time.get("preferredTime")) or time_norm.preferred_time,
            }
        )
    if model_price:
        min_price = min_price if min_price is not None else _coerce_float(model_price.get("min") or model_price.get("per_person_min"))
        max_price = max_price if max_price is not None else _coerce_float(model_price.get("max") or model_price.get("per_person_max"))
        target_price = target_price if target_price is not None else _coerce_float(model_price.get("target"))
    preferences = list(dict.fromkeys([*preferences, *model_preferences]))
    avoid = list(dict.fromkeys([*avoid, *model_avoid]))

    location_phrase = f"{city}附近" if city else "用户当前位置附近"
    time_phrase = _meal_period_label(time_norm)
    scene_phrase = _scene_label(scene)
    category_phrase = category if category and category != "餐厅" else None
    price_phrase: str | None = None
    if min_price is not None and max_price is not None:
        if min_price == max_price:
            price_phrase = f"人均{int(min_price)}元"
        elif target_price is not None and abs(target_price * 2 - (min_price + max_price)) < 1e-6:
            price_phrase = f"人均约{int(target_price)}元"
        else:
            price_phrase = f"人均{int(min_price)}-{int(max_price)}元"
    elif max_price is not None:
        price_phrase = f"人均{int(max_price)}元以内"

    parts: list[str] = []
    if shop_query:
        parts.append(shop_query)
    parts.append(location_phrase)
    if time_phrase:
        parts.append(time_phrase)
    if scene_phrase:
        parts.append(scene_phrase)
    if preferences:
        parts.extend(
            {
                "quiet": "环境安静",
                "parking_available": "有停车",
                "elder_friendly": "适合长辈",
                "family_dinner": "家庭聚餐",
                "private_room": "有包间",
                "light_taste": "口味清淡",
                "spicy_friendly": "口味偏辣",
            }.get(item, item)
            for item in preferences
        )
    if category_phrase:
        parts.append(category_phrase)
    if price_phrase:
        parts.append(price_phrase)
    normalized_query = model_normalized_query or ("搜索" + "、".join(parts) + "的餐厅")

    semantic_parts = []
    if shop_query:
        semantic_parts.append(f"围绕{shop_query}")
    if scene_phrase:
        semantic_parts.append(scene_phrase)
    if time_phrase:
        semantic_parts.append(time_phrase)
    if "quiet" in preferences:
        semantic_parts.append("环境安静")
    if "parking_available" in preferences:
        semantic_parts.append("有停车")
    if "elder_friendly" in preferences:
        semantic_parts.append("适合长辈")
    if "private_room" in preferences:
        semantic_parts.append("有包间")
    if "light_taste" in preferences:
        semantic_parts.append("口味清淡")
    if "spicy_friendly" in preferences:
        semantic_parts.append("口味偏辣")
    if category_phrase:
        semantic_parts.append(category_phrase)
    if price_phrase:
        semantic_parts.append(price_phrase)
    semantic_parts.append("附近餐厅")

    semantic_query = model_semantic_query or " ".join(part for part in semantic_parts if part)
    keyword_parts = [
        shop_query,
        city,
        location_phrase if city else "附近",
        time_phrase,
        scene_phrase,
        category_phrase,
        *(preference_rewrite or []),
        *model_preferences,
        *(price_rewrite or []),
        *model_constraints,
    ]
    keyword_query = model_keyword_query or " ".join(part for part in keyword_parts if part)
    rewritten_constraints = [*preference_rewrite, *model_preferences, *price_rewrite, *model_constraints]
    if scene:
        rewritten_constraints.append(f"场景:{scene_phrase or scene}")
    if city:
        rewritten_constraints.append(f"城市:{city}")
    if time_norm.type:
        rewritten_constraints.append(f"时间:{time_phrase or time_norm.type}")
    if category_phrase:
        rewritten_constraints.append(f"类别:{category_phrase}")
    if shop_query:
        rewritten_constraints.append(f"店名:{shop_query}")
    confidence = min(0.98, 0.35 + 0.1 * len(rewritten_constraints))
    confidence = min(0.98, max(confidence, model_confidence))
    return QueryUnderstandingResult(
        normalized_query=normalized_query,
        semantic_query=semantic_query.strip(),
        keyword_query=keyword_query.strip(),
        time_norm=time_norm,
        location_norm=location_norm,
        rewritten_constraints=rewritten_constraints,
        confidence=confidence,
        extra={
            "raw_query": text,
            "client_context_keys": sorted(client_context.keys()),
            "city": city,
            "category": category,
            "shop_query": shop_query,
            "scene": scene,
            "time": time_norm.model_dump(mode="json"),
            "location": location_norm.model_dump(mode="json"),
            "price": {
                "min": min_price,
                "max": max_price,
                "target": target_price,
            },
            "preferences": preferences,
            "avoid": avoid,
            "model_hint_used": bool(model_hint),
            "model_hint": dict(model_hint),
            "model_route_reason": model_route_reason,
            "rewrite_source": "model+rule" if model_hint else "rule",
        },
    )
