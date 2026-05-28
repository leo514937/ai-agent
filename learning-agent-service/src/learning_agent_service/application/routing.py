from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from ..domain.contracts import (
    AnswerContract,
    AnswerVerifierResult,
    EvidenceItem,
    EvidencePack,
    EvidenceQualityDecision,
    FastDecision,
    InputQualityDecision,
    IntentRoutingDecision,
    EntityJoinResult,
    PlanStep,
    PersistentSessionContext,
    RetrievalEligibility,
    RewriteDecision,
    RoutingDecision,
    TaskPlan,
    TurnRuntimeState,
)
from ..domain.enums import IntentType
from ..config import get_settings
from ..local_life.query_rewriter import _CITY_NAMES as _LOCAL_LIFE_CITY_NAMES
from .routing_signals import (
    DomainSignalRegistry,
    SemanticRoutingDraft,
    route_semantic_query,
    synthesize_retrieval_plan,
    synthesize_tool_selection,
)

_PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")
_NOISE_REPEAT_RE = re.compile(r"^(.)\1{5,}$", re.UNICODE)
_LOW_INFO_TOKENS = {
    "嗯",
    "啊",
    "哦",
    "唔",
    "好",
    "然后",
    "还有",
    "那",
    "这个",
    "那个",
    "就是",
    "对",
    "行",
    "可以",
    "额",
    "呃",
    "嗯嗯",
}
_GREETING_TOKENS = ("你好", "您好", "嗨", "hello", "hi", "hey")
_THANKS_TOKENS = ("谢谢", "多谢", "感谢", "辛苦了")
_PROFILE_TOKENS = ("你有什么功能", "有什么功能", "能做什么", "你会什么", "你是谁", "你是什么", "怎么用你")
_REFERENCE_TOKENS = (
    "这个呢",
    "那家呢",
    "第二个呢",
    "第二家呢",
    "第一个呢",
    "它呢",
    "这家",
    "那家",
    "这个店",
    "那个店",
    "这个套餐",
    "那个套餐",
    "第二个",
    "第二家",
    "第一个",
    "前一个",
    "后一个",
)
_INCOMPLETE_RECOMMEND_TOKENS = (
    "附近有什么推荐",
    "有什么推荐",
    "推荐一下",
    "帮我推荐",
    "有什么好的",
    "附近有啥",
    "附近好吃",
    "周边推荐",
)
_MEMORY_UPDATE_TOKENS = ("以后", "一直", "长期", "记住", "习惯", "不吃辣", "少吃辣", "不吃香菜", "不吃牛肉", "偏好")
_SESSION_ONLY_TOKENS = ("今天", "这次", "暂时", "今晚", "这顿", "这回", "本次")
_RETRIEVAL_ACTIONS = {"rag_retrieval", "rag_plus_tool"}
_NON_RETRIEVAL_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject", "tool_call"}
_DIRECT_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject"}
_RETRIEVAL_SCORE_THRESHOLD = 0.55
_PHASE0_TRACE_KEY = "phase0_trace"
_PHASE1_TRACE_KEY = "phase1_trace"
_PHASE2_TRACE_KEY = "phase2_trace"
_PHASE3_TRACE_KEY = "phase3_trace"
_PHASE4_TRACE_KEY = "phase4_trace"
_LOCAL_LIFE_QUERY_TOKENS = (
    "附近",
    "周边",
    "推荐",
    "火锅",
    "烤肉",
    "火锅店",
    "餐厅",
    "饭店",
    "店",
    "适合",
    "约会",
    "带父母",
    "带长辈",
    "现在营业",
    "营业",
    "开门",
    "还能用",
    "优惠券",
    "券",
    "团购",
    "套餐",
    "人均",
    "不踩雷",
    "不吵",
)
_UNSERVICEABLE_LOCATION_TOKENS = (
    "北极",
    "南极",
)
_PHASE1_DATA_SOURCE_SLOT = "slot"
_PHASE1_DATA_SOURCE_STATIC_RAG = "static_rag"
_PHASE1_DATA_SOURCE_DYNAMIC_TOOL = "dynamic_tool"
_PHASE1_DATA_SOURCE_CLIENT_CONTEXT = "client_context"
_PHASE1_DATA_SOURCE_MIXED = "mixed"


@dataclass(frozen=True)
class RoutingBuildContext:
    raw_query: str
    persistent: PersistentSessionContext
    client_context: Mapping[str, Any] | None = None


def normalize_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.replace("\u3000", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _compact(text: str) -> str:
    return "".join(normalize_query(text).split())


def _content_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall(normalize_query(text)) if token.strip()]


def _context_has_anchor(persistent: PersistentSessionContext) -> bool:
    return bool(
        persistent.current_topic
        or persistent.current_shop
        or persistent.recent_entities
        or persistent.last_candidates
        or persistent.current_city
        or persistent.current_location
        or persistent.current_constraints
        or persistent.pending_clarification
    )


def _context_has_candidate_anchor(persistent: PersistentSessionContext) -> bool:
    return bool(
        persistent.last_candidates
        or persistent.selected_shop_id
        or persistent.selected_shop_name
        or persistent.current_shop
    )


