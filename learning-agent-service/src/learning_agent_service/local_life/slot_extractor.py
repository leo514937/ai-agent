from __future__ import annotations

from typing import Any, Mapping, Optional

from .schemas import (
    ClarificationDecision,
    LocalLifeIntentType,
    LocalLifeSlots,
    LocationNorm,
    PriceNorm,
    QueryUnderstandingResult,
    SuggestedReply,
    TimeNorm,
)

_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("火锅", "火锅"),
    ("粤菜", "粤菜"),
    ("川菜", "川菜"),
    ("烧烤", "烧烤"),
    ("日料", "日料"),
    ("家常菜", "家常菜"),
    ("私房菜", "家常菜"),
    ("餐厅", "餐厅"),
    ("饭店", "餐厅"),
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


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


def _coerce_intent(value: Any) -> Optional[LocalLifeIntentType]:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "recommend": LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        "restaurant_recommendation": LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        "local_life_recommendation": LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        "compare": LocalLifeIntentType.RESTAURANT_COMPARISON,
        "comparison": LocalLifeIntentType.RESTAURANT_COMPARISON,
        "restaurant_comparison": LocalLifeIntentType.RESTAURANT_COMPARISON,
        "coupon": LocalLifeIntentType.COUPON,
        "restaurant_coupon": LocalLifeIntentType.COUPON,
        "detail": LocalLifeIntentType.DETAIL,
        "restaurant_detail": LocalLifeIntentType.DETAIL,
        "booking": LocalLifeIntentType.BOOKING,
        "book": LocalLifeIntentType.BOOKING,
        "restaurant_booking": LocalLifeIntentType.BOOKING,
        "order_status": LocalLifeIntentType.ORDER_STATUS,
        "status": LocalLifeIntentType.ORDER_STATUS,
        "order": LocalLifeIntentType.ORDER_STATUS,
        "cancel": LocalLifeIntentType.ORDER_STATUS,
        "refund": LocalLifeIntentType.ORDER_STATUS,
        "navigation": LocalLifeIntentType.NAVIGATION,
        "route": LocalLifeIntentType.NAVIGATION,
        "clarify": LocalLifeIntentType.CLARIFY,
    }
    if normalized in mapping:
        return mapping[normalized]
    for item in LocalLifeIntentType:
        if normalized == item.value:
            return item
    return None


def _extract_category(text: str, session_context: Mapping[str, Any]) -> Optional[str]:
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword in text:
            return category
    for key in ("current_category", "category"):
        value = session_context.get(key)
        if value:
            return str(value)
    return None


def _extract_shop_query(text: str, session_context: Mapping[str, Any]) -> Optional[str]:
    for key in ("selected_shop_name", "shop_name", "current_shop"):
        value = session_context.get(key)
        if value:
            return str(value)
    return None


def _classify_intent(text: str, has_shop_context: bool) -> LocalLifeIntentType:
    lowered = text.replace(" ", "")
    if any(token in lowered for token in ("对比", "比较", "区别", "哪家更")):
        return LocalLifeIntentType.RESTAURANT_COMPARISON
    if any(token in lowered for token in ("券", "优惠", "领券", "代金券")):
        return LocalLifeIntentType.COUPON
    if any(token in lowered for token in ("导航", "怎么走", "路线", "过去")):
        return LocalLifeIntentType.NAVIGATION
    if any(token in lowered for token in ("预约", "订座", "预订", "订位")):
        return LocalLifeIntentType.BOOKING
    if any(token in lowered for token in ("订单", "状态", "退款", "取消")):
        return LocalLifeIntentType.ORDER_STATUS
    if any(
        token in lowered
        for token in (
            "详情",
            "介绍",
            "信息",
            "怎么样",
            "值不值",
            "值不值得",
            "好不好",
            "这家",
            "这间",
            "这店",
            "这儿",
            "这里",
            "第一家",
            "第二家",
            "第一间",
            "第二间",
            "第一个",
            "第二个",
        )
    ):
        return LocalLifeIntentType.DETAIL
    return LocalLifeIntentType.RESTAURANT_RECOMMENDATION


def _last_candidate_ids(session_context: Mapping[str, Any]) -> list[int]:
    candidates = session_context.get("last_candidates") or []
    ids: list[int] = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, Mapping):
                candidate_id = item.get("shop_id") or item.get("id")
                if candidate_id is not None:
                    try:
                        ids.append(int(candidate_id))
                    except Exception:
                        continue
    return ids


def _build_clarification(question: str, options: list[tuple[str, str]]) -> ClarificationDecision:
    return ClarificationDecision(
        need_clarification=True,
        question=question,
        options=[SuggestedReply(label=label, prompt=prompt) for label, prompt in options],
    )


