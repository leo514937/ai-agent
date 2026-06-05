from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .graph_state import (
    MemoryArbitrationPolicy,
    build_memory_arbitration_result,
    build_perception_context,
)
from .schemas import LocalLifeSlots, UserNeed


def _is_blank(value: Any) -> bool:
    return value in (None, "", [], {}, ())


def _merge_slots(base: LocalLifeSlots, pending: Mapping[str, Any], current_query: str) -> LocalLifeSlots:
    pending_slots = dict(_as_mapping(pending.get("slots")))
    base_map = base.model_dump(mode="json")
    merged = dict(base_map)

    # 1. 级联失效判定：若本轮抽取的城市与 pending 城市存在且不同，说明重置了定位城市，清空与旧城市强相关的空间及子实体槽位
    current_city = merged.get("city")
    pending_city = pending_slots.get("city")
    if current_city and pending_city and str(current_city).strip() != str(pending_city).strip():
        pending_slots["shop_query"] = None
        pending_slots["shop_ids"] = []
        pending_slots["location"] = {}

    # 2. 特异性等级校验 (Specificity Check)：定义泛指代词表，防止具体店名商圈等被本轮口头低特异性代词静默覆盖
    for key in ("category", "city", "scene", "shop_query", "page"):
        current_value = merged.get(key)
        current_str = str(current_value or "").strip()
        
        is_generic = False
        if key == "category" and current_str in {"餐厅", "美食", "吃喝", "店", "商家", ""}:
            is_generic = True
        elif key == "shop_query" and current_str in {"这家店", "这店", "这里", "这间", "它", "这个商家", "刚才那家", "刚才那个"}:
            is_generic = True

        if (_is_blank(current_value) or is_generic) and not _is_blank(pending_slots.get(key)):
            merged[key] = pending_slots.get(key)

    base_price = _as_mapping(merged.get("price"))
    pending_price = _as_mapping(pending_slots.get("price"))
    for key in ("per_person_min", "per_person_max", "target"):
        if _is_blank(base_price.get(key)) and not _is_blank(pending_price.get(key)):
            base_price[key] = pending_price.get(key)
    merged["price"] = base_price

    base_location = _as_mapping(merged.get("location"))
    pending_location = _as_mapping(pending_slots.get("location"))
    for key in ("city", "lat", "lng", "radius_km"):
        if _is_blank(base_location.get(key)) and not _is_blank(pending_location.get(key)):
            base_location[key] = pending_location.get(key)
    merged["location"] = base_location

    # 3. 冲突消解逻辑 (Collision Resolution)：去重拼接，若 preferences 与 avoid 中有元素相交矛盾，以正面偏好为准，剔除 avoid
    for key in ("companions", "preferences", "avoid"):
        merged[key] = list(dict.fromkeys([*(pending_slots.get(key) or []), *(merged.get(key) or [])]))
    
    pref_set = set(merged.get("preferences") or [])
    avoid_set = set(merged.get("avoid") or [])
    conflict = set()
    for p in pref_set:
        for a in avoid_set:
            if (a and p) and (a in p or p in a):
                conflict.add(a)
    if conflict:
        merged["avoid"] = [x for x in merged["avoid"] if x not in conflict]

    if not merged.get("shop_ids") and pending_slots.get("shop_ids"):
        merged["shop_ids"] = list(pending_slots.get("shop_ids") or [])

    if _is_blank(merged.get("shop_query")) and pending_slots.get("shop_query"):
        merged["shop_query"] = pending_slots.get("shop_query")

    return LocalLifeSlots.model_validate(merged)


