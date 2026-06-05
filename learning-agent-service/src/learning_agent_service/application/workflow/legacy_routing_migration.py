from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain.contracts import PersistentSessionContext, RoutingDecision

_LEGACY_DIRECT_RESPONSE_TO_ACTION = {
    "greeting": "direct_answer",
    "thanks": "direct_answer",
    "farewell": "direct_answer",
    "profile": "direct_answer",
    "memory_update": "memory_update",
    "empty": "reject",
    "low_info": "clarify",
}

_LEGACY_ROUTE_TO_ACTION = {
    "clarify": "clarify",
    "direct_answer": "direct_answer",
    "retrieve_then_answer": "rag_retrieval",
    "tool_then_answer": "tool_call",
    "tool_then_rag": "rag_plus_tool",
    "rag_retrieval": "rag_retrieval",
    "rag_plus_tool": "rag_plus_tool",
    "memory_update": "memory_update",
    "memory_only": "memory_update",
    "reject": "reject",
    "no_op": "no_op",
}


def _legacy_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _legacy_action(
    *,
    route_decision: str | None,
    direct_response_kind: str | None,
    route_candidate: str | None,
) -> str | None:
    for candidate in (route_decision, route_candidate):
        normalized = str(candidate or "").strip().lower()
        if normalized in _LEGACY_ROUTE_TO_ACTION:
            return _LEGACY_ROUTE_TO_ACTION[normalized]
    normalized_kind = str(direct_response_kind or "").strip().lower()
    return _LEGACY_DIRECT_RESPONSE_TO_ACTION.get(normalized_kind)


def legacy_to_routing_decision(
    turn: Any,
    persistent: PersistentSessionContext,
    routing: RoutingDecision,
) -> RoutingDecision:
    """Fold legacy route metadata into RoutingDecision without letting it drive branching."""

    extra = dict(getattr(turn, "extra", {}) or {})
    cached_routing = _legacy_mapping(extra.get("routing_decision"))
    legacy_route_decision = (
        getattr(turn, "route_decision", None)
        or extra.get("route_decision")
        or cached_routing.get("route_decision")
    )
    legacy_route_reason = (
        getattr(turn, "route_reason", None)
        or extra.get("route_reason")
        or cached_routing.get("route_reason")
    )
    legacy_direct_response_kind = (
        getattr(turn, "direct_response_kind", None)
        or extra.get("direct_response_kind")
        or cached_routing.get("direct_response_kind")
        or extra.get("clarification_response_kind")
        or extra.get("response_kind")
    )
    route_candidate = (
        getattr(routing, "route_candidate", None)
        or extra.get("route_candidate")
        or cached_routing.get("route_candidate")
    )
    legacy_action = _legacy_action(
        route_decision=legacy_route_decision,
        direct_response_kind=legacy_direct_response_kind,
        route_candidate=route_candidate if isinstance(route_candidate, str) else None,
    )

    update: dict[str, Any] = {
        "extra": {
            **dict(routing.extra),
            "legacy_route_decision": legacy_route_decision,
            "legacy_route_reason": legacy_route_reason,
            "legacy_direct_response_kind": legacy_direct_response_kind,
            "legacy_route_candidate": route_candidate,
            "legacy_migration_source": "load_context",
            "legacy_session_current_topic": persistent.current_topic,
        }
    }
    if legacy_route_reason and not routing.route_reason:
        update["route_reason"] = str(legacy_route_reason)
    if legacy_action and routing.required_action in {"no_op", "direct_answer"}:
        update["required_action"] = legacy_action
        update["should_retrieve"] = legacy_action in {"rag_retrieval", "rag_plus_tool"}
        update["should_call_tool"] = legacy_action in {"tool_call", "rag_plus_tool"}
        update["should_rewrite_query"] = legacy_action in {"rag_retrieval", "rag_plus_tool"}
        update["should_use_memory"] = legacy_action not in {"clarify", "reject", "no_op"}
        update["should_persist_memory"] = legacy_action not in {"clarify", "reject", "no_op"}
        update["should_vectorize_memory"] = legacy_action not in {"clarify", "reject", "no_op"}
        update["should_emit_retrieval_events"] = legacy_action in {"rag_retrieval", "rag_plus_tool"}
    return routing.model_copy(update=update)
