from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.enums import IntentType, OutputStyle
from learning_agent_service.domain.utils import as_mapping as _as_mapping

RagVoteValue = str

ALLOW: RagVoteValue = "allow"
DENY: RagVoteValue = "deny"
UNCERTAIN: RagVoteValue = "uncertain"

_GREETING_PATTERNS = (
    "你好",
    "您好",
    "嗨",
    "hello",
    "hi",
    "hey",
    "早上好",
    "下午好",
    "晚上好",
)
_SOCIAL_PATTERNS = (
    "谢谢",
    "多谢",
    "感谢",
    "辛苦了",
    "麻烦了",
)
_FAREWELL_PATTERNS = (
    "再见",
    "拜拜",
    "回头见",
    "晚安",
)
_NEED_PRESENCE_PATTERNS = (
    "在吗",
    "有人吗",
    "还在吗",
    "在线吗",
)
_QUESTION_PATTERNS = (
    "怎么",
    "如何",
    "为什么",
    "区别",
    "原理",
    "流程",
    "实现",
    "分析",
    "解决",
    "问题",
    "报错",
    "错误",
    "异常",
    "代码",
    "RAG",
    "rag",
    "AOP",
    "Spring",
    "ThreadPool",
    "workflow",
    "路由",
    "检索",
    "记忆",
    "流式",
    "门禁",
    "刚才",
    "之前",
    "聊过",
    "说过",
    "记得",
    "上下文",
)
_PROFILE_PATTERNS = (
    "你有什么功能",
    "有什么功能",
    "你有什么工能",
    "有什么工能",
    "能做什么",
    "可以做什么",
    "你会什么",
    "你有什么能力",
    "你的功能",
    "介绍一下你",
    "你是谁",
    "你是什么",
    "怎么使用你",
    "怎么用你",
)
_EXPLAIN_INTENTS = {
    IntentType.EXPLAIN,
    IntentType.COMPARE,
    IntentType.SUMMARY,
    IntentType.FOLLOW_UP,
}
_PUNCTUATION_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)


@dataclass(frozen=True)
class RagGateRequest:
    raw_query: str
    intent: IntentType | None = None
    intent_confidence: float = 0.0
    requested_output_style: OutputStyle | None = None
    current_topic: str | None = None
    recent_entities: Sequence[str] = field(default_factory=tuple)
    history_summary: str | None = None
    pending_clarification: Mapping[str, Any] | None = None
    reference_confidence: float | None = None
    reference_resolved: bool | None = None
    client_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagGateVote:
    vote: RagVoteValue
    reason: str
    confidence: float = 0.0
    response_kind: str = "fallback"

    def as_dict(self) -> dict[str, Any]:
        return {
            "vote": self.vote,
            "reason": self.reason,
            "confidence": self.confidence,
            "response_kind": self.response_kind,
        }


@dataclass(frozen=True)
class RagGateDecision:
    allowed: bool
    reason: str
    rule_vote: RagGateVote
    llm_vote: RagGateVote | None = None
    confidence: float = 0.0
    response_kind: str = "fallback"
    precheck_skip_memory: bool = False
    final_vote: RagVoteValue = DENY
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "confidence": self.confidence,
            "response_kind": self.response_kind,
            "precheck_skip_memory": self.precheck_skip_memory,
            "final_vote": self.final_vote,
            "rule_vote": self.rule_vote.as_dict(),
            "llm_vote": self.llm_vote.as_dict() if self.llm_vote is not None else None,
            "metadata": dict(self.metadata),
        }


def normalize_rag_gate_request(request: RagGateRequest) -> str:
    return " ".join((request.raw_query or "").strip().split())


