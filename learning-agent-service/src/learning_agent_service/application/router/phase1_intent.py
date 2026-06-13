from __future__ import annotations

from collections import Counter

from collections.abc import Mapping, Sequence

from typing import Any

from ...domain.contracts import (
    FastDecision,
    IntentRoutingDecision,
    PersistentSessionContext,
    RewriteDecision,
    RoutingDecision,
)

from ...domain.enums import IntentType

from ..routing_primitives import (
    _compact,
    _content_tokens,
    normalize_query,
)

from ..routing_signals import SemanticRoutingDraft

from .base import (
    _DIRECT_ACTIONS,
    _normalize_entity_key,
    _LOCAL_LIFE_QUERY_TOKENS,
    _PHASE1_DATA_SOURCE_CLIENT_CONTEXT,
    _PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
    _PHASE1_DATA_SOURCE_MIXED,
    _PHASE1_DATA_SOURCE_SLOT,
    _PHASE1_DATA_SOURCE_STATIC_RAG,
    _RETRIEVAL_ACTIONS,
)


def _facet_dict(

    name: str,

    *,

    required: bool = True,

    data_source: str = _PHASE1_DATA_SOURCE_MIXED,

    freshness: str = "static_ok",

    entity_keys: Sequence[str] | None = None,

    missing_policy: str = "partial_grounded",

    evidence_roles: Sequence[str] | None = None,

    tool_names: Sequence[str] | None = None,

    detail: str | None = None,

) -> dict[str, Any]:

    return {

        "name": name,

        "required": required,

        "data_source": data_source,

        "freshness": freshness,

        "entity_keys": [str(item) for item in (entity_keys or []) if str(item).strip()],

        "missing_policy": missing_policy,

        "evidence_roles": [str(item) for item in (evidence_roles or []) if str(item).strip()],

        "tool_names": [str(item) for item in (tool_names or []) if str(item).strip()],

        "detail": detail,

    }


def _route_review_reason(

    current_action: str,

    recommended_action: str,

    semantic_route: SemanticRoutingDraft,

    routing: RoutingDecision,

) -> str:

    if current_action == recommended_action:

        return "route_review_no_change"

    if current_action in {"direct_answer", "clarify", "reject"} and recommended_action in _RETRIEVAL_ACTIONS | {"tool_call"}:

        return "route_review_local_life_upgrade"

    if routing.route_candidate and routing.route_candidate != semantic_route.route_candidate:

        return "route_review_semantic_alignment"

    return "route_review_updated"


def _route_review_priority(action: str) -> int:

    normalized = str(action or "").strip().lower()

    if normalized == "rag_plus_tool":

        return 2

    if normalized in {"rag_retrieval", "tool_call"}:

        return 1

    return 0


def _required_slots_from_fast_decision(fast_result: FastDecision) -> list[str]:

    slots = dict(fast_result.key_slots or {})

    return [str(item) for item in slots.get("required_slots", []) if item]


def _allowed_routes_from_fast_decision(fast_result: FastDecision) -> list[str]:

    extra = dict(fast_result.extra or {}) if isinstance(fast_result.extra, Mapping) else {}

    local_life_action = str(extra.get("local_life_intent") or "").strip().lower()

    if local_life_action in {"booking", "coupon"}:

        return ["tool_call"]

    if fast_result.needs_tool and fast_result.needs_rag:

        return ["rag_plus_tool"]

    if fast_result.needs_tool:

        return ["tool_call"]

    if fast_result.needs_rag:

        return ["rag_retrieval"]

    return ["direct_answer"]


def _forbidden_routes_from_fast_decision(fast_result: FastDecision) -> list[str]:

    if fast_result.needs_clarify:

        return ["rag_retrieval", "tool_call"]

    return []


