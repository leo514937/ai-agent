from __future__ import annotations

from collections.abc import Mapping

from typing import Any

from ...domain.contracts import (
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
)

from ..routing_primitives import (
    _client_context_has_candidate_anchor,
    _context_has_anchor,
    _context_has_candidate_anchor,
    _looks_like_unserviceable_location,
    _semantic_route_for_query,
    normalize_query,
)

from .base import _phase1_flags

from .phase1_intent import (
    _build_required_facets,
    _recommended_action_for_facets,
    _route_review_reason,
    _route_review_priority,
)


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

            input_quality=routing.input_quality,

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

    from learning_agent_service.local_life.clarification_strategy import ClarificationStrategy

    has_pronoun = any(p in raw_query for p in ("这家", "那家", "它", "该店", "此店", "这店", "这个店", "那个店", "这间", "刚才那家", "这商家", "这个商家", "刚才那个"))

    has_resolved_ref = bool(

        persistent.current_topic

        or persistent.current_shop

        or persistent.selected_shop_id

        or persistent.recent_entities

        or persistent.last_candidates

        or _client_context_has_candidate_anchor(client_context)

    )

    should_clarify, missing_slot, clarify_reason = ClarificationStrategy.should_clarify_target_shop(
        raw_query=raw_query,
        is_low_info=False,
        has_explicit_shop_hint=False,
        has_pronoun=has_pronoun,
        has_resolved_ref=has_resolved_ref,
    )

    if should_clarify:

        return RoutingDecision(

            raw_query=str(raw_query or ""),

            normalized_query=normalize_query(raw_query),

            domain="local_life",

            confidence=0.9,

            input_quality=routing.input_quality,

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



    review_decision: dict[str, Any] = {

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