def classify_rag_rule(request: RagGateRequest) -> RagGateVote:
    text = normalize_rag_gate_request(request)
    lowered = text.lower()
    content_tokens = _content_tokens(text)
    pending_clarification = _as_mapping(request.pending_clarification)

    if not text or _PUNCTUATION_RE.fullmatch(text) or not content_tokens:
        return RagGateVote(
            vote=DENY,
            reason="empty_or_noise",
            confidence=0.99,
            response_kind="empty",
        )

    if _contains_any(text, _GREETING_PATTERNS) or _contains_any(lowered, _GREETING_PATTERNS):
        return RagGateVote(
            vote=DENY,
            reason="greeting",
            confidence=0.99,
            response_kind="greeting",
        )

    if _contains_any(text, _NEED_PRESENCE_PATTERNS) or _contains_any(lowered, _NEED_PRESENCE_PATTERNS):
        return RagGateVote(
            vote=DENY,
            reason="need_presence",
            confidence=0.96,
            response_kind="greeting",
        )

    if _contains_any(text, _SOCIAL_PATTERNS) or _contains_any(lowered, _SOCIAL_PATTERNS):
        return RagGateVote(
            vote=DENY,
            reason="social_chitchat",
            confidence=0.95,
            response_kind="thanks",
        )

    if _contains_any(text, _FAREWELL_PATTERNS) or _contains_any(lowered, _FAREWELL_PATTERNS):
        return RagGateVote(
            vote=DENY,
            reason="farewell",
            confidence=0.95,
            response_kind="farewell",
        )

    if _looks_like_profile_query(text, lowered):
        return RagGateVote(
            vote=ALLOW,
            reason="profile_query",
            confidence=0.94,
            response_kind="profile",
        )

    has_question_signal = any(marker in text or marker in lowered for marker in _QUESTION_PATTERNS) or "?" in text or "？" in text
    has_explain_intent = request.intent in _EXPLAIN_INTENTS and request.intent_confidence >= 0.55
    has_context_anchor = bool(request.current_topic or request.recent_entities or request.history_summary)

    if has_question_signal:
        return RagGateVote(
            vote=ALLOW,
            reason="explicit_question_signal",
            confidence=0.86,
        )

    if has_explain_intent and (_contains_any(text, _QUESTION_PATTERNS) or len(text) >= 8 or has_context_anchor):
        return RagGateVote(
            vote=ALLOW,
            reason="contentful_explain_like_turn",
            confidence=min(max(request.intent_confidence, 0.72), 0.95),
        )

    if pending_clarification is not None and _matches_pending_clarification(text, pending_clarification):
        return RagGateVote(
            vote=ALLOW,
            reason="pending_clarification",
            confidence=0.9,
        )

    if len(content_tokens) <= 1 or len(text) <= 6:
        return RagGateVote(
            vote=DENY,
            reason="low_information",
            confidence=0.8,
            response_kind="low_info",
        )

    if len(text) >= 12 or has_context_anchor:
        return RagGateVote(
            vote=UNCERTAIN,
            reason="needs_llm_confirmation",
            confidence=0.45,
        )

    return RagGateVote(
        vote=DENY,
        reason="low_information",
        confidence=0.72,
        response_kind="low_info",
    )


def compose_direct_response_text(raw_query: str, response_kind: str | None, reason: str | None = None) -> str:
    kind = (response_kind or "").strip().lower()
    if kind == "greeting":
        return "你好，我在。你可以直接告诉我想查什么、想解释什么，或者把问题贴出来。"
    if kind == "thanks":
        return "不客气，有需要继续问我。"
    if kind == "farewell":
        return "好的，之后想继续查知识、门店或工具信息，随时来找我。"
    if kind == "profile":
        return "我可以帮你做通用问答、代码解释和调试、文本润色与翻译，也能结合本地生活信息帮你筛店、看券、做对比和推荐。"
    if kind == "memory_update":
        return "我记住了，这个偏好我会尽量沿用到后续对话里。"
    if kind == "conversation_recap":
        return "我记得我们刚才主要在聊上一轮的上下文。你可以继续问我刚才那家店、那张券，或者让我接着往下说。"
    if kind == "location_unavailable":
        return "这个位置不太适合本地生活推荐。你可以换成具体城市、商圈或地标，我再继续帮你找。"
    if kind == "empty":
        text = normalize_rag_gate_request(RagGateRequest(raw_query=raw_query))
        if text:
            return f"我先按你的问题理解为：{text}。如果你愿意补充一点上下文，我可以继续从原理、流程、示例或排错思路展开，给你更具体的说明。"
        return "我现在还缺少上下文。你可以补充一个具体问题、对象或范围。"
    if kind == "low_info":
        text = normalize_rag_gate_request(RagGateRequest(raw_query=raw_query))
        if text:
            return f"这个问题还不够具体。你可以补充对象、范围或目标；如果你是想问「{text}」相关内容，我可以继续展开，给你更具体的答复。"
        return "这个问题还不够具体。你可以补充对象、范围或目标，我给你更具体的回复。"

    text = (raw_query or "").strip()
    if text:
        if any(marker.lower() in text.lower() for marker in ("spring", "aop", "rag", "stream", "tool", "sse", "检索", "原理", "报错", "异常", "实现")):
            return f"我先按你的问题来理解：{text}。如果你愿意，我可以继续从原理、流程、示例或排错思路展开，给你更具体的答复。"
        return f"我先按你的问题来理解：{text}。如果你愿意补充一点上下文，我可以继续给你更具体的说明。"
    if reason:
        return "我需要更具体的信息才能继续。你可以补充对象、范围或目标。"
    return "我需要更具体的信息才能继续。你可以补充对象、范围或目标。"