def _required_action_from_fast_decision(fast_result: FastDecision) -> str:

    extra = dict(fast_result.extra or {}) if isinstance(fast_result.extra, Mapping) else {}

    local_life_action = str(extra.get("local_life_intent") or "").strip().lower()

    if local_life_action in {"booking", "coupon"}:

        return "tool_call"

    route_review = extra.get("route_review_decision")

    if isinstance(route_review, Mapping):

        current_action = str(route_review.get("current_action") or "").strip().lower()

        recommended_action = str(route_review.get("recommended_action") or "").strip().lower()

        if current_action in {"tool_call", "rag_plus_tool", "rag_retrieval", "direct_answer"}:

            if current_action == "rag_retrieval" and recommended_action in {"tool_call", "rag_plus_tool", "rag_retrieval", "direct_answer"}:

                return recommended_action

            return current_action

        if current_action == "clarify" and recommended_action in {"tool_call", "rag_plus_tool", "rag_retrieval", "direct_answer"}:

            return recommended_action

    if fast_result.needs_clarify:

        return "clarify"

    if fast_result.needs_tool and fast_result.needs_rag:

        return "rag_plus_tool"

    if fast_result.needs_tool:

        return "tool_call"

    if fast_result.needs_rag:

        return "rag_retrieval"

    return "direct_answer"


def _intent_name_from_fast_decision(fast_result: FastDecision, routing: RoutingDecision) -> str:

    extra = dict(fast_result.extra or {})

    route_candidate = str(extra.get("route_candidate") or routing.route_candidate or "").strip().lower()

    if route_candidate in {"conversation_recap", "session_memory_query", "continue_previous_topic"}:

        return "conversation_recap"

    if route_candidate in {"greeting", "thanks", "profile"}:

        return "chit_chat"

    if route_candidate in {"empty", "low_info"}:

        return "invalid_input"

    if route_candidate == "local_life":

        return "local_life_recommend"

    if route_candidate == "tool_then_rag":

        return "rag_plus_tool"

    if fast_result.needs_tool and fast_result.needs_rag:

        return "rag_plus_tool"

    if fast_result.needs_tool:

        return "tool_required"

    if fast_result.needs_rag and fast_result.intent == IntentType.RECOMMEND:

        return "local_life_recommend"

    if fast_result.intent == IntentType.COMPARE:

        return "comparison"

    if fast_result.intent == IntentType.SUMMARY:

        return "qa_general"

    if fast_result.intent == IntentType.RECOMMEND:

        return "local_life_recommend"

    if fast_result.intent == IntentType.FOLLOW_UP:

        return "follow_up_reference"

    if fast_result.intent == IntentType.EXPLAIN:

        return "qa_general"

    return routing.intent.name or "qa_general"


def _recommended_action_for_facets(

    required_facets: Sequence[Mapping[str, Any]],

    semantic_route: SemanticRoutingDraft,

    routing: RoutingDecision,

) -> str:

    data_sources = {

        str(facet.get("data_source") or "").strip().lower()

        for facet in required_facets

        if str(facet.get("name") or "").strip()

    }

    if _PHASE1_DATA_SOURCE_DYNAMIC_TOOL in data_sources and _PHASE1_DATA_SOURCE_STATIC_RAG in data_sources:

        return "rag_plus_tool"

    if _PHASE1_DATA_SOURCE_DYNAMIC_TOOL in data_sources:

        return "tool_call"

    if _PHASE1_DATA_SOURCE_STATIC_RAG in data_sources:

        return "rag_retrieval"

    if semantic_route.required_action:

        return str(semantic_route.required_action).strip().lower()

    return str(routing.required_action or "direct_answer").strip().lower()


