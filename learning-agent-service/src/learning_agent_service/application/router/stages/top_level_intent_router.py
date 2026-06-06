from __future__ import annotations

from dataclasses import dataclass, asdict
from collections.abc import Mapping
from typing import Any

from ...routing_primitives import _contains_any, normalize_query


_IDENTITY_TOKENS = ("你是谁", "你是誰", "身份", "id", "identity", "who are you")
_CAPABILITY_TOKENS = ("你能做什么", "你会什么", "功能", "能力", "capability", "what can you do", "怎么用你")
_DIRECT_CHAT_TOKENS = ("谢谢", "你好", "hello", "hi", "hey", "聊聊", "闲聊", "讲个笑话")
_OUT_OF_SCOPE_TOKENS = ("帮我写代码", "写代码", "编程", "debug", "报错", "python", "sql", "算法", "论文", "文档")
_PLANNING_TOKENS = ("计划", "安排", "行程", "日程", "规划", "方案")
_DOCUMENT_TOKENS = ("文档", "资料", "总结", "概述", "解释一下", "知识")
_MATH_CODE_TOKENS = ("数学", "公式", "计算", "代码", "程序", "脚本", "算法", "sql", "python")
_COMPARISON_TOKENS = ("对比", "比较", "区别", "哪个更", "哪家更")
_LOCAL_LIFE_TOKENS = ("附近", "周边", "推荐", "火锅", "烧烤", "餐厅", "饭店", "优惠券", "券", "套餐", "有券", "营业")
_UNSAFE_TOKENS = ("ignore previous instructions", "system prompt", "developer message", "prompt injection", "jailbreak", "越权", "泄露提示词")


@dataclass(frozen=True)
class TopLevelIntentResult:
    intent: str
    confidence: float
    reason: str
    domain: str
    required_action: str = "direct_answer"
    route_candidate: str | None = None
    matched_signals: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def route_top_level_intent(
    raw_query: str,
    *,
    persistent: Any | None = None,
    client_context: Mapping[str, Any] | None = None,
) -> TopLevelIntentResult:
    normalized = normalize_query(raw_query)
    compact = normalized.replace(" ", "")
    lowered = normalized.lower()
    context = dict(client_context or {})

    if any(token in compact or token.lower() in lowered for token in _UNSAFE_TOKENS):
        return TopLevelIntentResult(
            intent="unsafe",
            confidence=0.99,
            reason="top_level_unsafe",
            domain="general",
            required_action="reject",
            route_candidate="reject",
            matched_signals=["unsafe"],
        )

    if _contains_any(normalized, _IDENTITY_TOKENS) or _contains_any(compact, _IDENTITY_TOKENS):
        return TopLevelIntentResult(
            intent="identity",
            confidence=0.97,
            reason="top_level_identity",
            domain="general",
            route_candidate="profile",
            matched_signals=["identity"],
        )

    if _contains_any(normalized, _CAPABILITY_TOKENS) or _contains_any(compact, _CAPABILITY_TOKENS):
        return TopLevelIntentResult(
            intent="capability",
            confidence=0.96,
            reason="top_level_capability",
            domain="general",
            route_candidate="profile",
            matched_signals=["capability"],
        )

    if _contains_any(normalized, _DIRECT_CHAT_TOKENS) or _contains_any(compact, _DIRECT_CHAT_TOKENS):
        return TopLevelIntentResult(
            intent="direct_chat",
            confidence=0.95,
            reason="top_level_direct_chat",
            domain="general",
            route_candidate="thanks" if any(token in compact for token in ("谢谢", "thanks")) else "greeting",
            matched_signals=["direct_chat"],
        )

    if _contains_any(normalized, _COMPARISON_TOKENS) or _contains_any(compact, _COMPARISON_TOKENS):
        return TopLevelIntentResult(
            intent="comparison",
            confidence=0.9,
            reason="top_level_comparison",
            domain="local_life" if _contains_any(normalized, _LOCAL_LIFE_TOKENS) or _contains_any(compact, _LOCAL_LIFE_TOKENS) else "general",
            route_candidate="comparison",
            matched_signals=["comparison"],
        )

    if _contains_any(normalized, _PLANNING_TOKENS) or _contains_any(compact, _PLANNING_TOKENS):
        return TopLevelIntentResult(
            intent="planning",
            confidence=0.88,
            reason="top_level_planning",
            domain="general",
            route_candidate="planning",
            matched_signals=["planning"],
        )

    if _contains_any(normalized, _DOCUMENT_TOKENS) or _contains_any(compact, _DOCUMENT_TOKENS):
        return TopLevelIntentResult(
            intent="document_or_knowledge",
            confidence=0.85,
            reason="top_level_document_or_knowledge",
            domain="general",
            route_candidate="document",
            matched_signals=["document"],
        )

    if _contains_any(normalized, _MATH_CODE_TOKENS) or _contains_any(compact, _MATH_CODE_TOKENS):
        return TopLevelIntentResult(
            intent="math_or_code",
            confidence=0.9,
            reason="top_level_math_or_code",
            domain="general",
            route_candidate="code",
            matched_signals=["math_or_code"],
        )

    if _contains_any(normalized, _LOCAL_LIFE_TOKENS) or _contains_any(compact, _LOCAL_LIFE_TOKENS) or any(
        key in context for key in ("shopId", "shopName", "selected_shop_id", "selected_shop_name", "city", "location")
    ):
        intent = "recommendation" if _contains_any(normalized, ("推荐", "附近", "周边")) else "local_life"
        return TopLevelIntentResult(
            intent=intent,
            confidence=0.83,
            reason="top_level_local_life",
            domain="local_life",
            route_candidate="local_life",
            matched_signals=["local_life"],
        )

    return TopLevelIntentResult(
        intent="out_of_scope",
        confidence=0.7,
        reason="top_level_out_of_scope",
        domain="general",
        route_candidate="direct_answer",
        matched_signals=[],
    )
