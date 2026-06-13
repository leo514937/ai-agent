from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")

_SLOT_PATTERNS: dict[str, tuple[str, ...]] = {
    "city": (
        "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京",
        "重庆", "西安", "苏州", "天津", "长沙", "郑州", "东莞", "青岛",
        "沈阳", "宁波", "昆明", "大连", "厦门", "合肥", "佛山", "福州",
        "哈尔滨", "济南", "温州", "南宁", "长春", "泉州", "石家庄",
    ),
    "domain": (
        "餐厅", "吃饭", "饭店", "火锅", "烧烤", "咖啡", "奶茶",
        "商家", "商铺", "店", "优惠券", "团购", "预订", "预约",
        "订单", "探店", "美发", "美容", "按摩", "足疗", "理发",
    ),
    "time": (
        "今天", "明天", "后天", "昨天", "上午", "下午", "晚上",
        "中午", "周末", "下周", "这周", "现在",
    ),
    "price": (
        "价格", "多少钱", "人均", "价位", "费用", "便宜", "贵",
    ),
    "tool_name": (
        "booking", "business_status", "cancel_order", "coupon",
        "create_order", "order_status", "package_status", "refund_order",
    ),
}

_SLOT_LOSS_PATTERNS: dict[str, tuple[str, ...]] = {
    "shop_name": (),
    "city": (),
    "domain": (),
    "time": (),
    "price": (),
    "tool_name": (),
    "location": (),
}

_INTENT_DRIFT_PATTERNS: dict[str, tuple[str, ...]] = {
    "recommend": ("推荐", "附近", "好吃", "好评", "不错"),
    "compare": ("对比", "比较", "区别", "vs", "哪个好"),
    "booking": ("预订", "预约", "订位", "订桌"),
    "coupon": ("优惠券", "团购", "券", "折扣"),
    "navigation": ("导航", "路线", "怎么去", "距离"),
}


@dataclass(frozen=True)
class QueryRewriteGuardConfig:
    enabled: bool = True
    min_semantic_similarity: float = 0.25
    max_slot_loss_tolerance: int = 0
    max_new_constraint_tolerance: int = 1
    reject_on_intent_drift: bool = True
    downweight_on_partial_match: bool = True
    downweight_factor: float = 0.5


@dataclass(frozen=True)
class QueryRewriteGuardResult:
    accepted: bool
    rewrite_query: str
    original_query: str
    weight: float = 1.0
    reject_reason: str = ""
    slot_loss: tuple[str, ...] = ()
    new_constraints: tuple[str, ...] = ()
    intent_changed: bool = False
    semantic_similarity: float = 0.0
    debug_metadata: dict[str, Any] = field(default_factory=dict)