def _client_context_has_anchor(client_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(client_context, Mapping):
        return False
    for key in (
        "shopName",
        "shop_name",
        "selected_shop_name",
        "current_shop",
        "city",
        "current_city",
        "location",
        "current_location",
        "area",
        "current_area",
        "district",
        "region",
    ):
        value = client_context.get(key)
        if isinstance(value, Mapping):
            if any(str(item).strip() for item in value.values() if item not in (None, "", [], {}, ())):
                return True
            continue
        if str(value or "").strip():
            return True
    return False


def _client_context_has_candidate_anchor(client_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(client_context, Mapping):
        return False
    for key in ("shopName", "shop_name", "selected_shop_name", "current_shop", "shopId", "shop_id", "selected_shop_id"):
        if str(client_context.get(key) or "").strip():
            return True
    return False


def _pending_clarification_matches_query(raw_query: str, persistent: PersistentSessionContext) -> bool:
    pending = persistent.pending_clarification
    if pending is None:
        return False

    normalized = normalize_query(raw_query)
    if not normalized:
        return False

    options = getattr(pending, "options", None) or []
    for option in options:
        for key in ("value", "label", "description"):
            candidate = normalize_query(str(getattr(option, key, "") or ""))
            if candidate and candidate in normalized:
                return True

    ambiguity_type = str(getattr(pending, "ambiguity_type", "") or "").strip().lower()
    if ambiguity_type in {"location", "city", "area", "district", "region"}:
        if _contains_city_mention(normalized):
            return True
        if len(normalized) <= 6 and any("\u4e00" <= char <= "\u9fff" for char in normalized):
            return True

    return False


def _pending_clarification_follow_up_route(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    input_quality: InputQualityDecision,
    client_context: Mapping[str, Any] | None = None,
    base_route: RoutingDecision,
) -> RoutingDecision | None:
    pending = persistent.pending_clarification
    if pending is None or not _pending_clarification_matches_query(raw_query, persistent):
        return None

    ambiguity_type = str(getattr(pending, "ambiguity_type", "") or "").strip().lower()
    if ambiguity_type not in {"location", "city", "area", "district", "region"}:
        return None

    pending_payload = pending.model_dump(mode="json") if hasattr(pending, "model_dump") else dict(pending)
    resolved_query = normalize_query(raw_query)
    route_extra = dict(base_route.extra)
    route_extra["pending_clarification"] = pending_payload
    route_extra["pending_clarification_matched"] = True
    if ambiguity_type in {"location", "city", "area", "district", "region"}:
        original_intent = "local_life_recommend"
        original_route = "rag_retrieval"
    else:
        original_intent = str(
            pending_payload.get("original_intent")
            or pending_payload.get("intent")
            or persistent.clarification_result.get("original_intent")
            or persistent.clarification_result.get("intent")
            or "local_life_recommend"
        ).strip() or "local_life_recommend"
        original_route = str(
            pending_payload.get("original_route")
            or pending_payload.get("route")
            or persistent.clarification_result.get("original_route")
            or persistent.clarification_result.get("route")
            or "rag_retrieval"
        ).strip() or "rag_retrieval"
    route_extra["pending_clarification_restore"] = {
        "original_query": str(
            persistent.clarification_result.get("original_query")
            or persistent.clarification_result.get("query")
            or pending_payload.get("original_query")
            or pending_payload.get("query")
            or getattr(pending, "question", "")
            or ""
        ).strip(),
        "original_intent": original_intent,
        "original_route": original_route,
    }
    route_extra["client_context"] = dict(client_context or {})
    route_extra["context_has_anchor"] = _context_has_anchor(persistent)
    route_extra["context_has_candidate_anchor"] = _context_has_candidate_anchor(persistent)

    return RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=resolved_query,
        domain="local_life",
        confidence=max(base_route.confidence, 0.82),
        input_quality=input_quality,
        intent=IntentRoutingDecision(
            name="local_life_recommend",
            confidence=max(base_route.intent.confidence, 0.82),
            required_slots=[],
            missing_slots=[],
            allowed_routes=["rag_retrieval", "tool_call", "rag_plus_tool"],
            forbidden_routes=["clarify"],
        ),
        required_action="rag_retrieval",
        blocked=False,
        blocked_reason=None,
        should_rewrite_query=True,
        should_retrieve=True,
        should_call_tool=False,
        should_use_memory=True,
        should_persist_memory=True,
        should_vectorize_memory=True,
        should_emit_retrieval_events=True,
        retrieval_skipped_reason=None,
        missing_slots=[],
        resolved_references=[resolved_query] if resolved_query else [],
        route_reason="pending_clarification_location",
        safeguards_triggered=list(dict.fromkeys(list(base_route.safeguards_triggered) + ["pending_clarification"])),
        route_candidate="local_life",
        preferred_chunk_roles=["merchant_scene_fit", "merchant_review_summary"],
        tool_candidates=[],
        clarification_question=None,
        extra=route_extra,
    )


def _looks_like_unserviceable_location(raw_query: str) -> bool:
    normalized = normalize_query(raw_query)
    if not normalized:
        return False
    compact = normalized.replace(" ", "")
    if any(token in compact for token in _UNSERVICEABLE_LOCATION_TOKENS):
        return True
    return False


def _conversation_recap_route(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    input_quality: InputQualityDecision,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision | None:
    normalized = normalize_query(raw_query)
    if not normalized:
        return None
    compact = normalized.replace(" ", "")
    recap_patterns = (
        "你记得我们说过什么吗",
        "你记得我们说过什么",
        "你还记得我们说过什么",
        "我们说过什么",
        "刚才说到哪了",
        "上一个问题是什么",
        "我们刚才说什么",
        "继续刚才的话题",
        "前面我们聊到哪了",
        "回顾一下我们刚才聊了什么",
    )
    has_recap_signal = any(pattern in compact for pattern in recap_patterns)
    if not has_recap_signal:
        return None

    route_extra = {
        "client_context": dict(client_context or {}),
        "context_has_anchor": _context_has_anchor(persistent),
        "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
        "current_shop": persistent.current_shop or persistent.selected_shop_name,
        "conversation_recap": True,
    }
    return RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=normalized,
        domain="general",
        confidence=0.9 if persistent.history_summary or persistent.current_topic or persistent.recent_entities else 0.82,
        input_quality=input_quality,
        intent=IntentRoutingDecision(
            name="conversation_recap",
            confidence=0.9,
            required_slots=[],
            missing_slots=[],
            allowed_routes=["direct_answer"],
            forbidden_routes=["rag_retrieval", "tool_call"],
        ),
        required_action="direct_answer",
        blocked=False,
        blocked_reason=None,
        should_rewrite_query=False,
        should_retrieve=False,
        should_call_tool=False,
        should_use_memory=False,
        should_persist_memory=False,
        should_vectorize_memory=False,
        should_emit_retrieval_events=False,
        retrieval_skipped_reason=None,
        missing_slots=[],
        resolved_references=[],
        route_reason="conversation_recap_request",
        safeguards_triggered=["conversation_recap"],
        route_candidate="conversation_recap",
        preferred_chunk_roles=[],
        tool_candidates=[],
        clarification_question=None,
        extra=route_extra,
    )


def _continue_previous_topic_route(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    input_quality: InputQualityDecision,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision | None:
    normalized = normalize_query(raw_query)
    if not normalized:
        return None
    compact = normalized.replace(" ", "")
    continuation_patterns = (
        "继续",
        "继续说",
        "接着",
        "接着说",
        "继续刚才",
        "接着刚才",
        "继续上一个",
        "回到刚才的话题",
    )
    if not any(pattern in compact for pattern in continuation_patterns):
        return None

    has_anchor = _context_has_anchor(persistent) or _client_context_has_anchor(client_context)
    if not has_anchor:
        return None

    current_shop = str(
        persistent.current_shop
        or persistent.selected_shop_name
        or persistent.current_topic
        or (client_context or {}).get("current_shop")
        or (client_context or {}).get("shopName")
        or (client_context or {}).get("shop_name")
        or ""
    ).strip()
    current_topic = str(persistent.current_topic or current_shop or "").strip()
    route_extra = {
        "client_context": dict(client_context or {}),
        "context_has_anchor": True,
        "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
        "current_shop": current_shop or None,
    }
    return RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=normalized,
        domain="general",
        confidence=0.86 if persistent.history_summary or current_topic or current_shop else 0.78,
        input_quality=input_quality,
        intent=IntentRoutingDecision(
            name="continue_previous_topic",
            confidence=0.86,
            required_slots=[],
            missing_slots=[],
            allowed_routes=["direct_answer"],
            forbidden_routes=["rag_retrieval", "tool_call"],
        ),
        required_action="direct_answer",
        blocked=False,
        blocked_reason=None,
        should_rewrite_query=False,
        should_retrieve=False,
        should_call_tool=False,
        should_use_memory=False,
        should_persist_memory=False,
        should_vectorize_memory=False,
        should_emit_retrieval_events=False,
        retrieval_skipped_reason=None,
        missing_slots=[],
        resolved_references=[current_topic] if current_topic else [],
        route_reason="continue_previous_topic_request",
        safeguards_triggered=["continue_previous_topic"],
        route_candidate="continue_previous_topic",
        preferred_chunk_roles=[],
        tool_candidates=[],
        clarification_question=None,
        extra=route_extra,
    )


def _contains_any(text: str, tokens: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(token in text or token.lower() in lowered for token in tokens)


def _contains_city_mention(text: str) -> bool:
    normalized = normalize_query(text)
    return any(city in normalized for city in _LOCAL_LIFE_CITY_NAMES if city)


def build_input_quality(raw_query: str) -> InputQualityDecision:
    normalized = normalize_query(raw_query)
    compact = _compact(raw_query)
    if not normalized:
        return InputQualityDecision(kind="empty_input", is_valid=False, reason="empty_input", score=0.0)
    if _PUNCT_ONLY_RE.fullmatch(normalized):
        return InputQualityDecision(kind="pure_punctuation", is_valid=False, reason="pure_punctuation", score=0.0)

    if len(compact) >= 6 and len(set(compact)) <= 2:
        return InputQualityDecision(
            kind="repeated_noise",
            is_valid=False,
            reason="repeated_noise",
            score=0.05,
        )

    content_tokens = _content_tokens(normalized)
    if len(content_tokens) <= 1 and normalized in _LOW_INFO_TOKENS:
        return InputQualityDecision(
            kind="low_information",
            is_valid=False,
            reason="low_information",
            score=0.15,
        )

    if len(compact) <= 2 and compact in _LOW_INFO_TOKENS:
        return InputQualityDecision(
            kind="low_information",
            is_valid=False,
            reason="low_information",
            score=0.15,
        )

    if _contains_any(compact, _REFERENCE_TOKENS) or _contains_any(normalized, _REFERENCE_TOKENS):
        return InputQualityDecision(
            kind="ambiguous_reference",
            is_valid=True,
            reason="ambiguous_reference",
            score=0.58,
            signals=["reference_token"],
        )

    if _contains_any(compact, _INCOMPLETE_RECOMMEND_TOKENS) or _contains_any(normalized, _INCOMPLETE_RECOMMEND_TOKENS):
        if _contains_city_mention(normalized):
            return InputQualityDecision(
                kind="valid_task",
                is_valid=True,
                reason="valid_task",
                score=0.84,
                signals=["recommendation_hint", "city_mention"],
            )
        return InputQualityDecision(
            kind="incomplete_recommendation",
            is_valid=True,
            reason="incomplete_recommendation",
            score=0.66,
            signals=["recommendation_hint"],
        )

    if len(compact) <= 3 and any(token in compact for token in ("嗯", "啊", "哦", "好", "行", "对")):
        return InputQualityDecision(
            kind="low_information",
            is_valid=False,
            reason="low_information",
            score=0.2,
        )

    return InputQualityDecision(kind="valid_task", is_valid=True, reason="valid_task", score=0.92)


def _detect_response_kind(raw_query: str) -> tuple[str | None, str | None]:
    normalized = normalize_query(raw_query)
    compact = _compact(raw_query)
    lowered = normalized.lower()
    if not normalized:
        return "empty", "empty_input"
    if _contains_any(normalized, _PROFILE_TOKENS):
        return "profile", "profile_query"
    if _contains_any(normalized, _GREETING_TOKENS) or _contains_any(compact, _GREETING_TOKENS) or _contains_any(lowered, _GREETING_TOKENS):
        return "greeting", "greeting"
    if _contains_any(normalized, _THANKS_TOKENS) or _contains_any(compact, _THANKS_TOKENS) or _contains_any(lowered, _THANKS_TOKENS):
        return "thanks", "thanks"
    return None, None


def _detect_memory_update(raw_query: str) -> bool:
    compact = _compact(raw_query)
    return any(token in compact for token in _MEMORY_UPDATE_TOKENS) and not any(token in compact for token in _SESSION_ONLY_TOKENS)


def _detect_session_only_preference(raw_query: str) -> bool:
    compact = _compact(raw_query)
    session_tokens = any(token in compact for token in _SESSION_ONLY_TOKENS)
    memory_tokens = any(token in compact for token in _MEMORY_UPDATE_TOKENS)
    temporary_negation_tokens = any(token in compact for token in ("不想", "暂时不", "这次不", "今天不", "今晚不", "先不", "不要", "别"))
    return session_tokens and (memory_tokens or temporary_negation_tokens)


def _mark_routing_blocked(
    routing: RoutingDecision,
    *,
    reason: str,
    required_action: str = "clarify",
    route_candidate: str | None = None,
) -> RoutingDecision:
    safe_action = required_action if required_action in {"clarify", "reject", "no_op"} else "clarify"
    extra = dict(routing.extra)
    extra["blocked_reason"] = reason
    extra["retrieval_skipped_reason"] = reason
    return routing.model_copy(
        update={
            "blocked": True,
            "blocked_reason": reason,
            "required_action": safe_action,
            "should_rewrite_query": False,
            "should_retrieve": False,
            "should_call_tool": False,
            "should_use_memory": False,
            "should_persist_memory": False,
            "should_vectorize_memory": False,
            "should_emit_retrieval_events": False,
            "retrieval_skipped_reason": reason,
            "route_reason": routing.route_reason or reason,
            "route_candidate": route_candidate if route_candidate is not None else routing.route_candidate,
            "extra": extra,
        }
    )


def _is_retrieval_action(required_action: str | None) -> bool:
    return str(required_action or "").strip().lower() in _RETRIEVAL_ACTIONS


def _intent_allows_retrieval(intent: IntentRoutingDecision) -> bool:
    allowed_routes = {str(route).strip().lower() for route in intent.allowed_routes if str(route).strip()}
    forbidden_routes = {str(route).strip().lower() for route in intent.forbidden_routes if str(route).strip()}
    if _RETRIEVAL_ACTIONS & forbidden_routes:
        return False
    if _RETRIEVAL_ACTIONS & allowed_routes:
        return True
    intent_name = str(intent.name or "").strip().lower()
    return intent_name not in {"unknown", "chit_chat", "direct_answer", "memory_update", "invalid_input", "no_op"}


_DOMAIN_SIGNAL_REGISTRY = DomainSignalRegistry()


def _semantic_route_for_query(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    client_context: Mapping[str, Any] | None = None,
) -> SemanticRoutingDraft:
    return route_semantic_query(
        raw_query,
        persistent=persistent,
        client_context=client_context,
        registry=_DOMAIN_SIGNAL_REGISTRY,
    )


def _intent_from_semantic_route(route: SemanticRoutingDraft) -> IntentRoutingDecision:
    allowed_routes: list[str] = []
    forbidden_routes: list[str] = []
    action = str(route.required_action or "").strip().lower()
    if action == "rag_plus_tool":
        allowed_routes = ["rag_retrieval", "tool_call", "rag_plus_tool"]
    elif action == "rag_retrieval":
        allowed_routes = ["rag_retrieval"]
        forbidden_routes = ["tool_call"]
    elif action == "tool_call":
        allowed_routes = ["tool_call"]
        forbidden_routes = ["rag_retrieval"]
    elif action == "memory_update":
        allowed_routes = ["memory_update", "direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    elif action == "direct_answer":
        allowed_routes = ["direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    elif action in {"clarify", "reject", "no_op"}:
        allowed_routes = [action]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    return IntentRoutingDecision(
        name=str(route.intent or "unknown"),
        confidence=float(route.confidence or 0.0),
        required_slots=list(route.missing_slots),
        missing_slots=list(route.missing_slots),
        allowed_routes=allowed_routes,
        forbidden_routes=forbidden_routes,
    )


def _route_decision_from_semantic_route(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision:
    route = _semantic_route_for_query(raw_query, persistent, client_context=client_context)
    input_quality = build_input_quality(raw_query)
    intent = _intent_from_semantic_route(route)
    should_retrieve = bool(route.should_retrieve and route.required_action in _RETRIEVAL_ACTIONS and input_quality.is_valid)
    should_call_tool = bool(route.should_call_tool and route.required_action in {"tool_call", "rag_plus_tool"} and input_quality.is_valid)
    should_use_memory = route.required_action not in {"clarify", "reject", "no_op"} and input_quality.is_valid
    should_persist_memory = route.required_action not in {"clarify", "reject", "no_op"} and input_quality.is_valid
    should_vectorize_memory = should_persist_memory
    blocked = route.required_action in {"reject"} or not input_quality.is_valid
    blocked_reason = input_quality.reason if not input_quality.is_valid else None
    if route.required_action == "clarify" and route.clarification_question:
        route_reason = route.route_reason or "clarify_required"
    else:
        route_reason = route.route_reason or f"semantic:{route.route_candidate or route.intent}"
    return RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=normalize_query(raw_query),
        domain=route.domain,
        confidence=float(route.confidence or 0.0),
        input_quality=input_quality,
        intent=intent,
        required_action=route.required_action,
        blocked=blocked,
        blocked_reason=blocked_reason,
        should_rewrite_query=bool(route.should_rewrite_query and not blocked),
        should_retrieve=should_retrieve and not blocked,
        should_call_tool=should_call_tool and not blocked,
        should_use_memory=should_use_memory and not blocked,
        should_persist_memory=should_persist_memory and not blocked,
        should_vectorize_memory=should_vectorize_memory and not blocked,
        should_emit_retrieval_events=should_retrieve and not blocked,
        retrieval_skipped_reason=blocked_reason,
        missing_slots=list(route.missing_slots),
        resolved_references=[],
        route_reason=route_reason,
        safeguards_triggered=list(route.safeguards_triggered),
        route_candidate=route.route_candidate,
        preferred_chunk_roles=list(route.preferred_chunk_roles),
        tool_candidates=list(route.tool_candidates),
        clarification_question=route.clarification_question,
        extra={
            "semantic_route": route.__dict__,
            "candidate_names": list(route.candidate_names),
        },
    )


def build_initial_routing_decision(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision:
    normalized_query = normalize_query(raw_query)
    input_quality = build_input_quality(raw_query)
    response_kind, response_reason = _detect_response_kind(raw_query)
    route = _route_decision_from_semantic_route(raw_query, persistent, client_context=client_context)
    route_reason = route.route_reason or response_reason or input_quality.reason
    route_candidate = route.route_candidate
    missing_slots = list(route.missing_slots)
    clarification_question = route.clarification_question or build_clarification_question(
        missing_slots,
        query_text=raw_query,
    )
    if clarification_question and not route.clarification_question:
        route = route.model_copy(update={"clarification_question": clarification_question})
    if _looks_like_unserviceable_location(raw_query) or bool(dict(route.extra or {}).get("unserviceable_location")):
        route = RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalized_query,
            domain="local_life",
            confidence=max(route.confidence, 0.88),
            input_quality=input_quality,
            intent=IntentRoutingDecision(
                name="location_unavailable",
                confidence=0.88,
                required_slots=[],
                missing_slots=[],
                allowed_routes=["direct_answer"],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action="direct_answer",
            blocked=False,
            blocked_reason=None,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=None,
            missing_slots=[],
            resolved_references=[],
            route_reason="unserviceable_location",
            safeguards_triggered=list(dict.fromkeys(list(route.safeguards_triggered) + ["unserviceable_location"])),
            route_candidate="location_unavailable",
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                **dict(route.extra),
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                "unserviceable_location": True,
            },
        )
    pending_follow_up_route = _pending_clarification_follow_up_route(
        raw_query,
        persistent,
        input_quality=input_quality,
        client_context=client_context,
        base_route=route,
    )
    if pending_follow_up_route is not None:
        route = pending_follow_up_route
        route_reason = route.route_reason or response_reason or input_quality.reason
        route_candidate = route.route_candidate
        missing_slots = list(route.missing_slots)
        clarification_question = route.clarification_question
    recap_route = _conversation_recap_route(
        raw_query,
        persistent,
        input_quality=input_quality,
        client_context=client_context,
    )
    if recap_route is not None:
        route = recap_route
        route_reason = route.route_reason or response_reason or input_quality.reason
        route_candidate = route.route_candidate
        missing_slots = list(route.missing_slots)
        clarification_question = route.clarification_question
    continue_route = _continue_previous_topic_route(
        raw_query,
        persistent,
        input_quality=input_quality,
        client_context=client_context,
    )
    if continue_route is not None:
        route = continue_route
        route_reason = route.route_reason or response_reason or input_quality.reason
        route_candidate = route.route_candidate
        missing_slots = list(route.missing_slots)
        clarification_question = route.clarification_question
    resolved_references: list[str] = []
    safeguards_triggered = list(route.safeguards_triggered)

    if _looks_like_unserviceable_location(raw_query) or bool(dict(route.extra or {}).get("unserviceable_location")):
        route = RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalized_query,
            domain="local_life",
            confidence=max(route.confidence, 0.88),
            intent=IntentRoutingDecision(
                name="location_unavailable",
                confidence=0.88,
                required_slots=[],
                missing_slots=[],
                allowed_routes=["direct_answer"],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action="direct_answer",
            blocked=False,
            blocked_reason=None,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=None,
            missing_slots=[],
            resolved_references=[],
            route_reason="unserviceable_location",
            safeguards_triggered=list(dict.fromkeys(list(route.safeguards_triggered) + ["unserviceable_location"])),
            route_candidate="location_unavailable",
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                **dict(route.extra),
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                "unserviceable_location": True,
            },
        )
        route_reason = route.route_reason
        route_candidate = route.route_candidate
        missing_slots = list(route.missing_slots)
        clarification_question = route.clarification_question

    if input_quality.kind in {"empty_input", "pure_punctuation", "repeated_noise"}:
        return _mark_routing_blocked(
            RoutingDecision(
                raw_query=str(raw_query or ""),
                normalized_query=normalized_query,
                domain="general",
                confidence=0.0,
                input_quality=input_quality,
                intent=IntentRoutingDecision(name="invalid_input", confidence=0.0, allowed_routes=["reject"], forbidden_routes=["rag_retrieval", "tool_call"]),
                required_action="reject",
                blocked=True,
                blocked_reason=input_quality.reason,
                should_rewrite_query=False,
                should_retrieve=False,
                should_call_tool=False,
                should_use_memory=False,
                should_persist_memory=False,
                should_vectorize_memory=False,
                should_emit_retrieval_events=False,
                retrieval_skipped_reason=input_quality.reason,
                missing_slots=[],
                resolved_references=[],
                route_reason=input_quality.reason,
                safeguards_triggered=[input_quality.kind],
                route_candidate="reject",
                preferred_chunk_roles=[],
                tool_candidates=[],
                clarification_question=None,
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                },
            ),
            reason=input_quality.reason,
            required_action="reject",
            route_candidate="reject",
        )

    if input_quality.kind == "low_information":
        if response_kind in {"greeting", "thanks", "profile"}:
            route = RoutingDecision(
                raw_query=str(raw_query or ""),
                normalized_query=normalized_query,
                domain="general",
                confidence=0.97 if response_kind in {"greeting", "thanks"} else 0.92,
                input_quality=input_quality,
                intent=IntentRoutingDecision(
                    name="chit_chat" if response_kind in {"greeting", "thanks"} else "direct_answer",
                    confidence=0.97 if response_kind in {"greeting", "thanks"} else 0.92,
                    required_slots=[],
                    missing_slots=[],
                    allowed_routes=["direct_answer"],
                    forbidden_routes=["rag_retrieval", "tool_call"],
                ),
                required_action="direct_answer",
                blocked=False,
                should_rewrite_query=False,
                should_retrieve=False,
                should_call_tool=False,
                should_use_memory=False,
                should_persist_memory=False,
                should_vectorize_memory=False,
                should_emit_retrieval_events=False,
                retrieval_skipped_reason=None,
                missing_slots=[],
                resolved_references=[],
                route_reason=response_reason or response_kind,
                safeguards_triggered=safeguards_triggered,
                route_candidate=response_kind,
                preferred_chunk_roles=[],
                tool_candidates=[],
                clarification_question=None,
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent) or _client_context_has_anchor(client_context),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context),
                    "current_shop": persistent.current_shop or persistent.selected_shop_name,
                },
            )
        elif (_context_has_anchor(persistent) or _client_context_has_anchor(client_context)) and _contains_any(normalized_query, ("然后", "还有", "那", "继续")):
            route = RoutingDecision(
                raw_query=str(raw_query or ""),
                normalized_query=normalized_query,
                domain=route.domain,
                confidence=max(route.confidence, 0.58),
                input_quality=input_quality,
                intent=IntentRoutingDecision(
                    name="follow_up_reference",
                    confidence=0.58,
                    required_slots=[],
                    missing_slots=[],
                    allowed_routes=["rag_retrieval", "tool_call", "rag_plus_tool", "direct_answer"],
                    forbidden_routes=["reject"],
                ),
                required_action="rag_retrieval",
                blocked=False,
                should_rewrite_query=True,
                should_retrieve=True,
                should_call_tool=False,
                should_use_memory=True,
                should_persist_memory=True,
                should_vectorize_memory=True,
                should_emit_retrieval_events=True,
                retrieval_skipped_reason=None,
                missing_slots=[],
                resolved_references=[],
                route_reason="follow_up_reference_with_context",
                safeguards_triggered=safeguards_triggered,
                route_candidate="follow_up_reference",
                preferred_chunk_roles=["merchant_review_summary", "merchant_profile"],
                tool_candidates=[],
                clarification_question=None,
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent) or _client_context_has_anchor(client_context),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context),
                },
            )
        else:
            return _mark_routing_blocked(
                RoutingDecision(
                    raw_query=str(raw_query or ""),
                    normalized_query=normalized_query,
                    domain="general",
                    confidence=0.0,
                    input_quality=input_quality,
                    intent=IntentRoutingDecision(name="low_information", confidence=0.1, allowed_routes=["clarify"], forbidden_routes=["rag_retrieval", "tool_call"]),
                    required_action="clarify",
                    blocked=True,
                    blocked_reason="low_information",
                    should_rewrite_query=False,
                    should_retrieve=False,
                    should_call_tool=False,
                    should_use_memory=False,
                    should_persist_memory=False,
                    should_vectorize_memory=False,
                    should_emit_retrieval_events=False,
                    retrieval_skipped_reason="low_information",
                    missing_slots=[],
                    resolved_references=[],
                    route_reason="low_information",
                    safeguards_triggered=safeguards_triggered + ["low_information_gate"],
                    route_candidate="clarify",
                    preferred_chunk_roles=[],
                    tool_candidates=[],
                    clarification_question="你想具体查哪一项？",
                    extra={
                        "client_context": dict(client_context or {}),
                        "context_has_anchor": _context_has_anchor(persistent) or _client_context_has_anchor(client_context),
                        "context_has_candidate_anchor": _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context),
                    },
                ),
                reason="low_information",
                required_action="clarify",
                route_candidate="clarify",
            )

    if input_quality.kind == "ambiguous_reference":
        has_anchor = (
            _context_has_candidate_anchor(persistent)
            or _context_has_anchor(persistent)
            or _client_context_has_candidate_anchor(client_context)
            or _client_context_has_anchor(client_context)
        )
        if has_anchor:
            resolved_reference = str(
                persistent.current_shop
                or persistent.selected_shop_name
                or persistent.current_topic
                or (client_context or {}).get("shopName")
                or (client_context or {}).get("shop_name")
                or ""
            ).strip()
            route = RoutingDecision(
                raw_query=str(raw_query or ""),
                normalized_query=normalized_query,
                domain=route.domain,
                confidence=max(route.confidence, 0.62),
                input_quality=input_quality,
                intent=IntentRoutingDecision(
                    name="follow_up_reference",
                    confidence=0.62,
                    required_slots=[],
                    missing_slots=[],
                    allowed_routes=["rag_retrieval", "tool_call", "rag_plus_tool", "direct_answer"],
                    forbidden_routes=["reject"],
                ),
                required_action="rag_retrieval",
                blocked=False,
                should_rewrite_query=True,
                should_retrieve=True,
                should_call_tool=False,
                should_use_memory=True,
                should_persist_memory=True,
                should_vectorize_memory=True,
                should_emit_retrieval_events=True,
                retrieval_skipped_reason=None,
                missing_slots=[],
                resolved_references=[resolved_reference] if resolved_reference else [],
                route_reason="follow_up_reference",
                safeguards_triggered=safeguards_triggered,
                route_candidate="follow_up_reference",
                preferred_chunk_roles=["merchant_review_summary", "merchant_profile"],
                tool_candidates=[],
                clarification_question=None,
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent) or _client_context_has_anchor(client_context),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context),
                    "current_shop": persistent.current_shop or persistent.selected_shop_name,
                },
            )
        else:
            return _mark_routing_blocked(
                RoutingDecision(
                    raw_query=str(raw_query or ""),
                    normalized_query=normalized_query,
                    domain="general",
                    confidence=0.0,
                    input_quality=input_quality,
                    intent=IntentRoutingDecision(name="ambiguous_reference", confidence=0.1, allowed_routes=["clarify"], forbidden_routes=["rag_retrieval", "tool_call"]),
                    required_action="clarify",
                    blocked=True,
                    blocked_reason="ambiguous_reference_without_context",
                    should_rewrite_query=False,
                    should_retrieve=False,
                    should_call_tool=False,
                    should_use_memory=False,
                    should_persist_memory=False,
                    should_vectorize_memory=False,
                    should_emit_retrieval_events=False,
                    retrieval_skipped_reason="ambiguous_reference_without_context",
                    missing_slots=[],
                    resolved_references=[],
                    route_reason="ambiguous_reference_without_context",
                    safeguards_triggered=safeguards_triggered + ["ambiguous_reference_without_context"],
                    route_candidate="clarify",
                    preferred_chunk_roles=[],
                    tool_candidates=[],
                    clarification_question="你是指哪一家/哪一个？",
                    extra={
                        "client_context": dict(client_context or {}),
                        "context_has_anchor": _context_has_anchor(persistent) or _client_context_has_anchor(client_context),
                        "context_has_candidate_anchor": _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context),
                    },
                ),
                reason="ambiguous_reference_without_context",
                required_action="clarify",
                route_candidate="clarify",
            )

    if input_quality.kind == "incomplete_recommendation" and _context_has_candidate_anchor(persistent) and _contains_any(
        normalized_query,
        ("附近", "周边", "附近有什么", "附近有啥"),
    ):
        return _mark_routing_blocked(
            RoutingDecision(
                raw_query=str(raw_query or ""),
                normalized_query=normalized_query,
                domain="local_life",
                confidence=0.0,
                input_quality=input_quality,
                intent=IntentRoutingDecision(
                    name="local_life_recommend",
                    confidence=0.42,
                    required_slots=["shop_name", "location"],
                    missing_slots=["shop_name", "location"],
                    allowed_routes=["clarify"],
                    forbidden_routes=["rag_retrieval", "tool_call"],
                ),
                required_action="clarify",
                blocked=True,
                blocked_reason="incomplete_recommendation_ambiguous_with_current_shop",
                should_rewrite_query=False,
                should_retrieve=False,
                should_call_tool=False,
                should_use_memory=False,
                should_persist_memory=False,
                should_vectorize_memory=False,
                should_emit_retrieval_events=False,
                retrieval_skipped_reason="incomplete_recommendation_ambiguous_with_current_shop",
                missing_slots=["shop_name", "location"],
                resolved_references=[],
                route_reason="incomplete_recommendation_ambiguous_with_current_shop",
                safeguards_triggered=safeguards_triggered + ["incomplete_recommendation_ambiguous_with_current_shop"],
                route_candidate="clarify",
                preferred_chunk_roles=[],
                tool_candidates=[],
                clarification_question="你是想看这家店推荐菜，还是看当前位置附近的推荐？",
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                    "current_shop": persistent.current_shop or persistent.selected_shop_name,
                },
            ),
            reason="incomplete_recommendation_ambiguous_with_current_shop",
            required_action="clarify",
            route_candidate="clarify",
        )

    if input_quality.kind == "incomplete_recommendation" and not _context_has_anchor(persistent):
        return _mark_routing_blocked(
            RoutingDecision(
                raw_query=str(raw_query or ""),
                normalized_query=normalized_query,
                domain="local_life",
                confidence=0.0,
                input_quality=input_quality,
                intent=IntentRoutingDecision(name="local_life_recommend", confidence=0.35, required_slots=["city", "scene", "category"], missing_slots=["city", "scene", "category"], allowed_routes=["clarify"], forbidden_routes=["rag_retrieval", "tool_call"]),
                required_action="clarify",
                blocked=True,
                blocked_reason="incomplete_recommendation_missing_context",
                should_rewrite_query=False,
                should_retrieve=False,
                should_call_tool=False,
                should_use_memory=False,
                should_persist_memory=False,
                should_vectorize_memory=False,
                should_emit_retrieval_events=False,
                retrieval_skipped_reason="incomplete_recommendation_missing_context",
                missing_slots=["city", "scene", "category"],
                resolved_references=[],
                route_reason="incomplete_recommendation_missing_context",
                safeguards_triggered=safeguards_triggered + ["incomplete_recommendation_missing_context"],
                route_candidate="clarify",
                preferred_chunk_roles=[],
                tool_candidates=[],
                clarification_question="你更想找哪个城市、哪类场景的店？",
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                },
            ),
            reason="incomplete_recommendation_missing_context",
            required_action="clarify",
            route_candidate="clarify",
        )

    if _detect_memory_update(raw_query):
        route = RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalized_query,
            domain="memory",
            confidence=max(route.confidence, 0.78),
            input_quality=input_quality,
            intent=IntentRoutingDecision(
                name="memory_update",
                confidence=0.78,
                required_slots=[],
                missing_slots=[],
                allowed_routes=["direct_answer", "memory_update"],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action="memory_update",
            blocked=False,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=True,
            should_vectorize_memory=True,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=None,
            missing_slots=[],
            resolved_references=[],
            route_reason="memory_update",
            safeguards_triggered=safeguards_triggered + ["memory_update"],
            route_candidate="memory_update",
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
            },
        )

    if _detect_session_only_preference(raw_query):
        route = route.model_copy(
            update={
                "should_use_memory": False,
                "should_retrieve": False,
                "should_call_tool": False,
                "should_persist_memory": False,
                "should_vectorize_memory": False,
                "should_emit_retrieval_events": False,
                "safeguards_triggered": list(dict.fromkeys(list(route.safeguards_triggered) + ["session_only_constraint"])),
                "retrieval_skipped_reason": route.retrieval_skipped_reason or "session_only_constraint",
                "route_reason": route.route_reason or "session_only_constraint",
            }
        )

    if response_kind in {"greeting", "thanks", "profile"}:
        route = RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalized_query,
            domain="general",
            confidence=0.97 if response_kind in {"greeting", "thanks"} else 0.92,
            input_quality=input_quality,
            intent=IntentRoutingDecision(
                name="chit_chat" if response_kind in {"greeting", "thanks"} else "direct_answer",
                confidence=0.97 if response_kind in {"greeting", "thanks"} else 0.92,
                required_slots=[],
                missing_slots=[],
                allowed_routes=["direct_answer"],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action="direct_answer",
            blocked=False,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=None,
            missing_slots=[],
            resolved_references=[],
            route_reason=response_reason or response_kind,
            safeguards_triggered=safeguards_triggered,
            route_candidate=response_kind,
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
            },
        )

    if route.blocked and route.blocked_reason:
        route = _mark_routing_blocked(
            route,
            reason=route.blocked_reason,
            required_action=route.required_action,
            route_candidate=route.route_candidate,
        )

    route = route.model_copy(update={"route_reason": route.route_reason or input_quality.reason})
    if route.required_action in {"rag_retrieval", "rag_plus_tool"} and not route.preferred_chunk_roles:
        route = route.model_copy(update={"preferred_chunk_roles": _semantic_route_for_query(raw_query, persistent, client_context=client_context).preferred_chunk_roles})
    if route.required_action in {"tool_call", "rag_plus_tool"} and not route.tool_candidates:
        route = route.model_copy(update={"tool_candidates": _semantic_route_for_query(raw_query, persistent, client_context=client_context).tool_candidates})
    return _apply_route_review(route, raw_query=raw_query, persistent=persistent, client_context=client_context)