def _build_required_facets(

    routing: RoutingDecision,

    semantic_route: SemanticRoutingDraft,

    *,

    raw_query: str,

    persistent: PersistentSessionContext,

    client_context: Mapping[str, Any] | None = None,

) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:

    compact = _compact(raw_query)

    context = dict(client_context or {})

    slots = dict(semantic_route.slots or {})

    local_life_query = (

        routing.domain == "local_life"

        or semantic_route.domain == "local_life"

        or any(token in compact for token in _LOCAL_LIFE_QUERY_TOKENS)

    )

    required_facets: list[dict[str, Any]] = []

    optional_facets: list[dict[str, Any]] = []



    if local_life_query:

        has_location_context = bool(

            slots.get("location")

            or context.get("location")

            or context.get("city")

            or persistent.current_city

            or persistent.current_location

        )

        has_shop_hint = bool(

            slots.get("shop_id")

            or slots.get("shop_name")

            or persistent.selected_shop_id

            or persistent.selected_shop_name

            or persistent.current_shop

            or persistent.current_topic

            or context.get("shopId")

            or context.get("shopName")

            or any(token in compact for token in ("这家", "那家", "这个店", "那个店"))

        )

        has_coupon_hint = any(token in compact for token in ("券", "优惠", "优惠券", "团购", "套餐", "还能用", "可用"))

        has_open_status_hint = any(token in compact for token in ("营业", "开门", "开业", "还能去", "排队", "库存"))

        has_scene_hint = any(token in compact for token in ("适合", "带父母", "带长辈", "带小孩", "朋友聚餐", "深夜", "商务宴请", "约会", "家庭聚餐", "安静", "不吵", "老人", "孩子"))

        has_distance_hint = any(token in compact for token in ("附近", "周边", "离我", "离我近", "多远", "距离", "有多远", "导航", "路线", "怎么走", "怎么去"))

        needs_recommendation = has_scene_hint or any(token in compact for token in ("附近", "周边", "推荐", "适合", "约会", "家庭聚餐", "带小孩", "朋友聚餐", "深夜", "商务宴请", "安静", "不吵", "老人", "孩子"))

        needs_detail = any(token in compact for token in ("怎么样", "评价", "评分", "口碑", "环境", "详情", "介绍", "值不值", "好不好", "避坑", "踩雷", "翻车", "停车"))



        if needs_recommendation:

            required_facets.append(

                _facet_dict(

                    "location",

                    data_source=_PHASE1_DATA_SOURCE_CLIENT_CONTEXT if has_location_context else _PHASE1_DATA_SOURCE_SLOT,

                    freshness="near_realtime_required",

                    entity_keys=["city", "location"],

                    missing_policy="partial_grounded",

                    detail="user_position_or_city",

                )

            )

            if has_location_context:

                category_value = _normalize_entity_key(slots.get("category") or context.get("category") or context.get("typeName"))

                required_facets.append(

                    _facet_dict(

                        "category",

                        data_source=_PHASE1_DATA_SOURCE_SLOT,

                        freshness="static_ok",

                        entity_keys=["category"],

                        missing_policy="ask_clarification",

                        detail=category_value or "category_from_query",

                    )

                )

                required_facets.append(

                    _facet_dict(

                        "scene_fit",

                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,

                        freshness="static_ok",

                        entity_keys=["shop_name"],

                        missing_policy="partial_grounded",

                        evidence_roles=["merchant_scene_fit", "merchant_review_summary"],

                        tool_names=["getShopDetail"],

                        detail="scene_fit_recommendation",

                    )

                )

                required_facets.append(

                    _facet_dict(

                        "recommendation_reason",

                        data_source=_PHASE1_DATA_SOURCE_MIXED,

                        freshness="static_ok",

                        entity_keys=["shop_name"],

                        missing_policy="partial_grounded",

                        evidence_roles=["merchant_review_summary", "merchant_profile"],

                        tool_names=["search_restaurants", "getShopDetail"],

                        detail="recommendation_explanation",

                    )

                )

                required_facets.append(

                    _facet_dict(

                        "shop_detail",

                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,

                        freshness="static_ok",

                        entity_keys=["shop_name"],

                        missing_policy="partial_grounded",

                        evidence_roles=["merchant_profile", "merchant_review_summary"],

                        tool_names=["getShopDetail"],

                        detail="merchant_detail_summary",

                    )

                )

                if has_distance_hint:

                    required_facets.append(

                        _facet_dict(

                            "distance_eta",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_id", "location"],

                            missing_policy="partial_grounded",

                            tool_names=["get_distance_eta"],

                            detail="nearby_travel_eta",

                        )

                    )

                else:

                    optional_facets.append(

                        _facet_dict(

                            "distance_eta",

                            required=False,

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_id", "location"],

                            missing_policy="partial_grounded",

                            tool_names=["get_distance_eta"],

                            detail="nearby_travel_eta_optional",

                        )

                    )

            if has_coupon_hint:

                if has_shop_hint:

                    required_facets.append(

                        _facet_dict(

                            "coupon",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["get_coupon_list"],

                            detail="current_coupon_status",

                        )

                    )

                else:

                    optional_facets.append(

                        _facet_dict(

                            "coupon",

                            required=False,

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["get_coupon_list"],

                            detail="coupon_optional",

                        )

                    )

            if has_open_status_hint:

                if has_shop_hint and has_location_context:

                    required_facets.append(

                        _facet_dict(

                            "open_status",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],

                            detail="current_open_status",

                        )

                    )

                else:

                    optional_facets.append(

                        _facet_dict(

                            "open_status",

                            required=False,

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],

                            detail="open_status_optional",

                        )

                    )

        elif needs_detail:

            if has_shop_hint:

                required_facets.append(

                    _facet_dict(

                        "shop_detail",

                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,

                        freshness="static_ok",

                        entity_keys=["shop_name"],

                        missing_policy="partial_grounded",

                        evidence_roles=["merchant_profile", "merchant_review_summary"],

                        tool_names=["getShopDetail"],

                        detail="merchant_detail_summary",

                    )

                )

                required_facets.append(

                    _facet_dict(

                        "recommendation_reason",

                        data_source=_PHASE1_DATA_SOURCE_MIXED,

                        freshness="static_ok",

                        entity_keys=["shop_name"],

                        missing_policy="partial_grounded",

                        evidence_roles=["merchant_review_summary", "merchant_profile"],

                        tool_names=["search_restaurants", "getShopDetail"],

                        detail="recommendation_explanation",

                    )

                )

                if has_open_status_hint:

                    required_facets.append(

                        _facet_dict(

                            "open_status",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],

                            detail="current_open_status",

                        )

                    )

                if has_coupon_hint:

                    required_facets.append(

                        _facet_dict(

                            "coupon",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["get_coupon_list"],

                            detail="current_coupon_status",

                        )

                    )

                if has_distance_hint:

                    required_facets.append(

                        _facet_dict(

                            "distance_eta",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["get_distance_eta"],

                            detail="nearby_travel_eta",

                        )

                    )

            else:

                required_facets.append(

                    _facet_dict(

                        "location",

                        data_source=_PHASE1_DATA_SOURCE_SLOT,

                        freshness="near_realtime_required",

                    entity_keys=["city", "location"],

                    missing_policy="partial_grounded",

                        detail="user_position_or_city",

                    )

                )

        elif has_open_status_hint or has_coupon_hint:

            if has_shop_hint:

                if has_open_status_hint:

                    required_facets.append(

                        _facet_dict(

                            "open_status",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],

                            detail="current_open_status",

                        )

                    )

                if has_coupon_hint:

                    required_facets.append(

                        _facet_dict(

                            "coupon",

                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,

                            freshness="near_realtime_required",

                            entity_keys=["shop_name"],

                            missing_policy="partial_grounded",

                            tool_names=["get_coupon_list"],

                            detail="current_coupon_status",

                        )

                    )

            else:

                required_facets.append(

                    _facet_dict(

                        "location",

                        data_source=_PHASE1_DATA_SOURCE_SLOT,

                        freshness="near_realtime_required",

                        entity_keys=["city", "location"],

                        missing_policy="partial_grounded",

                        detail="user_position_or_city",

                    )

                )



    # 去重并保持稳定顺序

    dedup_required: list[dict[str, Any]] = []

    seen_required: set[str] = set()

    for facet in required_facets:

        name = str(facet.get("name") or "").strip()

        if not name or name in seen_required:

            continue

        seen_required.add(name)

        dedup_required.append(facet)



    dedup_optional: list[dict[str, Any]] = []

    seen_optional: set[str] = set(seen_required)

    for facet in optional_facets:

        name = str(facet.get("name") or "").strip()

        if not name or name in seen_optional:

            continue

        seen_optional.add(name)

        dedup_optional.append(facet)

    return dedup_required, dedup_optional