class QueryRewriteGuard:
    """Validates LLM rewrite results to prevent query drift.

    Ensures original user_query always participates in recall and rewrite
    only serves as a candidate variant.
    """

    def __init__(self, config: QueryRewriteGuardConfig | None = None) -> None:
        self._config = config or QueryRewriteGuardConfig()

    def validate_rewrite(
        self,
        original_query: str,
        rewrite_query: str,
        *,
        context_slots: dict[str, Any] | None = None,
        intent: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> QueryRewriteGuardResult:
        if not self._config.enabled:
            return QueryRewriteGuardResult(
                accepted=True,
                rewrite_query=rewrite_query,
                original_query=original_query,
                weight=1.0,
            )

        if not rewrite_query or not rewrite_query.strip():
            return QueryRewriteGuardResult(
                accepted=False,
                rewrite_query="",
                original_query=original_query,
                weight=0.0,
                reject_reason="empty_rewrite",
            )

        if rewrite_query.strip() == original_query.strip():
            return QueryRewriteGuardResult(
                accepted=True,
                rewrite_query=rewrite_query,
                original_query=original_query,
                weight=1.0,
                debug_metadata={"reason": "identical_to_original"},
            )

        semantic_sim = self._semantic_similarity(original_query, rewrite_query)

        slot_loss = self._detect_slot_loss(original_query, rewrite_query, context_slots or {})
        new_constraints = self._detect_new_constraints(original_query, rewrite_query)
        intent_changed = self._detect_intent_drift(original_query, rewrite_query, intent)

        debug = {
            "semantic_similarity": round(semantic_sim, 4),
            "slot_loss": list(slot_loss),
            "new_constraints": list(new_constraints),
            "intent_changed": intent_changed,
        }

        reject_reasons: list[str] = []

        if self._config.reject_on_intent_drift and intent_changed:
            reject_reasons.append("intent_drift")

        if len(slot_loss) > self._config.max_slot_loss_tolerance:
            reject_reasons.append(f"slot_loss:{','.join(slot_loss)}")

        if len(new_constraints) > self._config.max_new_constraint_tolerance:
            reject_reasons.append(f"new_constraints:{','.join(new_constraints)}")

        if semantic_sim < self._config.min_semantic_similarity:
            reject_reasons.append(f"low_semantic_similarity:{semantic_sim:.3f}")

        if reject_reasons:
            reason = ";".join(reject_reasons)
            _LOGGER.info(
                "query_rewrite_guard reject reason=%s original=%s rewrite=%s",
                reason,
                original_query[:80],
                rewrite_query[:80],
            )
            return QueryRewriteGuardResult(
                accepted=False,
                rewrite_query="",
                original_query=original_query,
                weight=0.0,
                reject_reason=reason,
                slot_loss=slot_loss,
                new_constraints=new_constraints,
                intent_changed=intent_changed,
                semantic_similarity=semantic_sim,
                debug_metadata=debug,
            )

        weight = 1.0
        if self._config.downweight_on_partial_match:
            if slot_loss or new_constraints:
                weight = self._config.downweight_factor
            elif semantic_sim < 0.5:
                weight = max(self._config.downweight_factor, 0.7)

        return QueryRewriteGuardResult(
            accepted=True,
            rewrite_query=rewrite_query,
            original_query=original_query,
            weight=weight,
            slot_loss=slot_loss,
            new_constraints=new_constraints,
            intent_changed=intent_changed,
            semantic_similarity=semantic_sim,
            debug_metadata=debug,
        )

    def build_query_variants(
        self,
        original_query: str,
        rewrite_query: str | None = None,
        hyde_passage: str | None = None,
        *,
        context_slots: dict[str, Any] | None = None,
        intent: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        variants: list[dict[str, Any]] = [
            {"query": original_query, "weight": 1.0, "source": "original"}
        ]

        if rewrite_query:
            guard_result = self.validate_rewrite(
                original_query,
                rewrite_query,
                context_slots=context_slots,
                intent=intent,
                extra=extra,
            )
            if guard_result.accepted:
                variants.append({
                    "query": rewrite_query,
                    "weight": guard_result.weight,
                    "source": "rewrite",
                    "guard": {
                        "accepted": True,
                        "semantic_similarity": guard_result.semantic_similarity,
                        "slot_loss": list(guard_result.slot_loss),
                        "new_constraints": list(guard_result.new_constraints),
                        "intent_changed": guard_result.intent_changed,
                    },
                })
            else:
                _LOGGER.info(
                    "query_rewrite_guard rewrite_rejected original=%s rewrite=%s reason=%s",
                    original_query[:80],
                    rewrite_query[:80],
                    guard_result.reject_reason,
                )

        if hyde_passage:
            variants.append({
                "query": hyde_passage,
                "weight": 0.3,
                "source": "hyde",
            })

        return {
            "variants": variants,
            "original_query": original_query,
            "primary_query": variants[0]["query"],
        }

    def _detect_slot_loss(
        self,
        original: str,
        rewrite: str,
        context_slots: dict[str, Any],
    ) -> tuple[str, ...]:
        lost: list[str] = []

        for slot_name in ("shop_name", "city", "domain", "time", "price", "location", "tool_name"):
            slot_value = context_slots.get(slot_name)
            if slot_value in (None, "", [], {}, ()):
                continue

            slot_str = str(slot_value)
            if slot_str.lower() not in original.lower():
                continue

            if slot_str.lower() not in rewrite.lower():
                lost.append(slot_name)

        for slot_name, patterns in _SLOT_PATTERNS.items():
            if not patterns:
                continue
            for pattern in patterns:
                if pattern in original and pattern not in rewrite:
                    if slot_name not in lost:
                        lost.append(slot_name)
                    break

        return tuple(lost)

    def _detect_new_constraints(self, original: str, rewrite: str) -> tuple[str, ...]:
        original_tokens = set(_tokenize(original))
        rewrite_tokens = set(_tokenize(rewrite))

        new_tokens = rewrite_tokens - original_tokens

        constraint_keywords = {
            "必须", "一定要", "只能", "只要", "禁止", "不能",
            "must", "only", "require", "forbid", "exclude",
        }

        new_constraints: list[str] = []
        for token in new_tokens:
            if token in constraint_keywords:
                new_constraints.append(token)

        for token in new_tokens:
            if token in _SLOT_PATTERNS.get("city", ()):
                if token not in _SLOT_PATTERNS.get("city", ())[:5]:
                    new_constraints.append(f"city:{token}")
            if token in _SLOT_PATTERNS.get("price", ()):
                new_constraints.append(f"price:{token}")

        return tuple(dict.fromkeys(new_constraints))

    def _detect_intent_drift(self, original: str, rewrite: str, intent: str | None) -> bool:
        if not intent:
            return False

        original_lower = original.lower()
        rewrite_lower = rewrite.lower()

        for intent_type, keywords in _INTENT_DRIFT_PATTERNS.items():
            if intent_type == intent:
                continue

            original_has = any(kw in original_lower for kw in keywords)
            rewrite_has = any(kw in rewrite_lower for kw in keywords)

            if not original_has and rewrite_has:
                return True

        return False

    @staticmethod
    def _semantic_similarity(left: str, right: str) -> float:
        left_tokens = set(_tokenize(left))
        right_tokens = set(_tokenize(right))
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / float(union or 1)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_PATTERN.findall(text or "")]


__all__ = [
    "QueryRewriteGuard",
    "QueryRewriteGuardConfig",
    "QueryRewriteGuardResult",
]