def apply_fast_decision_to_routing(
    routing: RoutingDecision,
    fast_result: FastDecision,
    *,
    reference_resolved: bool = False,
    reference_confidence: float | None = None,
    resolved_references: Sequence[str] | None = None,
) -> RoutingDecision:
    intent_name = _intent_name_from_fast_decision(fast_result, routing)
    allowed_routes = _allowed_routes_from_fast_decision(fast_result)
    forbidden_routes = _forbidden_routes_from_fast_decision(fast_result)
    required_action = _required_action_from_fast_decision(fast_result)
    blocked = bool(routing.blocked)
    should_retrieve = bool(fast_result.needs_rag and not blocked and required_action in _RETRIEVAL_ACTIONS)
    should_call_tool = bool(fast_result.needs_tool and not blocked and required_action in {"tool_call", "rag_plus_tool"})
    should_rewrite_query = bool(fast_result.needs_query_rewrite or routing.should_rewrite_query)
    should_use_memory = routing.should_use_memory and required_action not in _DIRECT_ACTIONS and not blocked
    should_persist_memory = routing.should_persist_memory and required_action not in {"direct_answer", "clarify", "reject", "no_op"} and not blocked
    should_vectorize_memory = routing.should_vectorize_memory and should_persist_memory
    intent_confidence = float(fast_result.confidence or 0.0)
    intent = IntentRoutingDecision(
        name=intent_name,
        confidence=intent_confidence,
        required_slots=_required_slots_from_fast_decision(fast_result),
        missing_slots=list(fast_result.extra.get("missing_slots", [])) if isinstance(fast_result.extra, Mapping) else [],
        allowed_routes=allowed_routes,
        forbidden_routes=forbidden_routes,
    )
    updated_resolved = list(routing.resolved_references)
    if resolved_references:
        updated_resolved.extend([ref for ref in resolved_references if ref])
    if reference_resolved and reference_confidence and reference_confidence >= 0.5:
        should_rewrite_query = True
    extra_slots = dict(fast_result.extra or {}) if isinstance(fast_result.extra, Mapping) else {}
    preferred_chunk_roles = list(
        dict.fromkeys(
            list(routing.preferred_chunk_roles)
            + [str(item) for item in extra_slots.get("preferred_chunk_roles", []) if str(item).strip()]
        )
    )
    tool_candidates = list(
        dict.fromkeys(
            list(routing.tool_candidates)
            + [str(item) for item in extra_slots.get("tool_candidates", []) if str(item).strip()]
        )
    )
    confidence = max(float(routing.confidence or 0.0), intent_confidence)

    extra = dict(routing.extra)
    extra.update(dict(fast_result.extra or {}))
    extra["fast_decision_confidence"] = intent_confidence
    extra["fast_decision_intent"] = fast_result.intent.value if fast_result.intent else None
    extra["fast_decision_route_candidate"] = fast_result.extra.get("route_candidate") if isinstance(fast_result.extra, Mapping) else None

    return routing.model_copy(
        update={
            "domain": str(extra_slots.get("domain") or routing.domain),
            "confidence": confidence,
            "intent": intent,
            "required_action": required_action,
            "should_rewrite_query": should_rewrite_query,
            "should_retrieve": should_retrieve,
            "should_call_tool": should_call_tool,
            "should_use_memory": should_use_memory,
            "should_persist_memory": should_persist_memory,
            "should_vectorize_memory": should_vectorize_memory,
            "should_emit_retrieval_events": should_retrieve,
            "missing_slots": list(intent.missing_slots),
            "resolved_references": updated_resolved,
            "route_reason": routing.route_reason or intent_name or routing.input_quality.reason,
            "route_candidate": fast_result.extra.get("route_candidate") if isinstance(fast_result.extra, Mapping) else routing.route_candidate,
            "preferred_chunk_roles": preferred_chunk_roles,
            "tool_candidates": tool_candidates,
            "clarification_question": extra_slots.get("clarification_question", routing.clarification_question),
            "extra": extra,
        }
    )


