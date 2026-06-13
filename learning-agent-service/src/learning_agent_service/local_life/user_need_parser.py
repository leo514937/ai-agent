from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .scene_policy import ScenePolicy
from .schemas import ContextRef, LocalLifeSlots, RequiredFacet, UserNeed

# Keywords for checking facets in raw queries
SCENE_KEYWORDS = ("约会", "氛围", "情侣", "带娃", "聚餐", "安静", "吵", "包间", "长辈", "父母", "老人", "家庭")
COUPON_KEYWORDS = ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购")
OPEN_KEYWORDS = ("营业", "开门", "开着", "营业时间", "现在是否开门")
LOCATION_KEYWORDS = ("附近", "周边", "哪里", "这附近", "距离", "有多远")
PRICE_KEYWORDS = ("人均", "便宜", "价格", "贵", "消费", "消费水平")
DISTANCE_KEYWORDS = ("离我多远", "距离", "有多远", "导航", "路线", "怎么走", "怎么去")
DETAIL_KEYWORDS = ("招牌", "特色", "推荐菜", "评价", "口碑", "服务", "环境")

PRONOUNS = ("它", "这家", "这店", "这间", "刚才那家", "这商家", "这个商家", "刚才那个")


def _has_explicit_entity_in_query(query: str, slots: LocalLifeSlots) -> bool:
    """检测 query 中是否含有显式店名（不同于纯代词指代）。
    规则：slots.shop_query 非空且不是代词本身，则认为含显式实体。
    用于'INLOVE KTV 这家有券吗'场景——显式实体优先，不沿用 session 历史。
    """
    sq = (slots.shop_query or "").strip()
    if not sq:
        return False
    # 如果 shop_query 本身就是代词，不算显式
    if sq in PRONOUNS:
        return False
    return True


