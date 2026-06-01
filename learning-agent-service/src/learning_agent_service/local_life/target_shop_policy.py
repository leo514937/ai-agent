from __future__ import annotations

import re
from typing import Any, List, Literal, Optional, Mapping
from pydantic import BaseModel, Field

_PRONOUNS = ("这家", "这店", "这间", "它", "他", "她", "刚才那家", "刚才那个", "这商家", "这个商家", "这几家", "第一家", "第二家")

_EXPLICIT_SUFFIXES = (
    "现在营业吗",
    "现在有券吗",
    "现在开吗",
    "有几张券",
    "有可用优惠券吗",
    "有券吗",
    "营业吗",
    "怎么样",
    "好不好",
    "值不值",
    "适合吗",
    "有啥特色",
    "有什么特色",
    "特色是什么",
)

_GENERIC_ENTITY_TOKENS = (
    "附近",
    "推荐",
    "餐厅",
    "餐馆",
    "美食",
    "店铺",
    "店家",
    "一家",
    "几家",
    "我在",
    "帮我找",
    "找个",
    "找一家",
    "想找",
    "附近推荐",
)

_GENERIC_ENTITY_PREFIXES = (
    "我在",
    "附近",
    "推荐",
    "帮我找",
    "找个",
    "找一家",
    "想找",
    "附近推荐",
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


def _normalize_alias(text: str) -> str:
    return re.sub(r"[\s\-\_/·、,，.。()（）\[\]【】]", "", text or "").lower()


def _looks_like_generic_query_entity(text: str) -> bool:
    compact = _normalize_alias(text)
    if not compact:
        return False
    if compact in {city.lower() for city in _CITY_NAMES}:
        return True
    if re.search(r'[a-zA-Z0-9]', compact):
        return False

    stripped = compact
    for token in sorted(list(_GENERIC_ENTITY_PREFIXES) + list(_GENERIC_ENTITY_TOKENS), key=len, reverse=True):
        stripped = stripped.replace(token, "")
    for stop in ("的", "好吃", "好玩", "有哪些", "有没有"):
        stripped = stripped.replace(stop, "")
    return len(stripped) == 0


def _resolve_alias_from_session(explicit_name: str, session_context_map: Mapping[str, Any]) -> tuple[int | None, str | None]:
    normalized_explicit = _normalize_alias(explicit_name)
    if not normalized_explicit:
        return None, None

    session_names: list[tuple[int | None, str | None]] = []

    for key in ("selected_shop_name", "current_shop"):
        name = session_context_map.get(key)
        shop_id = session_context_map.get("selected_shop_id") or session_context_map.get("current_shop_id")
        if name:
            session_names.append((int(shop_id) if shop_id not in (None, "") else None, str(name)))

    for item in session_context_map.get("last_candidates") or []:
        if not isinstance(item, Mapping):
            continue
        cand_name = item.get("name") or item.get("shop_name")
        cand_id = item.get("shop_id") or item.get("id")
        if cand_name:
            session_names.append((int(cand_id) if cand_id not in (None, "") else None, str(cand_name)))

    best_match: tuple[int | None, str | None] | None = None
    for shop_id, cand_name in session_names:
        normalized_candidate = _normalize_alias(cand_name)
        if not normalized_candidate:
            continue
        if normalized_explicit == normalized_candidate:
            return shop_id, cand_name
        if normalized_explicit in normalized_candidate or normalized_candidate in normalized_explicit:
            best_match = (shop_id, cand_name)
    return best_match if best_match is not None else (None, None)

class TargetShop(BaseModel):
    shop_id: int | None = None
    shop_name: str | None = None
    raw_mention: str | None = None
    source: Literal[
        "current_query",
        "pronoun_session",
        "candidate_selection",
        "session",
        "rag_fallback",
    ]
    confidence: float = 0.0
    is_explicit_in_current_turn: bool = False
    candidate_shop_ids: list[int] = Field(default_factory=list)

class TargetShopPolicy:
    @staticmethod
    def _extract_selection_index(query: str) -> int | None:
        compact = query.strip().lower()
        m = re.search(r"第([一二三四五六七八九十1-9])(?:个|家|间|店|名|商户|商家)", compact)
        if m:
            val = m.group(1)
            mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            try:
                return int(val)
            except ValueError:
                return mapping.get(val)
        return None

    @staticmethod
    def _strip_explicit_suffixes(text: str) -> str:
        prefix = text.strip().rstrip("？?。.!！")
        changed = True
        while changed and prefix:
            changed = False
            for suffix in sorted(_EXPLICIT_SUFFIXES, key=len, reverse=True):
                if prefix.endswith(suffix):
                    prefix = prefix[: -len(suffix)].strip(" ，,;；")
                    changed = True
                    break
        return prefix

    def resolve_target(
        self,
        *,
        raw_query: str,
        slots: Any,
        session_context: Mapping[str, Any] | None = None,
        explicit_entity: str | None = None,
        ranked_candidates: list[Any] | None = None,
    ) -> TargetShop:
        session_context_map = dict(session_context or {})
        query_lower = raw_query.strip().lower()
        generic_query_like = _looks_like_generic_query_entity(raw_query)

        # Precedence 1: 当前轮显式商铺
        shop_ids = getattr(slots, "shop_ids", []) or []
        shop_query = getattr(slots, "shop_query", None)
        
        eff_explicit_name = None
        if explicit_entity and explicit_entity.strip() not in _PRONOUNS:
            eff_explicit_name = explicit_entity.strip()
        if not eff_explicit_name:
            fallback_explicit = self._strip_explicit_suffixes(raw_query)
            if fallback_explicit and fallback_explicit not in _PRONOUNS:
                eff_explicit_name = fallback_explicit
        if not eff_explicit_name and shop_query and shop_query.strip() not in _PRONOUNS:
            eff_explicit_name = shop_query.strip()

        if eff_explicit_name and _looks_like_generic_query_entity(eff_explicit_name):
            eff_explicit_name = None

        if eff_explicit_name:
            alias_shop_id, alias_shop_name = _resolve_alias_from_session(eff_explicit_name, session_context_map)
            if alias_shop_name:
                return TargetShop(
                    shop_id=alias_shop_id,
                    shop_name=alias_shop_name,
                    raw_mention=eff_explicit_name,
                    source="current_query",
                    confidence=0.985,
                    is_explicit_in_current_turn=True,
                    candidate_shop_ids=[alias_shop_id] if alias_shop_id is not None else [],
                )

        if shop_ids or eff_explicit_name:
            shop_id = int(shop_ids[0]) if shop_ids else None
            return TargetShop(
                shop_id=shop_id,
                shop_name=eff_explicit_name,
                raw_mention=eff_explicit_name or (str(shop_id) if shop_id else None),
                source="current_query",
                confidence=0.98,
                is_explicit_in_current_turn=True,
                candidate_shop_ids=[int(sid) for sid in shop_ids]
            )

        # Precedence 2: 用户选择序号
        selection_idx = self._extract_selection_index(query_lower)
        if selection_idx is not None:
            last_candidates = session_context_map.get("last_candidates") or []
            if isinstance(last_candidates, list) and len(last_candidates) >= selection_idx:
                candidate = last_candidates[selection_idx - 1]
                cand_map = dict(candidate) if isinstance(candidate, Mapping) else {}
                shop_id = cand_map.get("shop_id") or cand_map.get("id")
                shop_name = cand_map.get("shop_name") or cand_map.get("name")
                if shop_id:
                    return TargetShop(
                        shop_id=int(shop_id),
                        shop_name=shop_name,
                        raw_mention=f"第{selection_idx}个",
                        source="candidate_selection",
                        confidence=0.95,
                        is_explicit_in_current_turn=True,
                        candidate_shop_ids=[int(shop_id)]
                    )

        # Precedence 3: 指代词 + session.current_shop
        has_pronoun = any(p in query_lower for p in _PRONOUNS)
        if has_pronoun:
            shop_id = session_context_map.get("selected_shop_id") or session_context_map.get("current_shop_id")
            shop_name = session_context_map.get("selected_shop_name") or session_context_map.get("current_shop")
            print(f"[DEBUG TargetShopPolicy] query: {raw_query}, shop_id: {shop_id}, shop_name: {shop_name}, session_keys: {list(session_context_map.keys())}")
            if shop_id or shop_name:
                return TargetShop(
                    shop_id=int(shop_id) if shop_id else None,
                    shop_name=shop_name,
                    raw_mention=raw_query,
                    source="pronoun_session",
                    confidence=0.9,
                    is_explicit_in_current_turn=False,
                    candidate_shop_ids=[int(shop_id)] if shop_id else []
                )

        # Precedence 4: session.current_shop
        shop_id = session_context_map.get("selected_shop_id") or session_context_map.get("current_shop_id")
        shop_name = session_context_map.get("selected_shop_name") or session_context_map.get("current_shop")
        if (shop_id or shop_name) and not generic_query_like:
            return TargetShop(
                shop_id=int(shop_id) if shop_id else None,
                shop_name=shop_name,
                raw_mention=None,
                source="session",
                confidence=0.85,
                is_explicit_in_current_turn=False,
                candidate_shop_ids=[int(shop_id)] if shop_id else []
            )

        # Precedence 5: RAG top1 fallback
        if ranked_candidates and not generic_query_like:
            first = ranked_candidates[0]
            first_map = dict(first) if isinstance(first, Mapping) else getattr(first, "__dict__", {})
            shop_id = first_map.get("shop_id") or first_map.get("id")
            shop_name = first_map.get("shop_name") or first_map.get("name")
            if shop_id:
                return TargetShop(
                    shop_id=int(shop_id),
                    shop_name=shop_name,
                    raw_mention=None,
                    source="rag_fallback",
                    confidence=0.7,
                    is_explicit_in_current_turn=False,
                    candidate_shop_ids=[int(shop_id)]
                )

        return TargetShop(
            source="session",
            confidence=0.0,
            is_explicit_in_current_turn=False
        )