def build_rewrite_decision(
    original_query: str,
    rewritten_query: str,
    *,
    confidence: float,
    reason: str,
    preserved_constraints: Sequence[str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> RewriteDecision:
    original = normalize_query(original_query)
    rewritten = normalize_query(rewritten_query)
    original_tokens = Counter(_content_tokens(original))
    rewritten_tokens = Counter(_content_tokens(rewritten))
    added_terms = list((rewritten_tokens - original_tokens).elements())
    removed_terms = list((original_tokens - rewritten_tokens).elements())
    preserved = list(preserved_constraints or [])
    risky = bool(added_terms) and (confidence < 0.65 or len(added_terms) > max(2, len(preserved) + 1))
    should_retrieve = bool(rewritten and confidence >= 0.4 and not risky)
    return RewriteDecision(
        original_query=original,
        rewritten_query=rewritten or original,
        added_terms=added_terms,
        removed_terms=removed_terms,
        preserved_constraints=preserved,
        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
        should_retrieve=should_retrieve,
        reason=reason,
        risky_rewrite=risky,
    )


def build_evidence_quality(
    pack: EvidencePack | None,
    *,
    intent_name: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> EvidenceQualityDecision:
    ctx = dict(context or {})
    client_context = ctx.get("client_context")
    client_context_has_anchor = False
    anchor_keys = (
        "shopName",
        "shop_name",
        "selected_shop_name",
        "current_shop",
        "city",
        "current_city",
        "location",
        "current_location",
        "area",
        "current_area",
        "district",
        "region",
    )

    def _mapping_has_anchor(mapping: Mapping[str, Any] | None) -> bool:
        if not isinstance(mapping, Mapping):
            return False
        for key in anchor_keys:
            value = mapping.get(key)
            if isinstance(value, Mapping):
                if any(str(item).strip() for item in value.values() if item not in (None, "", [], {}, ())):
                    return True
                continue
            if str(value or "").strip():
                return True
        return False

    client_context_has_anchor = _mapping_has_anchor(client_context)
    if not client_context_has_anchor:
        session_context_anchor = {key: ctx.get(key) for key in anchor_keys}
        client_context_has_anchor = _mapping_has_anchor(session_context_anchor)
    required_facets_ctx = [dict(item) for item in ctx.get("required_facets") or [] if isinstance(item, Mapping)]
    optional_facets_ctx = [dict(item) for item in ctx.get("optional_facets") or [] if isinstance(item, Mapping)]
    missing_slots_ctx = [str(item).strip() for item in (ctx.get("missing_slots") or []) if str(item).strip()]
    clarification_slot_ctx = str(ctx.get("clarification_slot") or "").strip() or None
    tool_candidates_ctx = [str(item).strip() for item in (ctx.get("tool_candidates") or []) if str(item).strip()]
    routing_action = str(ctx.get("routing_action") or ctx.get("required_action") or "").strip().lower()
    partial_grounded_enabled, slot_clarify_enabled, rag_plus_tool_partial_answer_enabled = _phase2_flags()

    def _is_ask_clarification_facet(facet: Mapping[str, Any]) -> bool:
        return str(facet.get("missing_policy") or "").strip().lower() == "ask_clarification"

    def _facet_names(facets: Sequence[Mapping[str, Any]]) -> list[str]:
        names: list[str] = []
        for facet in facets:
            name = str(facet.get("name") or "").strip()
            if name:
                names.append(name)
        return names

    if pack is None or not pack.items:
        clarification_slot = clarification_slot_ctx
        if not clarification_slot and missing_slots_ctx:
            clarification_slot = missing_slots_ctx[0]
        if not clarification_slot and required_facets_ctx:
            for facet in required_facets_ctx:
                if _is_ask_clarification_facet(facet):
                    clarification_slot = str(facet.get("name") or "").strip() or None
                    if clarification_slot:
                        break
        response_mode = "ask_clarification" if clarification_slot else "no_answer"
        missing_facets = _facet_names(required_facets_ctx)
        return EvidenceQualityDecision(
            evidence_count=0,
            top_score=0.0,
            score_gap=0.0,
            topic_consistency=0.0,
            entity_consistency=0.0,
            city_area_category_consistency=False,
            required_roles_covered=False,
            citation_available=False,
            stale_evidence=False,
            response_mode=response_mode,
            is_valid=False,
            reason="missing_required_slot" if response_mode == "ask_clarification" else "no_evidence",
            fallback_reason="slot_missing" if response_mode == "ask_clarification" else "empty_pack",
            missing_slots=missing_slots_ctx,
            clarification_slot=clarification_slot,
            covered_facets=[],
            missing_facets=missing_facets,
            tool_candidates=tool_candidates_ctx,
            details={
                "dominant_chunk_type": None,
                "chunk_types": {},
                "entity_consistency_minimal": None,
                "required_facets": required_facets_ctx,
                "optional_facets": optional_facets_ctx,
                "missing_slots": missing_slots_ctx,
                "clarification_slot": clarification_slot,
                "covered_facets": [],
                "missing_facets": missing_facets,
                "tool_candidates": tool_candidates_ctx,
                "evidence_after_gate_count": 0,
                "failure_reasons": ["empty_pack" if response_mode == "no_answer" else "slot_missing"],
            },
        )

    items = list(pack.items)
    query_text = str(ctx.get("query_text") or ctx.get("raw_query") or ctx.get("query") or "").strip()
    target_shop_id = str(ctx.get("shop_id") or ctx.get("selected_shop_id") or "").strip() or None
    target_shop_name = str(ctx.get("shop_name") or ctx.get("selected_shop_name") or ctx.get("current_shop") or "").strip() or None
    target_city = str(ctx.get("city") or ctx.get("current_city") or "").strip() or None
    target_area = str(ctx.get("area") or ctx.get("current_area") or "").strip() or None
    target_category = str(ctx.get("category") or ctx.get("current_category") or "").strip() or None
    tool_result_present = bool(ctx.get("tool_result_present") or ctx.get("has_tool_result"))
    tool_result_payload = ctx.get("tool_result_payload")
    role_tokens = {
        str(item.metadata.get("role") or item.chunk_type or "").strip().lower()
        for item in items
        if str(item.metadata.get("role") or item.chunk_type or "").strip()
    }
    shop_ids = {
        str(item.metadata.get("shop_id") or item.metadata.get("parent_shop_id") or item.document_id or "").strip()
        for item in items
        if item.metadata.get("shop_id") or item.metadata.get("parent_shop_id") or item.document_id
    }
    cities = {
        str(item.metadata.get("city") or "").strip()
        for item in items
        if str(item.metadata.get("city") or "").strip()
    }
    areas = {
        str(item.metadata.get("area") or "").strip()
        for item in items
        if str(item.metadata.get("area") or "").strip()
    }
    categories = {
        str(item.metadata.get("category") or "").strip()
        for item in items
        if str(item.metadata.get("category") or "").strip()
    }
    _, _, min_entity_consistency_enabled = _phase1_flags()
    scores = sorted((float(item.score or 0.0) for item in items), reverse=True)
    top_score = scores[0] if scores else 0.0
    second_score = scores[1] if len(scores) > 1 else 0.0
    score_gap = max(top_score - second_score, 0.0)
    citation_available = any(bool(item.citation_chunk_id) for item in items)
    stale_evidence = any(
        bool(item.metadata.get("deprecated") or item.metadata.get("is_deprecated") or item.metadata.get("stale"))
        for item in items
    )

    chunk_types = [str(item.chunk_type or item.metadata.get("chunk_type") or "") for item in items]
    chunk_type_counter = Counter(chunk_types)
    dominant_chunk_type, dominant_chunk_count = chunk_type_counter.most_common(1)[0]
    topic_consistency = dominant_chunk_count / max(len(items), 1)

    parent_ids = [
        str(item.parent_chunk_id or item.metadata.get("parent_chunk_id") or item.document_id or "")
        for item in items
        if (item.parent_chunk_id or item.metadata.get("parent_chunk_id") or item.document_id)
    ]
    parent_counter = Counter(parent_ids)
    entity_consistency = (parent_counter.most_common(1)[0][1] / max(len(parent_ids), 1)) if parent_ids else 0.0
    entity_consistency_minimal = None
    if min_entity_consistency_enabled:
        entity_consistency_minimal = _build_min_entity_consistency(
            context=ctx,
            evidence_items=items,
            tool_payload=tool_result_payload if isinstance(tool_result_payload, Mapping) else None,
        )

    specific_shop_question = bool(
        target_shop_id
        or target_shop_name
        or any(token in query_text for token in ("这家", "那家", "这个店", "那个店", "哪家", "该店"))
    )
    nearby_question = any(token in query_text for token in ("附近", "周边", "离我", "离我近", "附近有什么", "附近有啥"))
    package_question = any(token in query_text for token in ("套餐", "团购", "优惠券", "券", "代金券"))
    pitfall_question = any(token in query_text for token in ("避坑", "踩雷", "雷点", "坑", "不推荐"))

    city_area_category_consistency = bool(
        items
        and all(
            (
                (not target_city or str(item.metadata.get("city") or "").strip() == target_city)
                and (not target_area or str(item.metadata.get("area") or "").strip() == target_area)
                and (not target_category or str(item.metadata.get("category") or "").strip() == target_category)
            )
            for item in items
        )
    )

    required_roles_covered = False
    if intent_name in {"local_life_recommend", "merchant_detail", "package_or_coupon", "comparison"}:
        required_roles_covered = any(
            str(item.metadata.get("role") or item.chunk_type or "").lower()
            in {"review", "guide", "package", "coupon", "detail", "comparison", "concept", "business_evidence"}
            for item in items
        )
    else:
        required_roles_covered = True

    is_valid = True
    reason = "quality_ok"
    fallback_reason = None
    has_matching_shop_evidence = True
    if specific_shop_question:
        has_matching_shop_evidence = bool(
            (target_shop_id and target_shop_id in shop_ids)
            or (target_shop_name and any(target_shop_name in str(item.content or "") for item in items))
        )
    has_business_role = any(
        role in {"review", "guide", "package", "coupon", "detail", "comparison", "business_evidence"}
        for role in role_tokens
    )
    only_platform_rule = bool(role_tokens) and role_tokens <= {"platform_rule"}
    if len(items) < 2:
        is_valid = False
        reason = "too_few_evidence"
        fallback_reason = "insufficient_count"
    elif top_score < 0.35:
        is_valid = False
        reason = "low_top_score"
        fallback_reason = "low_score"
    elif score_gap < 0.04 and len(items) > 1:
        is_valid = False
        reason = "low_score_gap"
        fallback_reason = "ambiguous_ranking"
    elif stale_evidence:
        is_valid = False
        reason = "stale_evidence"
        fallback_reason = "stale_evidence"
    elif specific_shop_question and not has_matching_shop_evidence:
        is_valid = False
        reason = "shop_mismatch"
        fallback_reason = "shop_mismatch"
    elif specific_shop_question and only_platform_rule:
        is_valid = False
        reason = "platform_rule_only"
        fallback_reason = "platform_rule_only"
    elif nearby_question and not city_area_category_consistency:
        is_valid = False
        reason = "geo_mismatch"
        fallback_reason = "geo_mismatch"
    elif package_question and not (tool_result_present or any(role in {"package", "coupon"} for role in role_tokens)):
        is_valid = False
        reason = "required_role_missing"
        fallback_reason = "missing_role"
    elif pitfall_question and not any(role in {"review", "pitfall"} for role in role_tokens):
        is_valid = False
        reason = "required_role_missing"
        fallback_reason = "missing_role"
    elif intent_name in {"local_life_recommend", "merchant_detail", "package_or_coupon"} and not required_roles_covered:
        is_valid = False
        reason = "required_role_missing"
        fallback_reason = "missing_role"
    if entity_consistency_minimal is not None and entity_consistency_minimal.get("cross_entity_risk") and is_valid:
        is_valid = False
        reason = str(entity_consistency_minimal.get("mismatch_reason") or "entity_consistency_mismatch")
        fallback_reason = reason

    facet_covered_names: list[str] = []
    facet_missing_names: list[str] = []
    if required_facets_ctx:
        for facet in required_facets_ctx:
            facet_name = str(facet.get("name") or "").strip()
            if not facet_name:
                continue
            if _facet_covered_for_phase2(
                facet_name,
                role_tokens=role_tokens,
                tool_result_present=tool_result_present,
                has_matching_shop_evidence=has_matching_shop_evidence,
                city_area_category_consistency=city_area_category_consistency,
            ):
                facet_covered_names.append(facet_name)
            else:
                facet_missing_names.append(facet_name)

    if not facet_missing_names and missing_slots_ctx:
        facet_missing_names.extend(item for item in missing_slots_ctx if item not in facet_covered_names)
    if not facet_covered_names and required_roles_covered:
        facet_covered_names.extend(_facet_names(required_facets_ctx[:1]) if required_facets_ctx else [])

    # Force deduplication and mutual exclusion
    facet_covered_names = list(dict.fromkeys(facet_covered_names))
    facet_missing_names = [f for f in list(dict.fromkeys(facet_missing_names)) if f not in facet_covered_names]

    clarification_slot = clarification_slot_ctx
    if not clarification_slot and missing_slots_ctx:
        clarification_slot = missing_slots_ctx[0]
    if not clarification_slot and facet_missing_names:
        clarification_slot = facet_missing_names[0]
    if not clarification_slot and required_facets_ctx:
        for facet in required_facets_ctx:
            if _is_ask_clarification_facet(facet):
                clarification_slot = str(facet.get("name") or "").strip() or None
                if clarification_slot:
                    break

    phase2_enabled = bool(required_facets_ctx or missing_slots_ctx or clarification_slot_ctx)
    ask_clarification_required = bool(
        clarification_slot
        and (
            missing_slots_ctx
            or any(
                _is_ask_clarification_facet(facet) and str(facet.get("name") or "").strip() in facet_missing_names
                for facet in required_facets_ctx
            )
        )
    )
    hard_no_answer_reason = reason in {
        "shop_mismatch",
        "shop_missing",
        "geo_mismatch",
        "multi_shop_evidence",
        "multi_entity_tool_payload",
        "coupon_mismatch",
        "package_mismatch",
    }

    if not items:
        response_mode = (
            "ask_clarification"
            if (ask_clarification_required and slot_clarify_enabled and not client_context_has_anchor)
            else "no_answer"
        )
    elif hard_no_answer_reason and not phase2_enabled:
        response_mode = "no_answer"
    elif not is_valid and ask_clarification_required and slot_clarify_enabled:
        response_mode = "ask_clarification" if not client_context_has_anchor else ("partial_grounded" if partial_grounded_enabled else "weak_answer")
    elif not is_valid and phase2_enabled and (facet_covered_names or facet_missing_names or tool_result_present):
        if partial_grounded_enabled and (routing_action != "rag_plus_tool" or rag_plus_tool_partial_answer_enabled or client_context_has_anchor):
            response_mode = "partial_grounded"
        else:
            response_mode = "weak_answer"
    elif not is_valid and hard_no_answer_reason:
        if (
            phase2_enabled
            and partial_grounded_enabled
            and (routing_action != "rag_plus_tool" or rag_plus_tool_partial_answer_enabled or client_context_has_anchor)
        ):
            response_mode = "partial_grounded"
        else:
            response_mode = "no_answer"
    elif not is_valid and phase2_enabled:
        response_mode = (
            "partial_grounded"
            if (
                partial_grounded_enabled
                and (facet_covered_names or facet_missing_names or tool_result_present)
                and (routing_action != "rag_plus_tool" or rag_plus_tool_partial_answer_enabled or client_context_has_anchor)
            )
            else "weak_answer"
        )
    elif not is_valid:
        response_mode = "weak_answer"
    else:
        response_mode = "grounded"

    failure_reasons = [reason]
    if entity_consistency_minimal is not None and entity_consistency_minimal.get("cross_entity_risk"):
        failure_reasons.append(str(entity_consistency_minimal.get("mismatch_reason") or "entity_consistency_mismatch"))
    if facet_missing_names:
        failure_reasons.append("missing_facets:" + ",".join(dict.fromkeys(facet_missing_names)))
    if missing_slots_ctx:
        failure_reasons.append("missing_slots:" + ",".join(dict.fromkeys(missing_slots_ctx)))

    return EvidenceQualityDecision(
        evidence_count=len(items),
        top_score=top_score,
        score_gap=score_gap,
        topic_consistency=topic_consistency,
        entity_consistency=entity_consistency,
        city_area_category_consistency=city_area_category_consistency,
        required_roles_covered=required_roles_covered,
        citation_available=citation_available,
        stale_evidence=stale_evidence,
        response_mode=response_mode,
        is_valid=is_valid,
        reason=reason,
        fallback_reason=fallback_reason,
        missing_slots=missing_slots_ctx,
        clarification_slot=clarification_slot,
        covered_facets=facet_covered_names,
        missing_facets=facet_missing_names,
        tool_candidates=tool_candidates_ctx,
        details={
            "dominant_chunk_type": dominant_chunk_type,
            "chunk_types": dict(chunk_type_counter),
            "entity_consistency_minimal": entity_consistency_minimal,
            "required_facets": required_facets_ctx,
            "optional_facets": optional_facets_ctx,
            "missing_slots": missing_slots_ctx,
            "clarification_slot": clarification_slot,
            "covered_facets": facet_covered_names,
            "missing_facets": facet_missing_names,
            "tool_candidates": tool_candidates_ctx,
            "evidence_after_gate_count": len(items),
            "tool_result_present": tool_result_present,
            "tool_result_payload": tool_result_payload,
            "retrieval_plan_missing": bool(ctx.get("retrieval_plan_missing")),
            "tool_plan_missing": bool(ctx.get("tool_plan_missing")),
            "tool_slot_missing": bool(ctx.get("tool_slot_missing")),
            "tool_not_allowed": bool(ctx.get("tool_not_allowed")),
            "retrieval_not_allowed": bool(ctx.get("retrieval_not_allowed")),
            "rag_gate_blocked": bool(ctx.get("rag_gate_blocked")),
            "failure_reasons": failure_reasons,
        },
    )


def should_run_tool(routing: RoutingDecision | None) -> bool:
    return bool(
        routing is not None
        and not routing.blocked
        and routing.should_call_tool
        and str(routing.required_action).strip().lower() in {"tool_call", "rag_plus_tool"}
    )


def should_persist_memory(routing: RoutingDecision | None) -> bool:
    return bool(routing is not None and routing.should_persist_memory)


def _update_phase0_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]

    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase0_trace = dict(turn_extra.get(_PHASE0_TRACE_KEY, {}) or {})
    phase0_trace.update(updates)
    turn_extra[_PHASE0_TRACE_KEY] = phase0_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase0_trace = dict(runtime_metrics.get(_PHASE0_TRACE_KEY, {}) or {})
    runtime_phase0_trace.update(updates)
    runtime_metrics[_PHASE0_TRACE_KEY] = runtime_phase0_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase1_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]

    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase1_trace = dict(turn_extra.get(_PHASE1_TRACE_KEY, {}) or {})
    phase1_trace.update(updates)
    turn_extra[_PHASE1_TRACE_KEY] = phase1_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase1_trace = dict(runtime_metrics.get(_PHASE1_TRACE_KEY, {}) or {})
    runtime_phase1_trace.update(updates)
    runtime_metrics[_PHASE1_TRACE_KEY] = runtime_phase1_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase2_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]

    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase2_trace = dict(turn_extra.get(_PHASE2_TRACE_KEY, {}) or {})
    phase2_trace.update(updates)
    turn_extra[_PHASE2_TRACE_KEY] = phase2_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase2_trace = dict(runtime_metrics.get(_PHASE2_TRACE_KEY, {}) or {})
    runtime_phase2_trace.update(updates)
    runtime_metrics[_PHASE2_TRACE_KEY] = runtime_phase2_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase3_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]

    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase3_trace = dict(turn_extra.get(_PHASE3_TRACE_KEY, {}) or {})
    phase3_trace.update(updates)
    turn_extra[_PHASE3_TRACE_KEY] = phase3_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase3_trace = dict(runtime_metrics.get(_PHASE3_TRACE_KEY, {}) or {})
    runtime_phase3_trace.update(updates)
    runtime_metrics[_PHASE3_TRACE_KEY] = runtime_phase3_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _update_phase4_trace(state: Any, **updates: Any) -> Any:
    turn = state["turn"]
    runtime = state["runtime"]

    turn_extra = dict(getattr(turn, "extra", {}) or {})
    phase4_trace = dict(turn_extra.get(_PHASE4_TRACE_KEY, {}) or {})
    phase4_trace.update(updates)
    turn_extra[_PHASE4_TRACE_KEY] = phase4_trace
    state["turn"] = turn.model_copy(update={"extra": turn_extra})

    runtime_metrics = dict(getattr(runtime, "metrics", {}) or {})
    runtime_phase4_trace = dict(runtime_metrics.get(_PHASE4_TRACE_KEY, {}) or {})
    runtime_phase4_trace.update(updates)
    runtime_metrics[_PHASE4_TRACE_KEY] = runtime_phase4_trace
    state["runtime"] = runtime.model_copy(update={"metrics": runtime_metrics})
    return state


def _phase4_mode() -> str:
    settings = get_settings()
    return str(getattr(settings, "answer_verifier_mode", "warn_only") or "warn_only").strip().lower() or "warn_only"


def _extract_entity_key_from_evidence_item(item: EvidenceItem) -> str | None:
    metadata = dict(getattr(item, "metadata", {}) or {})
    for key in ("shop_id", "shopId", "merchant_id", "merchantId", "entity_id", "entityId"):
        value = _normalize_entity_key(metadata.get(key))
        if value:
            return value
    return _normalize_entity_key(getattr(item, "parent_chunk_id", None)) or _normalize_entity_key(getattr(item, "document_id", None))


