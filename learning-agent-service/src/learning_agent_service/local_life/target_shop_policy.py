from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field
from learning_agent_service.domain.utils import clean_text as _clean_text

_PRONOUNS = (
    "这家",
    "这店",
    "这间",
    "它",
    "他",
    "她",
    "刚才那家",
    "刚才那个",
    "这商家",
    "这个商家",
    "这几家",
    "第一家",
    "第二家",
    "第三家",
    "上面那家",
    "刚推荐的",
)

_LOW_INFO_QUERY_TOKENS = ("，", "。", "?", "？", "啊", "嗯", "1", "...")

_EXPLICIT_SUFFIXES = (
    "现在营业吗",
    "现在有券吗",
    "有团购吗",
    "团购吗",
    "有什么优惠",
    "优惠吗",
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
    "have_coupon",
    "有代金券吗",
    "有折扣吗",
    "有套餐吗",
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
    "火锅店",
    "烤肉店",
    "火锅",
    "烤肉",
    "饭店",
    "小吃",
    "适合约会",
    "情侣约会",
    "现在营业",
    "营业",
    "现在有券吗",
    "最好有券",
    "有券吗",
    "have_coupon",
    "有券",
    "优惠",
    "适合带娃",
    "带娃",
    "不踩雷",
    "约会",
    "适合带爸妈",
    "带爸妈",
    "适合爸妈",
    "爸妈",
    "长辈",
    "父母",
    "老人",
    "安静",
    "别太吵",
    "不吵",
    "有停车",
    "能停车",
    "停车",
    "停车位",
    "家庭聚餐",
    "聚餐",
    "最好",
    "一点",
    "一些",
    "店",
    "家",
    "吃饭",
    "吃",
    "馆子",
    "地",
    "地方",
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


def _normalize_alias(text: str | None) -> str:
    return re.sub(r"[\s\-\_/·、,，.。()（）\[\]【】]", "", text or "").lower()


def is_low_information_query(text: str) -> bool:
    compact = (text or "").strip()
    if not compact:
        return True
    stripped = re.sub(r"[\s，,。.!！？?；;：:…]+", "", compact)
    if not stripped:
        return True
    return stripped in _LOW_INFO_QUERY_TOKENS


def _looks_like_generic_query_entity(text: str) -> bool:
    compact = _normalize_alias(text)
    if not compact:
        return False
    if compact in {city.lower() for city in _CITY_NAMES}:
        return True
    if any(token in compact for token in ("天气", "气温", "预报", "温度")):
        return True
    if re.search(r'[a-zA-Z0-9]', compact):
        return False

    stripped = compact
    all_generic = list(_GENERIC_ENTITY_PREFIXES) + list(_GENERIC_ENTITY_TOKENS) + list(_PRONOUNS)
    for token in sorted(all_generic, key=len, reverse=True):
        stripped = stripped.replace(token, "")
    for stop in (
        "的",
        "好吃",
        "好玩",
        "有哪些",
        "有没有",
        "适合",
        "适合约会",
        "最好",
        "现在",
        "现在营业",
        "有券",
        "有",
        "没",
        "还",
        "约会",
        "营业",
        "餐厅",
        "推荐几家",
        "推荐几间",
        "推荐几家店",
        "吗",
        "？",
        "?",
    ):
        stripped = stripped.replace(stop, "")
    return len(stripped) == 0


def _resolve_alias_from_contexts(
    explicit_name: str,
    client_context_map: Mapping[str, Any],
    session_context_map: Mapping[str, Any],
) -> tuple[int | None, str | None, str | None]:
    normalized_explicit = _normalize_alias(explicit_name)
    if not normalized_explicit:
        return None, None, None

    context_names: list[tuple[int | None, str, str]] = []

    for source_label, context_map in (("client_selected_shop", client_context_map), ("session_current_shop", session_context_map)):
        shop_id = (
            context_map.get("selected_shop_id")
            or context_map.get("current_shop_id")
            or context_map.get("shopId")
            or context_map.get("currentShopId")
            or context_map.get("shop_id")
        )
        for key in ("selected_shop_name", "selected_shop", "shopName", "currentShopName", "current_shop", "shop_name"):
            name = context_map.get(key)
            if name:
                context_names.append((int(shop_id) if shop_id not in (None, "") else None, str(name), source_label))
                break

    for source_label, context_map in (("client_last_candidates", client_context_map), ("session_last_candidates", session_context_map)):
        for item in context_map.get("last_candidates") or []:
            if not isinstance(item, Mapping):
                continue
            cand_name = item.get("name") or item.get("shop_name")
            cand_id = item.get("shop_id") or item.get("id")
            if cand_name:
                context_names.append((int(cand_id) if cand_id not in (None, "") else None, str(cand_name), source_label))

    best_match: tuple[int | None, str | None, str | None] | None = None
    for shop_id, cand_name, source_label in context_names:
        normalized_candidate = _normalize_alias(cand_name)
        if not normalized_candidate:
            continue
        if normalized_explicit == normalized_candidate:
            return shop_id, cand_name, source_label
        if normalized_explicit in normalized_candidate or normalized_candidate in normalized_explicit:
            best_match = (shop_id, cand_name, source_label)
    return best_match if best_match is not None else (None, None, None)

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
    resolution_source: Literal[
        "explicit_query",
        "client_selected_shop",
        "pronoun_session_current",
        "candidate_reference",
        "session_current",
        "ambiguous",
        "missing",
        "rag_fallback",
    ] | None = None
    confidence: float = 0.0
    is_explicit_in_current_turn: bool = False
    is_pronoun_inherited: bool = False
    is_candidate_reference: bool = False
    should_clarify: bool = False
    reason: str | None = None
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
        client_context: Mapping[str, Any] | None = None,
        session_context: Mapping[str, Any] | None = None,
        explicit_entity: str | None = None,
        ranked_candidates: list[Any] | None = None,
    ) -> TargetShop:
        client_context_map = dict(client_context or {})
        session_context_map = dict(session_context or {})
        query_lower = raw_query.strip().lower()
        generic_query_like = _looks_like_generic_query_entity(raw_query)
        low_info = is_low_information_query(raw_query)

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

        has_explicit_shop_hint = bool(shop_ids) or bool(eff_explicit_name)
        if not has_explicit_shop_hint and not low_info:
            has_explicit_shop_hint = bool(
                _clean_text(
                    client_context_map.get("shopName")
                    or client_context_map.get("selected_shop_name")
                    or client_context_map.get("current_shop")
                    or client_context_map.get("shop_name")
                )
                or _clean_text(
                    session_context_map.get("shopName")
                    or session_context_map.get("selected_shop_name")
                    or session_context_map.get("current_shop")
                    or session_context_map.get("shop_name")
                )
            )

        if eff_explicit_name and (
            _looks_like_generic_query_entity(eff_explicit_name)
            or eff_explicit_name.lower().strip() in ("assistant", "ai", "general", "none")
        ):
            eff_explicit_name = None

        if eff_explicit_name:
            alias_shop_id, alias_shop_name, alias_source = _resolve_alias_from_contexts(
                eff_explicit_name,
                client_context_map,
                session_context_map,
            )
            if alias_shop_name:
                return TargetShop(
                    shop_id=alias_shop_id,
                    shop_name=alias_shop_name,
                    raw_mention=eff_explicit_name,
                    source="current_query",
                    resolution_source="explicit_query",
                    confidence=0.985,
                    is_explicit_in_current_turn=True,
                    reason=f"explicit entity matched {alias_source or 'context'}",
                    candidate_shop_ids=[alias_shop_id] if alias_shop_id is not None else [],
                )
            return TargetShop(
                shop_id=None,
                shop_name=eff_explicit_name,
                raw_mention=eff_explicit_name,
                source="current_query",
                resolution_source="explicit_query",
                confidence=0.95,
                is_explicit_in_current_turn=True,
                reason="explicit entity from current query",
                candidate_shop_ids=[],
            )

        # Precedence 2: 用户选择序号
        selection_idx = self._extract_selection_index(query_lower)
        if selection_idx is not None:
            candidate_pools = [
                client_context_map.get("last_candidates") or [],
                session_context_map.get("last_candidates") or [],
            ]
            for last_candidates in candidate_pools:
                if not isinstance(last_candidates, list) or len(last_candidates) < selection_idx:
                    continue
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
                        resolution_source="candidate_reference",
                        confidence=0.95,
                        is_explicit_in_current_turn=True,
                        is_candidate_reference=True,
                        reason=f"selected candidate #{selection_idx}",
                        candidate_shop_ids=[int(shop_id)]
                    )

        nearby_recommendation_like = any(
            token in query_lower
            for token in (
                "附近",
                "周边",
                "推荐",
                "几家",
                "多推荐",
                "适合约会",
                "家庭聚餐",
                "安静",
                "不吵",
            )
        )
        from learning_agent_service.local_life.clarification_strategy import ClarificationStrategy
        
        has_pronoun = any(p in query_lower for p in _PRONOUNS)
        context_candidates: list[tuple[str, int | None, str | None]] = []
        for source_label, context_map in (("client_selected_shop", client_context_map), ("session_current_shop", session_context_map)):
            shop_id = (
                context_map.get("selected_shop_id")
                or context_map.get("current_shop_id")
                or context_map.get("shopId")
                or context_map.get("currentShopId")
                or context_map.get("shop_id")
            )
            shop_name = (
                context_map.get("selected_shop_name")
                or context_map.get("selected_shop")
                or context_map.get("current_shop")
                or context_map.get("shopName")
                or context_map.get("currentShopName")
                or context_map.get("shop_name")
            )
            if shop_id or shop_name:
                context_candidates.append((source_label, int(shop_id) if shop_id not in (None, "") else None, str(shop_name) if shop_name not in (None, "") else None))

        has_resolved_ref = bool(context_candidates) or bool(ranked_candidates)
        should_clarify, missing_slot, clarify_reason = ClarificationStrategy.should_clarify_target_shop(
            raw_query=raw_query,
            is_low_info=low_info,
            has_explicit_shop_hint=has_explicit_shop_hint,
            has_pronoun=has_pronoun,
            has_resolved_ref=has_resolved_ref,
        )
        has_current_shop_context = bool(context_candidates) or bool(eff_explicit_name) or bool(shop_ids)
        if not should_clarify and ClarificationStrategy.requires_current_shop_for_ref(query_lower, has_current_shop_context):
            should_clarify = True
            missing_slot = missing_slot or "shop_name"
            clarify_reason = clarify_reason or "current_shop_required"

        if should_clarify:
            return TargetShop(
                source="session",
                resolution_source="missing",
                confidence=0.0,
                is_explicit_in_current_turn=False,
                should_clarify=True,
                reason=clarify_reason or "clarification_needed",
                candidate_shop_ids=[],
            )

        if nearby_recommendation_like and not has_pronoun and not eff_explicit_name:
            return TargetShop(
                shop_id=None,
                shop_name=None,
                raw_mention=None,
                source="rag_fallback",
                resolution_source="ambiguous",
                confidence=0.0,
                is_explicit_in_current_turn=False,
                reason="recommendation_query_should_not_lock_single_shop",
                candidate_shop_ids=[],
                )

        if has_pronoun and context_candidates:
            source_label, shop_id, shop_name = context_candidates[0]
            return TargetShop(
                shop_id=shop_id,
                shop_name=shop_name,
                raw_mention=raw_query,
                source="pronoun_session",
                resolution_source="pronoun_session_current" if source_label == "session_current_shop" else "client_selected_shop",
                confidence=0.9,
                is_explicit_in_current_turn=False,
                is_pronoun_inherited=True,
                reason=f"pronoun resolved from {source_label}",
                candidate_shop_ids=[int(shop_id)] if shop_id else [],
            )

        if shop_ids or eff_explicit_name:
            shop_id = int(shop_ids[0]) if shop_ids else None
            return TargetShop(
                shop_id=shop_id,
                shop_name=eff_explicit_name,
                raw_mention=eff_explicit_name or (str(shop_id) if shop_id else None),
                source="current_query",
                resolution_source="explicit_query",
                confidence=0.98,
                is_explicit_in_current_turn=True,
                reason="explicit shop ids or query text from current turn",
                candidate_shop_ids=[int(sid) for sid in shop_ids]
            )

        if context_candidates and not generic_query_like:
            source_label, shop_id, shop_name = context_candidates[0]
            return TargetShop(
                shop_id=shop_id,
                shop_name=shop_name,
                raw_mention=None,
                source="session",
                resolution_source="session_current" if source_label == "session_current_shop" else "client_selected_shop",
                confidence=0.85,
                is_explicit_in_current_turn=False,
                reason=f"context shop chosen from {source_label}",
                candidate_shop_ids=[int(shop_id)] if shop_id else [],
            )

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
                    resolution_source="rag_fallback",
                    confidence=0.7,
                    is_explicit_in_current_turn=False,
                    reason="ranked candidate fallback",
                    candidate_shop_ids=[int(shop_id)]
                )

        return TargetShop(
            source="session",
            resolution_source="missing" if low_info else "ambiguous",
            confidence=0.0,
            is_explicit_in_current_turn=False
        )
