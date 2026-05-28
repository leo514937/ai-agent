from __future__ import annotations

from typing import Any, Mapping

from .schemas import LocalLifeSlots, UserNeed


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


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
    ) -> dict[str, Any]:
        session = _as_mapping(session_context)
        client = _as_mapping(client_context)
        pending_user_need = _as_mapping(session.get("pending_user_need"))
        pending_clarification = _as_mapping(session.get("pending_clarification"))
        pending_source = dict(pending_user_need or pending_clarification)
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
                if p_cat != c_cat and c_cat not in ("餐厅", "美食", "吃喝", "店", "商家", ""):
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
            merged_need = UserNeed.model_validate(
                {
                     **user_need.model_dump(mode="json"),
                     "slots": merged_slots.model_dump(mode="json"),
                     "constraints": merged_constraints,
                     "required_facets": _merge_required_facets(user_need.required_facets, pending_source),
                     "context_refs": [ref.model_dump(mode="json") if hasattr(ref, "model_dump") else dict(ref) for ref in user_need.context_refs or []],
                }
            )
            restored = True
            clarification_action = "resume_pending_need"

        return {
            "user_need": merged_need,
            "pending_user_need": pending_source or {},
            "restored_pending_need": restored,
            "clarification_action": clarification_action,
            "source": "pending_user_need" if restored else "query",
            "reason": "pending_need_restored" if restored else "query_first",
        }