def _extract_entity_key_from_tool_result(tool_result: Any) -> str | None:
    if tool_result is None:
        return None

    payload = getattr(tool_result, "normalized_output", None)
    if not isinstance(payload, Mapping):
        payload = {}

    for key in ("shop_id", "shopId", "merchant_id", "merchantId", "entity_id", "entityId"):
        value = _normalize_entity_key(payload.get(key))
        if value:
            return value

    shop = payload.get("shop") if isinstance(payload.get("shop"), Mapping) else {}
    if isinstance(shop, Mapping):
        for key in ("shop_id", "shopId", "id", "name", "shop_name"):
            value = _normalize_entity_key(shop.get(key))
            if value:
                return value

    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    if isinstance(data, Mapping):
        for key in ("shop_id", "shopId", "merchant_id", "merchantId", "entity_id", "entityId"):
            value = _normalize_entity_key(data.get(key))
            if value:
                return value
    return None


def _build_entity_join_result(turn: Any) -> EntityJoinResult:
    rag_result = getattr(turn, "rag_result", None)
    tool_result = getattr(turn, "tool_result", None)
    evidence_pack = getattr(rag_result, "evidence_pack", None) if rag_result is not None else None
    evidence_items = list(getattr(evidence_pack, "items", None) or [])

    evidence_bindings: dict[str, list[str]] = {}
    tool_bindings: dict[str, list[str]] = {}
    candidate_entities: list[str] = []
    issues: list[str] = []

    for item in evidence_items:
        entity_key = _extract_entity_key_from_evidence_item(item)
        if not entity_key:
            continue
        if entity_key not in candidate_entities:
            candidate_entities.append(entity_key)
        evidence_bindings.setdefault(entity_key, []).append(str(getattr(item, "chunk_id", "") or ""))

    tool_entity = _extract_entity_key_from_tool_result(tool_result)
    tool_name = str(getattr(tool_result, "tool_name", "") or "").strip() or "tool_result"
    if tool_entity:
        if tool_entity not in candidate_entities:
            candidate_entities.append(tool_entity)
        tool_bindings.setdefault(tool_entity, []).append(tool_name)

    nonempty_entities = [entity for entity in candidate_entities if entity]
    selected_entity = nonempty_entities[0] if len(set(nonempty_entities)) == 1 else None
    cross_entity_detected = len(set(nonempty_entities)) > 1
    if cross_entity_detected:
        issues.append("cross_entity_stitching")

    extra = {
        "evidence_item_count": len(evidence_items),
        "tool_result_present": tool_result is not None,
        "tool_name": tool_name if tool_result is not None else None,
        "phase4_mode": _phase4_mode(),
    }
    return EntityJoinResult(
        candidate_entities=nonempty_entities,
        evidence_bindings=evidence_bindings,
        tool_bindings=tool_bindings,
        selected_entity=selected_entity,
        cross_entity_detected=cross_entity_detected,
        issues=issues,
        extra=extra,
    )


def _build_answer_contract(
    turn: Any,
    routing: RoutingDecision | None,
    evidence_quality: EvidenceQualityDecision | None,
    entity_join_result: EntityJoinResult,
) -> AnswerContract:
    routing_extra = dict(getattr(routing, "extra", {}) or {}) if routing is not None else {}
    required_facets = [dict(item) for item in routing_extra.get("required_facets") or [] if isinstance(item, Mapping)]
    missing_slots = list(getattr(routing, "missing_slots", None) or getattr(evidence_quality, "missing_slots", None) or [])
    clarification_slot = (
        str(getattr(routing, "clarification_slot", "") or "").strip()
        or str(getattr(evidence_quality, "clarification_slot", "") or "").strip()
        or None
    )
    covered_facets = list(getattr(evidence_quality, "covered_facets", None) or [])
    missing_facets = list(getattr(evidence_quality, "missing_facets", None) or [])
    required_facet_names = [
        str(facet.get("name") or "").strip()
        for facet in required_facets
        if str(facet.get("name") or "").strip()
    ]
    dynamic_facets = [
        str(facet.get("name") or "").strip()
        for facet in required_facets
        if str(facet.get("name") or "").strip()
        and str(facet.get("data_source") or "").strip().lower() == _PHASE1_DATA_SOURCE_DYNAMIC_TOOL
    ]
    static_facets = [
        str(facet.get("name") or "").strip()
        for facet in required_facets
        if str(facet.get("name") or "").strip()
        and str(facet.get("data_source") or "").strip().lower() == _PHASE1_DATA_SOURCE_STATIC_RAG
    ]
    evidence_requirements = {
        "required_facets": required_facet_names,
        "covered_facets": covered_facets,
        "missing_facets": missing_facets,
        "static_facets": static_facets,
        "dynamic_facets": dynamic_facets,
        "has_rag_result": getattr(turn, "rag_result", None) is not None,
        "has_evidence_pack": getattr(getattr(turn, "rag_result", None), "evidence_pack", None) is not None,
        "candidate_entities": list(entity_join_result.candidate_entities),
        "selected_entity": entity_join_result.selected_entity,
        "cross_entity_detected": entity_join_result.cross_entity_detected,
    }
    tool_candidates = [str(item) for item in (getattr(evidence_quality, "tool_candidates", None) or []) if str(item).strip()]
    if routing is not None:
        for candidate in getattr(routing, "tool_candidates", None) or []:
            candidate_text = str(candidate or "").strip()
            if candidate_text and candidate_text not in tool_candidates:
                tool_candidates.append(candidate_text)
    tool_bindings = dict(entity_join_result.tool_bindings)
    tool_entity = next(iter(tool_bindings.keys()), None)
    tool_requirements = {
        "tool_candidates": tool_candidates,
        "missing_slots": missing_slots,
        "clarification_slot": clarification_slot,
        "has_tool_result": getattr(turn, "tool_result", None) is not None,
        "tool_entity": tool_entity,
        "tool_bindings": tool_bindings,
    }
    forbidden_without_evidence = list(dict.fromkeys(dynamic_facets))
    return AnswerContract(
        original_query=str(getattr(turn, "raw_query", "") or ""),
        required_facets=required_facets,
        evidence_requirements=evidence_requirements,
        tool_requirements=tool_requirements,
        forbidden_without_evidence=forbidden_without_evidence,
        candidate_entities=list(entity_join_result.candidate_entities),
        selected_entity=entity_join_result.selected_entity,
        missing_slots=missing_slots,
        clarification_slot=clarification_slot,
        extra={
            "route_candidate": getattr(routing, "route_candidate", None) if routing is not None else None,
            "response_mode": str(getattr(evidence_quality, "response_mode", "") or "").strip().lower(),
            "phase4_mode": _phase4_mode(),
        },
    )


def _answer_verifier_repair_hint(issues: Sequence[str], answer_contract: AnswerContract) -> str:
    issue_set = {str(item).strip().lower() for item in issues if str(item).strip()}
    hints: list[str] = []
    if "cross_entity_stitching" in issue_set:
        hints.append("只保留同一家店的证据和工具结果，不要把不同门店拼在一起。")
    if "required_facets_missing" in issue_set:
        hints.append("先补齐必需 facets，再给结论；缺的部分可以降级为 partial_grounded。")
    if "dynamic_info_without_tool_result" in issue_set:
        hints.append("券、营业状态这类动态信息需要工具结果支撑，缺失时不要强答。")
    if "should_clarify_but_answered" in issue_set:
        hints.append("缺 slot 时先澄清，不要直接回答。")
    if "weak_evidence_claimed_as_certain" in issue_set:
        hints.append("把弱证据改成边界明确的部分判断。")
    if not hints:
        return "当前回答可以继续按可验证证据输出。"
    return "；".join(hints)


def _build_answer_verifier_result(
    request: Any,
    answer_text: str,
    entity_join_result: EntityJoinResult,
    answer_contract: AnswerContract,
) -> AnswerVerifierResult:
    evidence_quality = getattr(request, "evidence_quality", None)
    response_mode = str(
        getattr(request, "final_response_mode", None)
        or getattr(evidence_quality, "response_mode", None)
        or ""
    ).strip().lower()
    verifier_enabled, phase4_mode = _phase4_flags()
    if not verifier_enabled:
        return AnswerVerifierResult(
            passed=True,
            issues=[],
            suggested_response_mode=response_mode or "grounded",
            repair_hint="",
            extra={
                "response_mode": response_mode,
                "candidate_entities": list(answer_contract.candidate_entities),
                "selected_entity": answer_contract.selected_entity,
                "phase4_mode": "skipped",
            },
        )
    issues: list[str] = list(entity_join_result.issues)
    missing_facets = list(answer_contract.evidence_requirements.get("missing_facets") or [])
    dynamic_facets = list(answer_contract.evidence_requirements.get("dynamic_facets") or [])
    missing_slots = list(answer_contract.tool_requirements.get("missing_slots") or [])
    if missing_facets:
        issues.append("required_facets_missing")
    if dynamic_facets and getattr(request, "tool_result", None) is None:
        issues.append("dynamic_info_without_tool_result")
    if missing_slots and response_mode not in {"ask_clarification"}:
        issues.append("should_clarify_but_answered")
    if evidence_quality is not None and not bool(getattr(evidence_quality, "is_valid", True)) and response_mode == "grounded":
        issues.append("weak_evidence_claimed_as_certain")

    normalized_answer = str(answer_text or "").strip()
    if not normalized_answer:
        issues.append("empty_answer")

    dedup_issues: list[str] = []
    seen_issues: set[str] = set()
    for issue in issues:
        normalized_issue = str(issue or "").strip()
        if not normalized_issue or normalized_issue in seen_issues:
            continue
        seen_issues.add(normalized_issue)
        dedup_issues.append(normalized_issue)

    suggested_response_mode = "grounded"
    if "should_clarify_but_answered" in seen_issues:
        suggested_response_mode = "ask_clarification"
    elif "cross_entity_stitching" in seen_issues or "required_facets_missing" in seen_issues or "dynamic_info_without_tool_result" in seen_issues:
        suggested_response_mode = "partial_grounded"
    elif "weak_evidence_claimed_as_certain" in seen_issues:
        suggested_response_mode = "partial_grounded"
    elif "empty_answer" in seen_issues:
        suggested_response_mode = "no_answer"

    return AnswerVerifierResult(
        passed=not dedup_issues,
        issues=dedup_issues,
        suggested_response_mode=suggested_response_mode,
        repair_hint=_answer_verifier_repair_hint(dedup_issues, answer_contract),
        extra={
            "response_mode": response_mode,
            "candidate_entities": list(answer_contract.candidate_entities),
            "selected_entity": answer_contract.selected_entity,
            "phase4_mode": phase4_mode,
        },
    )


_TASK_PLAN_COMPLEX_INTENTS = {"local_life_recommend", "merchant_detail", "package_or_coupon", "comparison"}
_TASK_PLAN_STATIC_FACETS = {"scene_fit", "recommendation_reason", "shop_detail"}
_TASK_PLAN_DYNAMIC_FACETS = {"coupon", "open_status", "distance_eta", "package"}


