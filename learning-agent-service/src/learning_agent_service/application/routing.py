from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from ..domain.contracts import (
    EvidenceItem,
    EvidencePack,
    EvidenceQualityDecision,
    FastDecision,
    InputQualityDecision,
    IntentRoutingDecision,
    PersistentSessionContext,
    RetrievalEligibility,
    RewriteDecision,
    RoutingDecision,
    TurnRuntimeState,
)
from ..domain.enums import IntentType
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
        or persistent.recent_entities
        or persistent.last_candidates
        or persistent.current_city
        or persistent.current_location
        or persistent.current_constraints
    )


def _context_has_candidate_anchor(persistent: PersistentSessionContext) -> bool:
    return bool(persistent.last_candidates or persistent.selected_shop_id or persistent.selected_shop_name)


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
    resolved_references: list[str] = []
    safeguards_triggered = list(route.safeguards_triggered)

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
                    "context_has_anchor": _context_has_anchor(persistent),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                },
            )
        elif _context_has_anchor(persistent) and _contains_any(normalized_query, ("然后", "还有", "那", "继续")):
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
                    "context_has_anchor": _context_has_anchor(persistent),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
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
                        "context_has_anchor": _context_has_anchor(persistent),
                        "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                    },
                ),
                reason="low_information",
                required_action="clarify",
                route_candidate="clarify",
            )

    if input_quality.kind == "ambiguous_reference":
        if _context_has_candidate_anchor(persistent) or _context_has_anchor(persistent):
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
                resolved_references=[str(persistent.selected_shop_name or persistent.current_topic or "")],
                route_reason="follow_up_reference",
                safeguards_triggered=safeguards_triggered,
                route_candidate="follow_up_reference",
                preferred_chunk_roles=["merchant_review_summary", "merchant_profile"],
                tool_candidates=[],
                clarification_question=None,
                extra={
                    "client_context": dict(client_context or {}),
                    "context_has_anchor": _context_has_anchor(persistent),
                    "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
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
                        "context_has_anchor": _context_has_anchor(persistent),
                        "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                    },
                ),
                reason="ambiguous_reference_without_context",
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
    return route


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
    if pack is None or not pack.items:
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
            response_mode="no_answer",
            is_valid=False,
            reason="no_evidence",
            fallback_reason="empty_pack",
        )

    items = list(pack.items)
    query_text = str(ctx.get("query_text") or ctx.get("raw_query") or ctx.get("query") or "").strip()
    target_shop_id = str(ctx.get("shop_id") or ctx.get("selected_shop_id") or "").strip() or None
    target_shop_name = str(ctx.get("shop_name") or ctx.get("selected_shop_name") or "").strip() or None
    target_city = str(ctx.get("city") or ctx.get("current_city") or "").strip() or None
    target_area = str(ctx.get("area") or ctx.get("current_area") or "").strip() or None
    target_category = str(ctx.get("category") or ctx.get("current_category") or "").strip() or None
    tool_result_present = bool(ctx.get("tool_result_present") or ctx.get("has_tool_result"))
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
    scores = sorted((float(item.score or 0.0) for item in items), reverse=True)
    top_score = scores[0] if scores else 0.0
    second_score = scores[1] if len(scores) > 1 else 0.0
    score_gap = max(top_score - second_score, 0.0)
    citation_available = any(bool(item.citation_chunk_id) for item in items)
    stale_evidence = any(bool(item.metadata.get("deprecated") or item.metadata.get("is_deprecated") or item.metadata.get("stale")) for item in items)

    chunk_types = [str(item.chunk_type or item.metadata.get("chunk_type") or "") for item in items]
    chunk_type_counter = Counter(chunk_types)
    dominant_chunk_type, dominant_chunk_count = chunk_type_counter.most_common(1)[0]
    topic_consistency = dominant_chunk_count / max(len(items), 1)

    parent_ids = [str(item.parent_chunk_id or item.metadata.get("parent_chunk_id") or item.document_id or "") for item in items if (item.parent_chunk_id or item.metadata.get("parent_chunk_id") or item.document_id)]
    parent_counter = Counter(parent_ids)
    entity_consistency = (parent_counter.most_common(1)[0][1] / max(len(parent_ids), 1)) if parent_ids else 0.0

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
            str(item.metadata.get("role") or item.chunk_type or "").lower() in {"review", "guide", "package", "coupon", "detail", "comparison", "concept", "business_evidence"}
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
    has_business_role = any(role in {"review", "guide", "package", "coupon", "detail", "comparison", "business_evidence"} for role in role_tokens)
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

    if not items:
        response_mode = "no_answer"
    elif not is_valid and (
        reason in {"shop_mismatch", "geo_mismatch"}
        or (specific_shop_question and not has_business_role)
        or (package_question and not tool_result_present and not has_business_role)
        or (pitfall_question and not has_business_role)
    ):
        response_mode = "no_answer"
    elif not is_valid:
        response_mode = "weak_answer"
    else:
        response_mode = "grounded"

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
        details={
            "dominant_chunk_type": dominant_chunk_type,
            "chunk_types": dict(chunk_type_counter),
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


def ensure_retrieval_plan(state: Any) -> Any:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return state
    if routing.blocked or str(routing.required_action).strip().lower() not in _RETRIEVAL_ACTIONS or not routing.should_retrieve:
        turn_extra = dict(turn.extra)
        turn_extra["retrieval_skipped_reason"] = routing.blocked_reason or routing.retrieval_skipped_reason or "retrieval_not_allowed"
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state
    current_plan = getattr(turn, "retrieval_plan", None)
    current_semantic_query = str(getattr(current_plan, "semantic_query", "") or "").strip()
    if current_plan is not None and current_semantic_query:
        if not getattr(current_plan, "preferred_chunk_roles", None) and routing.preferred_chunk_roles:
            current_plan = current_plan.model_copy(update={"preferred_chunk_roles": list(routing.preferred_chunk_roles), "extra": {**dict(current_plan.extra), "preferred_chunk_roles": list(routing.preferred_chunk_roles), "source": "synthesized"}})
            state["turn"] = turn.model_copy(update={"retrieval_plan": current_plan})
        return state
    plan = synthesize_retrieval_plan(routing, turn, state["persistent"], state["runtime"].client_context)
    if plan is None:
        turn_extra = dict(turn.extra)
        turn_extra["retrieval_skipped_reason"] = routing.route_reason or routing.required_action or "retrieval_plan_missing"
        if routing.required_action in {"rag_retrieval", "rag_plus_tool"} and routing.required_action != "clarify":
            routing = routing.model_copy(
                update={
                    "required_action": "clarify",
                    "should_retrieve": False,
                    "should_call_tool": False,
                    "should_rewrite_query": False,
                    "retrieval_skipped_reason": "retrieval_plan_missing",
                    "clarification_question": routing.clarification_question or "我还差一点信息，能再补充一下吗？",
                }
            )
            turn_extra["routing_decision"] = routing.model_dump(mode="json")
        state["turn"] = turn.model_copy(update={"extra": turn_extra, "routing_decision": routing})
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
    turn_extra = dict(turn.extra)
    turn_extra["retrieval_plan"] = plan.model_dump(mode="json")
    turn_extra["routing_decision"] = routing.model_dump(mode="json")
    state["turn"] = turn.model_copy(update={"retrieval_plan": plan, "routing_decision": routing, "extra": turn_extra})
    return state


def ensure_tool_plan(state: Any) -> Any:
    turn = state["turn"]
    routing = _routing_from_turn(turn)
    if routing is None:
        return state
    if routing.blocked or str(routing.required_action).strip().lower() not in {"tool_call", "rag_plus_tool"} or not routing.should_call_tool:
        turn_extra = dict(turn.extra)
        turn_extra["tool_plan_skipped_reason"] = routing.blocked_reason or routing.retrieval_skipped_reason or "tool_not_allowed"
        state["turn"] = turn.model_copy(update={"extra": turn_extra})
        return state
    current_plan = getattr(turn, "tool_plan", None)
    if current_plan is not None and getattr(current_plan, "should_execute", False) and getattr(current_plan, "tool_name", None):
        return state
    plan = synthesize_tool_selection(routing, turn, state["persistent"], state["runtime"].client_context)
    if plan is None:
        routing = routing.model_copy(
            update={
                "required_action": "clarify",
                "should_call_tool": False,
                "should_retrieve": False,
                "should_rewrite_query": False,
                "clarification_question": routing.clarification_question or "我还差一点信息，能再补充一下吗？",
            }
        )
        turn_extra = dict(turn.extra)
        turn_extra["routing_decision"] = routing.model_dump(mode="json")
        turn_extra["tool_plan_skipped_reason"] = "tool_plan_missing"
        state["turn"] = turn.model_copy(update={"routing_decision": routing, "extra": turn_extra})
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
    turn_extra = dict(turn.extra)
    turn_extra["tool_plan"] = plan.model_dump(mode="json")
    turn_extra["routing_decision"] = routing.model_dump(mode="json")
    state["turn"] = turn.model_copy(update={"tool_plan": plan, "routing_decision": routing, "extra": turn_extra})
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