def extract_slots(
    understanding: QueryUnderstandingResult,
    raw_query: str,
    *,
    client_context: Mapping[str, Any] | None = None,
    session_context: Mapping[str, Any] | None = None,
    model_hint: Mapping[str, Any] | None = None,
) -> tuple[LocalLifeSlots, ClarificationDecision, LocalLifeIntentType]:
    client_context = _as_mapping(client_context)
    session_context = _as_mapping(session_context)
    model_hint = _as_mapping(model_hint)
    model_location = _as_mapping(model_hint.get("location"))
    model_time = _as_mapping(model_hint.get("time"))
    model_price = _as_mapping(model_hint.get("price"))
    text = (raw_query or "").strip()
    compact = text.replace(" ", "")

    category = _extract_category(compact, session_context)
    shop_query = _extract_shop_query(compact, session_context)
    city = (
        understanding.location_norm.city
        or understanding.extra.get("city")
        or client_context.get("city")
        or session_context.get("current_city")
        or session_context.get("city")
    )
    scene = "family_dinner" if any(token in compact for token in ("爸妈", "父母", "长辈", "老人")) else None
    if scene is None:
        scene = session_context.get("current_scene") or session_context.get("scene")
        if scene:
            scene = str(scene)
    companions: list[str] = []
    if any(token in compact for token in ("爸妈", "父母")):
        companions.append("parents")
    if any(token in compact for token in ("朋友", "同事")):
        companions.append("friends")
    if any(token in compact for token in ("家里人", "家人")):
        companions.append("family")

    preferences: list[str] = []
    avoid: list[str] = []
    if any(token in compact for token in ("别太吵", "安静", "安静点")):
        preferences.append("quiet")
    if any(token in compact for token in ("有停车", "能停车", "停车")):
        preferences.append("parking_available")
    if any(token in compact for token in ("适合爸妈", "带爸妈", "长辈", "老人")):
        preferences.extend(["elder_friendly", "family_dinner"])
    if any(token in compact for token in ("包间", "小包间")):
        preferences.append("private_room")
    if any(token in compact for token in ("清淡", "少油", "少辣")):
        preferences.append("light_taste")
    if any(token in compact for token in ("不要网红店", "别太网红", "不要排队", "少排队", "长队")):
        avoid.extend(["queue_risk", "busy"])

    price_min = None
    price_max = None
    target = None
    if understanding.extra.get("price"):
        price_min = understanding.extra["price"].get("min")
        price_max = understanding.extra["price"].get("max")
        target = understanding.extra["price"].get("target")
    # 直接从理解层提取的价格文字不一定保存在 extra，所以这里再做一层兜底。
    if price_max is None and "人均" in compact:
        import re

        match = re.search(r"人均(\d{2,4})(?:左右|上下|附近)?", compact)
        if match:
            target = float(match.group(1))
            price_min = max(0.0, target - 50.0)
            price_max = target + 50.0

    model_category = _clean_text(model_hint.get("category"))
    model_shop_query = _clean_text(model_hint.get("shop_query"))
    model_scene = _clean_text(model_hint.get("scene"))
    model_city = _clean_text(model_hint.get("city"))
    model_tool_name = _clean_text(model_hint.get("tool_name"))
    model_tool_input = _as_mapping(model_hint.get("tool_input"))
    model_preferences = _merge_text_values(model_hint.get("preferences"))
    model_avoid = _merge_text_values(model_hint.get("avoid"))
    model_companions = _merge_text_values(model_hint.get("companions"))
    model_shop_ids = _merge_text_values(model_hint.get("shop_ids"))
    model_intent = _coerce_intent(model_hint.get("intent") or model_hint.get("action"))
    model_confidence = 0.0
    try:
        model_confidence = float(model_hint.get("confidence", 0.0) or 0.0)
    except Exception:
        model_confidence = 0.0

    if model_category:
        category = model_category
    if model_shop_query:
        shop_query = model_shop_query
    if model_scene:
        scene = model_scene
    if model_city and not city:
        city = model_city

    if model_price:
        hinted_min = _coerce_float(model_price.get("min") or model_price.get("per_person_min"))
        hinted_max = _coerce_float(model_price.get("max") or model_price.get("per_person_max"))
        hinted_target = _coerce_float(model_price.get("target"))
        if hinted_min is not None and price_min is None:
            price_min = hinted_min
        if hinted_max is not None and price_max is None:
            price_max = hinted_max
        if hinted_target is not None and target is None:
            target = hinted_target

    session_preferences = _merge_text_values(session_context.get("local_life_preferences"))
    session_avoid = _merge_text_values(session_context.get("local_life_avoid"))

    preferences = list(dict.fromkeys([*session_preferences, *preferences, *model_preferences]))
    avoid = list(dict.fromkeys([*session_avoid, *avoid, *model_avoid]))
    companions = list(dict.fromkeys([*companions, *model_companions]))

    base_time = understanding.time_norm or TimeNorm()
    if model_time:
        time_value = base_time.model_copy(
            update={
                "type": _clean_text(model_time.get("type")) or base_time.type,
                "date": _clean_text(model_time.get("date")) or base_time.date,
                "meal_period": _clean_text(model_time.get("meal_period") or model_time.get("mealPeriod")) or base_time.meal_period,
                "preferred_time": _clean_text(model_time.get("preferred_time") or model_time.get("preferredTime")) or base_time.preferred_time,
            }
        )
    else:
        time_value = base_time

    base_location = understanding.location_norm or LocationNorm()
    location = base_location.model_copy(
        update={
            "city": _clean_text(model_location.get("city")) or base_location.city or city or model_city,
            "lat": _coerce_float(model_location.get("lat") or model_location.get("latitude")) or base_location.lat,
            "lng": _coerce_float(model_location.get("lng") or model_location.get("longitude")) or base_location.lng,
            "radius_km": _coerce_float(model_location.get("radius_km") or model_location.get("radiusKm")) or base_location.radius_km,
        }
    )
    if location.city is None:
        location.city = city or model_city or client_context.get("city") or session_context.get("current_city")

    slots = LocalLifeSlots(
        category=category or understanding.extra.get("category") or "餐厅",
        city=location.city or client_context.get("city") or session_context.get("current_city"),
        location=location,
        time=time_value,
        price=PriceNorm(
            per_person_min=price_min,
            per_person_max=price_max,
            target=target,
        ),
        scene=scene,
        companions=companions,
        preferences=sorted(dict.fromkeys(preferences)),
        avoid=sorted(dict.fromkeys(avoid)),
        page=str(client_context.get("entry") or session_context.get("page") or "") or None,
        shop_query=shop_query,
        tool_name=model_tool_name,
        tool_input=dict(model_tool_input),
    )

    if model_shop_ids:
        resolved_shop_ids: list[int] = []
        for value in model_shop_ids:
            try:
                resolved_shop_ids.append(int(value))
            except Exception:
                continue
        if resolved_shop_ids:
            slots.shop_ids = list(dict.fromkeys([*slots.shop_ids, *resolved_shop_ids]))

    last_ids = _last_candidate_ids(session_context)
    if any(token in compact for token in ("第二家", "第二个", "第二间")) and len(last_ids) >= 2:
        slots.shop_ids = [last_ids[1]]
        slots.action = LocalLifeIntentType.DETAIL
    elif any(token in compact for token in ("第一家", "第一个", "第一间")) and len(last_ids) >= 1:
        slots.shop_ids = [last_ids[0]]
        slots.action = LocalLifeIntentType.DETAIL

    intent = _classify_intent(compact, bool(slots.shop_ids or slots.shop_query))
    if model_intent is not None and model_confidence >= 0.45:
        intent = model_intent
    slots.action = slots.action or intent

    clarification = ClarificationDecision()
    if intent == LocalLifeIntentType.RESTAURANT_RECOMMENDATION:
        pass
    elif intent in {LocalLifeIntentType.COUPON, LocalLifeIntentType.DETAIL, LocalLifeIntentType.NAVIGATION}:
        pass
    if intent == LocalLifeIntentType.CLARIFY or model_intent == LocalLifeIntentType.CLARIFY:
        raw_options = model_hint.get("clarification_options") or []
        options: list[SuggestedReply] = []
        if isinstance(raw_options, (list, tuple, set)):
            for item in raw_options:
                if isinstance(item, Mapping):
                    label = _clean_text(item.get("label") or item.get("prompt") or item.get("value"))
                    prompt = _clean_text(item.get("prompt") or item.get("value") or label)
                else:
                    label = _clean_text(item)
                    prompt = label
                if label and prompt:
                    options.append(SuggestedReply(label=label, prompt=prompt))
        if not options:
            options = [
                SuggestedReply(label="家常菜", prompt="推荐家常菜"),
                SuggestedReply(label="火锅", prompt="推荐火锅"),
                SuggestedReply(label="粤菜", prompt="推荐粤菜"),
            ]
        clarification = ClarificationDecision(
            need_clarification=True,
            question=_clean_text(model_hint.get("clarification_question")) or "你想先看哪一类？",
            options=options[:3],
            ambiguity_type=_clean_text(model_hint.get("clarification_type")) or "local_life",
        )
        slots.action = intent

    return slots, clarification, intent