def _task_plan_required_facets(routing: RoutingDecision | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if routing is None:
        return [], []
    extra = dict(getattr(routing, "extra", {}) or {})
    required_facets = [dict(item) for item in extra.get("required_facets") or [] if isinstance(item, Mapping)]
    optional_facets = [dict(item) for item in extra.get("optional_facets") or [] if isinstance(item, Mapping)]
    return required_facets, optional_facets


def _task_plan_enabled(turn: Any, routing: RoutingDecision | None) -> tuple[bool, str]:
    if not _phase3_flags():
        return False, "task_plan_disabled"
    if routing is None:
        return False, "routing_missing"
    action = str(getattr(routing, "required_action", "") or "").strip().lower()
    if routing.blocked:
        return False, "routing_blocked"
    if action != "rag_plus_tool":
        return False, "not_rag_plus_tool"
    required_facets, optional_facets = _task_plan_required_facets(routing)
    if not required_facets:
        return False, "missing_required_facets"
    if list(getattr(routing, "missing_slots", []) or []):
        return False, "missing_slots"
    if not (routing.should_retrieve and routing.should_call_tool):
        return False, "not_a_combined_task"
    intent_name = str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower()
    if intent_name not in _TASK_PLAN_COMPLEX_INTENTS:
        return False, "intent_not_complex"
    facet_names = {
        str(facet.get("name") or "").strip().lower()
        for facet in [*required_facets, *optional_facets]
        if str(facet.get("name") or "").strip()
    }
    if len(facet_names) < 4:
        return False, "facet_count_too_low"
    if not ({"coupon", "open_status"} <= facet_names):
        return False, "missing_dynamic_combo"
    if not (facet_names & _TASK_PLAN_STATIC_FACETS):
        return False, "insufficient_facet_mix"
    return True, "complex_local_life_combo"


def _task_plan_step_payload(turn: Any, persistent: PersistentSessionContext) -> dict[str, Any]:
    slots = dict(getattr(turn, "slots", {}) or {}) if isinstance(getattr(turn, "slots", {}), Mapping) else {}
    location = persistent.current_location if isinstance(persistent.current_location, Mapping) else {}
    preferences = slots.get("preferences")
    avoid = slots.get("avoid")
    return {
        "query": getattr(turn, "raw_query", ""),
        "city": persistent.current_city,
        "area": location.get("area") if isinstance(location, Mapping) else None,
        "location": dict(location) if isinstance(location, Mapping) else location,
        "category": slots.get("category"),
        "scene": slots.get("scene"),
        "preferences": list(preferences or []) if isinstance(preferences, (list, tuple, set)) else preferences,
        "avoid": list(avoid or []) if isinstance(avoid, (list, tuple, set)) else avoid,
        "shop_id": persistent.selected_shop_id or slots.get("shop_id"),
        "shop_name": persistent.current_shop or persistent.selected_shop_name or slots.get("shop_name"),
        "shop_query": slots.get("shop_query") or slots.get("shop") or slots.get("name"),
        "price": slots.get("price"),
        "limit": 10,
    }


def _build_task_plan(turn: Any, routing: RoutingDecision, persistent: PersistentSessionContext) -> TaskPlan | None:
    enabled, reason = _task_plan_enabled(turn, routing)
    required_facets, optional_facets = _task_plan_required_facets(routing)
    if not enabled:
        return TaskPlan(
            enabled=False,
            trigger_reason=reason,
            summary="",
            route_candidate=routing.route_candidate,
            task_complexity="simple",
            execution_mode="auto",
            can_fallback_to_legacy=True,
            required_facets=required_facets,
            optional_facets=optional_facets,
            steps=[],
            failure_reason=reason,
            extra={"source": "skipped"},
        )

    step_payload = _task_plan_step_payload(turn, persistent)
    facet_names = {
        str(facet.get("name") or "").strip().lower()
        for facet in [*required_facets, *optional_facets]
        if str(facet.get("name") or "").strip()
    }
    steps: list[PlanStep] = [
        PlanStep(
            step_id="resolve_location",
            goal="整理本轮任务的地理与店铺上下文。",
            expected_output="可用于后续规划的地点上下文。",
            input_payload=step_payload,
            risk_level="low",
        )
    ]
    if facet_names & {"scene_fit", "recommendation_reason", "shop_detail", "location", "category"}:
        steps.append(
            PlanStep(
                step_id="search_restaurants",
                goal="筛选符合场景与品类的候选门店。",
                expected_output="候选门店列表。",
                allowed_tools=["search_restaurants"],
                input_payload={
                    "query": step_payload["query"],
                    "city": step_payload["city"],
                    "area": step_payload["area"],
                    "category": step_payload["category"],
                    "scene": step_payload["scene"],
                    "preferences": step_payload["preferences"],
                    "avoid": step_payload["avoid"],
                    "limit": step_payload["limit"],
                },
                risk_level="low",
            )
        )
    if facet_names & {"scene_fit", "recommendation_reason", "shop_detail"}:
        steps.append(
            PlanStep(
                step_id="retrieve_scene_evidence",
                goal="拉取与店铺场景、环境和推荐理由相关的静态证据。",
                expected_output="静态 RAG 证据。",
                allowed_tools=["get_shop_detail"],
                input_payload={
                    "shop_id": step_payload["shop_id"],
                    "shop_name": step_payload["shop_name"],
                    "query": step_payload["query"],
                },
                risk_level="low",
            )
        )
    if "open_status" in facet_names:
        steps.append(
            PlanStep(
                step_id="check_open_status",
                goal="确认当前营业状态。",
                expected_output="营业状态结果。",
                allowed_tools=["check_open_status"],
                input_payload={
                    "shop_id": step_payload["shop_id"],
                    "shop_name": step_payload["shop_name"],
                    "open_hours": None,
                },
                risk_level="low",
            )
        )
    if "coupon" in facet_names:
        steps.append(
            PlanStep(
                step_id="get_coupon_list",
                goal="确认当前可用优惠券或套餐。",
                expected_output="优惠券列表。",
                allowed_tools=["get_coupon_list"],
                input_payload={
                    "shop_id": step_payload["shop_id"],
                    "shop_name": step_payload["shop_name"],
                    "limit": 10,
                },
                risk_level="low",
            )
        )
    if facet_names & _TASK_PLAN_STATIC_FACETS and facet_names & _TASK_PLAN_DYNAMIC_FACETS:
        steps.append(
            PlanStep(
                step_id="entity_join",
                goal="把静态证据和动态工具结果按同一实体对齐。",
                expected_output="实体一致的候选集合。",
                input_payload={
                    "required_facets": required_facets,
                    "optional_facets": optional_facets,
                },
                risk_level="low",
            )
        )
    if len(steps) > 1:
        steps.append(
            PlanStep(
                step_id="rank_candidates",
                goal="排序并选出最适合当前问题的候选门店。",
                expected_output="排序后的候选及推荐理由。",
                input_payload={
                    "query": step_payload["query"],
                    "required_facets": required_facets,
                },
                risk_level="low",
            )
        )
    steps.append(
        PlanStep(
            step_id="compose_answer",
            goal="基于 TaskPlan 结果生成最终回答。",
            expected_output="最终回答文本。",
            input_payload={
                "query": step_payload["query"],
                "task_plan_mode": "plan_execute",
            },
            risk_level="low",
        )
    )
    summary = f"复杂本地生活组合任务，覆盖 {', '.join(sorted(facet_names))}。"
    return TaskPlan(
        enabled=True,
        trigger_reason=reason,
        summary=summary,
        route_candidate=routing.route_candidate,
        task_complexity="complex",
        execution_mode="plan_execute",
        can_fallback_to_legacy=True,
        required_facets=required_facets,
        optional_facets=optional_facets,
        steps=steps,
        failure_reason=None,
        extra={
            "task_plan_step_count": len(steps),
            "task_plan_step_ids": [step.step_id for step in steps],
        },
    )


def ensure_task_plan(state: Any) -> Any:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return state

    task_plan = getattr(turn, "task_plan", None)
    if task_plan is not None and getattr(task_plan, "steps", None):
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["task_plan"] = task_plan.model_dump(mode="json")
        turn_extra["task_plan_status"] = "reused"
        turn_extra["task_plan_failure_reason"] = None
        state["turn"] = turn.model_copy(
            update={
                "task_plan": task_plan,
                "plan": list(task_plan.steps),
                "task_complexity": getattr(task_plan, "task_complexity", "complex"),
                "execution_mode": getattr(task_plan, "execution_mode", "plan_execute"),
                "extra": turn_extra,
            }
        )
        state = _update_phase3_trace(
            state,
            task_plan_status="reused",
            task_plan_failure_reason=None,
            task_plan_enabled=bool(getattr(task_plan, "enabled", False)),
            task_plan_trigger_reason=getattr(task_plan, "trigger_reason", None),
            task_plan_step_count=len(getattr(task_plan, "steps", []) or []),
            task_plan_step_ids=[step.step_id for step in getattr(task_plan, "steps", []) or []],
            task_plan_route_candidate=getattr(task_plan, "route_candidate", None),
        )
        return state

    task_plan = _build_task_plan(turn, routing, state["persistent"])
    if task_plan is None or not getattr(task_plan, "enabled", False) or not getattr(task_plan, "steps", None):
        reason = getattr(task_plan, "failure_reason", "task_plan_unavailable") if task_plan is not None else "task_plan_unavailable"
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["task_plan_status"] = "skipped"
        turn_extra["task_plan_failure_reason"] = reason
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        state = _update_phase3_trace(
            state,
            task_plan_status="skipped",
            task_plan_failure_reason=reason,
            task_plan_enabled=False,
            task_plan_step_count=0,
            task_plan_step_ids=[],
            task_plan_route_candidate=routing.route_candidate,
        )
        return state

    turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
    turn_extra["task_plan"] = task_plan.model_dump(mode="json")
    turn_extra["task_plan_status"] = "synthesized"
    turn_extra["task_plan_failure_reason"] = None
    turn_extra["task_plan_step_count"] = len(task_plan.steps)
    turn_extra["task_plan_step_ids"] = [step.step_id for step in task_plan.steps]
    state["turn"] = turn.model_copy(
        update={
            "task_plan": task_plan,
            "plan": list(task_plan.steps),
            "task_complexity": task_plan.task_complexity,
            "execution_mode": task_plan.execution_mode,
            "extra": turn_extra,
        }
    )
    state = _update_phase3_trace(
        state,
        task_plan_status="synthesized",
        task_plan_failure_reason=None,
        task_plan_enabled=True,
        task_plan_trigger_reason=task_plan.trigger_reason,
        task_plan_step_count=len(task_plan.steps),
        task_plan_step_ids=[step.step_id for step in task_plan.steps],
        task_plan_route_candidate=task_plan.route_candidate,
        task_plan_required_facets=task_plan.required_facets,
        task_plan_optional_facets=task_plan.optional_facets,
    )
    return state


def _apply_phase1_routing_extra(turn_extra: dict[str, Any], routing: RoutingDecision | None) -> dict[str, Any]:
    if routing is None:
        return turn_extra
    merged = dict(turn_extra)
    routing_extra = dict(getattr(routing, "extra", {}) or {})
    for key in ("route_review_decision", "required_facets", "optional_facets", "required_facets_source_constraints", "user_need"):
        value = routing_extra.get(key)
        if value is not None:
            merged[key] = value
    return merged


def _phase1_flags() -> tuple[bool, bool, bool]:
    settings = get_settings()
    return (
        bool(getattr(settings, "enable_route_review", True)),
        bool(getattr(settings, "enable_required_facets", True)),
        bool(getattr(settings, "enable_min_entity_consistency_check", True)),
    )


def _phase1_plan_flags() -> bool:
    settings = get_settings()
    return bool(getattr(settings, "enable_required_facets_to_plans", True))


def _phase2_flags() -> tuple[bool, bool, bool]:
    settings = get_settings()
    return (
        bool(getattr(settings, "enable_partial_grounded", True)),
        bool(getattr(settings, "enable_slot_clarify", True)),
        bool(getattr(settings, "enable_rag_plus_tool_partial_answer", True)),
    )


def _phase3_flags() -> bool:
    settings = get_settings()
    return bool(getattr(settings, "enable_task_plan_for_local_life", True))


def _phase4_flags() -> tuple[bool, str]:
    settings = get_settings()
    return (
        bool(getattr(settings, "enable_answer_verifier", True)),
        str(getattr(settings, "answer_verifier_mode", "warn_only") or "warn_only").strip().lower() or "warn_only",
    )


def _normalize_entity_key(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if raw in (None, "", [], {}, ()):
        return None
    text = str(raw).strip()
    return text or None


def _facet_dict(
    name: str,
    *,
    required: bool = True,
    data_source: str = _PHASE1_DATA_SOURCE_MIXED,
    freshness: str = "static_ok",
    entity_keys: Sequence[str] | None = None,
    missing_policy: str = "partial_grounded",
    evidence_roles: Sequence[str] | None = None,
    tool_names: Sequence[str] | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "data_source": data_source,
        "freshness": freshness,
        "entity_keys": [str(item) for item in (entity_keys or []) if str(item).strip()],
        "missing_policy": missing_policy,
        "evidence_roles": [str(item) for item in (evidence_roles or []) if str(item).strip()],
        "tool_names": [str(item) for item in (tool_names or []) if str(item).strip()],
        "detail": detail,
    }


def _clarification_label_for_slot(slot: str) -> str:
    normalized = str(slot or "").strip().lower()
    if normalized in {"location", "city", "area", "district", "region", "lat", "lng"}:
        return "城市或商圈"
    if normalized in {"shop_id", "shop_name", "shop", "merchant", "merchant_name"}:
        return "店名"
    if normalized in {"shop_detail", "merchant_detail", "detail"}:
        return "门店详情"
    if normalized in {"time", "booking_time", "date", "datetime"}:
        return "时间"
    if normalized in {"voucher_id", "coupon_id", "package_id", "coupon", "package"}:
        return "券或套餐"
    if normalized in {"order_id", "booking_id", "selected_order_id", "selected_booking_id"}:
        return "订单号"
    if normalized in {"category", "type", "type_name"}:
        return "品类"
    if normalized in {"price", "budget", "amount"}:
        return "预算"
    if normalized in {"scene", "scene_fit"}:
        return "场景"
    return normalized or "关键信息"


def build_clarification_question(
    missing_slots: Sequence[str] | None = None,
    *,
    clarification_slot: str | None = None,
    required_facets: Sequence[Mapping[str, Any]] | None = None,
    query_text: str | None = None,
    fallback: str | None = None,
) -> str | None:
    normalized_slots = [str(slot).strip().lower() for slot in (missing_slots or []) if str(slot).strip()]
    slot = str(clarification_slot or "").strip().lower() or None

    if not slot and required_facets:
        for facet in required_facets:
            if not isinstance(facet, Mapping):
                continue
            missing_policy = str(facet.get("missing_policy") or "").strip().lower()
            if missing_policy != "ask_clarification":
                continue
            facet_name = str(facet.get("name") or "").strip().lower()
            if facet_name:
                slot = facet_name
                break

    if not slot and normalized_slots:
        slot = normalized_slots[0]

    if not slot:
        text = str(fallback or "").strip()
        return text or None

    if slot in {"location", "city", "area", "district", "region", "lat", "lng"}:
        return "你方便补充一下城市或商圈吗？"
    if slot in {"shop_id", "shop_name", "shop", "merchant", "merchant_name"}:
        return "你是指刚才那家店，还是要重新推荐一家？"
    if slot in {"shop_detail", "merchant_detail", "detail"}:
        return "你是想看哪家店的详情，还是想重新选一家店？"
    if slot in {"time", "booking_time", "date", "datetime"}:
        return "你是问现在，还是某个具体时间？"
    if slot in {"voucher_id", "coupon_id", "package_id", "coupon", "package"}:
        return "你想查哪张券或哪个套餐？"
    if slot in {"order_id", "booking_id", "selected_order_id", "selected_booking_id"}:
        return "你方便补充订单号吗？"
    if slot in {"category", "type", "type_name"}:
        return "你想看的品类是什么？"
    if slot in {"price", "budget", "amount"}:
        return "你方便补充一下预算范围吗？"
    if slot in {"scene", "scene_fit"}:
        return "你更看重哪种场景？"
    if len(normalized_slots) > 1:
        labels = [label for label in dict.fromkeys(_clarification_label_for_slot(item) for item in normalized_slots) if label]
        if labels:
            return f"你方便补充一下{ '、'.join(labels[:2]) }吗？"
    label = _clarification_label_for_slot(slot)
    return f"你方便补充一下{label}吗？"


def _facet_covered_for_phase2(
    facet_name: str,
    *,
    role_tokens: set[str],
    tool_result_present: bool,
    has_matching_shop_evidence: bool,
    city_area_category_consistency: bool,
) -> bool:
    normalized = str(facet_name or "").strip().lower()
    if normalized in {"location", "city", "area"}:
        return city_area_category_consistency
    if normalized in {"scene_fit", "recommendation_reason", "shop_detail"}:
        return bool(role_tokens & {"review", "guide", "detail", "merchant_profile", "merchant_review_summary", "business_evidence"})
    if normalized in {"coupon", "open_status", "distance_eta", "price", "package"}:
        return bool(tool_result_present or role_tokens & {"coupon", "package", "status", "business_evidence", "distance", "navigation"})
    if normalized in {"category", "scene"}:
        return bool(role_tokens or has_matching_shop_evidence)
    if normalized in {"shop_id", "shop_name"}:
        return bool(has_matching_shop_evidence)
    return bool(role_tokens or tool_result_present or has_matching_shop_evidence)


def _route_review_reason(
    current_action: str,
    recommended_action: str,
    semantic_route: SemanticRoutingDraft,
    routing: RoutingDecision,
) -> str:
    if current_action == recommended_action:
        return "route_review_no_change"
    if current_action in {"direct_answer", "clarify", "reject"} and recommended_action in _RETRIEVAL_ACTIONS | {"tool_call"}:
        return "route_review_local_life_upgrade"
    if routing.route_candidate and routing.route_candidate != semantic_route.route_candidate:
        return "route_review_semantic_alignment"
    return "route_review_updated"


def _route_review_priority(action: str) -> int:
    normalized = str(action or "").strip().lower()
    if normalized == "rag_plus_tool":
        return 2
    if normalized in {"rag_retrieval", "tool_call"}:
        return 1
    return 0


def _build_required_facets(
    routing: RoutingDecision,
    semantic_route: SemanticRoutingDraft,
    *,
    raw_query: str,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = normalize_query(raw_query)
    compact = _compact(raw_query)
    context = dict(client_context or {})
    slots = dict(semantic_route.slots or {})
    local_life_query = (
        routing.domain == "local_life"
        or semantic_route.domain == "local_life"
        or any(token in compact for token in _LOCAL_LIFE_QUERY_TOKENS)
    )
    required_facets: list[dict[str, Any]] = []
    optional_facets: list[dict[str, Any]] = []

    if local_life_query:
        has_location_context = bool(
            slots.get("location")
            or context.get("location")
            or context.get("city")
            or persistent.current_city
            or persistent.current_location
        )
        has_shop_hint = bool(
            slots.get("shop_id")
            or slots.get("shop_name")
            or persistent.selected_shop_id
            or persistent.selected_shop_name
            or persistent.current_shop
            or persistent.current_topic
            or context.get("shopId")
            or context.get("shopName")
            or any(token in compact for token in ("这家", "那家", "这个店", "那个店"))
        )
        has_coupon_hint = any(token in compact for token in ("券", "优惠券", "团购", "套餐", "还能用", "可用"))
        has_open_status_hint = any(token in compact for token in ("营业", "开门", "开业", "还能去", "排队", "库存"))
        has_scene_hint = any(token in compact for token in ("适合", "带父母", "带长辈", "约会", "家庭聚餐", "安静", "不吵", "老人", "孩子"))
        has_distance_hint = bool(has_location_context and any(token in compact for token in ("附近", "周边", "离我", "离我近")))
        needs_recommendation = has_scene_hint or any(token in compact for token in ("附近", "周边", "推荐", "适合", "约会", "家庭聚餐", "安静", "不吵", "老人", "孩子"))
        needs_detail = any(token in compact for token in ("怎么样", "评价", "评分", "口碑", "环境", "详情", "介绍", "值不值", "好不好", "避坑", "踩雷", "翻车", "停车"))

        if needs_recommendation:
            required_facets.append(
                _facet_dict(
                    "location",
                    data_source=_PHASE1_DATA_SOURCE_CLIENT_CONTEXT if has_location_context else _PHASE1_DATA_SOURCE_SLOT,
                    freshness="near_realtime_required",
                    entity_keys=["city", "location"],
                    missing_policy="ask_clarification",
                    detail="user_position_or_city",
                )
            )
            if has_location_context:
                category_value = _normalize_entity_key(slots.get("category") or context.get("category") or context.get("typeName"))
                required_facets.append(
                    _facet_dict(
                        "category",
                        data_source=_PHASE1_DATA_SOURCE_SLOT,
                        freshness="static_ok",
                        entity_keys=["category"],
                        missing_policy="ask_clarification",
                        detail=category_value or "category_from_query",
                    )
                )
                required_facets.append(
                    _facet_dict(
                        "scene_fit",
                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,
                        freshness="static_ok",
                        entity_keys=["shop_id", "shop_name"],
                        missing_policy="partial_grounded",
                        evidence_roles=["merchant_scene_fit", "merchant_review_summary"],
                        tool_names=["getShopDetail"],
                        detail="scene_fit_recommendation",
                    )
                )
                required_facets.append(
                    _facet_dict(
                        "recommendation_reason",
                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,
                        freshness="static_ok",
                        entity_keys=["shop_id", "shop_name"],
                        missing_policy="partial_grounded",
                        evidence_roles=["merchant_review_summary", "merchant_profile"],
                        tool_names=["search_restaurants", "getShopDetail"],
                        detail="recommendation_explanation",
                    )
                )
                required_facets.append(
                    _facet_dict(
                        "shop_detail",
                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,
                        freshness="static_ok",
                        entity_keys=["shop_id", "shop_name"],
                        missing_policy="partial_grounded",
                        evidence_roles=["merchant_profile", "merchant_review_summary"],
                        tool_names=["getShopDetail"],
                        detail="merchant_detail_summary",
                    )
                )
                if has_distance_hint:
                    required_facets.append(
                        _facet_dict(
                            "distance_eta",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "location"],
                            missing_policy="ask_clarification",
                            tool_names=["get_distance_eta"],
                            detail="nearby_travel_eta",
                        )
                    )
                else:
                    optional_facets.append(
                        _facet_dict(
                            "distance_eta",
                            required=False,
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "location"],
                            missing_policy="partial_grounded",
                            tool_names=["get_distance_eta"],
                            detail="nearby_travel_eta_optional",
                        )
                    )
            if has_coupon_hint:
                if has_shop_hint and has_location_context:
                    required_facets.append(
                        _facet_dict(
                            "coupon",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name", "voucher_id"],
                            missing_policy="ask_clarification",
                            tool_names=["get_coupon_list"],
                            detail="current_coupon_status",
                        )
                    )
                else:
                    optional_facets.append(
                        _facet_dict(
                            "coupon",
                            required=False,
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name", "voucher_id"],
                            missing_policy="partial_grounded",
                            tool_names=["get_coupon_list"],
                            detail="coupon_optional",
                        )
                    )
            if has_open_status_hint:
                if has_shop_hint and has_location_context:
                    required_facets.append(
                        _facet_dict(
                            "open_status",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name"],
                            missing_policy="ask_clarification",
                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],
                            detail="current_open_status",
                        )
                    )
                else:
                    optional_facets.append(
                        _facet_dict(
                            "open_status",
                            required=False,
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name"],
                            missing_policy="partial_grounded",
                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],
                            detail="open_status_optional",
                        )
                    )
        elif needs_detail:
            if has_shop_hint:
                required_facets.append(
                    _facet_dict(
                        "shop_detail",
                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,
                        freshness="static_ok",
                        entity_keys=["shop_id", "shop_name"],
                        missing_policy="partial_grounded",
                        evidence_roles=["merchant_profile", "merchant_review_summary"],
                        tool_names=["getShopDetail"],
                        detail="merchant_detail_summary",
                    )
                )
                required_facets.append(
                    _facet_dict(
                        "recommendation_reason",
                        data_source=_PHASE1_DATA_SOURCE_STATIC_RAG,
                        freshness="static_ok",
                        entity_keys=["shop_id", "shop_name"],
                        missing_policy="partial_grounded",
                        evidence_roles=["merchant_review_summary", "merchant_profile"],
                        tool_names=["search_restaurants", "getShopDetail"],
                        detail="recommendation_explanation",
                    )
                )
                if has_open_status_hint:
                    required_facets.append(
                        _facet_dict(
                            "open_status",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name"],
                            missing_policy="ask_clarification",
                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],
                            detail="current_open_status",
                        )
                    )
                if has_coupon_hint:
                    required_facets.append(
                        _facet_dict(
                            "coupon",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name", "voucher_id"],
                            missing_policy="ask_clarification",
                            tool_names=["get_coupon_list"],
                            detail="current_coupon_status",
                        )
                    )
            else:
                required_facets.append(
                    _facet_dict(
                        "location",
                        data_source=_PHASE1_DATA_SOURCE_SLOT,
                        freshness="near_realtime_required",
                        entity_keys=["city", "location"],
                        missing_policy="ask_clarification",
                        detail="user_position_or_city",
                    )
                )
        elif has_open_status_hint or has_coupon_hint:
            if has_shop_hint:
                if has_open_status_hint:
                    required_facets.append(
                        _facet_dict(
                            "open_status",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name"],
                            missing_policy="ask_clarification",
                            tool_names=["check_open_status", "getShopDetail", "getBusinessStatus"],
                            detail="current_open_status",
                        )
                    )
                if has_coupon_hint:
                    required_facets.append(
                        _facet_dict(
                            "coupon",
                            data_source=_PHASE1_DATA_SOURCE_DYNAMIC_TOOL,
                            freshness="near_realtime_required",
                            entity_keys=["shop_id", "shop_name", "voucher_id"],
                            missing_policy="ask_clarification",
                            tool_names=["get_coupon_list"],
                            detail="current_coupon_status",
                        )
                    )
            else:
                required_facets.append(
                    _facet_dict(
                        "location",
                        data_source=_PHASE1_DATA_SOURCE_SLOT,
                        freshness="near_realtime_required",
                        entity_keys=["city", "location"],
                        missing_policy="ask_clarification",
                        detail="user_position_or_city",
                    )
                )

    # 去重并保持稳定顺序
    dedup_required: list[dict[str, Any]] = []
    seen_required: set[str] = set()
    for facet in required_facets:
        name = str(facet.get("name") or "").strip()
        if not name or name in seen_required:
            continue
        seen_required.add(name)
        dedup_required.append(facet)

    dedup_optional: list[dict[str, Any]] = []
    seen_optional: set[str] = set(seen_required)
    for facet in optional_facets:
        name = str(facet.get("name") or "").strip()
        if not name or name in seen_optional:
            continue
        seen_optional.add(name)
        dedup_optional.append(facet)
    return dedup_required, dedup_optional


