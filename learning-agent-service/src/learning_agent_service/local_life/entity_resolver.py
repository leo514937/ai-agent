from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .catalog import get_default_catalog
from .facet_execution_plan import FacetExecutionItem, FacetExecutionPlan
from .schemas import LocalLifeSlots
from .target_shop_policy import TargetShopPolicy

_PRONOUNS = ("这家", "这店", "这间", "它", "他", "她", "刚才那家", "刚才那个", "这商家", "这个商家", "这几家", "第一家", "第二家")
_EXPLICIT_SUFFIXES = (
    "现在营业吗",
    "现在有券吗",
    "现在能不能订",
    "现在能不能约",
    "现在开吗",
    "适合带爸妈吗",
    "适合家庭聚餐吗",
    "怎么样呢",
    "有券吗呢",
    "营业吗呢",
    "怎么样",
    "有券吗",
    "有券",
    "有几张券",
    "有可用优惠券吗",
    "适合约会吗",
    "适合吗",
    "好不好",
    "值不值得",
    "值不值",
    "营业吗",
    "呢",
    "店呢",
    "家呢",
    "商家呢",
    "哪个呢",
)



def _first_int(value: Any) -> int | None:
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


def _strip_facet_suffixes(prefix: str) -> str:
    if not prefix:
        return prefix
    facet_suffixes = ("环境", "价格", "人均", "味道", "口味", "服务", "券", "优惠", "营业时间", "营业状态", "地址", "电话")
    # Also strip question-verb patterns that embed facet keywords
    _question_verb_patterns = (
        "有券吗", "有优惠吗", "有优惠券吗", "有没有券", "有没有优惠",
        "有券", "有优惠", "营业吗", "开门吗", "现在营业吗",
    )
    changed = True
    while changed:
        changed = False
        for qv in _question_verb_patterns:
            if prefix.endswith(qv):
                prefix = prefix[:-len(qv)].strip(" 的，,;；")
                changed = True
                break
        if not changed:
            for f_suf in facet_suffixes:
                if prefix.endswith(f_suf):
                    prefix = prefix[:-len(f_suf)].strip(" 的，,;；")
                    changed = True
                    break
    return prefix


