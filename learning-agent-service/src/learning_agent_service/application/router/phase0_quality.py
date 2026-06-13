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
    check_query_safety,
)
from ...local_life.hybrid_router import get_hybrid_router


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
    input_quality = build_input_quality(raw_query)

    # 使用 HybridRouter 获取路由决策
    router = get_hybrid_router()
    session_context = None
    if persistent is not None:
        session_context = {
            "session_id": getattr(persistent, "session_id", None),
            "current_shop": getattr(persistent, "current_shop", None),
            "recent_shops": getattr(persistent, "recent_entities", []) or [],
            "last_intent": getattr(persistent, "last_intent", None),
        }
    
    decision, trace = router.route(
        raw_query,
        session_context=session_context,
        client_context=dict(client_context or {}),
    )
    
    # Map intent to old format
    intent_mapping = {
        "greeting": "identity",
        "detail": "local_life",
        "recommend": "local_life",
        "compare": "local_life",
        "coupon": "local_life",
        "open_status": "local_life",
        "navigation": "local_life",
        "booking": "local_life",
        "refund": "local_life",
        "clarification": "local_life",
        "out_of_scope": "out_of_scope",
        "unsafe": "unsafe",
        "identity": "identity",
        "capability": "capability",
        "realtime": "local_life",
    }
    
    intent_name = intent_mapping.get(decision.intent, "local_life")
    requires_current_shop = decision.route in {"merchant_reasoning"} and not decision.slots.get("shop_name")
    requires_candidate_context = decision.route == "compare_multi_parent" and not decision.slots.get("shop_name")
    
    top_level_intent = {
        "intent": intent_name,
        "domain": decision.domain,
        "confidence": decision.confidence,
        "reason": decision.reasoning,
        "route_candidate": decision.route,
        "matched_signals": [decision.route],
        "requires_current_shop": requires_current_shop,
        "requires_candidate_context": requires_candidate_context,
        "slots": decision.slots,
        "trace_id": trace.trace_id,
    }

    # 安全检查（优先级最高）
    safety_result = check_query_safety(raw_query, client_context=dict(client_context or {}))
    if safety_result.blocked:
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
                "top_level_intent": top_level_intent.get("intent", "local_life"),
                "top_level_intent_reason": top_level_intent.get("reason", "fallback_to_hybrid_router"),
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

    # 使用 HybridRouter 的决策结果
    llm_slots = top_level_intent.get("slots", {})
    route_type = top_level_intent.get("route_candidate", "merchant_reasoning")
    intent_name = top_level_intent.get("intent", "local_life")
    confidence = top_level_intent.get("confidence", 0.85)
    reason = top_level_intent.get("reason", "")

    # 根据 route_type 决定路由行为
    route_mapping = {
        "realtime_tool": ("tool_call", True, False),
        "compare_multi_parent": ("rag_retrieval", True, False),
        "structured_first": ("rag_retrieval", True, False),
        "merchant_reasoning": ("rag_retrieval", True, False),
        "guide_rule_rag": ("rag_retrieval", True, False),
        "general_chat": ("direct_answer", False, False),
    }

    required_action, should_retrieve, should_call_tool = route_mapping.get(
        route_type, ("rag_retrieval", True, False)
    )

    # 判断是否需要澄清
    missing_slots = []
    clarification_question = None
    if top_level_intent.get("requires_current_shop"):
        missing_slots = ["shop_name"]
        clarification_question = "你想查哪家店？"
        required_action = "clarify"
    elif top_level_intent.get("requires_candidate_context"):
        missing_slots = ["shop_name"]
        clarification_question = "你想比较哪家店？"
        required_action = "clarify"
    # 对于 realtime_tool 类型的查询，如果没有 shop_name 且没有 current_shop，需要澄清
    elif (
        route_type == "realtime_tool"
        and not llm_slots.get("shop_name")
        and not persistent.current_shop
        and not persistent.selected_shop_id
    ):
        missing_slots = ["shop_name"]
        clarification_question = "你想查哪家店？请告诉我具体店名。"
        required_action = "clarify"

    # 构建 allowed_routes / forbidden_routes
    allowed_routes = []
    forbidden_routes = []
    if required_action in {"rag_retrieval", "tool_call"}:
        allowed_routes = [required_action]
    elif required_action == "rag_plus_tool":
        allowed_routes = ["rag_retrieval", "tool_call", "rag_plus_tool"]
    elif required_action == "direct_answer":
        allowed_routes = ["direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]

    route = RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=normalized_query,
        domain=top_level_intent.get("domain", "local_life"),
        confidence=confidence,
        input_quality=input_quality,
        intent=IntentRoutingDecision(
            name=intent_name,
            confidence=confidence,
            required_slots=list(llm_slots.keys()) + missing_slots,
            missing_slots=missing_slots,
            allowed_routes=allowed_routes,
            forbidden_routes=forbidden_routes,
        ),
        required_action=required_action,
        blocked=False,
        should_rewrite_query=should_retrieve or should_call_tool,
        should_retrieve=should_retrieve,
        should_call_tool=should_call_tool,
        should_use_memory=required_action not in {"clarify", "reject", "no_op"},
        should_persist_memory=required_action not in {"clarify", "reject", "no_op"},
        should_vectorize_memory=required_action not in {"clarify", "reject", "no_op"},
        should_emit_retrieval_events=should_retrieve,
        missing_slots=missing_slots,
        resolved_references=[],
        route_reason=reason or f"hybrid_router:{route_type}",
        safeguards_triggered=[],
        route_candidate=intent_name,
        preferred_chunk_roles=[],
        tool_candidates=[],
        clarification_question=clarification_question,
        extra={
            "client_context": dict(client_context or {}),
            "context_has_anchor": _context_has_anchor(persistent),
            "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
            "top_level_intent": intent_name,
            "top_level_intent_reason": reason,
            "hybrid_router_route": route_type,
            "hybrid_router_slots": llm_slots,
        },
    )
    route = _annotate_execution_mode(route)

    # Follow-up reference detection: if query is ambiguous/low-information and there's
    # a context anchor (current_shop), override intent to follow_up_reference
    has_anchor = _context_has_anchor(persistent) or _client_context_has_anchor(client_context)
    has_candidate_anchor = _context_has_candidate_anchor(persistent) or _client_context_has_candidate_anchor(client_context)
    has_any_anchor = has_anchor or has_candidate_anchor

    is_follow_up_ref = False
    if input_quality.kind == "ambiguous_reference" and has_any_anchor:
        is_follow_up_ref = True
    elif input_quality.kind == "low_information" and has_any_anchor and _contains_any(normalized_query, ("然后", "还有", "那", "继续", "这家", "那个", "这个")):
        is_follow_up_ref = True

    if is_follow_up_ref:
        context_shop = persistent.current_shop or persistent.selected_shop_name or persistent.current_topic
        route = route.model_copy(
            update={
                "intent": IntentRoutingDecision(
                    name="follow_up_reference",
                    confidence=0.62 if input_quality.kind == "ambiguous_reference" else 0.58,
                    required_slots=[],
                    missing_slots=[],
                    allowed_routes=["rag_retrieval"],
                    forbidden_routes=["tool_call"],
                ),
                "route_candidate": "follow_up_reference",
                "should_rewrite_query": True,
                "should_retrieve": True,
                "should_call_tool": False,
                "resolved_references": [context_shop] if context_shop else [],
                "extra": {
                    **dict(route.extra or {}),
                    "follow_up_reference": True,
                    "context_shop": context_shop,
                },
            }
        )

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

    # Apply post-routing review
    route = _apply_route_review(route, raw_query=raw_query, persistent=persistent, client_context=client_context)

    # Nearby clarification: when user has a current shop but asks about "nearby" recommendations,
    # clarify whether they want recommendations for the current shop or nearby shops
    # This must happen AFTER _apply_route_review to prevent the review from overriding it
    if (
        not is_follow_up_ref
        and persistent.current_shop
        and route.required_action in {"rag_retrieval", "rag_plus_tool"}
        and _contains_any(normalized_query, ("附近", "周边", "旁边", "周围"))
        and not _contains_any(normalized_query, ("这家店", "这家", "那个店"))
    ):
        clarification = f"你是想了解{persistent.current_shop}（这家店）的推荐菜，还是想看看当前位置附近的推荐菜？"
        route = route.model_copy(
            update={
                "required_action": "clarify",
                "blocked": True,
                "route_candidate": "clarify",
                "clarification_question": clarification,
                "should_retrieve": False,
                "should_call_tool": False,
                "safeguards_triggered": list(dict.fromkeys(list(route.safeguards_triggered) + ["nearby_shop_clarification"])),
                "extra": {
                    **dict(route.extra or {}),
                    "nearby_shop_clarification": True,
                },
            }
        )

    return _annotate_execution_mode(route)
