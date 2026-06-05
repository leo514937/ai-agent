from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.utils import compact_text as _compact_text

from .schemas import LocalLifeIntentType, LocalLifeSlots

_REALTIME_KEYWORDS = (
    "订单",
    "支付",
    "退款",
    "取消",
    "订座",
    "预约",
    "库存",
    "发票",
    "售后",
    "订单状态",
    "支付状态",
    "实时库存",
    "现在能不能退",
    "现在能不能订",
    "现在是否开门",
    "现在营业吗",
    "当前营业状态",
    "已下单",
    "待支付",
    "待发货",
)
_MEMORY_KEYWORDS = (
    "记得",
    "聊过",
    "刚才",
    "之前",
    "上次",
    "上回",
    "回忆",
    "历史",
    "上下文",
    "我们说过",
    "继续刚才",
)
_STRUCTURED_KEYWORDS = (
    "附近",
    "周边",
    "人均",
    "评分",
    "距离",
    "营业中",
    "开门",
    "品类",
    "菜系",
    "价格",
    "停车",
    "安静",
    "约会",
    "聚餐",
    "家庭",
    "长辈",
    "套餐",
    "优惠",
    "团购",
    "券",
)
_GUIDE_RULE_KEYWORDS = (
    "攻略",
    "规则",
    "平台",
    "怎么选",
    "怎么用",
    "注意事项",
    "避坑",
    "避雷",
    "排队",
    "流程",
    "技巧",
    "说明",
)
_COMPARE_KEYWORDS = (
    "对比",
    "比较",
    "区别",
    "哪家更",
    "哪个更",
    "还是",
    "选哪个",
    "更适合",
    "二选一",
)
_MANUAL_SHOP_HINTS = ("这家", "这间", "这店", "第一家", "第二家", "第一间", "第二间")


@dataclass(frozen=True)
class LocalLifeRouteDecision:
    route: str
    retrieval_strategy: str
    route_reason: str
    candidate_shop_ids: tuple[int, ...] = ()
    parent_top_k: int = 5
    child_top_k: int = 30
    sibling_limit_per_parent: int = 6
    preferred_roles: tuple[str, ...] = ()
    use_business_candidates: bool = True
    use_qdrant: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "retrieval_strategy": self.retrieval_strategy,
            "route_reason": self.route_reason,
            "candidate_shop_ids": list(self.candidate_shop_ids),
            "parent_top_k": self.parent_top_k,
            "child_top_k": self.child_top_k,
            "sibling_limit_per_parent": self.sibling_limit_per_parent,
            "preferred_roles": list(self.preferred_roles),
            "use_business_candidates": self.use_business_candidates,
            "use_qdrant": self.use_qdrant,
            "extra": dict(self.extra),
        }


