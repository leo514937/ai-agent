from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain.contracts import (
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
)
from ..routing_primitives import (
    _client_context_has_anchor,
    _client_context_has_candidate_anchor,
    _contains_any,
    _context_has_anchor,
    _context_has_candidate_anchor,
    _continue_previous_topic_route,
    _conversation_recap_route,
    _detect_response_kind,
    _detect_session_only_preference,
    _looks_like_unserviceable_location,
    _mark_routing_blocked,
    _pending_clarification_follow_up_route,
    build_input_quality,
    normalize_query,
)
from .phase3_review import _apply_route_review
from .stages import (
    route_execution_mode,
    check_hard_guard,
    check_query_safety,
    merge_local_life_query_context,
    check_signal_policy,
    parse_query_with_llm,
    resolve_target_merchant,
    route_top_level_intent,
)


def _annotate_execution_mode(decision: RoutingDecision) -> RoutingDecision:
    execution_mode = route_execution_mode(decision)
    extra = dict(getattr(decision, "extra", {}) or {})
    extra["execution_mode"] = execution_mode.execution_mode
    extra["execution_mode_reason"] = execution_mode.reason
    extra["execution_mode_signals"] = list(execution_mode.signals)
    return decision.model_copy(update={"execution_mode": execution_mode.execution_mode, "extra": extra})


