from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.contracts import (
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
)
from ...local_life.query_rewriter import _CITY_NAMES as _LOCAL_LIFE_CITY_NAMES
from ..routing_primitives import (
    _client_context_has_anchor,
    _client_context_has_candidate_anchor,
    _compact,
    _contains_any,
    _context_has_anchor,
    _context_has_candidate_anchor,
    _continue_previous_topic_route,
    _conversation_recap_route,
    _detect_memory_update,
    _detect_response_kind,
    _detect_session_only_preference,
    _looks_like_unserviceable_location,
    _mark_routing_blocked,
    _pending_clarification_follow_up_route,
    _route_decision_from_semantic_route,
    _semantic_route_for_query,
    build_input_quality,
    normalize_query,
)
from .base import _LOCAL_LIFE_QUERY_TOKENS
from .phase2_slots import build_clarification_question
from .phase3_review import _apply_route_review

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

        missing_slots = list(route.missing_slots)

        clarification_question = route.clarification_question

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