class LocalLifeQueryRouter:
    def route(
        self,
        query: str,
        *,
        slots: LocalLifeSlots | Mapping[str, Any] | None = None,
        intent: LocalLifeIntentType | str | None = None,
        candidate_shop_ids: Sequence[int] | None = None,
        structured_candidates: Sequence[Any] | None = None,
        client_context: Mapping[str, Any] | None = None,
        session_context: Mapping[str, Any] | None = None,
    ) -> LocalLifeRouteDecision:
        slots_obj = self._normalize_slots(slots)
        compact = self._compact_text(query)
        candidate_ids = self._normalize_ids(candidate_shop_ids or slots_obj.shop_ids)
        structured_candidates = tuple(structured_candidates or ())

        route, route_reason = self._infer_route(compact, intent=intent, slots=slots_obj)
        if route == "general_chat":
            return LocalLifeRouteDecision(
                route=route,
                retrieval_strategy="general_answer_only",
                route_reason=route_reason,
                candidate_shop_ids=(),
                parent_top_k=0,
                child_top_k=0,
                sibling_limit_per_parent=0,
                preferred_roles=(),
                use_business_candidates=False,
                use_qdrant=False,
                extra=self._build_extra(route=route, intent=intent, slots=slots_obj, query=compact),
            )
        if route == "realtime_tool":
            return LocalLifeRouteDecision(
                route=route,
                retrieval_strategy="java_business_tool_only",
                route_reason=route_reason,
                candidate_shop_ids=candidate_ids,
                parent_top_k=0,
                child_top_k=0,
                sibling_limit_per_parent=0,
                preferred_roles=(),
                use_business_candidates=False,
                use_qdrant=False,
                extra=self._build_extra(route=route, intent=intent, slots=slots_obj, query=compact),
            )

        if route == "compare_multi_parent":
            return LocalLifeRouteDecision(
                route=route,
                retrieval_strategy="business_candidates->multi_parent_rag->shop_rerank",
                route_reason=route_reason,
                candidate_shop_ids=candidate_ids,
                parent_top_k=8,
                child_top_k=40,
                sibling_limit_per_parent=8,
                preferred_roles=("merchant_review_summary", "merchant_scene_fit", "merchant_pitfall_summary", "package_description"),
                use_business_candidates=True,
                use_qdrant=True,
                extra=self._build_extra(
                    route=route,
                    intent=intent,
                    slots=slots_obj,
                    query=compact,
                    structured_candidates=structured_candidates,
                ),
            )

        if route == "guide_rule_rag":
            return LocalLifeRouteDecision(
                route=route,
                retrieval_strategy="guide_rule_rag->parent_child_rag",
                route_reason=route_reason,
                candidate_shop_ids=candidate_ids,
                parent_top_k=4,
                child_top_k=24,
                sibling_limit_per_parent=4,
                preferred_roles=("local_guide", "platform_rule"),
                use_business_candidates=False,
                use_qdrant=True,
                extra=self._build_extra(route=route, intent=intent, slots=slots_obj, query=compact),
            )

        if route == "structured_first":
            return LocalLifeRouteDecision(
                route=route,
                retrieval_strategy="business_candidates->parent_child_rag->shop_rerank",
                route_reason=route_reason,
                candidate_shop_ids=candidate_ids,
                parent_top_k=5,
                child_top_k=30,
                sibling_limit_per_parent=6,
                preferred_roles=("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
                use_business_candidates=True,
                use_qdrant=True,
                extra=self._build_extra(
                    route=route,
                    intent=intent,
                    slots=slots_obj,
                    query=compact,
                    structured_candidates=structured_candidates,
                ),
            )

        return LocalLifeRouteDecision(
            route="merchant_reasoning",
            retrieval_strategy="parent_child_rag->shop_rerank",
            route_reason=route_reason,
            candidate_shop_ids=candidate_ids,
            parent_top_k=5,
            child_top_k=30,
            sibling_limit_per_parent=6,
            preferred_roles=("merchant_profile", "merchant_review_summary", "merchant_scene_fit"),
            use_business_candidates=True,
            use_qdrant=True,
            extra=self._build_extra(
                route="merchant_reasoning",
                intent=intent,
                slots=slots_obj,
                query=compact,
                structured_candidates=structured_candidates,
            ),
        )

    def _infer_route(
        self,
        compact_query: str,
        *,
        intent: LocalLifeIntentType | str | None,
        slots: LocalLifeSlots,
    ) -> tuple[str, str]:
        intent_value = self._normalize_intent(intent)
        if intent_value in {LocalLifeIntentType.BOOKING, LocalLifeIntentType.ORDER_STATUS}:
            return "realtime_tool", "intent_realtime_business"

        if self._contains_any(compact_query, _REALTIME_KEYWORDS):
            return "realtime_tool", "realtime_business_terms"

        if self._contains_any(compact_query, _MEMORY_KEYWORDS):
            return "general_chat", "memory_or_history_query"

        if self._contains_any(compact_query, _COMPARE_KEYWORDS) or intent_value == LocalLifeIntentType.RESTAURANT_COMPARISON:
            return "compare_multi_parent", "comparison_query"

        if self._contains_any(compact_query, _GUIDE_RULE_KEYWORDS):
            return "guide_rule_rag", "guide_or_rule_query"

        if self._contains_any(compact_query, _STRUCTURED_KEYWORDS) or self._looks_structured(slots):
            return "structured_first", "structured_filters"

        return "merchant_reasoning", "merchant_reasoning_default"

    def _build_extra(
        self,
        *,
        route: str,
        intent: LocalLifeIntentType | str | None,
        slots: LocalLifeSlots,
        query: str,
        structured_candidates: Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "route": route,
            "intent": self._normalize_intent(intent).value if self._normalize_intent(intent) else str(intent or ""),
            "query_tags": self._query_tags(query),
            "has_city": bool(slots.city),
            "has_location": bool(slots.location.lat is not None or slots.location.lng is not None),
            "has_price": bool(
                slots.price.per_person_min is not None
                or slots.price.per_person_max is not None
                or slots.price.target is not None
            ),
            "has_preferences": bool(slots.preferences),
        }
        if structured_candidates:
            extra["structured_candidate_count"] = len(structured_candidates)
        return extra

    @staticmethod
    def _normalize_slots(slots: LocalLifeSlots | Mapping[str, Any] | None) -> LocalLifeSlots:
        if isinstance(slots, LocalLifeSlots):
            return slots
        if isinstance(slots, Mapping):
            try:
                return LocalLifeSlots.model_validate(slots)
            except Exception:
                pass
        return LocalLifeSlots()

    @staticmethod
    def _normalize_ids(values: Sequence[Any] | None) -> tuple[int, ...]:
        normalized: list[int] = []
        for value in values or ():
            try:
                normalized.append(int(value))
            except Exception:
                continue
        return tuple(dict.fromkeys(normalized))

    @staticmethod
    def _normalize_intent(intent: LocalLifeIntentType | str | None) -> LocalLifeIntentType | None:
        if isinstance(intent, LocalLifeIntentType):
            return intent
        if intent is None:
            return None
        text = str(intent).strip().lower().replace("-", "_").replace(" ", "_")
        for item in LocalLifeIntentType:
            if text == item.value:
                return item
        mapping = {
            "recommend": LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
            "comparison": LocalLifeIntentType.RESTAURANT_COMPARISON,
            "compare": LocalLifeIntentType.RESTAURANT_COMPARISON,
            "detail": LocalLifeIntentType.DETAIL,
            "booking": LocalLifeIntentType.BOOKING,
            "order_status": LocalLifeIntentType.ORDER_STATUS,
            "navigation": LocalLifeIntentType.NAVIGATION,
            "clarify": LocalLifeIntentType.CLARIFY,
        }
        return mapping.get(text)

    @staticmethod
    def _compact_text(value: str) -> str:
        return _compact_text(value)

    @staticmethod
    def _contains_any(text: str, keywords: Sequence[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    @staticmethod
    def _looks_structured(slots: LocalLifeSlots) -> bool:
        return bool(
            slots.city
            or slots.location.city
            or slots.location.lat is not None
            or slots.location.lng is not None
            or slots.price.target is not None
            or slots.price.per_person_min is not None
            or slots.price.per_person_max is not None
            or slots.preferences
            or slots.scene
            or slots.category
            or slots.shop_query
        )

    @staticmethod
    def _looks_shop_specific(text: str, slots: LocalLifeSlots) -> bool:
        if slots.shop_ids or slots.shop_query:
            return True
        return any(token in text for token in _MANUAL_SHOP_HINTS)

    @staticmethod
    def _query_tags(text: str) -> list[str]:
        tags: list[str] = []
        if any(keyword in text for keyword in _REALTIME_KEYWORDS):
            tags.append("realtime")
        if any(keyword in text for keyword in _COMPARE_KEYWORDS):
            tags.append("compare")
        if any(keyword in text for keyword in _GUIDE_RULE_KEYWORDS):
            tags.append("guide_rule")
        if any(keyword in text for keyword in _STRUCTURED_KEYWORDS):
            tags.append("structured")
        return list(dict.fromkeys(tags))


__all__ = ["LocalLifeQueryRouter", "LocalLifeRouteDecision"]