class UserNeedParser:
    @staticmethod
    def parse(
        query: str,
        *,
        slots: LocalLifeSlots,
        intent: Any,
        client_context: Mapping[str, Any] | None = None,
        session_context: Mapping[str, Any] | None = None,
    ) -> UserNeed:
        client_ctx = client_context or {}
        session_ctx = session_context or {}
        normalized_query = query.strip().lower()

        # 1. Resolve Pronouns / Context References
        # 规则：显式实体（slots.shop_query 含非代词店名）的优先级 > 代词历史解析
        context_refs: list[ContextRef] = []
        has_pronoun = any(p in normalized_query for p in PRONOUNS)
        has_explicit_entity = _has_explicit_entity_in_query(normalized_query, slots)

        # 隐式指代消解：如果意图是商户特异性的（如查券、查详情、导航等），且用户未显式提及店名或ID，
        # 则视为隐式指代，自动从 session 历史中提取最近提到的商户，行为等同于“这家/它”
        intent_str = str(intent.value if hasattr(intent, "value") else intent)
        is_implicit_ref = (
            intent_str in ("coupon", "detail", "navigation", "booking", "order_status")
            and not has_explicit_entity
            and not slots.shop_ids
        )

        if has_explicit_entity:
            # ★ 显式实体优先：query 含明确店名（如 "INLOVE KTV 这家有券吗"），
            # 绑定当前显式实体，不沿用 session 历史 shop_id
            context_refs.append(
                ContextRef(
                    type="shop",
                    id=str(slots.shop_ids[0]) if slots.shop_ids else None,
                    name=slots.shop_query,
                    source="explicit_entity",
                    confidence=0.98,
                )
            )
        elif slots.shop_ids:
            # slots 直接带有 shop_ids（由 slot_extractor 解析出来的精确 ID）
            for shop_id in slots.shop_ids:
                context_refs.append(
                    ContextRef(
                        type="shop",
                        id=str(shop_id),
                        name=slots.shop_query or f"商户{shop_id}",
                        source="slots",
                        confidence=0.95,
                    )
                )
        elif has_pronoun or is_implicit_ref:
            # 纯代词：从 session 历史解析
                shop_id = session_ctx.get("selected_shop_id") or session_ctx.get("current_shop_id")
                shop_name = session_ctx.get("selected_shop_name") or session_ctx.get("current_shop")

                # 正则防御性解析：如果 shop_id 没拿到，但 shop_name / current_shop 里类似于 shop:N，提取出真实的 shop_id (P0-Fix)
                import re as _re
                if shop_id in (None, ""):
                    for val in (shop_name, session_ctx.get("current_shop"), session_ctx.get("selected_shop_name")):
                        if val:
                            match = _re.match(r"^shop:(\d+)$", str(val).strip())
                            if match:
                                shop_id = int(match.group(1))
                                break

                if shop_id not in (None, ""):
                    context_refs.append(
                        ContextRef(
                            type="shop",
                            id=str(shop_id),
                            name=str(shop_name) if shop_name else f"商户{shop_id}",
                            source="session_context",
                            confidence=0.9,
                        )
                    )
                else:
                    last_candidates = session_ctx.get("last_candidates") or []
                    if isinstance(last_candidates, list) and len(last_candidates) > 0:
                        for item in last_candidates:
                            if isinstance(item, Mapping):
                                sid = item.get("shop_id") or item.get("id")
                                sname = item.get("name") or item.get("shop_name")
                                if sid is not None:
                                    context_refs.append(
                                        ContextRef(
                                            type="shop",
                                            id=str(sid),
                                            name=str(sname) if sname else None,
                                            source="recent_entities",
                                            confidence=0.9,
                                        )
                                    )
                                    break

        # 2. Extract Required and Optional Facets
        required_facets: list[RequiredFacet] = []
        optional_facets: list[RequiredFacet] = []

        # Location Facet
        has_location_ctx = (
            client_ctx.get("city") is not None
            or client_ctx.get("lat") is not None
            or client_ctx.get("lng") is not None
            or slots.city is not None
            or slots.location.city is not None
        )
        has_location_keyword = any(k in normalized_query for k in LOCATION_KEYWORDS)
        
        if has_location_keyword or has_location_ctx:
            required_facets.append(
                RequiredFacet(
                    name="location",
                    required=True,
                    data_source="client_context" if has_location_ctx else "slot",
                    freshness="near_realtime_required",
                    entity_keys=["location_id"],
                    missing_policy="ask_clarification" if not has_location_ctx else "partial_grounded",
                )
            )

        # Category Facet
        has_category = bool(slots.category and slots.category != "餐厅")
        if has_category or any(keyword in normalized_query for keyword in ("火锅", "粤菜", "川菜", "烧烤", "日料", "家常菜")):
            required_facets.append(
                RequiredFacet(
                    name="category",
                    required=True,
                    data_source="slot",
                    freshness="static_ok",
                    entity_keys=[],
                    missing_policy="partial_grounded",
                )
            )

        # Scene Fit Facet
        has_scene_query = any(k in normalized_query for k in SCENE_KEYWORDS) or slots.scene is not None
        if has_scene_query:
            required_facets.append(
                RequiredFacet(
                    name="scene_fit",
                    required=True,
                    data_source="static_rag",
                    freshness="static_ok",
                    entity_keys=["shop_id"],
                    missing_policy="partial_grounded",
                )
            )

        # Coupon Facet (Dynamic)
        has_coupon_query = any(k in normalized_query for k in COUPON_KEYWORDS) or intent == "coupon"
        if has_coupon_query:
            required_facets.append(
                RequiredFacet(
                    name="coupon",
                    required=True,
                    data_source="dynamic_tool",
                    freshness="near_realtime_required",
                    entity_keys=["shop_id", "coupon_id"],
                    missing_policy="partial_grounded",
                )
            )

        # Open Status Facet (Dynamic)
        has_open_query = any(k in normalized_query for k in OPEN_KEYWORDS)
        if has_open_query:
            required_facets.append(
                RequiredFacet(
                    name="open_status",
                    required=True,
                    data_source="dynamic_tool",
                    freshness="near_realtime_required",
                    entity_keys=["shop_id"],
                    missing_policy="partial_grounded",
                )
            )

        # Price Facet
        has_price_query = any(k in normalized_query for k in PRICE_KEYWORDS) or (slots.price.target is not None or slots.price.per_person_max is not None)
        if has_price_query:
            required_facets.append(
                RequiredFacet(
                    name="price",
                    required=True,
                    data_source="static_rag",
                    freshness="static_ok",
                    entity_keys=["shop_id"],
                    missing_policy="partial_grounded",
                )
            )

        # Distance ETA Facet (Dynamic)
        has_dist_query = any(k in normalized_query for k in DISTANCE_KEYWORDS) or intent == "navigation"
        if has_dist_query:
            required_facets.append(
                RequiredFacet(
                    name="distance_eta",
                    required=True,
                    data_source="dynamic_tool",
                    freshness="near_realtime_required",
                    entity_keys=["shop_id"],
                    missing_policy="ask_clarification" if not has_location_ctx else "partial_grounded",
                )
            )

        # Shop Detail Facet
        intent_str = str(intent.value if hasattr(intent, "value") else intent)
        has_detail_query = any(k in normalized_query for k in DETAIL_KEYWORDS) or intent_str == "detail"
        if has_detail_query:
            required_facets.append(
                RequiredFacet(
                    name="shop_detail",
                    required=True,
                    data_source="static_rag",
                    freshness="static_ok",
                    entity_keys=["shop_id"],
                    missing_policy="partial_grounded",
                )
            )

        # Recommendation Reason
        optional_facets.append(
            RequiredFacet(
                name="recommendation_reason",
                required=False,
                data_source="mixed",
                freshness="static_ok",
                entity_keys=["shop_id"],
                missing_policy="partial_grounded",
            )
        )

        # 3. Missing slots determination
        missing_slots: list[str] = []
        from learning_agent_service.local_life.clarification_strategy import ClarificationStrategy

        pending_ambiguity = ""
        pending_clarification = session_ctx.get("pending_clarification")
        if isinstance(pending_clarification, Mapping):
            pending_ambiguity = str(pending_clarification.get("ambiguity_type") or "").strip().lower()
        clarification_asked_slots: list[str] = []
        if pending_ambiguity in {"location", "city", "area", "district", "region"}:
            clarification_asked_slots.append("location")
        elif pending_ambiguity in {"reference_clarify", "shop_name"}:
            clarification_asked_slots.append("shop_name")
        elif pending_ambiguity == "category":
            clarification_asked_slots.append("category")

        should_clarify_location = ClarificationStrategy.should_clarify_location(
            is_recommendation=bool(has_location_keyword or intent == "restaurant_recommendation"),
            has_location_slot=has_location_ctx,
            has_explicit_shop=bool(slots.shop_query or slots.shop_ids),
        )
        if should_clarify_location:
            missing_slots.append("location")

        constraints: dict[str, Any] = {}
        detected_scene = ScenePolicy.detect_scene(query)
        if detected_scene:
            constraints["scene_detected"] = detected_scene
        scene_preferred_facets = ScenePolicy.get_preferred_facets(query)
        if scene_preferred_facets:
            constraints["scene_preferred_facets"] = scene_preferred_facets
        if slots.scene:
            constraints["scene"] = slots.scene
        if slots.preferences:
            constraints["preferences"] = list(slots.preferences)
        if slots.avoid:
            constraints["avoid"] = list(slots.avoid)
        if clarification_asked_slots:
            constraints["clarification_asked_slots"] = clarification_asked_slots

        has_context_shop = bool(
            session_ctx.get("selected_shop_id")
            or session_ctx.get("current_shop_id")
            or session_ctx.get("selected_shop_name")
            or session_ctx.get("current_shop")
            or client_ctx.get("selected_shop_id")
            or client_ctx.get("shopId")
            or client_ctx.get("selected_shop_name")
            or client_ctx.get("shopName")
        )
        priority_slot = ClarificationStrategy.get_clarification_priority(
            missing_slots=missing_slots,
            intent=intent_str,
            has_context_shop=has_context_shop,
        )
        if priority_slot:
            constraints["clarification_priority_slot"] = priority_slot
            missing_slots = [priority_slot, *[slot for slot in missing_slots if slot != priority_slot]]

        # Parse recommendation count
        recommendation_count = 3
        if "推荐一家" in query or "推荐一个" in query or "推荐1家" in query:
            recommendation_count = 1
        elif "多推荐几家" in query or "多推荐几个" in query or "推荐5家" in query or "多推荐" in query:
            recommendation_count = 5

        return UserNeed(
            intent=str(intent.value if hasattr(intent, "value") else intent),
            raw_query=query,
            resolved_query=query,
            slots=slots,
            constraints=constraints,
            required_facets=required_facets,
            optional_facets=optional_facets,
            missing_slots=missing_slots,
            context_refs=context_refs,
            recommendation_count=recommendation_count,
        )