def build_initial_routing_decision(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    client_context: Mapping[str, Any] | None = None,
    model_gateway: Any | None = None,
) -> RoutingDecision:
    normalized_query = normalize_query(raw_query)
    top_level_intent = route_top_level_intent(raw_query, persistent=persistent, client_context=client_context)
    safety_result = check_query_safety(raw_query, client_context=dict(client_context or {}))

    if safety_result.blocked:
        input_quality = build_input_quality(raw_query)
        decision = RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalized_query,
            domain="general",
            confidence=safety_result.confidence,
            input_quality=input_quality,
            intent=IntentRoutingDecision(
                name="unsafe",
                confidence=safety_result.confidence,
                allowed_routes=["reject"],
                forbidden_routes=["rag_retrieval", "tool_call", "direct_answer"],
            ),
            required_action="reject",
            blocked=True,
            blocked_reason=safety_result.reason,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=safety_result.reason,
            missing_slots=[],
            resolved_references=[],
            route_reason=safety_result.reason or "unsafe",
            safeguards_triggered=[safety_result.reason] if safety_result.reason else ["unsafe"],
            route_candidate=safety_result.route_candidate or "reject",
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                "top_level_intent": top_level_intent.intent,
                "top_level_intent_reason": top_level_intent.reason,
                "query_safety": safety_result.to_dict(),
            },
        )
        return _annotate_execution_mode(
            _mark_routing_blocked(
            decision,
            reason=safety_result.reason or "unsafe",
            required_action="reject",
            route_candidate=safety_result.route_candidate or "reject",
            )
        )

    # 1. Stage 1: Hard Guard
    guard_result = check_hard_guard(raw_query, persistent, client_context)
    if guard_result.blocked:
        input_quality = build_input_quality(raw_query)
        route_candidate = guard_result.route_candidate or "reject"
        required_action = guard_result.required_action or "reject"

        decision = RoutingDecision(
            raw_query=str(raw_query or ""),
            normalized_query=normalized_query,
            domain="general" if guard_result.reason != "incomplete_recommendation_missing_context" else "local_life",
            confidence=0.0,
            input_quality=input_quality,
            intent=IntentRoutingDecision(
                name="invalid_input" if guard_result.reason in ("empty_input", "pure_punctuation", "repeated_noise") else (guard_result.reason or "invalid_input"),
                confidence=0.0,
                allowed_routes=[required_action],
                forbidden_routes=["rag_retrieval", "tool_call"],
            ),
            required_action=required_action,
            blocked=True,
            blocked_reason=guard_result.reason,
            should_rewrite_query=False,
            should_retrieve=False,
            should_call_tool=False,
            should_use_memory=False,
            should_persist_memory=False,
            should_vectorize_memory=False,
            should_emit_retrieval_events=False,
            retrieval_skipped_reason=guard_result.reason,
            missing_slots=[],
            resolved_references=[],
            route_reason=guard_result.reason or "blocked",
            safeguards_triggered=[guard_result.reason] if guard_result.reason else [],
            route_candidate=route_candidate,
            preferred_chunk_roles=[],
            tool_candidates=[],
            clarification_question=None,
            extra={
                "client_context": dict(client_context or {}),
                "context_has_anchor": _context_has_anchor(persistent),
                "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
                "top_level_intent": top_level_intent.intent,
                "top_level_intent_reason": top_level_intent.reason,
                "query_safety": safety_result.to_dict(),
            },
        )

        if guard_result.reason == "incomplete_recommendation_missing_context":
            decision.intent.required_slots = ["city", "scene", "category"]
            decision.intent.missing_slots = ["city", "scene", "category"]
            decision.missing_slots = ["city", "scene", "category"]
            decision.clarification_question = "你更想找哪个城市、哪类场景的店？"
        elif guard_result.reason == "incomplete_recommendation_ambiguous_with_current_shop":
            decision.intent.required_slots = ["shop_name", "location"]
            decision.intent.missing_slots = ["shop_name", "location"]
            decision.missing_slots = ["shop_name", "location"]
            decision.clarification_question = "你是想看这家店推荐菜，还是看当前位置附近的推荐？"
        elif guard_result.reason == "ambiguous_reference_without_context":
            decision.clarification_question = "你指哪一家/哪一个？" if ("个" in raw_query or "家" in raw_query) else "你指哪家店？"
        elif guard_result.reason == "low_information":
            decision.clarification_question = "你想具体查哪一项？"

        return _annotate_execution_mode(
            _mark_routing_blocked(
            decision,
            reason=guard_result.reason or "blocked",
            required_action=required_action,
            route_candidate=route_candidate,
            )
        )

    # 2. Stage 2: Signal Policy
    signal_result = check_signal_policy(raw_query, persistent, client_context)

    # 3. Stage 3: LLM Semantic Parser
    parser_result = parse_query_with_llm(raw_query, persistent, signal_result, model_gateway)

    merged_query = merge_local_life_query_context(
        raw_query,
        persistent=persistent,
        parser_slots=parser_result.slots,
        client_context=client_context,
        target_reference=getattr(parser_result.target_shop, "shop_name", None) if parser_result.target_shop else None,
    )

    # 4. Stage 4: Target Resolution
    target_result = resolve_target_merchant(
        raw_query,
        parser_result,
        signal_result,
        persistent,
        client_context,
        merged_query=merged_query,
    )

    # 5. Build RoutingDecision from Stage 1-4 outputs
    input_quality = build_input_quality(raw_query)

    # Context-aware follow-up/continuation overrides
    has_anchor = _context_has_anchor(persistent) or _client_context_has_anchor(client_context)
    has_candidate_anchor = _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context)
    has_any_anchor = has_anchor or has_candidate_anchor

    is_follow_up_ref = False
    if input_quality.kind == "ambiguous_reference" and has_any_anchor:
        is_follow_up_ref = True
    elif input_quality.kind == "low_information" and has_any_anchor and _contains_any(normalized_query, ("然后", "还有", "那", "继续")):
        is_follow_up_ref = True

    if is_follow_up_ref:
        parser_result.intent = "follow_up_reference"
        parser_result.confidence = 0.62 if input_quality.kind == "ambiguous_reference" else 0.58
        parser_result.needs_rag = True
        parser_result.needs_tool = False
        parser_result.needs_clarify = False
        parser_result.facet_needs = ["merchant_review_summary", "merchant_profile"]

    allowed_routes = []
    forbidden_routes = []
    if parser_result.needs_tool and parser_result.needs_rag:
        allowed_routes = ["rag_retrieval", "tool_call", "rag_plus_tool"]
    elif parser_result.needs_tool:
        allowed_routes = ["tool_call"]
        forbidden_routes = ["rag_retrieval"]
    elif parser_result.needs_rag:
        allowed_routes = ["rag_retrieval"]
        forbidden_routes = ["tool_call"]
    elif parser_result.intent == "chit_chat":
        allowed_routes = ["direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    elif parser_result.intent == "memory_update":
        allowed_routes = ["memory_update", "direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    else:
        allowed_routes = ["direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]

    missing_slots = list(parser_result.missing_slots) if parser_result.needs_clarify else []
    if target_result.missing:
        required_action = "clarify"
        if "shop_name" not in missing_slots:
            missing_slots.append("shop_name")

    intent_decision = IntentRoutingDecision(
        name=parser_result.intent,
        confidence=parser_result.confidence,
        required_slots=list(parser_result.slots.keys()) + missing_slots,
        missing_slots=missing_slots,
        allowed_routes=allowed_routes,
        forbidden_routes=forbidden_routes,
    )

    required_action = "direct_answer"
    if parser_result.needs_clarify or target_result.missing:
        required_action = "clarify"
    elif parser_result.needs_tool and parser_result.needs_rag:
        required_action = "rag_plus_tool"
    elif parser_result.needs_tool:
        required_action = "tool_call"
    elif parser_result.needs_rag:
        required_action = "rag_retrieval"
    elif parser_result.intent == "memory_update":
        required_action = "memory_update"

    tool_candidates = []
    for cand in signal_result.candidates:
        if cand.intent_name == parser_result.intent and cand.tool_candidates:
            tool_candidates = list(cand.tool_candidates)
            break
    if not tool_candidates and signal_result.candidates:
        tool_candidates = list(signal_result.candidates[0].tool_candidates)

    resolved_references = list(target_result.resolved_references)
    if is_follow_up_ref:
        context_shop = persistent.current_shop or persistent.selected_shop_name or persistent.current_topic
        if context_shop:
            resolved_references = [context_shop]

    clarification_question = target_result.clarification_question

    should_retrieve = parser_result.needs_rag
    should_call_tool = parser_result.needs_tool
    should_rewrite_query = parser_result.needs_rag or parser_result.needs_tool or parser_result.intent in {"merchant_detail", "local_life_recommend", "follow_up_reference"}


    route_candidate = parser_result.intent
    if signal_result.candidates and parser_result.intent != "follow_up_reference":
        route_candidate = signal_result.candidates[0].matched_signal

    route = RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=normalized_query,
        domain="local_life" if parser_result.intent in ("local_life_recommend", "merchant_detail", "merchant_status", "package_or_coupon", "merchant_pitfall", "follow_up_reference") else "general",
        confidence=parser_result.confidence,
        input_quality=input_quality,
        intent=intent_decision,
        required_action=required_action,
        blocked=False,
        should_rewrite_query=should_rewrite_query,
        should_retrieve=should_retrieve,
        should_call_tool=should_call_tool,
        should_use_memory=required_action not in {"clarify", "reject", "no_op"},
        should_persist_memory=required_action not in {"clarify", "reject", "no_op"},
        should_vectorize_memory=required_action not in {"clarify", "reject", "no_op"},
        should_emit_retrieval_events=should_retrieve,
        missing_slots=missing_slots,
        resolved_references=resolved_references,
        route_reason=parser_result.reason or f"semantic:{parser_result.intent}",
        safeguards_triggered=[],
        route_candidate=route_candidate,
        preferred_chunk_roles=parser_result.facet_needs,
        tool_candidates=tool_candidates,
        clarification_question=clarification_question,
        extra={
            "client_context": dict(client_context or {}),
            "context_has_anchor": _context_has_anchor(persistent) or _client_context_has_anchor(client_context),
            "context_has_candidate_anchor": _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context),
            "current_shop": persistent.current_shop or persistent.selected_shop_name,
            "top_level_intent": top_level_intent.intent,
            "top_level_intent_reason": top_level_intent.reason,
            "query_safety": safety_result.to_dict(),
            "query_merge": merged_query.to_dict(),
        },
    )
    route = _annotate_execution_mode(route)

    # Apply clarification, recap, and topic continuation helpers from routing_primitives
    pending_follow_up_route = _pending_clarification_follow_up_route(
        raw_query,
        persistent,
        input_quality=input_quality,
        client_context=client_context,
        base_route=route,
    )
    if pending_follow_up_route is not None:
        route = pending_follow_up_route

    recap_route = _conversation_recap_route(
        raw_query,
        persistent,
        input_quality=input_quality,
        client_context=client_context,
    )
    if recap_route is not None:
        route = recap_route

    continue_route = _continue_previous_topic_route(
        raw_query,
        persistent,
        input_quality=input_quality,
        client_context=client_context,
    )
    if continue_route is not None:
        route = continue_route

    # Handle location unserviceable/unavailable as a fallback
    if _looks_like_unserviceable_location(raw_query):
        route = route.model_copy(
            update={
                "domain": "local_life",
                "confidence": 0.88,
                "intent": IntentRoutingDecision(
                    name="location_unavailable",
                    confidence=0.88,
                    required_slots=[],
                    missing_slots=[],
                    allowed_routes=["direct_answer"],
                    forbidden_routes=["rag_retrieval", "tool_call"],
                ),
                "required_action": "direct_answer",
                "should_rewrite_query": False,
                "should_retrieve": False,
                "should_call_tool": False,
                "should_use_memory": False,
                "should_persist_memory": False,
                "should_vectorize_memory": False,
                "should_emit_retrieval_events": False,
                "missing_slots": [],
                "resolved_references": [],
                "route_reason": "unserviceable_location",
                "safeguards_triggered": list(dict.fromkeys(list(route.safeguards_triggered) + ["unserviceable_location"])),
                "route_candidate": "location_unavailable",
                "extra": {
                    **dict(route.extra or {}),
                    "unserviceable_location": True,
                },
            }
        )

    # Greeting/thanks/profile override
    response_kind, response_reason = _detect_response_kind(raw_query)
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
            missing_slots=[],
            resolved_references=[],
            route_reason=response_reason or response_kind,
            safeguards_triggered=[],
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

    # Session only preference override
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

    # 6. Apply post-routing review
    route = _apply_route_review(route, raw_query=raw_query, persistent=persistent, client_context=client_context)
    return _annotate_execution_mode(route)
