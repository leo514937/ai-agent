"""Local-life facet taxonomy and lightweight protocol helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import Facet


LOCAL_LIFE_FACET_TAXONOMY: dict[str, tuple[str, ...]] = {
    "location": ("nearby", "distance", "business_area", "travel_time"),
    "category": ("restaurant", "hotpot", "coffee", "dessert", "parent_child", "entertainment", "shopping"),
    "scene": ("date_scene", "family_with_kids", "friends_party", "quiet", "lively", "business_meeting", "work_study", "late_night"),
    "status": ("open_now", "open_late", "reservation_available", "queue_status"),
    "deal": ("coupon", "discount", "group_buy", "cost_performance"),
    "price": ("avg_price", "budget", "budget_around_x", "price_compare"),
    "quality": ("rating", "review_tags", "popularity", "service", "environment", "taste"),
    "preference": ("not_too_noisy", "kid_friendly", "parking", "private_room", "spicy", "light_food", "vegetarian"),
    "reference": ("current_shop", "ordinal_reference", "previous_recommendation", "comparison_targets"),
}

_FACET_TO_GROUP: dict[str, str] = {
    facet: group for group, facets in LOCAL_LIFE_FACET_TAXONOMY.items() for facet in facets
}
_LEGACY_FACET_TO_STANDARD: dict[str, str] = {
    "open_status": "open_now",
    "review_summary": "review_tags",
    "scene_fit": "family_with_kids",
    "rating": "rating",
    "coupon": "coupon",
    "distance": "distance",
    "price": "avg_price",
    "category": "category",
    "current_shop": "current_shop",
    "ordinal_reference": "ordinal_reference",
    "previous_recommendation": "previous_recommendation",
    "comparison_targets": "comparison_targets",
}


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


def _session_value(state: Any, field: str) -> Any:
    if state is None:
        return None
    if isinstance(state, dict):
        value = state.get(field)
        if value is not None:
            return value
        session = state.get("session_state") or state.get("session_state_before")
        if isinstance(session, dict):
            return session.get(field)
        if session is not None:
            return getattr(session, field, None)
        return None
    value = getattr(state, field, None)
    if value is not None:
        return value
    session = getattr(state, "session_state", None) or getattr(state, "session_state_before", None)
    if isinstance(session, dict):
        return session.get(field)
    if session is not None:
        return getattr(session, field, None)
    return None


class QueryFacet(BaseModel):
    """Normalized facet request with a group boundary."""

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    group: str = ""
    value: Any | None = None
    source: str | None = None
    confidence: float | None = None
    evidence_ref: str | None = None
    required: bool = False
    owner: str | None = None
    resolution_reason: str | None = None


class ConflictingFacet(BaseModel):
    facets: list[str] = Field(default_factory=list)
    reason: str = ""
    severity: str | None = None


class RankingPolicy(BaseModel):
    primary_facets: list[str] = Field(default_factory=list)
    secondary_facets: list[str] = Field(default_factory=list)
    tradeoff_notes: list[str] = Field(default_factory=list)


class TargetResolutionResult(BaseModel):
    resolved: bool = False
    target_shop: dict[str, Any] | None = None
    source: str | None = None
    confidence: float = 0.0
    owner: str | None = None
    resolution_reason: str | None = None
    reference_type: str | None = None
    unresolved_reason: str | None = None
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("comparison_targets", mode="before")
    @classmethod
    def _coerce_comparison_targets(cls, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [item for item in value if item is not None]
        if isinstance(value, (tuple, set)):
            return [item for item in value if item is not None]
        return [value]


class FacetSet(BaseModel):
    facets: list[QueryFacet] = Field(default_factory=list)
    conflicting_facets: list[ConflictingFacet] = Field(default_factory=list)
    ranking_policy: RankingPolicy | None = None
    target_resolution: TargetResolutionResult | None = None


def _normalize_facet_name(name: Any) -> str:
    raw = str(getattr(name, "value", name) or "").strip()
    return _LEGACY_FACET_TO_STANDARD.get(raw, raw)


def _facet_group_for_name(name: str) -> str:
    normalized = _normalize_facet_name(name)
    return _FACET_TO_GROUP.get(normalized, "")


def _query_facet_from_item(item: Any, *, source: str, confidence: float | None = None) -> QueryFacet | None:
    if item is None:
        return None
    if isinstance(item, QueryFacet):
        facet = item.model_copy(deep=True)
        if not facet.group:
            facet.group = _facet_group_for_name(facet.name)
        facet.name = _normalize_facet_name(facet.name)
        facet.source = facet.source or source
        if facet.confidence is None and confidence is not None:
            facet.confidence = confidence
        return facet
    if isinstance(item, Facet):
        name = _normalize_facet_name(item.value)
        return QueryFacet(name=name, group=_facet_group_for_name(name), source=source, confidence=confidence)
    if isinstance(item, dict):
        raw = dict(item)
        name = _normalize_facet_name(raw.get("name", raw.get("facet", raw.get("facet_name", ""))))
        if not name:
            return None
        group = str(raw.get("group", "") or "").strip() or _facet_group_for_name(name)
        return QueryFacet(
            name=name,
            group=group,
            value=raw.get("value"),
            source=str(raw.get("source", "") or source) or source,
            confidence=raw.get("confidence", confidence),
            evidence_ref=raw.get("evidence_ref"),
            required=bool(raw.get("required", False)),
            owner=raw.get("owner"),
            resolution_reason=raw.get("resolution_reason"),
        )
    if hasattr(item, "name") or hasattr(item, "facet"):
        raw = _to_dict(item)
        return _query_facet_from_item(raw, source=source, confidence=confidence)
    name = _normalize_facet_name(item)
    if not name:
        return None
    return QueryFacet(name=name, group=_facet_group_for_name(name), source=source, confidence=confidence)


def _merge_facets(target: list[QueryFacet], item: Any, *, source: str) -> None:
    facet = _query_facet_from_item(item, source=source)
    if facet is None:
        return
    key = (facet.group or "", facet.name)
    if any((existing.group or "", existing.name) == key for existing in target):
        return
    target.append(facet)


def _make_conflict(groups: list[str], reason: str, severity: str | None = None) -> ConflictingFacet:
    return ConflictingFacet(facets=groups, reason=reason, severity=severity)


def _has_reference_cue(text: str, *, frame: dict[str, Any], session_state: dict[str, Any] | Any | None) -> bool:
    return bool(
        frame.get("current_shop")
        or frame.get("deictic_references")
        or frame.get("ordinal_references")
        or frame.get("reference_mentions")
        or frame.get("comparison_targets")
        or any(token in text for token in ("这家", "那家", "这间", "那间", "这位", "那位", "第一家", "第二家", "第一个", "第二个", "它", "这款", "那款"))
    )


def normalize_query_facets(
    semantic_frame: dict[str, Any] | Any | None = None,
    session_state: dict[str, Any] | Any | None = None,
    raw_text: str = "",
) -> FacetSet:
    """Derive a normalized facet set from semantic structure and text."""

    frame = _to_dict(semantic_frame)
    text = str(raw_text or frame.get("primary_task", "") or frame.get("goal_summary", "") or "").strip()
    lowered = text.lower()
    facets: list[QueryFacet] = []

    facet_set = _to_dict(frame.get("facet_set"))
    for item in facet_set.get("facets", []) or []:
        _merge_facets(facets, item, source="facet_set")

    for item in frame.get("facets", []) or []:
        _merge_facets(facets, item, source="semantic_frame")

    ranked_signals = _to_dict(frame.get("ranking_signals"))
    soft_preferences = _to_dict(frame.get("soft_preferences"))
    hard_constraints = _to_dict(frame.get("hard_constraints"))

    def add(name: str, group: str, *, value: Any = None, source: str = "text", confidence: float | None = 0.8, required: bool = False, resolution_reason: str | None = None) -> None:
        _merge_facets(
            facets,
            {
                "name": name,
                "group": group,
                "value": value,
                "source": source,
                "confidence": confidence,
                "required": required,
                "resolution_reason": resolution_reason,
            },
            source=source,
        )

    if any(token in text for token in ("附近", "周边", "周围", "离我", "多远", "距离")):
        add("nearby", "location", source="text")
    if any(token in text for token in ("距离", "多远", "多久", "几分钟", "步行", "车程", "地铁")):
        add("distance", "location", source="text")
    if any(token in text for token in ("远吗", "远不远", "太远", "有点远")):
        add("distance", "location", source="text")
    if any(token in text for token in ("商圈", "写字楼", "学校附近", "地铁口")):
        add("business_area", "location", source="text")
    if any(token in text for token in ("多久", "几分钟", "分钟到", "步行", "车程", "路程")):
        add("travel_time", "location", source="text")

    category_rules = {
        "hotpot": ("火锅",),
        "coffee": ("咖啡", "咖啡店", "咖啡馆"),
        "dessert": ("甜品", "甜点", "蛋糕", "下午茶"),
        "parent_child": ("亲子", "带娃", "儿童", "小朋友"),
        "entertainment": ("娱乐", "k歌", "电影", "影院", "玩乐", "游玩"),
        "shopping": ("购物", "商场", "逛街", "买买买"),
        "restaurant": ("餐厅", "饭店", "美食", "吃饭", "就餐"),
    }
    for name, tokens in category_rules.items():
        if any(token in text for token in tokens):
            add(name, "category", source="text")

    scene_rules = {
        "date_scene": ("约会",),
        "family_with_kids": ("亲子", "带娃", "孩子", "小孩"),
        "friends_party": ("聚餐", "朋友", "同学", "聚会"),
        "quiet": ("安静", "别太吵", "不吵", "静一点"),
        "lively": ("热闹", "氛围好", "人多"),
        "business_meeting": ("商务", "见客户", "谈事", "会客"),
        "work_study": ("工作", "学习", "自习", "办公"),
        "late_night": ("深夜", "夜宵", "凌晨"),
    }
    for name, tokens in scene_rules.items():
        if any(token in text for token in tokens):
            add(name, "scene", source="text")

    status_rules = {
        "open_now": ("现在营业", "正在营业", "营业中", "开门", "开着"),
        "open_late": ("营业到很晚", "深夜营业", "通宵"),
        "reservation_available": ("可预订", "可预约", "预约"),
        "queue_status": ("排队", "等位", "等很久", "排长队"),
    }
    for name, tokens in status_rules.items():
        if any(token in text for token in tokens):
            add(name, "status", source="text")

    deal_rules = {
        "coupon": ("有券", "优惠券", "券", "代金券"),
        "discount": ("打折", "折扣"),
        "group_buy": ("团购", "套餐", "买单"),
        "cost_performance": ("性价比", "划算", "值不值"),
    }
    for name, tokens in deal_rules.items():
        if any(token in text for token in tokens):
            add(name, "deal", source="text")

    if "人均" in text or "预算" in text or "价格" in text or "多少钱" in text:
        add("avg_price", "price", source="text")
    if any(token in text for token in ("预算", "便宜", "省钱")):
        add("budget", "price", source="text")
    budget_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb)?\s*(?:左右|以内|上下|附近)", text, re.I)
    if budget_match and any(token in text for token in ("预算", "人均", "价格")):
        add("budget_around_x", "price", value=budget_match.group(1), source="text")
    if any(token in text for token in ("比", "比较", "对比", "贵不贵", "便宜不便宜", "更便宜", "更贵")) and any(token in text for token in ("价格", "人均", "预算", "便宜", "贵")):
        add("price_compare", "price", source="text")

    quality_rules = {
        "rating": ("评分", "几分", "星级"),
        "review_tags": ("评价", "口碑", "点评"),
        "popularity": ("热门", "人气", "排队多", "很多人"),
        "service": ("服务",),
        "environment": ("环境",),
        "taste": ("味道", "好吃"),
    }
    for name, tokens in quality_rules.items():
        if any(token in text for token in tokens):
            add(name, "quality", source="text")

    preference_rules = {
        "not_too_noisy": ("不吵", "安静点", "别太吵"),
        "kid_friendly": ("带娃", "亲子", "儿童", "小朋友"),
        "parking": ("停车", "停车场"),
        "private_room": ("包间", "私密"),
        "spicy": ("辣", "微辣", "重辣"),
        "light_food": ("清淡", "轻食"),
        "vegetarian": ("素食", "素菜", "素一点"),
    }
    for name, tokens in preference_rules.items():
        if any(token in text for token in tokens):
            add(name, "preference", source="text")

    explicit_current_shop = _to_dict(frame.get("current_shop"))
    current_shop = explicit_current_shop or _to_dict(_session_value(session_state, "current_shop"))
    last_recommendations = list(_session_value(session_state, "last_recommendation_list") or [])
    has_reference_cue = _has_reference_cue(text, frame=frame, session_state=session_state)
    if has_reference_cue and (explicit_current_shop.get("shop_id") or explicit_current_shop.get("shop_name")):
        add("current_shop", "reference", value=current_shop, source="current_shop", confidence=1.0, resolution_reason="current_shop_available")

    if frame.get("ordinal_references") or re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", text):
        add("ordinal_reference", "reference", value=list(frame.get("ordinal_references") or []), source="semantic_frame" if frame.get("ordinal_references") else "text", confidence=0.95)

    if has_reference_cue and (last_recommendations or frame.get("deictic_references")):
        add("previous_recommendation", "reference", value=last_recommendations[:5], source="session_state" if last_recommendations else "semantic_frame", confidence=0.9)

    if frame.get("comparison_targets") or any(token in text for token in ("对比", "比较", "比一比")):
        add("comparison_targets", "reference", value=list(frame.get("comparison_targets") or []), source="semantic_frame" if frame.get("comparison_targets") else "text", confidence=0.9)

    reference_targets: list[str] = [facet.name for facet in facets if facet.group == "reference"]
    conflict_groups: list[ConflictingFacet] = []
    if {"quiet", "lively"}.issubset({facet.name for facet in facets}):
        conflict_groups.append(_make_conflict(["quiet", "lively"], "user requested mutually conflicting ambience"))
    if {"budget", "price_compare"}.issubset({facet.name for facet in facets}):
        conflict_groups.append(_make_conflict(["budget", "price_compare"], "user is mixing budget preference and price comparison"))

    primary_facets = [
        facet.name
        for facet in facets
        if facet.group in {"location", "category", "scene", "status", "reference", "deal"}
    ]
    secondary_facets = [
        facet.name
        for facet in facets
        if facet.group not in {"location", "category", "scene", "status", "reference", "deal"}
    ]
    tradeoff_notes: list[str] = []
    if conflict_groups:
        tradeoff_notes.extend(conflict.reason for conflict in conflict_groups if conflict.reason)
    if any(facet.name == "budget_around_x" for facet in facets):
        tradeoff_notes.append("budget_around_x should be treated as a soft constraint, not a winner selector")
    if any(facet.name == "comparison_targets" for facet in facets):
        tradeoff_notes.append("comparison_targets are reference inputs, not recommendation winners")

    return FacetSet(
        facets=facets,
        conflicting_facets=conflict_groups,
        ranking_policy=RankingPolicy(
            primary_facets=list(dict.fromkeys(primary_facets or reference_targets)),
            secondary_facets=list(dict.fromkeys(secondary_facets)),
            tradeoff_notes=list(dict.fromkeys(tradeoff_notes)),
        ),
        target_resolution=build_target_resolution_result(frame, session_state=session_state, raw_text=raw_text),
    )


def build_target_resolution_result(
    semantic_frame: dict[str, Any] | Any | None = None,
    *,
    session_state: dict[str, Any] | Any | None = None,
    raw_text: str = "",
) -> TargetResolutionResult:
    """Create the minimal target-resolution protocol without guessing."""

    frame = _to_dict(semantic_frame)
    text = str(raw_text or frame.get("primary_task", "") or frame.get("goal_summary", "") or "").strip()
    lower = text.lower()
    explicit_current_shop = _to_dict(frame.get("current_shop"))
    current_shop = explicit_current_shop or _to_dict(_session_value(session_state, "current_shop"))
    last_recommendations = [
        _to_dict(item)
        for item in (_session_value(session_state, "last_recommendation_list") or [])
        if _to_dict(item)
    ]
    comparison_targets = [
        _to_dict(item)
        for item in (frame.get("comparison_targets") or [])
        if _to_dict(item)
    ]
    ordinal_refs = [str(item).strip() for item in (frame.get("ordinal_references") or []) if str(item).strip()]
    deictic_refs = [str(item).strip() for item in (frame.get("deictic_references") or []) if str(item).strip()]
    reference_mentions = [str(item).strip() for item in (frame.get("reference_mentions") or []) if str(item).strip()]
    merchant_mentions = [str(item).strip() for item in (frame.get("merchant_mentions") or []) if str(item).strip()]
    has_current_shop_hint = bool(current_shop.get("shop_id") or current_shop.get("shop_name"))
    has_deictic_hint = any(token in text for token in ("这家", "那家", "它", "这间", "那间")) or bool(deictic_refs)
    has_ordinal_hint = bool(re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", text)) or bool(ordinal_refs)
    has_comparison_hint = bool(comparison_targets) or any(token in text for token in ("对比", "比较", "比一比", "哪家", "哪间"))

    def _clean_shop(shop: dict[str, Any]) -> dict[str, Any]:
        return {
            "shop_id": str(shop.get("shop_id", "") or "").strip(),
            "shop_name": str(shop.get("shop_name", "") or "").strip(),
            "address": str(shop.get("address", "") or "").strip(),
            "alias": shop.get("alias", []),
        }

    has_reference_cue = bool(
        explicit_current_shop.get("shop_id")
        or explicit_current_shop.get("shop_name")
        or comparison_targets
        or ordinal_refs
        or deictic_refs
        or reference_mentions
        or merchant_mentions
        or any(token in text for token in ("这家", "那家", "这间", "那间", "它", "第一家", "第二家"))
    )

    if has_current_shop_hint and has_reference_cue and (has_deictic_hint or any(token in lower for token in ("这家", "那家", "它", "第一家", "第二家"))):
        return TargetResolutionResult(
            resolved=True,
            target_shop=_clean_shop(current_shop),
            source="current_shop",
            confidence=1.0,
            owner="orchestration_router",
            resolution_reason="current_shop_reference",
            reference_type="current_shop",
            comparison_targets=[],
        )

    if comparison_targets:
        cleaned_targets = [_clean_shop(item) for item in comparison_targets if _clean_shop(item).get("shop_id") or _clean_shop(item).get("shop_name")]
        if len(cleaned_targets) >= 2:
            return TargetResolutionResult(
                resolved=True,
                target_shop=cleaned_targets[0],
                source="comparison_targets",
                confidence=0.95,
                owner="orchestration_router",
                resolution_reason="comparison_targets_resolved",
                reference_type="comparison_targets",
                comparison_targets=cleaned_targets,
            )
        return TargetResolutionResult(
            resolved=False,
            target_shop=cleaned_targets[0] if cleaned_targets else None,
            source="comparison_targets",
            confidence=0.4 if cleaned_targets else 0.0,
            owner="orchestration_router",
            resolution_reason="comparison_targets_need_clarification",
            reference_type="comparison_targets",
            unresolved_reason="comparison_targets_need_clarification",
            comparison_targets=cleaned_targets,
        )

    if has_ordinal_hint:
        if not last_recommendations:
            return TargetResolutionResult(
                resolved=False,
                target_shop=None,
                source="last_recommendation_list",
                confidence=0.0,
                owner="orchestration_router",
                resolution_reason="missing_last_recommendation_list",
                reference_type="ordinal_reference",
                unresolved_reason="missing_last_recommendation_list",
            )
        index = 1
        match = re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", text)
        if match:
            token = match.group(1)
            chinese_to_int = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            if token.isdigit():
                index = int(token)
            else:
                index = chinese_to_int.get(token, 1)
        if 1 <= index <= len(last_recommendations):
            target = _clean_shop(last_recommendations[index - 1])
            if target.get("shop_id") or target.get("shop_name"):
                return TargetResolutionResult(
                    resolved=True,
                    target_shop=target,
                    source="last_recommendation_list",
                    confidence=0.95,
                    owner="orchestration_router",
                    resolution_reason="ordinal_reference",
                    reference_type="ordinal_reference",
                    comparison_targets=[],
                )
        return TargetResolutionResult(
            resolved=False,
            target_shop=None,
            source="last_recommendation_list",
            confidence=0.0,
            owner="orchestration_router",
            resolution_reason="ordinal_out_of_range",
            reference_type="ordinal_reference",
            unresolved_reason="ordinal_out_of_range",
        )

    if merchant_mentions and len(merchant_mentions) == 1 and not has_comparison_hint:
        return TargetResolutionResult(
            resolved=False,
            target_shop=None,
            source="explicit_shop_name",
            confidence=0.5,
            owner="orchestration_router",
            resolution_reason="explicit_shop_name_needs_candidate_resolution",
            reference_type="explicit_shop_name",
            unresolved_reason="explicit_shop_name_needs_candidate_resolution",
        )

    if has_current_shop_hint and has_deictic_hint:
        return TargetResolutionResult(
            resolved=True,
            target_shop=_clean_shop(current_shop),
            source="current_shop",
            confidence=1.0,
            owner="orchestration_router",
            resolution_reason="current_shop_reference",
            reference_type="current_shop",
        )

    if deictic_refs or has_deictic_hint:
        return TargetResolutionResult(
            resolved=False,
            target_shop=None,
            source="current_shop",
            confidence=0.0,
            owner="orchestration_router",
            resolution_reason="missing_current_shop",
            reference_type="current_shop",
            unresolved_reason="missing_current_shop",
        )

    if has_comparison_hint and not comparison_targets:
        return TargetResolutionResult(
            resolved=False,
            target_shop=None,
            source="comparison_targets",
            confidence=0.0,
            owner="orchestration_router",
            resolution_reason="comparison_targets_need_clarification",
            reference_type="comparison_targets",
            unresolved_reason="comparison_targets_need_clarification",
        )

    if has_current_shop_hint and has_reference_cue and (has_ordinal_hint or bool(reference_mentions) or bool(merchant_mentions)):
        return TargetResolutionResult(
            resolved=True,
            target_shop=_clean_shop(current_shop),
            source="current_shop",
            confidence=1.0,
            owner="orchestration_router",
            resolution_reason="current_shop_reference",
            reference_type="current_shop",
        )

    return TargetResolutionResult(
        resolved=False,
        target_shop=None,
        source="current_shop" if has_current_shop_hint else None,
        confidence=0.0,
        owner="orchestration_router",
        resolution_reason="no_target_detected",
        reference_type="current_shop" if has_current_shop_hint else None,
        unresolved_reason="no_target_detected",
    )
