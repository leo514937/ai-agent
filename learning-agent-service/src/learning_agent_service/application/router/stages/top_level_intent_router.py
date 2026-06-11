from __future__ import annotations

from dataclasses import dataclass, asdict
from collections.abc import Mapping
from typing import Any

from ...routing_primitives import _contains_any, normalize_query


_IDENTITY_TOKENS = (
    "你是谁",
    "你是什么",
    "你叫什么",
    "介绍一下你",
    "介绍你自己",
    "你是誰",
    "身份",
    "id",
    "identity",
    "who are you",
)

_STRONG_CAPABILITY_PATTERNS = (
    "你有什么作用",
    "有什么作用",
    "你有什么用",
    "你能做什么",
    "能做什么",
    "你可以做什么",
    "可以做什么",
    "你会什么",
    "你能干嘛",
    "你能干什么",
    "你可以干嘛",
    "你可以干什么",
    "有什么功能",
    "有哪些功能",
    "你有什么功能",
    "你有哪些功能",
    "有什么能力",
    "有哪些能力",
    "你有什么能力",
    "你有哪些能力",
    "帮我做什么",
    "你可以帮我做什么",
    "这个助手有什么功能",
    "这个助手有什么作用",
    "这个系统有什么功能",
    "这个系统有什么作用",
    "capability",
    "what can you do",
)

_WEAK_META_TOKENS = (
    "作用",
    "功能",
    "能力",
    "有什么用",
    "有什么功能",
    "有什么作用",
    "有什么能力",
    "有哪些功能",
    "有哪些能力",
)

_ASSISTANT_SUBJECT_TOKENS = (
    "你",
    "你们",
    "助手",
    "这个助手",
    "系统",
    "这个系统",
    "bot",
    "agent",
    "机器人",
)

_HELP_TOKENS = (
    "怎么用",
    "怎么用你",
    "怎么使用你",
    "如何使用",
    "使用说明",
    "帮助",
    "help",
)

_DIRECT_CHAT_TOKENS = ("谢谢", "你好", "hello", "hi", "hey", "聊聊", "闲聊", "讲个笑话")
_OUT_OF_SCOPE_TOKENS = ("帮我写代码", "写代码", "编程", "debug", "报错", "python", "sql", "算法", "论文", "文档")
_PLANNING_TOKENS = ("计划", "安排", "行程", "日程", "规划", "方案")
_DOCUMENT_TOKENS = ("文档", "资料", "总结", "概述", "解释一下", "知识")
_MATH_CODE_TOKENS = ("数学", "公式", "计算", "代码", "程序", "脚本", "算法", "sql", "python", "编程", "debug")

_COMPARISON_TOKENS = (
    "对比",
    "比较",
    "区别",
    "哪个更",
    "哪家更",
    "哪个好",
    "哪家好",
    "比一下",
    "对比一下",
    "比一比",
)

_LOCAL_LIFE_TOKENS = (
    "附近",
    "周边",
    "推荐",
    "火锅",
    "烧烤",
    "餐厅",
    "饭店",
    "优惠券",
    "券",
    "套餐",
    "有券",
    "营业",
    "海底捞",
    "巴奴",
    "呷哺呷哺",
    "西贝",
    "外婆家",
    "绿茶",
    "必胜客",
    "肯德基",
    "麦当劳",
    "星巴克",
    "瑞幸",
    "这家",
    "那家",
    "这个",
    "那个",
    "商场",
    "店铺",
    "门店",
    "咖啡",
    "奶茶",
    "地址",
    "在哪",
    "位置",
    "营业时间",
    "几点开门",
    "几点关门",
    "团购",
    "价格",
    "人均",
    "环境",
    "口味",
    "服务",
    "排队",
    "停车",
)

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
    requires_current_shop: bool = False
    requires_candidate_context: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _has_domain_signal(normalized: str, compact: str) -> bool:
    if not _contains_any(normalized, _LOCAL_LIFE_TOKENS) and not _contains_any(compact, _LOCAL_LIFE_TOKENS):
        return False
    if _contains_any(normalized, ("这个助手", "这个系统", "那个助手", "那个系统")) or _contains_any(compact, ("这个助手", "这个系统", "那个助手", "那个系统")):
        return False
    return True


def _has_shop_entity(normalized: str, compact: str) -> bool:
    shop_names = ("海底捞", "巴奴", "呷哺呷哺", "西贝", "外婆家", "绿茶", "必胜客", "肯德基", "麦当劳", "星巴克", "瑞幸")
    return bool(_contains_any(normalized, shop_names) or _contains_any(compact, shop_names))


_PRONOUN_COMPARISON_TOKENS = (
    "这两家", "这两个", "这两家店", "这两个店",
    "它们", "这几个", "这些店", "这几个店",
)