def _explicit_entity_from_query(raw_query: str) -> str | None:
    text = (raw_query or "").strip()
    if not text:
        return None
    compact = _clean_text(text).replace(" ", "")
    compact = compact.rstrip("。！？?!")

    suffix_patterns = (
        "怎么样$",
        "好不好$",
        "值不值得$",
        "适合约会吗$",
        "适合约会$",
        "有券吗$",
        "现在营业吗$",
        "现在还营业吗$",
        "营业吗$",
        "多少钱$",
        "怎么走$",
        "在哪里$",
        "在哪$",
    )
    for pattern_text in suffix_patterns:
        match = re.search(pattern_text, compact, flags=re.IGNORECASE)
        if match and match.end() == len(compact):
            candidate = compact[: match.start()].strip(" 、,。！？?!")
            if candidate and candidate not in _PRONOUNS:
                return candidate

    generic_query_tokens = (
        "附近",
        "推荐",
        "餐厅",
        "餐馆",
        "美食",
        "店铺",
        "店家",
        "一家",
        "几家",
    )
    has_entity_shape = any(token in compact for token in ("(", "（", "）", ")", "店", "馆", "街", "路"))

    for pronoun in _PRONOUNS:
        idx = compact.find(pronoun)
        if idx > 0:
            prefix = compact[:idx].strip(" 、,。！？?!")
            if prefix and prefix not in _PRONOUNS and (
                not any(token in prefix for token in generic_query_tokens)
                or has_entity_shape
            ):
                return _strip_facet_suffixes(prefix)

    for suffix in _EXPLICIT_SUFFIXES:
        if compact.endswith(suffix):
            prefix = compact[: -len(suffix)].strip(" 、,。！？?!")
            if prefix and not any(pronoun in prefix for pronoun in _PRONOUNS):
                if not any(token in prefix for token in generic_query_tokens) or has_entity_shape:
                    return _strip_facet_suffixes(prefix)

    match = re.match("^(?P<name>.+?)(?:\s+)?(?:怎么样|好不好|值不值得|适合约会|有券吗|现在营业吗|现在还营业吗|营业吗)$", compact)
    if match:
        prefix = match.group("name").strip(" 、,。！？?!")
        if prefix and not any(pronoun in prefix for pronoun in _PRONOUNS):
            return _strip_facet_suffixes(prefix)
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
    ) -> FacetExecutionPlan:
        session_context_map = _as_mapping(session_context)
        client_context_map = _as_mapping(client_context)
        user_need_map = _as_mapping(user_need)
        explicit_entity = _explicit_entity_from_query(raw_query)
        pronoun_only = _is_pronoun_only_query(raw_query, explicit_entity)

        context_refs = list(getattr(user_need, "context_refs", []) or [])
        target_shop = TargetShopPolicy().resolve_target(
            raw_query=raw_query,
            slots=slots,
            client_context=client_context_map,
            session_context=session_context_map,
            explicit_entity=explicit_entity
        )
        explicit_lookup_name = explicit_entity or getattr(target_shop, "shop_name", None) or getattr(slots, "shop_query", None)
        nearby_recommendation_like = any(
            token in (raw_query or "")
            for token in ("附近", "周边", "推荐", "几家", "多推荐", "适合约会", "家庭聚餐", "安静", "不吵")
        )
        skip_session_shop_fallback = (
            target_shop.source == "rag_fallback"
            or (nearby_recommendation_like and not explicit_entity and not pronoun_only)
        )

        if explicit_lookup_name and target_shop.confidence > 0.0 and target_shop.shop_id is None:
            try:
                catalog = get_default_catalog()
                catalog_matches = catalog.search_shops(query=explicit_lookup_name, slots=slots, limit=5)
                if catalog_matches:
                    best_match = next(
                        (
                            item
                            for item in catalog_matches
                            if _normalize_alias(getattr(item, "name", None)) == _normalize_alias(explicit_lookup_name)
                        ),
                        catalog_matches[0],
                    )
                    # Verify best_match is actually relevant to explicit_entity
                    from .catalog import _tokenize
                    query_tokens = _tokenize(explicit_lookup_name)
                    # Filter out very generic tokens
                    generic_shop_tokens = {"ktv", "spa", "店", "馆", "餐厅", "美食", "家", "分店", "分店）", "）", "（"}
                    meaningful_tokens = {t for t in query_tokens if t not in generic_shop_tokens}
                    
                    best_blob = ((best_match.name or "") + " " + (best_match.review_summary or "")).lower()
                    
                    has_match = False
                    if meaningful_tokens:
                        has_match = any(token in best_blob for token in meaningful_tokens)
                    else:
                        has_match = any(token in best_blob for token in query_tokens)
                        
                    ee_lower = explicit_lookup_name.lower()
                    bm_name_lower = (best_match.name or "").lower()
                    if ee_lower in bm_name_lower or bm_name_lower in ee_lower:
                        has_match = True
                        
                    if True:
                        matched_ids = []
                        for item in catalog_matches:
                            if getattr(item, "id", None) is not None:
                                matched_ids.append(int(item.id))
                        target_shop = target_shop.model_copy(
                            update={
                                "shop_id": int(best_match.id),
                                "shop_name": best_match.name,
                                "candidate_shop_ids": matched_ids or [int(best_match.id)],
                            }
                        )
            except Exception:
                pass

        resolved_shop_id: int | None = None
        resolved_shop_name: str | None = None
        candidate_shop_ids: list[int] = []
        shop_context_source: str | None = None

        def add_candidate(value: Any) -> None:
            shop_id = _first_int(value)
            if shop_id is None or shop_id in candidate_shop_ids:
                return
            candidate_shop_ids.append(shop_id)

        if target_shop.confidence > 0.0:
            resolved_shop_id = target_shop.shop_id
            resolved_shop_name = target_shop.shop_name
            candidate_shop_ids = list(target_shop.candidate_shop_ids)
            shop_context_source = target_shop.source
            for value in target_shop.candidate_shop_ids:
                add_candidate(value)
        else:
            if skip_session_shop_fallback:
                shop_context_source = target_shop.source or "rag_fallback"
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

            if resolved_shop_id is None and not explicit_entity and not skip_session_shop_fallback:
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

            if not explicit_entity and not skip_session_shop_fallback:
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
            leisure_words = {"ktv", "唱歌", "足疗", "spa", "按摩", "酒店", "机票", "电影院", "洗浴"}
            if any(w in category_lower for w in leisure_words) and not any(w in shop_name_lower for w in leisure_words):
                resolved_shop_id = None
                resolved_shop_name = None
                candidate_shop_ids = []
                shop_context_source = None

        execution_items = []
        for f in required_facets:
            if f == "coupon":
                execution_items.append(FacetExecutionItem(
                    facet="coupon",
                    source="tool",
                    tool_name="get_coupon_list",
                    required=True
                ))
            elif f == "open_status":
                execution_items.append(FacetExecutionItem(
                    facet="open_status",
                    source="tool",
                    tool_name="check_open_status",
                    required=True
                ))
            elif f == "distance_eta":
                execution_items.append(FacetExecutionItem(
                    facet="distance_eta",
                    source="tool",
                    tool_name="get_distance_eta",
                    required=True
                ))
            else:
                src = "rag" if execute_rag else "context"
                execution_items.append(FacetExecutionItem(
                    facet=f,
                    source=src,
                    required=False
                ))

        return FacetExecutionPlan(
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
            target_shop=target_shop,
            items=execution_items,
            extra={
                "explicit_entity": explicit_entity,
                "pronoun_only": pronoun_only,
                "user_need": user_need_map,
            },
        )


def _explicit_entity_from_query_v2(raw_query: str) -> str | None:
    text = (raw_query or "").strip()
    if not text:
        return None
    compact = _clean_text(text).replace(" ", "")
    compact = compact.rstrip("\u3002\uff01\uff1f?!")

    suffix_patterns = (
        "\u600e\u4e48\u6837$",
        "\u597d\u4e0d\u597d$",
        "\u503c\u4e0d\u503c\u5f97$",
        "\u9002\u5408\u7ea6\u4f1a\u5417$",
        "\u9002\u5408\u7ea6\u4f1a$",
        "\u6709\u5238\u5417$",
        "\u73b0\u5728\u8425\u4e1a\u5417$",
        "\u73b0\u5728\u8fd8\u8425\u4e1a\u5417$",
        "\u8425\u4e1a\u5417$",
        "\u591a\u5c11\u94b1$",
        "\u600e\u4e48\u8d70$",
        "\u5728\u54ea\u91cc$",
        "\u5728\u54ea$",
    )
    for pattern_text in suffix_patterns:
        match = re.search(pattern_text, compact, flags=re.IGNORECASE)
        if match and match.end() == len(compact):
            candidate = compact[: match.start()].strip(" \u3001,\u3002\uff01\uff1f?!")
            if candidate:
                return candidate
    return None


_explicit_entity_from_query = _explicit_entity_from_query_v2