def _recommended_action_for_facets(
    required_facets: Sequence[Mapping[str, Any]],
    semantic_route: SemanticRoutingDraft,
    routing: RoutingDecision,
) -> str:
    data_sources = {
        str(facet.get("data_source") or "").strip().lower()
        for facet in required_facets
        if str(facet.get("name") or "").strip()
    }
    if _PHASE1_DATA_SOURCE_DYNAMIC_TOOL in data_sources and _PHASE1_DATA_SOURCE_STATIC_RAG in data_sources:
        return "rag_plus_tool"
    if _PHASE1_DATA_SOURCE_DYNAMIC_TOOL in data_sources:
        return "tool_call"
    if _PHASE1_DATA_SOURCE_STATIC_RAG in data_sources:
        return "rag_retrieval"
    if semantic_route.required_action:
        return str(semantic_route.required_action).strip().lower()
    return str(routing.required_action or "direct_answer").strip().lower()


def _apply_route_review(
    routing: RoutingDecision,
    *,
    raw_query: str,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision:
    if _looks_like_unserviceable_location(raw_query) or bool(dict(getattr(routing, "extra", {}) or {}).get("unserviceable_location")):
        return RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalize_query(raw_query),
            domain="local_life",
            confidence=max(float(getattr(routing, "confidence", 0.0) or 0.0), 0.88),
            input_quality=getattr(routing, "input_quality"),
            intent=IntentRoutingDecision(
                name="location_unavailable",
                confidence=0.88,
                required_slots=[],
                missing_slots=[],
                allowed_routes=["direct_answer"],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action="direct_answer",
            blocked=False,
            blocked_reason=None,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=None,
            missing_slots=[],
            resolved_references=[],
            route_reason="unserviceable_location",
            safeguards_triggered=list(dict.fromkeys(list(getattr(routing, "safeguards_triggered", []) or []) + ["unserviceable_location"])),
            route_candidate="location_unavailable",
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                **dict(getattr(routing, "extra", {}) or {}),
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                "unserviceable_location": True,
            },
        )
    # Check for pronoun reference failure in sequential routing
    has_pronoun = any(p in raw_query for p in ("这家", "那家", "它", "该店", "此店", "这店", "这个店", "那个店", "这间", "刚才那家", "这商家", "这个商家", "刚才那个"))
    has_resolved_ref = bool(
        persistent.current_topic
        or persistent.current_shop
        or persistent.selected_shop_id
        or persistent.recent_entities
        or persistent.last_candidates
        or _client_context_has_candidate_anchor(client_context)
    )
    if has_pronoun and not has_resolved_ref:
        return RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalize_query(raw_query),
            domain="local_life",
            confidence=0.9,
            input_quality=getattr(routing, "input_quality"),
            intent=IntentRoutingDecision(
                name="clarify",
                confidence=0.9,
                required_slots=["shop_name"],
                missing_slots=["shop_name"],
                allowed_routes=["clarify"],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action="clarify",
            blocked=False,
            blocked_reason=None,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason="reference_resolution_failed",
            missing_slots=["shop_name"],
            resolved_references=[],
            route_reason="reference_resolution_failed",
            route_candidate="clarify",
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question="你问的是哪家店？请告诉我具体店名或选择刚才提到的商家。",
            extra={
                **dict(getattr(routing, "extra", {}) or {}),
                "client_context": dict(client_context or {}),
                "ambiguity_type": "reference_clarify",
            },
        )

    route_review_enabled, required_facets_enabled, _ = _phase1_flags()
    if not route_review_enabled:
        return routing

    semantic_route = _semantic_route_for_query(raw_query, persistent, client_context=client_context)
    required_facets: list[dict[str, Any]] = []
    optional_facets: list[dict[str, Any]] = []
    if required_facets_enabled:
        required_facets, optional_facets = _build_required_facets(
            routing,
            semantic_route,
            raw_query=raw_query,
            persistent=persistent,
            client_context=client_context,
        )
    recommended_action = _recommended_action_for_facets(required_facets, semantic_route, routing)
    current_action = str(routing.required_action or "").strip().lower()
    current_priority = _route_review_priority(current_action)
    recommended_priority = _route_review_priority(recommended_action)
    should_upgrade = (
        routing.input_quality.is_valid
        and routing.domain == "local_life"
        and recommended_action in {"rag_retrieval", "tool_call", "rag_plus_tool"}
        and (
            recommended_priority > current_priority
            or (current_priority == recommended_priority == 1 and current_action != recommended_action)
        )
    )

    review_decision = {
        "reviewed": True,
        "enabled": True,
        "semantic_route": semantic_route.__dict__,
        "current_action": current_action,
        "recommended_action": recommended_action,
        "changed": should_upgrade,
        "reason": _route_review_reason(current_action, recommended_action, semantic_route, routing),
    }
    if required_facets_enabled:
        review_decision["required_facets"] = required_facets
        review_decision["optional_facets"] = optional_facets
        review_decision["required_facets_source_constraints"] = {
            str(facet.get("name") or ""): str(facet.get("data_source") or "")
            for facet in [*required_facets, *optional_facets]
            if str(facet.get("name") or "").strip()
        }

    if not should_upgrade:
        extra = dict(routing.extra)
        extra["route_review_decision"] = review_decision
        if required_facets_enabled:
            extra["required_facets"] = required_facets
            extra["optional_facets"] = optional_facets
            extra["required_facets_source_constraints"] = review_decision["required_facets_source_constraints"]
            extra["user_need"] = {
                "intent": semantic_route.intent,
                "slots": dict(semantic_route.slots or {}),
                "missing_slots": list(semantic_route.missing_slots or []),
                "required_facets": required_facets,
                "optional_facets": optional_facets,
            }
        return routing.model_copy(update={"extra": extra})

    updated_route = routing.model_copy(
        update={
            "domain": semantic_route.domain,
            "confidence": max(routing.confidence, semantic_route.confidence),
            "intent": IntentRoutingDecision(
                name=semantic_route.intent,
                confidence=max(routing.intent.confidence, semantic_route.confidence),
                required_slots=list(routing.intent.required_slots or []),
                missing_slots=list(dict.fromkeys(list(routing.intent.missing_slots or []) + list(semantic_route.missing_slots or []))),
                allowed_routes=(
                    ["rag_retrieval", "tool_call", "rag_plus_tool"]
                    if recommended_action == "rag_plus_tool"
                    else ["tool_call"]
                    if recommended_action == "tool_call"
                    else ["rag_retrieval"]
                ),
                forbidden_routes=["reject"],
            ),
            "required_action": recommended_action,
            "blocked": False,
            "blocked_reason": None,
            "should_rewrite_query": bool(semantic_route.should_rewrite_query or routing.should_rewrite_query or recommended_action in {"rag_retrieval", "tool_call", "rag_plus_tool"}),
            "should_retrieve": recommended_action in {"rag_retrieval", "rag_plus_tool"},
            "should_call_tool": recommended_action in {"tool_call", "rag_plus_tool"},
            "should_use_memory": recommended_action not in {"clarify", "reject", "no_op"},
            "should_persist_memory": recommended_action not in {"clarify", "reject", "no_op"},
            "should_vectorize_memory": recommended_action not in {"clarify", "reject", "no_op"},
            "should_emit_retrieval_events": recommended_action in {"rag_retrieval", "rag_plus_tool"},
            "retrieval_skipped_reason": None,
            "missing_slots": list(dict.fromkeys(list(routing.missing_slots or []) + list(semantic_route.missing_slots or []))),
            "resolved_references": list(dict.fromkeys(list(routing.resolved_references or []))),
            "route_reason": _route_review_reason(current_action, recommended_action, semantic_route, routing),
            "route_candidate": semantic_route.route_candidate or routing.route_candidate,
            "preferred_chunk_roles": list(dict.fromkeys(list(semantic_route.preferred_chunk_roles or []) + list(routing.preferred_chunk_roles or []))),
            "tool_candidates": list(dict.fromkeys(list(semantic_route.tool_candidates or []) + list(routing.tool_candidates or []))),
            "clarification_question": semantic_route.clarification_question or routing.clarification_question,
        }
    )
    extra = dict(updated_route.extra)
    extra["route_review_decision"] = review_decision
    if required_facets_enabled:
        extra["required_facets"] = required_facets
        extra["optional_facets"] = optional_facets
        extra["required_facets_source_constraints"] = review_decision["required_facets_source_constraints"]
        extra["user_need"] = {
            "intent": semantic_route.intent,
            "slots": dict(semantic_route.slots or {}),
            "missing_slots": list(semantic_route.missing_slots or []),
            "required_facets": required_facets,
            "optional_facets": optional_facets,
        }
    return updated_route.model_copy(update={"extra": extra})