def _is_comparison_query(normalized: str, compact: str) -> bool:
    if ("和" in normalized or "跟" in normalized) and ("哪个好" in normalized or "哪家好" in normalized or "哪个更好" in normalized or "哪家更好" in normalized):
        return True
    if ("比" in normalized) and ("怎么样" in normalized or "如何" in normalized):
        return True
    if normalized in ("这两个哪个好", "这两家哪个好", "这两个店哪个好", "这两家店哪个好", "它们哪个好", "这几个哪个好", "这些店哪个好", "这几个店哪个好"):
        return True
    if _contains_any(compact, ("哪个好", "哪家好", "哪个更好", "哪家更好")):
        return True
    if _contains_any(compact, ("对比一下", "比一下", "比一比")):
        return True
    if _contains_any(compact, ("对比", "比较", "区别")):
        tail = compact[compact.index("对比") + 2:] if "对比" in compact else ""
        tail = compact[compact.index("比较") + 2:] if "比较" in compact else tail
        tail = compact[compact.index("区别") + 2:] if "区别" in compact else tail
        if not tail or not _contains_any(tail, ("全", "好", "多", "少", "大", "小")):
            return True
    return False


def _is_pronoun_comparison(normalized: str, compact: str) -> bool:
    if _contains_any(normalized, _PRONOUN_COMPARISON_TOKENS) or _contains_any(compact, _PRONOUN_COMPARISON_TOKENS):
        return True
    return False


def _requires_current_shop_for_ref(normalized: str) -> bool:
    ref_tokens = ("这家", "它", "那个", "这个", "那家")
    if _contains_any(normalized, ref_tokens):
        return True
    bare_followup = ("地址在哪", "在哪", "有券吗", "有券", "几点开门", "几点关门", "营业时间", "营业时间是什么")
    stripped = normalized.rstrip("？?。. ")
    if stripped in bare_followup or normalized in bare_followup:
        return True
    return False


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

    if _contains_any(normalized, _HELP_TOKENS) or _contains_any(compact, _HELP_TOKENS):
        domain_hit = _has_domain_signal(normalized, compact)
        if not domain_hit:
            return TopLevelIntentResult(
                intent="help",
                confidence=0.95,
                reason="top_level_help",
                domain="general",
                route_candidate="profile",
                matched_signals=["help"],
            )

    domain_hit = _has_domain_signal(normalized, compact)
    shop_entity_hit = _has_shop_entity(normalized, compact)

    if _contains_any(normalized, _STRONG_CAPABILITY_PATTERNS) or _contains_any(compact, _STRONG_CAPABILITY_PATTERNS):
        if not domain_hit and not shop_entity_hit:
            return TopLevelIntentResult(
                intent="capability",
                confidence=0.96,
                reason="top_level_capability",
                domain="general",
                route_candidate="profile",
                matched_signals=["capability"],
            )

    weak_meta_hit = _contains_any(normalized, _WEAK_META_TOKENS) or _contains_any(compact, _WEAK_META_TOKENS)
    if weak_meta_hit and not domain_hit and not shop_entity_hit:
        assistant_subject = _contains_any(normalized, _ASSISTANT_SUBJECT_TOKENS) or _contains_any(compact, _ASSISTANT_SUBJECT_TOKENS)
        if assistant_subject:
            return TopLevelIntentResult(
                intent="capability",
                confidence=0.88,
                reason="top_level_capability_weak",
                domain="general",
                route_candidate="profile",
                matched_signals=["capability"],
            )

    if _is_comparison_query(normalized, compact):
        needs_candidates = _is_pronoun_comparison(normalized, compact)
        return TopLevelIntentResult(
            intent="comparison",
            confidence=0.92,
            reason="top_level_comparison",
            domain="local_life" if domain_hit or shop_entity_hit else "general",
            route_candidate="comparison",
            matched_signals=["comparison"],
            requires_candidate_context=needs_candidates,
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

    if domain_hit or shop_entity_hit or any(
        key in context for key in ("shopId", "shopName", "selected_shop_id", "selected_shop_name", "city", "location")
    ):
        from learning_agent_service.local_life.clarification_strategy import ClarificationStrategy
        
        has_context_shop = bool(context.get("selected_shop_id") or context.get("shopId"))
        requires_current_shop = ClarificationStrategy.requires_current_shop_for_ref(normalized, has_context_shop)
        if _contains_any(normalized, ("推荐", "附近", "周边")) or _contains_any(compact, ("推荐", "附近", "周边")):
            intent = "recommendation"
        else:
            intent = "local_life"

        return TopLevelIntentResult(
            intent=intent,
            confidence=0.85,
            reason="top_level_local_life",
            domain="local_life",
            route_candidate="local_life",
            matched_signals=["local_life"],
            requires_current_shop=requires_current_shop,
        )

    return TopLevelIntentResult(
        intent="out_of_scope",
        confidence=0.7,
        reason="top_level_out_of_scope",
        domain="general",
        route_candidate="direct_answer",
        matched_signals=[],
    )
