from __future__ import annotations



import re

import unicodedata


from collections.abc import Mapping, Sequence

from dataclasses import dataclass

from typing import Any




from ..domain.contracts import (

    InputQualityDecision,

    IntentRoutingDecision,

    PersistentSessionContext,

    RoutingDecision,

)


from ..local_life.query_rewriter import _CITY_NAMES as _LOCAL_LIFE_CITY_NAMES

from ..rag.domain_rules import _BUILTIN_DOMAIN_RULES

from .routing_signals import (

    DomainSignalRegistry,

    SemanticRoutingDraft,

    route_semantic_query,

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

# 问候/感谢/身份关键词已移至 domain_rules.py 统一管理

_RETRIEVAL_ACTIONS = {"rag_retrieval", "rag_plus_tool"}

_NON_RETRIEVAL_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject", "tool_call"}

_DIRECT_ACTIONS = {"direct_answer", "clarify", "memory_update", "no_op", "reject"}

_RETRIEVAL_SCORE_THRESHOLD = 0.55

_PHASE0_TRACE_KEY = "phase0_trace"

_PHASE1_TRACE_KEY = "phase1_trace"

_PHASE2_TRACE_KEY = "phase2_trace"

_PHASE3_TRACE_KEY = "phase3_trace"

_PHASE4_TRACE_KEY = "phase4_trace"

_LOCAL_LIFE_QUERY_TOKENS = ("附近", "周边", "推荐", "火锅", "餐厅", "饭店", "店", "优惠券", "券", "团购", "套餐")

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



    reference_tokens = ("这家", "那家", "这个店", "那个店", "第二个", "第二家", "第一个")
    if _contains_any(compact, reference_tokens) or _contains_any(normalized, reference_tokens):

        return InputQualityDecision(

            kind="ambiguous_reference",

            is_valid=True,

            reason="ambiguous_reference",

            score=0.58,

            signals=["reference_token"],

        )



    recommend_tokens = ("附近", "周边", "推荐", "好吃的", "有什么好的")
    if _contains_any(compact, recommend_tokens) or _contains_any(normalized, recommend_tokens):

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



    incomplete_recommend_tokens = ("附近", "周边", "推荐", "好吃的", "有什么好的")
    if _contains_any(compact, incomplete_recommend_tokens) or _contains_any(normalized, incomplete_recommend_tokens):

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

    if _contains_any(normalized, _BUILTIN_DOMAIN_RULES.profile_patterns):

        return "profile", "profile_query"

    if _contains_any(normalized, _BUILTIN_DOMAIN_RULES.greeting_tokens) or _contains_any(compact, _BUILTIN_DOMAIN_RULES.greeting_tokens) or _contains_any(lowered, _BUILTIN_DOMAIN_RULES.greeting_tokens):

        return "greeting", "greeting"

    if _contains_any(normalized, _BUILTIN_DOMAIN_RULES.thanks_tokens) or _contains_any(compact, _BUILTIN_DOMAIN_RULES.thanks_tokens) or _contains_any(lowered, _BUILTIN_DOMAIN_RULES.thanks_tokens):

        return "thanks", "thanks"

    return None, None





def _detect_memory_update(raw_query: str) -> bool:

    return False





def _detect_session_only_preference(raw_query: str) -> bool:

    return False





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






__all__ = [name for name in globals() if not name.startswith('__')]