def _extract_entity_values_from_mapping(mapping: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = mapping.get(key)
        if value in (None, "", [], {}, ()):
            continue
        if isinstance(value, (list, tuple, set)):
            for item in value:
                normalized = _normalize_entity_key(item)
                if normalized and normalized not in values:
                    values.append(normalized)
            continue
        normalized = _normalize_entity_key(value)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _build_min_entity_consistency(
    *,
    context: Mapping[str, Any],
    evidence_items: Sequence[EvidenceItem],
    tool_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target_shop_id = _normalize_entity_key(context.get("shop_id") or context.get("selected_shop_id"))
    target_shop_name = _normalize_entity_key(context.get("shop_name") or context.get("selected_shop_name") or context.get("current_shop"))
    target_voucher_id = _normalize_entity_key(context.get("coupon_id") or context.get("voucher_id"))
    target_package_id = _normalize_entity_key(context.get("package_id"))

    evidence_shop_ids: list[str] = []
    evidence_shop_names: list[str] = []
    evidence_voucher_ids: list[str] = []
    evidence_package_ids: list[str] = []
    for item in evidence_items:
        metadata = dict(getattr(item, "metadata", {}) or {})
        for value in _extract_entity_values_from_mapping(metadata, "shop_id", "parent_shop_id", "entity_shop_id"):
            if value not in evidence_shop_ids:
                evidence_shop_ids.append(value)
        for value in _extract_entity_values_from_mapping(metadata, "shop_name", "parent_shop_name", "entity_shop_name"):
            if value not in evidence_shop_names:
                evidence_shop_names.append(value)
        for value in _extract_entity_values_from_mapping(metadata, "coupon_id", "voucher_id"):
            if value not in evidence_voucher_ids:
                evidence_voucher_ids.append(value)
        for value in _extract_entity_values_from_mapping(metadata, "package_id"):
            if value not in evidence_package_ids:
                evidence_package_ids.append(value)

    tool_payload = dict(tool_payload or {})
    tool_shop_ids = _extract_entity_values_from_mapping(tool_payload, "shop_id", "selected_shop_id")
    tool_shop_names = _extract_entity_values_from_mapping(tool_payload, "shop_name", "selected_shop_name", "current_shop")
    tool_voucher_ids = _extract_entity_values_from_mapping(tool_payload, "coupon_id", "voucher_id")
    tool_package_ids = _extract_entity_values_from_mapping(tool_payload, "package_id")

    cross_entity_risk = False
    mismatch_reason = None
    if len(set(evidence_shop_ids)) > 1 or len(set(evidence_shop_names)) > 1:
        cross_entity_risk = True
        mismatch_reason = "multi_shop_evidence"
    elif target_shop_id and evidence_shop_ids and target_shop_id not in evidence_shop_ids:
        cross_entity_risk = True
        mismatch_reason = "shop_mismatch"
    elif target_shop_name and evidence_shop_names and target_shop_name not in evidence_shop_names:
        cross_entity_risk = True
        mismatch_reason = "shop_mismatch"
    elif target_voucher_id and evidence_voucher_ids and target_voucher_id not in evidence_voucher_ids:
        cross_entity_risk = True
        mismatch_reason = "coupon_mismatch"
    elif target_package_id and evidence_package_ids and target_package_id not in evidence_package_ids:
        cross_entity_risk = True
        mismatch_reason = "package_mismatch"
    elif len(set(tool_shop_ids)) > 1 or len(set(tool_voucher_ids)) > 1 or len(set(tool_package_ids)) > 1:
        cross_entity_risk = True
        mismatch_reason = "multi_entity_tool_payload"

    if target_shop_name and not evidence_shop_ids and not evidence_shop_names:
        cross_entity_risk = True
        mismatch_reason = "shop_missing"

    return {
        "checked": True,
        "passed": not cross_entity_risk,
        "entity_keys": {
            "target": {
                "shop_id": target_shop_id,
                "shop_name": target_shop_name,
                "voucher_id": target_voucher_id,
                "package_id": target_package_id,
            },
            "evidence": {
                "shop_id": evidence_shop_ids,
                "shop_name": evidence_shop_names,
                "voucher_id": evidence_voucher_ids,
                "package_id": evidence_package_ids,
            },
            "tool": {
                "shop_id": tool_shop_ids,
                "shop_name": tool_shop_names,
                "voucher_id": tool_voucher_ids,
                "package_id": tool_package_ids,
            },
        },
        "mismatch_reason": mismatch_reason,
        "cross_entity_risk": cross_entity_risk,
    }


def ensure_retrieval_plan(state: Any) -> Any:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return state
    plan_facet_metadata_enabled = _phase1_plan_flags()
    if routing.blocked or str(routing.required_action).strip().lower() not in _RETRIEVAL_ACTIONS or not routing.should_retrieve:
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["retrieval_skipped_reason"] = routing.blocked_reason or routing.retrieval_skipped_reason or "retrieval_not_allowed"
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        state = _update_phase0_trace(
            state,
            retrieval_plan_status="skipped",
            retrieval_plan_failure_reason=turn_extra["retrieval_skipped_reason"],
        )
        return state
    current_plan = getattr(turn, "retrieval_plan", None)
    current_semantic_query = str(getattr(current_plan, "semantic_query", "") or "").strip()
    if current_plan is not None and current_semantic_query:
        current_plan_extra = dict(current_plan.extra)
        for key in ("route_review_decision",):
            if key in routing.extra and key not in current_plan_extra:
                current_plan_extra[key] = routing.extra[key]
        if plan_facet_metadata_enabled:
            for key in ("required_facets", "optional_facets", "required_facets_source_constraints", "user_need"):
                if key in routing.extra and key not in current_plan_extra:
                    current_plan_extra[key] = routing.extra[key]
        if not getattr(current_plan, "preferred_chunk_roles", None) and routing.preferred_chunk_roles:
            current_plan_extra["preferred_chunk_roles"] = list(routing.preferred_chunk_roles)
            current_plan_extra["source"] = "synthesized"
            current_plan = current_plan.model_copy(
                update={
                    "preferred_chunk_roles": list(routing.preferred_chunk_roles),
                    "extra": current_plan_extra,
                }
            )
            state["turn"] = turn.model_copy(update={"retrieval_plan": current_plan})
        elif current_plan_extra != dict(current_plan.extra):
            current_plan = current_plan.model_copy(update={"extra": current_plan_extra})
            state["turn"] = turn.model_copy(update={"retrieval_plan": current_plan})
        state = _update_phase0_trace(
            state,
            retrieval_plan_status="reused",
            retrieval_plan_failure_reason=None,
        )
        return state
    plan = synthesize_retrieval_plan(routing, turn, state["persistent"], state["runtime"].client_context)
    if plan is None:
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["retrieval_skipped_reason"] = routing.route_reason or routing.required_action or "retrieval_plan_missing"
        if routing.required_action in {"rag_retrieval", "rag_plus_tool"} and routing.required_action != "clarify":
            routing = routing.model_copy(
                update={
                    "required_action": "clarify",
                    "should_retrieve": False,
                    "should_call_tool": False,
                    "should_rewrite_query": False,
                    "retrieval_skipped_reason": "retrieval_plan_missing",
                    "clarification_question": routing.clarification_question
                    or build_clarification_question(routing.missing_slots, query_text=turn.raw_query),
                }
            )
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
        state["turn"] = turn.model_copy(update={"extra": turn_extra, "routing_decision": routing})
        state = _update_phase0_trace(
            state,
            retrieval_plan_status="missing",
            retrieval_plan_failure_reason=turn_extra["retrieval_skipped_reason"],
        )
        return state
    routing = routing.model_copy(
        update={
            "preferred_chunk_roles": list(plan.preferred_chunk_roles or routing.preferred_chunk_roles),
            "should_retrieve": True,
            "should_emit_retrieval_events": True,
            "retrieval_skipped_reason": None,
            "route_reason": routing.route_reason or plan.extra.get("source", "synthesized"),
            "extra": {**dict(routing.extra), "retrieval_plan_synthesized": plan.model_dump(mode="json")},
        }
    )
    turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
    turn_extra["retrieval_plan"] = plan.model_dump(mode="json")
    turn_extra["routing_decision"] = routing.model_dump(mode="json")
    state["turn"] = turn.model_copy(update={"retrieval_plan": plan, "routing_decision": routing, "extra": turn_extra})
    state = _update_phase0_trace(
        state,
        retrieval_plan_status="synthesized",
        retrieval_plan_failure_reason=None,
    )
    return state


def ensure_tool_plan(state: Any) -> Any:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return state
    plan_facet_metadata_enabled = _phase1_plan_flags()
    if routing.blocked or str(routing.required_action).strip().lower() not in {"tool_call", "rag_plus_tool"} or not routing.should_call_tool:
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["tool_plan_skipped_reason"] = routing.blocked_reason or routing.retrieval_skipped_reason or "tool_not_allowed"
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        state = _update_phase0_trace(
            state,
            tool_plan_status="skipped",
            tool_plan_failure_reason=turn_extra["tool_plan_skipped_reason"],
        )
        return state
    current_plan = getattr(turn, "tool_plan", None)
    if current_plan is not None and getattr(current_plan, "should_execute", False) and getattr(current_plan, "tool_name", None):
        current_plan_extra = dict(current_plan.extra)
        for key in ("route_review_decision",):
            if key in routing.extra and key not in current_plan_extra:
                current_plan_extra[key] = routing.extra[key]
        if plan_facet_metadata_enabled:
            for key in ("required_facets", "optional_facets", "required_facets_source_constraints", "user_need"):
                if key in routing.extra and key not in current_plan_extra:
                    current_plan_extra[key] = routing.extra[key]
        if current_plan_extra != dict(current_plan.extra):
            current_plan = current_plan.model_copy(update={"extra": current_plan_extra})
            state["turn"] = turn.model_copy(update={"tool_plan": current_plan})
        state = _update_phase0_trace(
            state,
            tool_plan_status="reused",
            tool_plan_failure_reason=None,
        )
        return state
    plan = synthesize_tool_selection(routing, turn, state["persistent"], state["runtime"].client_context)
    if plan is None:
        routing = routing.model_copy(
            update={
                "required_action": "clarify",
                "should_call_tool": False,
                "should_retrieve": False,
                "should_rewrite_query": False,
                "clarification_question": routing.clarification_question
                or build_clarification_question(routing.missing_slots, query_text=turn.raw_query),
            }
        )
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        turn_extra["tool_plan_skipped_reason"] = "tool_plan_missing"
        state["turn"] = turn.model_copy(update={"routing_decision": routing, "extra": turn_extra})
        state = _update_phase0_trace(
            state,
            tool_plan_status="missing",
            tool_plan_failure_reason="tool_plan_missing",
        )
        return state
    routing = routing.model_copy(
        update={
            "tool_candidates": list(dict.fromkeys(list(routing.tool_candidates) + [plan.tool_name])),
            "should_call_tool": True,
            "retrieval_skipped_reason": routing.retrieval_skipped_reason,
            "route_reason": routing.route_reason or plan.reason,
            "extra": {**dict(routing.extra), "tool_plan_synthesized": plan.model_dump(mode="json")},
        }
    )
    turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
    turn_extra["tool_plan"] = plan.model_dump(mode="json")
    turn_extra["routing_decision"] = routing.model_dump(mode="json")
    state["turn"] = turn.model_copy(update={"tool_plan": plan, "routing_decision": routing, "extra": turn_extra})
    state = _update_phase0_trace(
        state,
        tool_plan_status="synthesized",
        tool_plan_failure_reason=None,
    )
    return state


def can_enter_retrieval(state: Any) -> RetrievalEligibility:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return RetrievalEligibility(
            allowed=False,
            blocked=True,
            reason="missing_routing_decision",
            blocked_reason="missing_routing_decision",
            failure_reasons=["missing_routing_decision"],
        )

    state = ensure_retrieval_plan(state)
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    retrieval_plan = getattr(turn, "retrieval_plan", None)
    rewrite_decision = getattr(routing, "rewrite_decision", None)
    normalized_query = str(routing.normalized_query or "").strip()
    semantic_query = str(getattr(retrieval_plan, "semantic_query", "") or "").strip()
    rewritten_query = str(
        getattr(rewrite_decision, "rewritten_query", "") or semantic_query or normalized_query or ""
    ).strip()
    retrieval_plan_valid = bool(retrieval_plan is not None and semantic_query)
    intent_allowed = _intent_allows_retrieval(routing.intent)
    input_quality_ok = bool(routing.input_quality.is_valid and float(routing.input_quality.score or 0.0) >= _RETRIEVAL_SCORE_THRESHOLD)
    retrieval_action_ok = _is_retrieval_action(routing.required_action)
    blocked = bool(routing.blocked)
    failure_reasons: list[str] = []

    if blocked:
        failure_reasons.append(routing.blocked_reason or "routing_blocked")
    if not routing.should_retrieve:
        failure_reasons.append("routing_should_retrieve_false")
    if not retrieval_action_ok:
        failure_reasons.append(f"required_action_{routing.required_action or 'unknown'}")
    if not input_quality_ok:
        failure_reasons.append(f"input_quality_{routing.input_quality.kind or 'unknown'}")
    if not normalized_query:
        failure_reasons.append("normalized_query_empty")
    if not rewritten_query:
        failure_reasons.append("rewritten_query_empty")
    if not semantic_query:
        failure_reasons.append("semantic_query_empty")
    if not intent_allowed:
        failure_reasons.append(f"intent_disallows_{routing.intent.name or 'unknown'}")
    if not retrieval_plan_valid:
        failure_reasons.append("retrieval_plan_invalid")
    if routing.input_quality.kind in {"empty_input", "pure_punctuation", "repeated_noise", "low_information"}:
        failure_reasons.append(f"input_quality_{routing.input_quality.kind}")
    if routing.required_action in {"clarify", "direct_answer", "memory_update", "no_op", "reject"}:
        failure_reasons.append(f"turn_action_{routing.required_action}")
    if rewrite_decision is not None and bool(getattr(rewrite_decision, "risky_rewrite", False)):
        failure_reasons.append("risky_rewrite")

    allowed = not failure_reasons
    reason = "retrieval_eligible" if allowed else failure_reasons[0]
    return RetrievalEligibility(
        allowed=allowed,
        blocked=blocked,
        reason=reason,
        blocked_reason=routing.blocked_reason if blocked else None,
        failure_reasons=list(dict.fromkeys(failure_reasons)),
        required_action=routing.required_action,
        intent_allowed=intent_allowed,
        input_quality_ok=input_quality_ok,
        input_quality_score=float(routing.input_quality.score or 0.0),
        normalized_query=normalized_query or None,
        rewritten_query=rewritten_query or None,
        semantic_query=semantic_query or None,
        retrieval_plan_valid=retrieval_plan_valid,
        route_candidate=routing.route_candidate,
        details={
            "route_reason": routing.route_reason,
            "input_quality_kind": routing.input_quality.kind,
            "intent_name": routing.intent.name,
            "should_retrieve": routing.should_retrieve,
            "should_emit_retrieval_events": routing.should_emit_retrieval_events,
        },
    )


def can_enter_tool(state: Any) -> RetrievalEligibility:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return RetrievalEligibility(
            allowed=False,
            blocked=True,
            reason="missing_routing_decision",
            blocked_reason="missing_routing_decision",
            failure_reasons=["missing_routing_decision"],
        )

    state = ensure_tool_plan(state)
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    tool_plan = getattr(turn, "tool_plan", None)
    tool_name = str(getattr(tool_plan, "tool_name", "") or "").strip()
    tool_plan_valid = bool(tool_plan is not None and tool_name and bool(getattr(tool_plan, "should_execute", False)))
    blocked = bool(routing.blocked)
    input_quality_ok = bool(routing.input_quality.is_valid and float(routing.input_quality.score or 0.0) >= _RETRIEVAL_SCORE_THRESHOLD)
    action_ok = str(routing.required_action).strip().lower() in {"tool_call", "rag_plus_tool"}
    failure_reasons: list[str] = []
    if blocked:
        failure_reasons.append(routing.blocked_reason or "routing_blocked")
    if not routing.should_call_tool:
        failure_reasons.append("routing_should_call_tool_false")
    if not action_ok:
        failure_reasons.append(f"required_action_{routing.required_action or 'unknown'}")
    if not input_quality_ok:
        failure_reasons.append(f"input_quality_{routing.input_quality.kind or 'unknown'}")
    if not tool_plan_valid:
        failure_reasons.append("tool_plan_invalid")
    if routing.required_action in {"clarify", "direct_answer", "memory_update", "no_op", "reject", "rag_retrieval"}:
        failure_reasons.append(f"turn_action_{routing.required_action}")
    allowed = not failure_reasons
    reason = "tool_eligible" if allowed else failure_reasons[0]
    return RetrievalEligibility(
        allowed=allowed,
        blocked=blocked,
        reason=reason,
        blocked_reason=routing.blocked_reason if blocked else None,
        failure_reasons=list(dict.fromkeys(failure_reasons)),
        required_action=routing.required_action,
        intent_allowed=action_ok,
        input_quality_ok=input_quality_ok,
        input_quality_score=float(routing.input_quality.score or 0.0),
        normalized_query=routing.normalized_query or None,
        rewritten_query=tool_name or None,
        semantic_query=tool_name or None,
        retrieval_plan_valid=tool_plan_valid,
        route_candidate=routing.route_candidate,
        details={
            "route_reason": routing.route_reason,
            "input_quality_kind": routing.input_quality.kind,
            "intent_name": routing.intent.name,
            "should_call_tool": routing.should_call_tool,
        },
    )


def routing_trace_payload(routing: RoutingDecision | None) -> dict[str, Any]:
    if routing is None:
        return {}
    return routing.model_dump(mode="json")


def _required_slots_from_fast_decision(fast_result: FastDecision) -> list[str]:
    slots = dict(fast_result.key_slots or {})
    return [str(item) for item in slots.get("required_slots", []) if item]


def _allowed_routes_from_fast_decision(fast_result: FastDecision) -> list[str]:
    extra = dict(fast_result.extra or {}) if isinstance(fast_result.extra, Mapping) else {}
    local_life_action = str(extra.get("local_life_intent") or "").strip().lower()
    if local_life_action in {"booking", "coupon"}:
        return ["tool_call"]
    if fast_result.needs_tool and fast_result.needs_rag:
        return ["rag_plus_tool"]
    if fast_result.needs_tool:
        return ["tool_call"]
    if fast_result.needs_rag:
        return ["rag_retrieval"]
    return ["direct_answer"]


def _forbidden_routes_from_fast_decision(fast_result: FastDecision) -> list[str]:
    if fast_result.needs_clarify:
        return ["rag_retrieval", "tool_call"]
    return []


def _required_action_from_fast_decision(fast_result: FastDecision) -> str:
    extra = dict(fast_result.extra or {}) if isinstance(fast_result.extra, Mapping) else {}
    local_life_action = str(extra.get("local_life_intent") or "").strip().lower()
    if local_life_action in {"booking", "coupon"}:
        return "tool_call"
    if fast_result.needs_clarify:
        return "clarify"
    if fast_result.needs_tool and fast_result.needs_rag:
        return "rag_plus_tool"
    if fast_result.needs_tool:
        return "tool_call"
    if fast_result.needs_rag:
        return "rag_retrieval"
    return "direct_answer"


def _intent_name_from_fast_decision(fast_result: FastDecision, routing: RoutingDecision) -> str:
    extra = dict(fast_result.extra or {})
    route_candidate = str(extra.get("route_candidate") or routing.route_candidate or "").strip().lower()
    if route_candidate in {"conversation_recap", "session_memory_query", "continue_previous_topic"}:
        return "conversation_recap"
    if route_candidate in {"greeting", "thanks", "profile"}:
        return "chit_chat"
    if route_candidate in {"empty", "low_info"}:
        return "invalid_input"
    if route_candidate == "local_life":
        return "local_life_recommend"
    if route_candidate == "tool_then_rag":
        return "rag_plus_tool"
    if fast_result.needs_tool and fast_result.needs_rag:
        return "rag_plus_tool"
    if fast_result.needs_tool:
        return "tool_required"
    if fast_result.needs_rag and fast_result.intent == IntentType.RECOMMEND:
        return "local_life_recommend"
    if fast_result.intent == IntentType.COMPARE:
        return "comparison"
    if fast_result.intent == IntentType.SUMMARY:
        return "qa_general"
    if fast_result.intent == IntentType.RECOMMEND:
        return "local_life_recommend"
    if fast_result.intent == IntentType.FOLLOW_UP:
        return "follow_up_reference"
    if fast_result.intent == IntentType.EXPLAIN:
        return "qa_general"
    return routing.intent.name or "qa_general"


def _routing_from_turn(turn: Any) -> RoutingDecision | None:
    routing = getattr(turn, "routing_decision", None)
    if isinstance(routing, RoutingDecision):
        return routing
    return None
