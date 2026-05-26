from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..config import get_settings
from ..domain.contracts import PersistentSessionContext, RetrievalPlan, RoutingDecision, ToolSelection, TurnRuntimeState
from ..local_life.query_rewriter import _CITY_NAMES as _LOCAL_LIFE_CITY_NAMES


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.replace("\u3000", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _compact_text(text: str) -> str:
    return "".join(_normalize_text(text).split())


def _contains_any(text: str, tokens: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(token in text or token.lower() in lowered for token in tokens if token)


def _regex_any(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns if pattern)


def _extract_city_from_text(text: str) -> str | None:
    normalized = _normalize_text(text)
    for city in _LOCAL_LIFE_CITY_NAMES:
        if city and city in normalized:
            return city
    return None


@dataclass(frozen=True)
class DomainSignalSpec:
    name: str
    domain: str
    keywords: tuple[str, ...] = ()
    regex_patterns: tuple[str, ...] = ()
    entity_hints: tuple[str, ...] = ()
    default_intent: str = "unknown"
    default_required_action: str = "clarify"
    fallback_required_action: str = "clarify"
    required_slots: tuple[str, ...] = ()
    preferred_chunk_roles: tuple[str, ...] = ()
    tool_candidates: tuple[str, ...] = ()
    confidence_boost: float = 0.0
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainSignalCandidate:
    spec_name: str
    domain: str
    intent: str
    required_action: str
    confidence: float
    missing_slots: tuple[str, ...] = ()
    slots: tuple[tuple[str, Any], ...] = ()
    preferred_chunk_roles: tuple[str, ...] = ()
    tool_candidates: tuple[str, ...] = ()
    route_reason: str = ""
    clarification_question: str | None = None
    matched_terms: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec_name": self.spec_name,
            "domain": self.domain,
            "intent": self.intent,
            "required_action": self.required_action,
            "confidence": self.confidence,
            "missing_slots": list(self.missing_slots),
            "slots": dict(self.slots),
            "preferred_chunk_roles": list(self.preferred_chunk_roles),
            "tool_candidates": list(self.tool_candidates),
            "route_reason": self.route_reason,
            "clarification_question": self.clarification_question,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class SemanticRoutingDraft:
    domain: str
    intent: str
    confidence: float
    required_action: str
    should_retrieve: bool
    should_call_tool: bool
    should_rewrite_query: bool
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    preferred_chunk_roles: list[str] = field(default_factory=list)
    tool_candidates: list[str] = field(default_factory=list)
    route_reason: str = ""
    clarification_question: str | None = None
    candidate_names: list[str] = field(default_factory=list)
    route_candidate: str | None = None
    safeguards_triggered: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LLMIntentRouterOutput:
    domain: str
    intent: str
    confidence: float
    required_action: str
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    should_retrieve: bool = False
    should_call_tool: bool = False
    should_rewrite_query: bool = False
    preferred_chunk_roles: list[str] = field(default_factory=list)
    tool_candidates: list[str] = field(default_factory=list)
    route_reason: str = ""
    clarification_question: str | None = None


def _default_specs() -> tuple[DomainSignalSpec, ...]:
    return (
        DomainSignalSpec(
            name="local_life.package_or_coupon",
            domain="local_life",
            keywords=("套餐", "团购", "券", "优惠券", "还能用", "可用", "值不值", "值不值", "有没有券"),
            regex_patterns=(r"(套餐|团购|券|优惠券|优惠券?).*?(还能用|可用|过期|有效|值不值)",),
            default_intent="package_or_coupon",
            default_required_action="tool_call",
            fallback_required_action="clarify",
            required_slots=("voucher_id", "shop_name"),
            preferred_chunk_roles=("package_description", "merchant_review_summary", "merchant_pitfall_summary"),
            tool_candidates=("get_coupon_list", "getVoucherDetail", "resolveVoucher", "searchVoucher"),
            confidence_boost=0.24,
            examples=("这个套餐现在还能用吗", "这个券现在可用吗"),
        ),
        DomainSignalSpec(
            name="local_life.merchant_status",
            domain="local_life",
            keywords=("营业", "开门", "开业", "现在营业", "还能去", "排队", "库存", "预约", "歇业", "关门"),
            regex_patterns=(r"(现在|今天|目前).*(营业|开门|开业|还能去|排队|库存|预约)",),
            default_intent="merchant_status",
            default_required_action="tool_call",
            fallback_required_action="clarify",
            required_slots=("shop_id", "shop_name"),
            preferred_chunk_roles=("merchant_profile", "merchant_status", "merchant_review_summary"),
            tool_candidates=("getShopDetail", "getBusinessStatus", "resolveShop"),
            confidence_boost=0.25,
            examples=("湖畔私房菜现在营业吗", "这家店现在开门吗"),
        ),
        DomainSignalSpec(
            name="local_life.scene_fit",
            domain="local_life",
            keywords=("适合", "带父母", "带长辈", "约会", "家庭聚餐", "安静", "不吵", "老人", "孩子"),
            default_intent="merchant_detail",
            default_required_action="rag_retrieval",
            fallback_required_action="clarify",
            required_slots=("shop_name",),
            preferred_chunk_roles=("merchant_scene_fit", "merchant_review_summary", "merchant_pitfall_summary", "merchant_profile"),
            tool_candidates=("getShopDetail",),
            confidence_boost=0.2,
            examples=("湖畔私房菜适合带父母吗", "适合家庭聚餐吗"),
        ),
        DomainSignalSpec(
            name="local_life.pitfall",
            domain="local_life",
            keywords=("避坑", "踩雷", "排队", "停车", "坑不坑", "服务怎么样", "翻车"),
            default_intent="merchant_pitfall",
            default_required_action="rag_retrieval",
            fallback_required_action="clarify",
            required_slots=("shop_name",),
            preferred_chunk_roles=("merchant_pitfall_summary", "merchant_review_summary", "merchant_profile"),
            tool_candidates=("getShopDetail",),
            confidence_boost=0.18,
            examples=("这家店有啥坑吗", "停车方便吗"),
        ),
        DomainSignalSpec(
            name="local_life.nearby_recommend",
            domain="local_life",
            keywords=("附近", "周边", "推荐", "有什么好吃", "吃饭", "去哪", "附近有什么", "周边有什么"),
            default_intent="local_life_recommend",
            default_required_action="rag_plus_tool",
            fallback_required_action="clarify",
            required_slots=("location",),
            preferred_chunk_roles=("merchant_parent_summary", "merchant_scene_fit", "merchant_review_summary", "merchant_profile"),
            tool_candidates=("search_restaurants", "recommendShops"),
            confidence_boost=0.18,
            examples=("附近有什么适合带父母吃饭的地方", "周边推荐一下"),
        ),
        DomainSignalSpec(
            name="local_life.merchant_detail",
            domain="local_life",
            keywords=("怎么样", "评价", "评分", "口碑", "人均", "环境", "详情", "介绍", "值不值", "好不好"),
            default_intent="merchant_detail",
            default_required_action="rag_retrieval",
            fallback_required_action="clarify",
            required_slots=("shop_name",),
            preferred_chunk_roles=("merchant_parent_summary", "merchant_review_summary", "merchant_profile", "merchant_scene_fit"),
            tool_candidates=("getShopDetail",),
            confidence_boost=0.16,
            examples=("湖畔私房菜怎么样", "这家店值不值"),
        ),
        DomainSignalSpec(
            name="local_life.booking_or_order",
            domain="local_life",
            keywords=("订座", "预约", "预订", "订位", "下单", "购买", "买单", "支付", "订单", "取消", "退款"),
            default_intent="merchant_status",
            default_required_action="tool_call",
            fallback_required_action="clarify",
            required_slots=("shop_name",),
            preferred_chunk_roles=("merchant_profile", "merchant_status"),
            tool_candidates=("create_booking", "create_order", "cancel_order", "refund_order", "get_order_status"),
            confidence_boost=0.26,
            examples=("怎么订座", "我想取消订单"),
        ),
    )


class DomainSignalRegistry:
    def __init__(self, specs: Sequence[DomainSignalSpec] | None = None) -> None:
        self._specs = tuple(specs or _default_specs())

    @property
    def specs(self) -> tuple[DomainSignalSpec, ...]:
        return self._specs

    def match(
        self,
        raw_query: str,
        *,
        persistent: PersistentSessionContext | None = None,
        client_context: Mapping[str, Any] | None = None,
    ) -> list[DomainSignalCandidate]:
        normalized = _normalize_text(raw_query)
        compact = _compact_text(raw_query)
        context = dict(client_context or {})
        persistent = persistent or PersistentSessionContext()
        recent_entities = [str(item).strip() for item in (persistent.recent_entities or []) if str(item).strip()]
        anchors = [
            str(persistent.current_topic or "").strip(),
            str(persistent.current_shop or "").strip(),
            str(persistent.selected_shop_name or "").strip(),
            str(persistent.current_city or "").strip(),
            str(context.get("shopName") or context.get("shop_name") or "").strip(),
            str(context.get("city") or context.get("current_city") or "").strip(),
        ]
        anchor_text = " ".join(value for value in anchors if value)
        candidates: list[DomainSignalCandidate] = []
        for spec in self._specs:
            matched_terms: list[str] = []
            keyword_hits = [keyword for keyword in spec.keywords if keyword and (keyword in normalized or keyword in compact)]
            matched_terms.extend(keyword_hits)
            regex_hits = [pattern for pattern in spec.regex_patterns if pattern and re.search(pattern, normalized, re.IGNORECASE)]
            if regex_hits:
                matched_terms.extend(regex_hits)
            entity_hits = [hint for hint in spec.entity_hints if hint and (hint in normalized or hint in compact or hint in anchor_text)]
            if entity_hits:
                matched_terms.extend(entity_hits)

            if not matched_terms:
                continue

            slots = _extract_slots(spec, normalized, compact, persistent, context)
            confidence = min(
                0.98,
                max(
                    0.2,
                    spec.confidence_boost
                    + 0.08 * len(keyword_hits)
                    + 0.12 * len(regex_hits)
                    + 0.05 * len(entity_hits)
                    + (0.08 if anchor_text else 0.0),
                ),
            )
            required_action = spec.default_required_action
            clarification_question = None
            missing_slots = tuple(slot for slot in spec.required_slots if not slots.get(slot))
            if spec.name.endswith("package_or_coupon") and not _has_voucher_context(persistent, context, normalized):
                required_action = spec.fallback_required_action
                clarification_question = "你说的是哪个套餐或券？"
                missing_slots = tuple(sorted(set(missing_slots) | {"voucher_id"}))
            elif spec.name.endswith("merchant_status") and not _has_shop_context(persistent, context, normalized):
                required_action = spec.fallback_required_action
                clarification_question = "你想查哪家店的营业情况？"
                missing_slots = tuple(sorted(set(missing_slots) | {"shop_name"}))
            elif spec.name.endswith("nearby_recommend") and not _has_location_context(persistent, context, normalized):
                required_action = spec.fallback_required_action
                clarification_question = "你现在在哪个城市或位置附近？"
                missing_slots = tuple(sorted(set(missing_slots) | {"location"}))
            elif spec.name.endswith("booking_or_order") and not _has_shop_context(persistent, context, normalized):
                required_action = spec.fallback_required_action
                clarification_question = "你想处理哪家店的订单或预约？"
                missing_slots = tuple(sorted(set(missing_slots) | {"shop_name"}))

            candidates.append(
                DomainSignalCandidate(
                    spec_name=spec.name,
                    domain=spec.domain,
                    intent=spec.default_intent,
                    required_action=required_action,
                    confidence=confidence,
                    missing_slots=missing_slots,
                    slots=tuple(sorted(slots.items())),
                    preferred_chunk_roles=spec.preferred_chunk_roles,
                    tool_candidates=spec.tool_candidates,
                    route_reason=f"registry:{spec.name}",
                    clarification_question=clarification_question,
                    matched_terms=tuple(matched_terms),
                )
            )
        return sorted(candidates, key=lambda item: item.confidence, reverse=True)


def _extract_slots(
    spec: DomainSignalSpec,
    normalized: str,
    compact: str,
    persistent: PersistentSessionContext,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    shop_name = (
        context.get("shopName")
        or context.get("shop_name")
        or persistent.current_shop
        or persistent.selected_shop_name
        or persistent.current_topic
        or _extract_shop_name(normalized, compact)
    )
    if shop_name:
        slots["shop_name"] = str(shop_name).strip()
    city = _extract_city_from_text(normalized) or context.get("city") or context.get("current_city") or persistent.current_city
    if city:
        slots["city"] = str(city).strip()
    location = context.get("location") or persistent.current_location
    if isinstance(location, Mapping) and location:
        slots["location"] = dict(location)
    elif isinstance(location, str) and location.strip():
        slots["location"] = {"text": location.strip()}
    elif city:
        slots["location"] = {"city": str(city).strip()}
    if persistent.selected_shop_id is not None:
        slots["shop_id"] = persistent.selected_shop_id
    if "券" in compact or "套餐" in compact or "团购" in compact:
        voucher_id = context.get("voucher_id") or context.get("voucherId")
        if voucher_id:
            slots["voucher_id"] = voucher_id
    if "带父母" in compact or "带长辈" in compact:
        slots["scene"] = "family_dinner"
        slots["companions"] = ["parents"]
    if "约会" in compact:
        slots["scene"] = "date"
    if "安静" in compact or "不吵" in compact:
        slots["scene"] = slots.get("scene") or "quiet"
        slots.setdefault("preferences", [])
        if "quiet" not in slots["preferences"]:
            slots["preferences"].append("quiet")
    if "停车" in compact:
        slots.setdefault("preferences", [])
        if "parking" not in slots["preferences"]:
            slots["preferences"].append("parking")
    return slots


def _extract_shop_name(normalized: str, compact: str) -> str | None:
    patterns = (
        r"([\u4e00-\u9fffA-Za-z0-9]{2,20}?)(?:现在|目前|到底|究竟)?(?:营业|开门|怎么样|适合|能用|可用|值不值|好吗|好不好)",
        r"([\u4e00-\u9fffA-Za-z0-9]{2,20}?)(?:店|餐厅|饭店|商家)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized or compact)
        if match:
            candidate = str(match.group(1)).strip()
            if candidate:
                return candidate
    return None


def _has_shop_context(persistent: PersistentSessionContext, context: Mapping[str, Any], normalized: str) -> bool:
    return bool(
        persistent.selected_shop_id
        or persistent.selected_shop_name
        or persistent.current_shop
        or context.get("shop_id")
        or context.get("shopId")
        or context.get("shop_name")
        or context.get("shopName")
        or _extract_shop_name(normalized, _compact_text(normalized))
    )


def _has_voucher_context(persistent: PersistentSessionContext, context: Mapping[str, Any], normalized: str) -> bool:
    return bool(
        context.get("voucher_id")
        or context.get("voucherId")
        or persistent.last_candidates
        or _has_shop_context(persistent, context, normalized)
    )


def _has_location_context(
    persistent: PersistentSessionContext,
    context: Mapping[str, Any],
    normalized: str | None = None,
) -> bool:
    return bool(
        _extract_city_from_text(normalized or "")
        or persistent.current_city
        or persistent.current_location
        or context.get("location")
        or context.get("city")
        or context.get("current_city")
    )


def _looks_like_coupon_environment_query(normalized: str, compact: str) -> bool:
    coupon_hit = any(token in compact for token in ("套餐", "团购", "券", "优惠券", "可用", "还能用", "值不值"))
    environment_hit = any(
        token in compact
        for token in ("怎么样", "评价", "评分", "口碑", "环境", "安静", "氛围", "适合", "家庭聚餐", "带父母", "带长辈", "约会", "老人", "孩子")
    )
    return coupon_hit and environment_hit


def _is_coupon_environment_pair(left_spec: str, right_spec: str) -> bool:
    pair = {str(left_spec or "").strip().lower(), str(right_spec or "").strip().lower()}
    return "local_life.package_or_coupon" in pair and bool(pair & {"local_life.scene_fit", "local_life.merchant_detail"})


def _merge_candidate_slots(*candidates: DomainSignalCandidate) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for candidate in candidates:
        merged.update(dict(candidate.slots))
    return merged


def _phase1_routing_extra(routing: RoutingDecision) -> dict[str, Any]:
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    settings = get_settings()
    phase1_keys = ["route_review_decision"]
    if bool(getattr(settings, "enable_required_facets_to_plans", True)):
        phase1_keys.extend(
            [
                "required_facets",
                "optional_facets",
                "required_facets_source_constraints",
                "user_need",
            ]
        )
    return {key: routing_extra[key] for key in phase1_keys if key in routing_extra}


def route_semantic_query(
    raw_query: str,
    *,
    persistent: PersistentSessionContext | None = None,
    client_context: Mapping[str, Any] | None = None,
    registry: DomainSignalRegistry | None = None,
) -> SemanticRoutingDraft:
    registry = registry or DomainSignalRegistry()
    persistent = persistent or PersistentSessionContext()
    normalized = _normalize_text(raw_query)
    candidates = registry.match(raw_query, persistent=persistent, client_context=client_context)
    candidate_names = [candidate.spec_name for candidate in candidates]

    if not normalized:
        return SemanticRoutingDraft(
            domain="general",
            intent="no_op",
            confidence=0.0,
            required_action="reject",
            should_retrieve=False,
            should_call_tool=False,
            should_rewrite_query=False,
            route_reason="empty_input",
            candidate_names=candidate_names,
            route_candidate="empty",
            safeguards_triggered=["empty_input"],
        )

    if not candidates:
        return _fallback_semantic_route(normalized, persistent, client_context, candidate_names)

    top = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    if runner_up is not None and _is_coupon_environment_pair(top.spec_name, runner_up.spec_name):
        has_shop_context = _has_shop_context(persistent, client_context or {}, normalized)
        merged_tools = list(dict.fromkeys(list(top.tool_candidates) + list(runner_up.tool_candidates) + ["get_coupon_list"]))
        merged_roles = list(
            dict.fromkeys(
                list(top.preferred_chunk_roles)
                + list(runner_up.preferred_chunk_roles)
                + ["package_description", "merchant_review_summary", "merchant_scene_fit", "merchant_profile"]
            )
        )
        merged_slots = _merge_candidate_slots(top, runner_up)
        if has_shop_context:
            intent = top.intent if top.spec_name.endswith("package_or_coupon") else runner_up.intent
            return SemanticRoutingDraft(
                domain="local_life",
                intent=intent,
                confidence=max(top.confidence, runner_up.confidence),
                required_action="rag_plus_tool",
                should_retrieve=True,
                should_call_tool=True,
                should_rewrite_query=True,
                slots=merged_slots,
                missing_slots=[],
                preferred_chunk_roles=merged_roles,
                tool_candidates=merged_tools,
                route_reason="coupon_environment_merged",
                clarification_question=None,
                candidate_names=candidate_names,
                route_candidate="coupon_environment_merged",
            )
        return SemanticRoutingDraft(
            domain="local_life",
            intent=top.intent if top.spec_name.endswith("package_or_coupon") else runner_up.intent,
            confidence=max(top.confidence, runner_up.confidence),
            required_action="clarify",
            should_retrieve=False,
            should_call_tool=False,
            should_rewrite_query=False,
            slots=merged_slots,
            missing_slots=["shop_name"],
            preferred_chunk_roles=merged_roles,
            tool_candidates=merged_tools,
            route_reason="coupon_environment_missing_shop",
            clarification_question="你想查哪家店的券和环境？",
            candidate_names=candidate_names,
            route_candidate="coupon_environment_missing_shop",
            safeguards_triggered=["signal_conflict"],
        )
    if runner_up is not None and abs(top.confidence - runner_up.confidence) < 0.08:
        if top.spec_name.endswith("nearby_recommend") or runner_up.spec_name.endswith("nearby_recommend"):
            nearby_candidate = top if top.spec_name.endswith("nearby_recommend") else runner_up
            if _has_location_context(persistent, client_context or {}, normalized):
                merged_roles = list(dict.fromkeys(list(top.preferred_chunk_roles) + list(runner_up.preferred_chunk_roles)))
                merged_tools = list(dict.fromkeys(list(top.tool_candidates) + list(runner_up.tool_candidates)))
                return SemanticRoutingDraft(
                    domain="local_life",
                    intent="local_life_recommend",
                    confidence=max(top.confidence, runner_up.confidence),
                    required_action="rag_plus_tool",
                    should_retrieve=True,
                    should_call_tool=True,
                    should_rewrite_query=True,
                    slots=dict(nearby_candidate.slots),
                    missing_slots=[],
                    preferred_chunk_roles=merged_roles,
                    tool_candidates=merged_tools,
                    route_reason="nearby_recommend_merged",
                    clarification_question=None,
                    candidate_names=candidate_names,
                    route_candidate="nearby_recommend",
                )
            return SemanticRoutingDraft(
                domain="local_life",
                intent="local_life_recommend",
                confidence=max(top.confidence, runner_up.confidence),
                required_action="clarify",
                should_retrieve=False,
                should_call_tool=False,
                should_rewrite_query=False,
                slots=dict(nearby_candidate.slots),
                missing_slots=["location"],
                preferred_chunk_roles=list(nearby_candidate.preferred_chunk_roles),
                tool_candidates=list(nearby_candidate.tool_candidates),
                route_reason="nearby_recommend_missing_location",
                clarification_question="你现在在哪个城市或位置附近？",
                candidate_names=candidate_names,
                route_candidate="nearby_recommend",
                safeguards_triggered=["signal_conflict"],
            )
        if top.required_action != runner_up.required_action:
            return SemanticRoutingDraft(
                domain=top.domain,
                intent=top.intent,
                confidence=min(top.confidence, runner_up.confidence),
                required_action="clarify",
                should_retrieve=False,
                should_call_tool=False,
                should_rewrite_query=False,
                slots=dict(top.slots),
                missing_slots=list(sorted(set(top.missing_slots) | set(runner_up.missing_slots))),
                preferred_chunk_roles=list(dict.fromkeys(list(top.preferred_chunk_roles) + list(runner_up.preferred_chunk_roles))),
                tool_candidates=list(dict.fromkeys(list(top.tool_candidates) + list(runner_up.tool_candidates))),
                route_reason="conflicting_domain_signals",
                clarification_question=top.clarification_question or runner_up.clarification_question or "你更想查商家状态还是看详情？",
                candidate_names=candidate_names,
                route_candidate="conflict_clarify",
                safeguards_triggered=["signal_conflict"],
            )

    required_action = top.required_action
    if top.required_action == "clarify" and top.clarification_question:
        route_reason = top.route_reason or "clarify_by_registry"
    else:
        route_reason = top.route_reason or f"registry:{top.spec_name}"
    should_retrieve = required_action in {"rag_retrieval", "rag_plus_tool"}
    should_call_tool = required_action in {"tool_call", "rag_plus_tool"}
    should_rewrite_query = should_retrieve or should_call_tool or top.intent in {"merchant_detail", "local_life_recommend"}
    return SemanticRoutingDraft(
        domain=top.domain,
        intent=top.intent,
        confidence=top.confidence,
        required_action=required_action,
        should_retrieve=should_retrieve,
        should_call_tool=should_call_tool,
        should_rewrite_query=should_rewrite_query,
        slots=dict(top.slots),
        missing_slots=list(top.missing_slots),
        preferred_chunk_roles=list(top.preferred_chunk_roles),
        tool_candidates=list(top.tool_candidates),
        route_reason=route_reason,
        clarification_question=top.clarification_question,
        candidate_names=candidate_names,
        route_candidate=top.spec_name,
    )


def _fallback_semantic_route(
    normalized: str,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None,
    candidate_names: list[str],
) -> SemanticRoutingDraft:
    compact = _compact_text(normalized)
    lowered = normalized.lower()
    context_has_location = _has_location_context(persistent, client_context or {}, normalized)
    context_has_shop = _has_shop_context(persistent, client_context or {}, normalized)
    if any(token in compact for token in ("以后", "长期", "记住", "偏好", "不吃辣", "少吃辣", "不吃香菜", "不吃牛肉")):
        return SemanticRoutingDraft(
            domain="memory",
            intent="memory_update",
            confidence=0.84,
            required_action="memory_update",
            should_retrieve=False,
            should_call_tool=False,
            should_rewrite_query=False,
            route_reason="memory_update_signal",
            candidate_names=candidate_names,
            route_candidate="memory_update",
        )
    if any(token in compact for token in ("你好", "您好", "hello", "hi", "hey")):
        return SemanticRoutingDraft(
            domain="general",
            intent="chit_chat",
            confidence=0.97,
            required_action="direct_answer",
            should_retrieve=False,
            should_call_tool=False,
            should_rewrite_query=False,
            route_reason="greeting",
            candidate_names=candidate_names,
            route_candidate="greeting",
        )
    if any(token in compact for token in ("谢谢", "多谢", "感谢", "辛苦了")):
        return SemanticRoutingDraft(
            domain="general",
            intent="chit_chat",
            confidence=0.97,
            required_action="direct_answer",
            should_retrieve=False,
            should_call_tool=False,
            should_rewrite_query=False,
            route_reason="thanks",
            candidate_names=candidate_names,
            route_candidate="thanks",
        )
    if any(token in compact for token in ("功能", "能力", "是谁", "怎么用你")):
        return SemanticRoutingDraft(
            domain="general",
            intent="explain",
            confidence=0.92,
            required_action="direct_answer",
            should_retrieve=False,
            should_call_tool=False,
            should_rewrite_query=False,
            route_reason="profile_query",
            candidate_names=candidate_names,
            route_candidate="profile",
        )
    if any(token in compact for token in ("套餐", "券", "团购", "优惠券", "还能用", "可用")):
        required_action = "tool_call" if context_has_shop else "clarify"
        return SemanticRoutingDraft(
            domain="local_life",
            intent="package_or_coupon",
            confidence=0.78 if context_has_shop else 0.5,
            required_action=required_action,
            should_retrieve=False,
            should_call_tool=context_has_shop,
            should_rewrite_query=False,
            missing_slots=[] if context_has_shop else ["voucher_id"],
            preferred_chunk_roles=["package_description", "merchant_review_summary", "merchant_pitfall_summary"],
            tool_candidates=["get_coupon_list", "getVoucherDetail", "resolveVoucher", "searchVoucher"],
            route_reason="package_or_coupon_fallback",
            clarification_question=None if context_has_shop else "你说的是哪个套餐或券？",
            candidate_names=candidate_names,
            route_candidate="package_or_coupon",
        )
    if any(token in compact for token in ("营业", "开门", "开业", "歇业", "关门", "还能去", "预约", "排队", "库存")):
        required_action = "tool_call" if context_has_shop else "clarify"
        return SemanticRoutingDraft(
            domain="local_life",
            intent="merchant_status",
            confidence=0.8 if context_has_shop else 0.52,
            required_action=required_action,
            should_retrieve=False,
            should_call_tool=context_has_shop,
            should_rewrite_query=False,
            missing_slots=[] if context_has_shop else ["shop_name"],
            preferred_chunk_roles=["merchant_profile", "merchant_status", "merchant_review_summary"],
            tool_candidates=["getShopDetail", "getBusinessStatus", "resolveShop"],
            route_reason="merchant_status_fallback",
            clarification_question=None if context_has_shop else "你想查哪家店的营业情况？",
            candidate_names=candidate_names,
            route_candidate="merchant_status",
        )
    if any(token in compact for token in ("适合", "带父母", "带长辈", "约会", "家庭聚餐", "安静", "不吵", "老人")):
        return SemanticRoutingDraft(
            domain="local_life",
            intent="merchant_detail",
            confidence=0.76,
            required_action="rag_retrieval",
            should_retrieve=True,
            should_call_tool=False,
            should_rewrite_query=True,
            slots={},
            missing_slots=[] if context_has_shop else ["shop_name"],
            preferred_chunk_roles=["merchant_scene_fit", "merchant_review_summary", "merchant_pitfall_summary", "merchant_profile"],
            tool_candidates=["getShopDetail"],
            route_reason="scene_fit_fallback",
            candidate_names=candidate_names,
            route_candidate="scene_fit",
        )
    if any(token in compact for token in ("避坑", "踩雷", "排队", "停车", "坑不坑", "服务怎么样", "翻车")):
        return SemanticRoutingDraft(
            domain="local_life",
            intent="merchant_pitfall",
            confidence=0.75,
            required_action="rag_retrieval",
            should_retrieve=True,
            should_call_tool=False,
            should_rewrite_query=True,
            preferred_chunk_roles=["merchant_pitfall_summary", "merchant_review_summary", "merchant_profile"],
            tool_candidates=["getShopDetail"],
            route_reason="pitfall_fallback",
            candidate_names=candidate_names,
            route_candidate="pitfall",
        )
    if _looks_like_coupon_environment_query(normalized, compact):
        required_action = "rag_plus_tool" if context_has_shop else "clarify"
        return SemanticRoutingDraft(
            domain="local_life",
            intent="package_or_coupon",
            confidence=0.76 if context_has_shop else 0.54,
            required_action=required_action,
            should_retrieve=context_has_shop,
            should_call_tool=context_has_shop,
            should_rewrite_query=context_has_shop,
            slots={},
            missing_slots=[] if context_has_shop else ["shop_name"],
            preferred_chunk_roles=["package_description", "merchant_scene_fit", "merchant_review_summary", "merchant_pitfall_summary", "merchant_profile"],
            tool_candidates=["get_coupon_list", "getVoucherDetail", "resolveVoucher", "searchVoucher"],
            route_reason="coupon_environment_fallback",
            clarification_question=None if context_has_shop else "你想查哪家店的券和环境？",
            candidate_names=candidate_names,
            route_candidate="coupon_environment",
        )
    if any(token in compact for token in ("附近", "周边", "推荐", "好吃", "去哪")):
        required_action = "rag_plus_tool" if context_has_location else "clarify"
        return SemanticRoutingDraft(
            domain="local_life",
            intent="local_life_recommend",
            confidence=0.74 if context_has_location else 0.52,
            required_action=required_action,
            should_retrieve=context_has_location,
            should_call_tool=context_has_location,
            should_rewrite_query=True if context_has_location else False,
            missing_slots=[] if context_has_location else ["location"],
            preferred_chunk_roles=["merchant_parent_summary", "merchant_scene_fit", "merchant_review_summary", "merchant_profile"],
            tool_candidates=["search_restaurants", "recommendShops"],
            route_reason="nearby_recommend_fallback",
            clarification_question=None if context_has_location else "你现在在哪个城市或位置附近？",
            candidate_names=candidate_names,
            route_candidate="nearby_recommend",
        )
    if any(token in compact for token in ("订单", "取消", "退款", "下单", "支付", "订座", "预约", "预订", "订位")):
        required_action = "tool_call" if context_has_shop else "clarify"
        return SemanticRoutingDraft(
            domain="local_life",
            intent="merchant_status",
            confidence=0.78 if context_has_shop else 0.5,
            required_action=required_action,
            should_retrieve=False,
            should_call_tool=context_has_shop,
            should_rewrite_query=False,
            missing_slots=[] if context_has_shop else ["shop_name"],
            preferred_chunk_roles=["merchant_profile", "merchant_status"],
            tool_candidates=["create_booking", "create_order", "cancel_order", "refund_order", "get_order_status"],
            route_reason="transaction_fallback",
            clarification_question=None if context_has_shop else "你想处理哪家店的订单或预约？",
            candidate_names=candidate_names,
            route_candidate="transaction",
        )
    if context_has_shop and any(token in compact for token in ("怎么样", "评价", "评分", "口碑", "人均", "环境", "详情", "介绍", "值不值")):
        return SemanticRoutingDraft(
            domain="local_life",
            intent="merchant_detail",
            confidence=0.72,
            required_action="rag_retrieval",
            should_retrieve=True,
            should_call_tool=False,
            should_rewrite_query=True,
            preferred_chunk_roles=["merchant_parent_summary", "merchant_review_summary", "merchant_profile", "merchant_scene_fit"],
            tool_candidates=["getShopDetail"],
            route_reason="merchant_detail_fallback",
            candidate_names=candidate_names,
            route_candidate="merchant_detail",
        )
    if context_has_shop and any(token in lowered for token in ("this", "that", "previous", "it")):
        return SemanticRoutingDraft(
            domain="local_life",
            intent="follow_up_reference",
            confidence=0.62,
            required_action="rag_retrieval",
            should_retrieve=True,
            should_call_tool=False,
            should_rewrite_query=True,
            route_reason="follow_up_reference",
            candidate_names=candidate_names,
            route_candidate="follow_up_reference",
        )
    return SemanticRoutingDraft(
        domain="general",
        intent="explain",
        confidence=0.66,
        required_action="clarify" if len(normalized) <= 4 else "direct_answer",
        should_retrieve=False,
        should_call_tool=False,
        should_rewrite_query=False,
        route_reason="semantic_fallback",
        candidate_names=candidate_names,
        route_candidate="semantic_fallback",
    )


def synthesize_retrieval_plan(
    routing: RoutingDecision,
    turn: TurnRuntimeState,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
) -> RetrievalPlan | None:
    required_action = str(routing.required_action or "").strip().lower()
    if required_action not in {"rag_retrieval", "rag_plus_tool"} or routing.blocked:
        return None
    normalized_query = _normalize_text(turn.raw_query or routing.normalized_query)
    semantic_query = str(
        getattr(getattr(routing, "rewrite_decision", None), "rewritten_query", "") or normalized_query
    ).strip()
    if not semantic_query:
        return None

    slots = dict(getattr(turn, "slots", {}) or {})
    slots.update(dict(routing.extra.get("semantic_slots", {}) or {}))
    if client_context:
        slots.setdefault("client_context", dict(client_context))

    preferred_chunk_roles = list(routing.preferred_chunk_roles or [])
    if not preferred_chunk_roles:
        preferred_chunk_roles = _default_preferred_chunk_roles(routing.intent.name if routing.intent else None, normalized_query)
    retrieval_filters: dict[str, Any] = {
        "domain": routing.domain if hasattr(routing, "domain") else "local_life",
        "is_active": True,
        "is_latest": True,
    }
    shop_name = str(slots.get("shop_name") or persistent.current_shop or persistent.selected_shop_name or "").strip()
    if shop_name:
        retrieval_filters["shop_name"] = shop_name
    shop_id = slots.get("shop_id") or persistent.selected_shop_id
    if shop_id is not None:
        retrieval_filters["shop_id"] = shop_id
    city = str(slots.get("city") or persistent.current_city or "").strip()
    if city:
        retrieval_filters["city"] = city
    location = slots.get("location") or persistent.current_location
    if isinstance(location, Mapping) and location:
        retrieval_filters["location"] = dict(location)
    strategy = "dense+sparse+metadata->rrf->rerank->evidence"
    return RetrievalPlan(
        semantic_query=semantic_query,
        keyword_query=_keyword_query_for_retrieval(normalized_query, routing, slots),
        retrieval_filters=retrieval_filters,
        preferred_chunk_types=list(preferred_chunk_roles),
        need_retry_rewrite=False,
        reasoning_notes=["synthesized_from_routing_decision"],
        extra={
            "source": "synthesized",
            "strategy": strategy,
            "preferred_chunk_roles": list(preferred_chunk_roles),
            "semantic_slots": slots,
            **_phase1_routing_extra(routing),
        },
    )


def synthesize_tool_selection(
    routing: RoutingDecision,
    turn: TurnRuntimeState,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
) -> ToolSelection | None:
    required_action = str(routing.required_action or "").strip().lower()
    if required_action not in {"tool_call", "rag_plus_tool"} or routing.blocked:
        return None
    slots = dict(getattr(turn, "slots", {}) or {})
    if client_context:
        slots.setdefault("client_context", dict(client_context))
    tool_name, reason = _choose_tool_name(routing, turn, persistent, slots)
    if not tool_name:
        return None
    input_payload = _build_tool_input(tool_name, routing, turn, persistent, slots)
    approval_required = tool_name in {"create_booking", "create_order", "cancel_order", "refund_order"}
    return ToolSelection(
        tool_name=tool_name,
        should_execute=True,
        input_payload=input_payload,
        reason=reason,
        approval_required=approval_required,
        approval_request={"reason": reason, "tool_name": tool_name} if approval_required else {},
        extra={
            "selection_source": "synthesized",
            "tool_call_id": f"synth-{routing.route_candidate or tool_name}",
            "planning_state": "synthesized",
            "route_reason": routing.route_reason,
            "resolved_intent": routing.intent.name if routing.intent else None,
            **_phase1_routing_extra(routing),
        },
    )


def _default_preferred_chunk_roles(intent_name: str | None, normalized_query: str) -> list[str]:
    compact = _compact_text(normalized_query)
    if any(token in compact for token in ("适合", "带父母", "带长辈", "约会", "家庭聚餐", "安静", "不吵")):
        return ["merchant_scene_fit", "merchant_review_summary", "merchant_pitfall_summary", "merchant_profile"]
    if any(token in compact for token in ("避坑", "踩雷", "排队", "停车", "坑不坑", "服务怎么样")):
        return ["merchant_pitfall_summary", "merchant_review_summary", "merchant_profile"]
    if any(token in compact for token in ("套餐", "团购", "券", "优惠券", "还能用", "可用", "值不值")):
        return ["package_description", "merchant_review_summary", "merchant_pitfall_summary"]
    if any(token in compact for token in ("附近", "周边", "推荐", "吃饭", "去哪")):
        return ["merchant_parent_summary", "merchant_scene_fit", "merchant_review_summary", "merchant_profile"]
    return ["merchant_parent_summary", "merchant_review_summary", "merchant_profile"]


def _keyword_query_for_retrieval(normalized_query: str, routing: RoutingDecision, slots: Mapping[str, Any]) -> str:
    query = normalized_query
    hints = list(routing.preferred_chunk_roles or [])
    if any(token in normalized_query for token in ("带父母", "带长辈", "约会", "家庭聚餐")):
        query = f"{query} 家庭聚餐 安静 稳定体验"
    elif any(token in normalized_query for token in ("避坑", "踩雷", "排队", "停车", "坑不坑", "服务怎么样")):
        query = f"{query} 避坑 排队 停车"
    elif any(token in normalized_query for token in ("套餐", "团购", "券", "优惠券", "还能用", "可用", "值不值")):
        query = f"{query} 套餐 券 评价 环境"
    elif any(token in normalized_query for token in ("附近", "周边", "推荐", "吃饭", "去哪")):
        query = f"{query} 附近 推荐 适合"
    if hints:
        query = f"{query} {' '.join(hints[:3])}"
    return query.strip()


def _choose_tool_name(
    routing: RoutingDecision,
    turn: TurnRuntimeState,
    persistent: PersistentSessionContext,
    slots: Mapping[str, Any],
) -> tuple[str | None, str]:
    normalized = _normalize_text(turn.raw_query or routing.normalized_query)
    compact = _compact_text(normalized)
    shop_id = slots.get("shop_id") or persistent.selected_shop_id
    shop_name = slots.get("shop_name") or persistent.current_shop or persistent.selected_shop_name or persistent.current_topic
    voucher_id = slots.get("voucher_id") or slots.get("coupon_id")
    location = slots.get("location") or persistent.current_location
    if any(token in compact for token in ("营业", "开门", "开业", "还能去", "排队", "库存")):
        if shop_id or shop_name:
            return "get_shop_detail", "synthesized_shop_status"
        return None, "missing_shop_name"
    if any(token in compact for token in ("套餐", "团购", "券", "优惠券", "还能用", "可用")):
        if voucher_id:
            return "get_coupon_list", "synthesized_coupon_status"
        if shop_name or shop_id:
            return "get_coupon_list", "synthesized_coupon_lookup"
        return None, "missing_voucher_context"
    if any(token in compact for token in ("附近", "周边", "推荐", "吃饭", "去哪")):
        if isinstance(location, Mapping) and location:
            return "search_restaurants", "synthesized_nearby_search"
        return None, "missing_location"
    if any(token in compact for token in ("订单", "取消", "退款", "下单", "支付", "订座", "预约", "预订", "订位")):
        return "get_order_status", "synthesized_transaction_lookup"
    return "get_shop_detail" if shop_name or shop_id else None, "synthesized_detail_lookup" if shop_name or shop_id else "missing_shop_name"


def _build_tool_input(
    tool_name: str,
    routing: RoutingDecision,
    turn: TurnRuntimeState,
    persistent: PersistentSessionContext,
    slots: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_text(turn.raw_query or routing.normalized_query)
    if tool_name == "search_restaurants":
        location = slots.get("location") or persistent.current_location or {}
        city = slots.get("city") or persistent.current_city
        return {
            "query": normalized,
            "city": city,
            "location": dict(location) if isinstance(location, Mapping) else location,
            "scene": slots.get("scene") or "nearby_recommend",
            "preferences": list(slots.get("preferences") or []),
            "avoid": list(slots.get("avoid") or []),
            "limit": 5,
        }
    if tool_name == "get_coupon_list":
        return {
            "shop_id": slots.get("shop_id") or persistent.selected_shop_id,
            "shop_name": slots.get("shop_name") or persistent.current_shop or persistent.selected_shop_name or persistent.current_topic,
            "voucher_id": slots.get("voucher_id"),
            "query": normalized,
        }
    if tool_name == "get_order_status":
        return {
            "shop_id": slots.get("shop_id") or persistent.selected_shop_id,
            "shop_name": slots.get("shop_name") or persistent.current_shop or persistent.selected_shop_name or persistent.current_topic,
            "query": normalized,
        }
    return {
        "shop_id": slots.get("shop_id") or persistent.selected_shop_id,
        "shop_name": slots.get("shop_name") or persistent.current_shop or persistent.selected_shop_name or persistent.current_topic,
        "query": normalized,
    }