def _matches_pending_clarification(text: str, pending_clarification: Mapping[str, Any]) -> bool:
    normalized = normalize_rag_gate_request(RagGateRequest(raw_query=text))
    if not normalized:
        return False

    options = pending_clarification.get("options")
    if isinstance(options, (list, tuple)):
        for option in options:
            if not isinstance(option, Mapping):
                continue
            for key in ("value", "label", "description"):
                candidate = normalize_rag_gate_request(RagGateRequest(raw_query=str(option.get(key) or "")))
                if candidate and candidate in normalized:
                    return True

    ambiguity_type = str(pending_clarification.get("ambiguity_type") or "").strip().lower()
    if ambiguity_type in {"location", "city", "area", "district", "region"}:
        if any(city in normalized for city in ("北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "天津")):
            return True
        if len(normalized) <= 6 and any("\u4e00" <= char <= "\u9fff" for char in normalized):
            return True

    return False


def _combine_votes(rule_vote: RagVoteValue, llm_vote: RagVoteValue | None) -> RagVoteValue:
    if llm_vote is None:
        return rule_vote if rule_vote != UNCERTAIN else DENY
    if DENY in {rule_vote, llm_vote}:
        return DENY
    if ALLOW in {rule_vote, llm_vote}:
        return ALLOW
    return DENY


def _resolve_reason(rule: RagGateVote, llm: RagGateVote | None, final_vote: RagVoteValue) -> str:
    if final_vote == ALLOW:
        if llm is not None and llm.vote == ALLOW and llm.reason:
            return llm.reason
        return rule.reason
    if rule.vote == DENY:
        return rule.reason
    if llm is not None and llm.vote == DENY:
        return llm.reason
    if llm is not None and llm.reason:
        return llm.reason
    return rule.reason


def _resolve_response_kind(rule: RagGateVote, llm: RagGateVote | None) -> str:
    if rule.vote == DENY and rule.response_kind != "fallback":
        return rule.response_kind
    if llm is not None and llm.vote == DENY and llm.response_kind != "fallback":
        return llm.response_kind
    return rule.response_kind if rule.response_kind != "fallback" else (llm.response_kind if llm else "fallback")


def _aggregate_confidence(rule: RagGateVote, llm: RagGateVote | None, final_vote: RagVoteValue) -> float:
    if llm is None:
        return rule.confidence
    if final_vote == ALLOW:
        return max(rule.confidence, llm.confidence)
    if final_vote == DENY:
        return max(rule.confidence, llm.confidence)
    return min(rule.confidence, llm.confidence)


@dataclass
class RagRouteGate:
    llm_judge: Callable[[RagGateRequest], RagGateVote] | None = None

    def precheck(self, request: RagGateRequest) -> RagGateVote:
        return classify_rag_rule(request)

    def should_skip_memory_retrieval(self, request: RagGateRequest) -> bool:
        return self.precheck(request).vote == DENY

    def decide(self, request: RagGateRequest) -> RagGateDecision:
        rule_vote = self.precheck(request)
        if rule_vote.vote == DENY:
            return RagGateDecision(
                allowed=False,
                reason=rule_vote.reason,
                rule_vote=rule_vote,
                confidence=rule_vote.confidence,
                response_kind=rule_vote.response_kind,
                precheck_skip_memory=True,
                final_vote=DENY,
                metadata={"voting_mode": "rule_only"},
            )

        llm_vote = None
        if self.llm_judge is not None:
            try:
                llm_vote = self.llm_judge(request)
            except Exception as exc:  # pragma: no cover - defensive fallback
                llm_vote = RagGateVote(
                    vote=UNCERTAIN,
                    reason=f"llm_error:{exc}",
                    confidence=0.0,
                    response_kind="fallback",
                )

        final_vote = _combine_votes(rule_vote.vote, llm_vote.vote if llm_vote is not None else None)
        return RagGateDecision(
            allowed=final_vote == ALLOW,
            reason=_resolve_reason(rule_vote, llm_vote, final_vote),
            rule_vote=rule_vote,
            llm_vote=llm_vote,
            confidence=_aggregate_confidence(rule_vote, llm_vote, final_vote),
            response_kind=_resolve_response_kind(rule_vote, llm_vote),
            precheck_skip_memory=rule_vote.vote == DENY,
            final_vote=final_vote,
            metadata={
                "voting_mode": "rule_plus_llm" if llm_vote is not None else "rule_only",
                "raw_query": request.raw_query,
            },
        )


def _contains_any(text: str, patterns: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _content_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)
    return [token for token in tokens if token.strip()]


def _looks_like_profile_query(text: str, lowered: str) -> bool:
    compact = text.replace(" ", "")
    if _contains_any(compact, _PROFILE_PATTERNS) or _contains_any(lowered, tuple(pattern.lower() for pattern in _PROFILE_PATTERNS)):
        return True
    if len(compact) <= 12 and any(token in compact for token in ("功能", "工能", "能力")) and any(
        token in compact for token in ("你", "我", "介绍", "帮助", "是什么", "是谁")
    ):
        return True
    return any(token in lowered for token in ("what can you do", "what are your capabilities", "what can you help with"))