def apply_fast_decision_to_routing(

    routing: RoutingDecision,

    fast_result: FastDecision,

    *,

    reference_resolved: bool = False,

    reference_confidence: float | None = None,

    resolved_references: Sequence[str] | None = None,

) -> RoutingDecision:

    intent_name = _intent_name_from_fast_decision(fast_result, routing)

    allowed_routes = _allowed_routes_from_fast_decision(fast_result)

    forbidden_routes = _forbidden_routes_from_fast_decision(fast_result)

    required_action = _required_action_from_fast_decision(fast_result)

    blocked = bool(routing.blocked)

    should_retrieve = bool(fast_result.needs_rag and not blocked and required_action in _RETRIEVAL_ACTIONS)

    should_call_tool = bool(fast_result.needs_tool and not blocked and required_action in {"tool_call", "rag_plus_tool"})

    should_rewrite_query = bool(fast_result.needs_query_rewrite or routing.should_rewrite_query)

    should_use_memory = routing.should_use_memory and required_action not in _DIRECT_ACTIONS and not blocked

    should_persist_memory = routing.should_persist_memory and required_action not in {"direct_answer", "clarify", "reject", "no_op"} and not blocked

    should_vectorize_memory = routing.should_vectorize_memory and should_persist_memory

    intent_confidence = float(fast_result.confidence or 0.0)

    intent = IntentRoutingDecision(

        name=intent_name,

        confidence=intent_confidence,

        required_slots=_required_slots_from_fast_decision(fast_result),

        missing_slots=list(fast_result.extra.get("missing_slots", [])) if isinstance(fast_result.extra, Mapping) else [],

        allowed_routes=allowed_routes,

        forbidden_routes=forbidden_routes,

    )

    updated_resolved = list(routing.resolved_references)

    if resolved_references:

        updated_resolved.extend([ref for ref in resolved_references if ref])

    if reference_resolved and reference_confidence and reference_confidence >= 0.5:

        should_rewrite_query = True

    extra_slots = dict(fast_result.extra or {}) if isinstance(fast_result.extra, Mapping) else {}

    preferred_chunk_roles = list(

        dict.fromkeys(

            list(routing.preferred_chunk_roles)

            + [str(item) for item in extra_slots.get("preferred_chunk_roles", []) if str(item).strip()]

        )

    )

    tool_candidates = list(

        dict.fromkeys(

            list(routing.tool_candidates)

            + [str(item) for item in extra_slots.get("tool_candidates", []) if str(item).strip()]

        )

    )

    confidence = max(float(routing.confidence or 0.0), intent_confidence)



    extra = dict(routing.extra)

    extra.update(dict(fast_result.extra or {}))

    extra["fast_decision_confidence"] = intent_confidence

    extra["fast_decision_intent"] = fast_result.intent.value if fast_result.intent else None

    extra["fast_decision_route_candidate"] = fast_result.extra.get("route_candidate") if isinstance(fast_result.extra, Mapping) else None



    return routing.model_copy(

        update={

            "domain": str(extra_slots.get("domain") or routing.domain),

            "confidence": confidence,

            "intent": intent,

            "required_action": required_action,

            "should_rewrite_query": should_rewrite_query,

            "should_retrieve": should_retrieve,

            "should_call_tool": should_call_tool,

            "should_use_memory": should_use_memory,

            "should_persist_memory": should_persist_memory,

            "should_vectorize_memory": should_vectorize_memory,

            "should_emit_retrieval_events": should_retrieve,

            "missing_slots": list(intent.missing_slots),

            "resolved_references": updated_resolved,

            "route_reason": routing.route_reason or intent_name or routing.input_quality.reason,

            "route_candidate": fast_result.extra.get("route_candidate") if isinstance(fast_result.extra, Mapping) else routing.route_candidate,

            "preferred_chunk_roles": preferred_chunk_roles,

            "tool_candidates": tool_candidates,

            "clarification_question": extra_slots.get("clarification_question", routing.clarification_question),

            "extra": extra,

        }

    )


def build_rewrite_decision(

    original_query: str,

    rewritten_query: str,

    *,

    confidence: float,

    reason: str,

    preserved_constraints: Sequence[str] | None = None,

    extra: Mapping[str, Any] | None = None,

) -> RewriteDecision:

    original = normalize_query(original_query)

    rewritten = normalize_query(rewritten_query)

    original_tokens = Counter(_content_tokens(original))

    rewritten_tokens = Counter(_content_tokens(rewritten))

    added_terms = list((rewritten_tokens - original_tokens).elements())

    removed_terms = list((original_tokens - rewritten_tokens).elements())

    preserved = list(preserved_constraints or [])

    risky = bool(added_terms) and (confidence < 0.65 or len(added_terms) > max(2, len(preserved) + 1))

    should_retrieve = bool(rewritten and confidence >= 0.4 and not risky)

    return RewriteDecision(

        original_query=original,

        rewritten_query=rewritten or original,

        added_terms=added_terms,

        removed_terms=removed_terms,

        preserved_constraints=preserved,

        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),

        should_retrieve=should_retrieve,

        reason=reason,

        risky_rewrite=risky,

    )