def _merge_required_facets(current: list[Any], pending: Mapping[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: Any) -> None:
        item_map = _as_mapping(item)
        name = str(item_map.get("name") or "").strip()
        if not name:
            return
        if name in seen:
            return
        seen.add(name)
        merged.append(
            {
                "name": name,
                "required": bool(item_map.get("required", True)),
                "data_source": str(item_map.get("data_source") or "slot"),
                "freshness": str(item_map.get("freshness") or "static_ok"),
                "entity_keys": list(item_map.get("entity_keys") or []),
                "missing_policy": str(item_map.get("missing_policy") or "partial_grounded"),
            }
        )

    for item in current or []:
        add(item)
    for item in pending.get("required_facets") or []:
        add(item)
    return merged


class ContextArbitration:
    def arbitrate(
        self,
        *,
        raw_query: str,
        slots: LocalLifeSlots,
        user_need: UserNeed,
        session_context: Mapping[str, Any] | None = None,
        client_context: Mapping[str, Any] | None = None,
        perception_context: Any | None = None,
        policy: MemoryArbitrationPolicy | None = None,
    ) -> dict[str, Any]:
        session = _as_mapping(session_context)
        client = _as_mapping(client_context)
        perception = perception_context or build_perception_context(
            raw_query=raw_query,
            normalized_query=raw_query,
            slots=slots,
            client_context=client,
            session_context=session,
        )
        if isinstance(policy, Mapping):
            policy = MemoryArbitrationPolicy(
                **{
                    key: value
                    for key, value in _as_mapping(policy).items()
                    if key in {"priority_source", "session_keywords", "long_term_keywords", "strict_latest_turn"}
                }
            )
        else:
            policy = policy or MemoryArbitrationPolicy()
        pending_user_need = _as_mapping(session.get("pending_user_need"))
        pending_clarification = _as_mapping(session.get("pending_clarification"))
        pending_source = dict(pending_user_need or pending_clarification)
        previous_topic = str(
            session.get("current_topic")
            or (session.get("clarification_result") or {}).get("original_query")
            or ""
        ).strip()
        merged_need = user_need
        restored = False
        clarification_action = None

        if pending_source:
            # 4. 意图与品类漂移保护 (Intent Drift Guard)：
            # 若挂起品类存在，且当前抽取出的品类也存在且不相同，且新抽取品类不是泛指品类，则判定用户转移了话题
            pending_slots_data = _as_mapping(pending_source.get("slots"))
            pending_category = pending_slots_data.get("category")
            current_category = slots.category
            
            is_drift = False
            if pending_category and current_category:
                p_cat = str(pending_category).strip()
                c_cat = str(current_category).strip()
                if p_cat != c_cat and c_cat not in ("餐厅", "美食", "吃喝", "店", "商家", "") and p_cat not in ("餐厅", "美食", "吃喝", "店", "商家", ""):
                    is_drift = True
            
            # 如果发生意图/品类漂移，主动清除 pending 并重置为全新状态，阻止合并
            if is_drift:
                pending_source = {}
                pending_user_need = {}
                pending_clarification = {}


        if pending_source:
            merged_slots = _merge_slots(user_need.slots, pending_source, raw_query)
            merged_constraints = dict(user_need.constraints)
            if not merged_constraints.get("client_context") and client:
                merged_constraints["client_context"] = client
            if not merged_constraints.get("pending_user_need") and pending_user_need:
                merged_constraints["pending_user_need"] = pending_user_need
            restored_intent = str(
                pending_source.get("intent")
                or pending_user_need.get("intent")
                or pending_clarification.get("intent")
                or user_need.intent
            )
            if restored_intent == str(user_need.intent) or restored_intent not in {"coupon", "open_status", "distance_eta"}:
                topic_hint = str(
                    previous_topic
                    or pending_source.get("question")
                    or pending_clarification.get("question")
                    or pending_source.get("original_query")
                    or ""
                ).strip()
                coupon_keywords = ("券", "优惠", "领券", "打折", "代金券", "折扣", "团购")
                open_keywords = ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗")
                distance_keywords = ("距离", "有多远", "导航", "路线", "怎么走", "怎么去")
                if any(token in topic_hint for token in coupon_keywords):
                    restored_intent = "coupon"
                elif any(token in topic_hint for token in open_keywords):
                    restored_intent = "open_status"
                elif any(token in topic_hint for token in distance_keywords):
                    restored_intent = "distance_eta"
            merged_facets = _merge_required_facets(user_need.required_facets, pending_source)
            if restored_intent in ("coupon", "open_status", "distance_eta"):
                merged_facets = [f for f in merged_facets if f.get("name") == restored_intent]
                if not merged_facets:
                    merged_facets = [{
                        "name": restored_intent,
                        "required": True,
                        "data_source": "dynamic_tool" if restored_intent != "distance_eta" else "client_context",
                        "freshness": "near_realtime_required",
                        "entity_keys": ["shop_id", "coupon_id"] if restored_intent == "coupon" else ["shop_id"],
                        "missing_policy": "partial_grounded",
                    }]
            merged_need = UserNeed.model_validate(
                {
                     **user_need.model_dump(mode="json"),
                     "intent": restored_intent,
                     "slots": merged_slots.model_dump(mode="json"),
                     "constraints": merged_constraints,
                     "required_facets": merged_facets,
                     "context_refs": [ref.model_dump(mode="json") if hasattr(ref, "model_dump") else dict(ref) for ref in user_need.context_refs or []],
                }
            )
            restored = True
            clarification_action = "resume_pending_need"

        if not restored and session.get("current_action") in ("coupon", "open_status", "distance_eta"):
            prev_action = session.get("current_action")
            opposing_keywords = ["环境", "服务", "口味", "特色", "怎么样", "推荐", "好吗", "评价", "好不好", "菜单", "价格"]
            if not any(k in raw_query for k in opposing_keywords):
                restored_intent = prev_action
                merged_facets = [{
                    "name": restored_intent,
                    "required": True,
                    "data_source": "dynamic_tool" if restored_intent != "distance_eta" else "client_context",
                    "freshness": "near_realtime_required",
                    "entity_keys": ["shop_id", "coupon_id"] if restored_intent == "coupon" else ["shop_id"],
                    "missing_policy": "partial_grounded",
                }]
                merged_need = UserNeed.model_validate(
                    {
                         **user_need.model_dump(mode="json"),
                         "intent": restored_intent,
                         "required_facets": merged_facets,
                    }
                )
                restored = True
                clarification_action = "carry_over_intent"

        if not restored:
            previous_route = str(session.get("route_decision") or "").strip().lower()
            compact_query = str(raw_query or "").replace(" ", "")
            raw_query_is_shop_hint = bool(
                any(token in compact_query for token in ("店", "门店", "分店", "商场"))
                or (
                    len(compact_query) <= 6
                    and not any(token in compact_query for token in ("券", "优惠", "营业", "距离", "推荐", "评价", "怎么样", "好不好"))
                )
            )
            if raw_query_is_shop_hint and previous_topic:
                coupon_keywords = ("券", "优惠", "领券", "打折", "代金券", "折扣", "团购")
                open_keywords = ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗")
                distance_keywords = ("距离", "有多远", "导航", "路线", "怎么走", "怎么去")
                inferred_pending_intent = None
                if any(token in previous_topic for token in coupon_keywords):
                    inferred_pending_intent = "coupon"
                elif any(token in previous_topic for token in open_keywords):
                    inferred_pending_intent = "open_status"
                elif any(token in previous_topic for token in distance_keywords):
                    inferred_pending_intent = "distance_eta"

                if inferred_pending_intent is not None:
                    merged_facets = _merge_required_facets(user_need.required_facets, {"intent": inferred_pending_intent})
                    if inferred_pending_intent in ("coupon", "open_status", "distance_eta"):
                        merged_facets = [f for f in merged_facets if f.get("name") == inferred_pending_intent]
                        if not merged_facets:
                            merged_facets = [{
                                "name": inferred_pending_intent,
                                "required": True,
                                "data_source": "dynamic_tool" if inferred_pending_intent != "distance_eta" else "client_context",
                                "freshness": "near_realtime_required",
                                "entity_keys": ["shop_id", "coupon_id"] if inferred_pending_intent == "coupon" else ["shop_id"],
                                "missing_policy": "partial_grounded",
                            }]
                    merged_need = UserNeed.model_validate(
                        {
                        **user_need.model_dump(mode="json"),
                        "intent": inferred_pending_intent,
                        "required_facets": merged_facets,
                    }
                )
                restored = True
                clarification_action = "resume_session_clarify" if previous_route == "clarify" else "resume_topic_clarify"

        memory_arbitration = build_memory_arbitration_result(
            merged_context={
                "user_need": merged_need.model_dump(mode="json"),
                "pending_user_need": pending_source or {},
                "restored_pending_need": restored,
                "clarification_action": clarification_action,
                "source": "pending_user_need" if restored else "query",
                "reason": "pending_need_restored" if restored else "query_first",
                "priority_source": policy.priority_source,
                "temporal_scope": getattr(perception, "temporal_scope", "neutral"),
            },
            winning_sources={
                "priority_source": policy.priority_source,
                "temporal_scope": getattr(perception, "temporal_scope", "neutral"),
                "client_context": bool(client),
                "session_context": bool(session),
            },
            suppressed_memories=[],
            promotion_candidates=(
                [{"raw_query": raw_query, "temporal_scope": getattr(perception, "temporal_scope", "neutral")}]
                if getattr(perception, "temporal_scope", "neutral") == "long_term"
                else []
            ),
            conflict_reason="pending_need_restored" if restored else None,
        )
        return {
            "user_need": merged_need,
            "pending_user_need": pending_source or {},
            "pending_intent": pending_source.get("intent") if pending_source else None,
            "restored_pending_need": restored,
            "clarification_action": clarification_action,
            "source": "pending_user_need" if restored else "query",
            "reason": "pending_need_restored" if restored else "query_first",
            "perception_context": perception.to_dict() if hasattr(perception, "to_dict") else perception,
            "memory_arbitration": memory_arbitration.to_dict(),
        }
