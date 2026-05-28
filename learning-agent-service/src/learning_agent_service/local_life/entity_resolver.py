from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from .execution_contract import ExecutionContract
from .schemas import LocalLifeSlots

_PRONOUNS = ("这家", "这店", "这间", "它", "刚才那家", "刚才那个", "这商家", "这个商家")
_EXPLICIT_SUFFIXES = (
    "怎么样",
    "有券吗",
    "有券",
    "适合约会吗",
    "适合吗",
    "好不好",
    "值不值得",
    "值不值",
    "营业吗",
    "现在营业吗",
    "现在有券吗",
    "现在能不能订",
    "现在能不能约",
    "现在开吗",
    "适合带爸妈吗",
    "适合家庭聚餐吗",
    "呢",
    "店呢",
    "家呢",
    "商家呢",
    "哪个呢",
    "怎么样呢",
    "有券吗呢",
    "营业吗呢",
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _get_val(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _explicit_entity_from_query(raw_query: str) -> str | None:
    text = (raw_query or "").strip()
    if not text:
        return None
    compact = text.rstrip("？?。.!！")
    if compact.startswith("那"):
        compact = re.sub(r"^那[，,\s]?", "", compact).strip()
    for pronoun in _PRONOUNS:
        idx = compact.find(pronoun)
        if idx > 0:
            prefix = compact[:idx].strip(" ，,;；")
            if prefix and prefix not in _PRONOUNS:
                return prefix
    for suffix in _EXPLICIT_SUFFIXES:
        if compact.endswith(suffix):
            prefix = compact[: -len(suffix)].strip(" ，,;；")
            if prefix and prefix not in _PRONOUNS:
                return prefix
    match = re.match(r"^(?P<name>.+?)(?:\s+)?(什么|哪家|哪个好|行不行|可以吗)$", compact)
    if match:
        prefix = match.group("name").strip(" ，,;；")
        if prefix and prefix not in _PRONOUNS:
            return prefix
    return None


def _is_pronoun_only_query(raw_query: str, explicit_entity: str | None) -> bool:
    if explicit_entity:
        return False
    compact = (raw_query or "").strip()
    if not compact:
        return False
    return any(pronoun in compact for pronoun in _PRONOUNS)


class EntityResolver:
    def resolve(
        self,
        *,
        raw_query: str,
        slots: LocalLifeSlots,
        user_need: Any | None = None,
        session_context: Mapping[str, Any] | None = None,
        query_route: Any | None = None,
        client_context: Mapping[str, Any] | None = None,
    ) -> ExecutionContract:
        session_context_map = _as_mapping(session_context)
        client_context_map = _as_mapping(client_context)
        user_need_map = _as_mapping(user_need)
        explicit_entity = _explicit_entity_from_query(raw_query)
        pronoun_only = _is_pronoun_only_query(raw_query, explicit_entity)

        context_refs = list(getattr(user_need, "context_refs", []) or [])
        resolved_shop_id: Optional[int] = None
        resolved_shop_name: Optional[str] = None
        candidate_shop_ids: list[int] = []
        shop_context_source: Optional[str] = None

        def add_candidate(value: Any) -> None:
            shop_id = _first_int(value)
            if shop_id is None or shop_id in candidate_shop_ids:
                return
            candidate_shop_ids.append(shop_id)

        # 1. 物理隔离高优先级代词指代解析：优先扫描并绑定用户显式口头提问 (ref_source == "explicit_entity") 的引用，防止静态页面默认抢占
        explicit_refs = [r for r in context_refs if _clean_text(_get_val(r, "source")) == "explicit_entity"]
        other_refs = [r for r in context_refs if _clean_text(_get_val(r, "source")) != "explicit_entity"]

        for ref in explicit_refs:
            ref_type = _get_val(ref, "type")
            ref_id = _get_val(ref, "id")
            ref_name = _clean_text(_get_val(ref, "name"))
            ref_source = _clean_text(_get_val(ref, "source"))
            if ref_type == "shop":
                if ref_id not in (None, ""):
                    add_candidate(ref_id)
                    if resolved_shop_id is None:
                        resolved_shop_id = _first_int(ref_id)
                        resolved_shop_name = ref_name
                        shop_context_source = ref_source or "explicit_entity"
                elif explicit_entity and resolved_shop_name is None:
                    resolved_shop_name = explicit_entity
                    shop_context_source = "query"

        for ref in other_refs:
            ref_type = _get_val(ref, "type")
            ref_id = _get_val(ref, "id")
            ref_name = _clean_text(_get_val(ref, "name"))
            ref_source = _clean_text(_get_val(ref, "source"))
            if ref_type == "shop":
                if ref_id not in (None, ""):
                    add_candidate(ref_id)
                    if resolved_shop_id is None:
                        resolved_shop_id = _first_int(ref_id)
                        resolved_shop_name = ref_name
                        shop_context_source = ref_source or "context_ref"
                elif explicit_entity and resolved_shop_name is None:
                    resolved_shop_name = explicit_entity
                    shop_context_source = "query"

        if explicit_entity and resolved_shop_name is None:
            resolved_shop_name = explicit_entity
            shop_context_source = "query"
            for value in slots.shop_ids:
                add_candidate(value)
            if resolved_shop_id is None:
                for value in slots.shop_ids:
                    resolved_shop_id = _first_int(value)
                    if resolved_shop_id is not None:
                        break
        elif slots.shop_query and slots.shop_query.strip() and resolved_shop_name is None:
            resolved_shop_name = _clean_text(slots.shop_query)
            if slots.shop_ids:
                resolved_shop_id = _first_int(slots.shop_ids[0])
                shop_context_source = "slot"

        if resolved_shop_id is None and not explicit_entity:
            selected_shop_id = _first_int(session_context_map.get("selected_shop_id") or session_context_map.get("current_shop_id"))
            current_shop_name = _clean_text(session_context_map.get("selected_shop_name") or session_context_map.get("current_shop"))
            if selected_shop_id is not None:
                resolved_shop_id = selected_shop_id
                resolved_shop_name = resolved_shop_name or current_shop_name
                add_candidate(selected_shop_id)
                shop_context_source = shop_context_source or "session"
            elif current_shop_name and not pronoun_only:
                resolved_shop_name = resolved_shop_name or current_shop_name
                shop_context_source = shop_context_source or "session"

        if not explicit_entity:
            for item in session_context_map.get("last_candidates") or []:
                if isinstance(item, Mapping):
                    add_candidate(item.get("shop_id") or item.get("id"))

        if not candidate_shop_ids and resolved_shop_id is not None:
            add_candidate(resolved_shop_id)

        intent = str(getattr(user_need, "intent", None) or user_need_map.get("intent") or "")
        if pronoun_only and resolved_shop_id is None and not candidate_shop_ids:
            clarification_action = "reference_clarify"
            forbid_global_fallback = True
        elif resolved_shop_id is None and intent in ("local_life_shop_detail", "local_life_coupon_query", "coupon", "detail"):
            clarification_action = "reference_clarify"
            forbid_global_fallback = True
        else:
            clarification_action = None
            forbid_global_fallback = bool(explicit_entity)

        execute_rag = bool(getattr(query_route, "use_qdrant", True))
        execute_tools = list(getattr(query_route, "extra", {}) or {}).copy()
        if isinstance(query_route, Mapping):
            execute_tools = list(query_route.get("extra", {}).keys()) if isinstance(query_route.get("extra"), Mapping) else []

        required_facets = []
        if hasattr(user_need, "required_facets"):
            required_facets = [getattr(facet, "name", str(facet)) for facet in getattr(user_need, "required_facets", []) or []]
        elif user_need_map.get("required_facets"):
            required_facets = [str(item.get("name") or item) for item in user_need_map.get("required_facets") or []]

        city = _clean_text(slots.city or client_context_map.get("city") or session_context_map.get("current_city") or session_context_map.get("city"))
        area = _clean_text(client_context_map.get("area") or client_context_map.get("district") or session_context_map.get("area"))
        category = _clean_text(slots.category)
        price_max = slots.price.per_person_max or slots.price.target
        scene_keywords = list(dict.fromkeys([*(slots.preferences or []), *(slots.avoid or [])]))

        # 2. 品类解耦相关性过滤器 (Category Disjoint Filter)：
        # 若用户明确查询非餐饮的品类（如 KTV, SPA, 酒店, 唱歌 等），而当前绑定的商家并没有这些休闲娱乐的词汇，说明意图彻底跳转，解绑页面/历史商家上下文
        if category and resolved_shop_name:
            category_lower = str(category).lower()
            shop_name_lower = str(resolved_shop_name).lower()
            leisure_words = {"ktv", "唱歌", "足疗", "spa", "按摩", "酒店", "机票", "电影院", "洗浴", "唱歌"}
            if any(w in category_lower for w in leisure_words) and not any(w in shop_name_lower for w in leisure_words):
                resolved_shop_id = None
                resolved_shop_name = None
                candidate_shop_ids = []
                shop_context_source = None

        return ExecutionContract(
            raw_query=raw_query,
            resolved_query=explicit_entity or _clean_text(slots.shop_query) or raw_query.strip(),
            intent=str(getattr(user_need, "intent", None) or user_need_map.get("intent") or ""),
            resolved_shop_id=resolved_shop_id,
            resolved_shop_name=resolved_shop_name,
            candidate_shop_ids=candidate_shop_ids,
            required_facets=required_facets,
            execute_rag=execute_rag,
            execute_tools=execute_tools,
            city=city,
            area=area,
            category=category,
            shop_type_id=_first_int(client_context_map.get("shop_type_id") or client_context_map.get("typeId") or client_context_map.get("shopTypeId")),
            price_max=price_max,
            scene_keywords=scene_keywords,
            negative_categories=list(dict.fromkeys(slots.avoid or [])),
            clarification_action=clarification_action,
            forbid_global_fallback=forbid_global_fallback,
            reason="explicit_entity" if explicit_entity else ("pronoun_reference" if pronoun_only else "session_context"),
            source=shop_context_source or ("query" if explicit_entity else ("reference" if pronoun_only else "session")),
            shop_context_source=shop_context_source,
            extra={
                "explicit_entity": explicit_entity,
                "pronoun_only": pronoun_only,
                "user_need": user_need_map,
            },
        )
