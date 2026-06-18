from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class RouteRegistryEntry:
    route_id: str
    entry_node: str
    route_kind: str
    supported_intents: tuple[str, ...] = ()
    supported_actions: tuple[str, ...] = ()
    required_context: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    fallback_route: str = "clarification_node"
    safety_level: str = "normal"
    alias_names: tuple[str, ...] = ()


def _normalize_route_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("／", "/").replace("\\", "/")
    text = re.sub(r"\s+", "", text)
    text = text.replace("-", "_").replace("/", "_")
    return text


def _entry(
    route_id: str,
    *,
    entry_node: str,
    route_kind: str,
    supported_intents: Iterable[str] = (),
    supported_actions: Iterable[str] = (),
    required_context: Iterable[str] = (),
    preconditions: Iterable[str] = (),
    fallback_route: str = "clarification_node",
    safety_level: str = "normal",
    alias_names: Iterable[str] = (),
) -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=route_id,
        entry_node=entry_node,
        route_kind=route_kind,
        supported_intents=tuple(_normalize_route_token(item) for item in supported_intents if _normalize_route_token(item)),
        supported_actions=tuple(_normalize_route_token(item) for item in supported_actions if _normalize_route_token(item)),
        required_context=tuple(_normalize_route_token(item) for item in required_context if _normalize_route_token(item)),
        preconditions=tuple(_normalize_route_token(item) for item in preconditions if _normalize_route_token(item)),
        fallback_route=fallback_route,
        safety_level=safety_level,
        alias_names=tuple(_normalize_route_token(item) for item in alias_names if _normalize_route_token(item)),
    )


ROUTE_REGISTRY: dict[str, RouteRegistryEntry] = {
    "identity": _entry(
        "identity",
        entry_node="identity_answer",
        route_kind="top_level",
        supported_intents=("identity", "profile"),
        supported_actions=("direct_answer",),
        alias_names=("identity_answer", "profile_answer"),
        fallback_route="capability",
    ),
    "capability": _entry(
        "capability",
        entry_node="capability_answer",
        route_kind="top_level",
        supported_intents=("capability", "help"),
        supported_actions=("direct_answer",),
        alias_names=("capability_answer", "help_answer"),
        fallback_route="identity",
    ),
    "greeting": _entry(
        "greeting",
        entry_node="direct_chat_answer",
        route_kind="top_level",
        supported_intents=("greeting", "direct_chat"),
        supported_actions=("direct_answer",),
        alias_names=("direct_chat_answer", "hello", "hi", "thanks", "farewell"),
        fallback_route="local_life",
    ),
    "out_of_scope": _entry(
        "out_of_scope",
        entry_node="out_of_scope_response",
        route_kind="top_level",
        supported_intents=("unsafe", "math_or_code", "document_or_knowledge", "planning", "out_of_scope"),
        supported_actions=("direct_answer", "reject"),
        alias_names=("out_of_scope_response", "reject", "safety_reject_response"),
        fallback_route="local_life",
        safety_level="restricted",
    ),
    "local_life": _entry(
        "local_life",
        entry_node="query_merge_for_local_life",
        route_kind="top_level",
        supported_intents=(
            "local_life",
            "recommendation",
            "comparison",
            "package_or_coupon",
            "merchant_detail",
            "merchant_status",
            "distance_eta",
            "local_life_recommend",
        ),
        supported_actions=("tool_call", "recommendation", "direct_answer"),
        alias_names=("query_merge_for_local_life", "local_life_recommend", "merchant_status", "merchant_detail", "distance_eta"),
        fallback_route="clarify",
    ),
    "clarify": _entry(
        "clarify",
        entry_node="compose_answer",
        route_kind="execution",
        supported_actions=("clarify",),
        alias_names=("low_info", "question", "clarification_node"),
        fallback_route="clarify",
        safety_level="restricted",
    ),
    "direct": _entry(
        "direct",
        entry_node="compose_answer",
        route_kind="execution",
        supported_actions=("direct_answer", "memory_update", "no_op", "reject"),
        alias_names=("final_answer", "direct_chat", "direct_answer"),
        fallback_route="direct",
    ),
    "tool": _entry(
        "tool",
        entry_node="tool_subgraph",
        route_kind="execution",
        supported_actions=("tool_call",),
        required_context=("shop_context",),
        preconditions=("requires_shop_context",),
        alias_names=("single_shop_tool", "merchant_status_tool", "coupon_tool", "distance_tool", "transaction_tool"),
        fallback_route="clarify",
    ),
    "recommendation": _entry(
        "recommendation",
        entry_node="recommendation_subgraph",
        route_kind="execution",
        supported_intents=("recommendation", "comparison", "local_life_recommend"),
        supported_actions=("recommendation", "tool_call"),
        required_context=("candidate_context",),
        alias_names=("recommendation_tool", "comparison_tool", "local_life_recommend"),
        fallback_route="clarify",
    ),
}

_ROUTE_ALIAS_TO_ID: dict[str, str] = {}
for entry in ROUTE_REGISTRY.values():
    for token in (entry.route_id, entry.entry_node, *entry.supported_intents, *entry.supported_actions, *entry.alias_names):
        normalized = _normalize_route_token(token)
        if normalized:
            _ROUTE_ALIAS_TO_ID[normalized] = entry.route_id


def route_registry_snapshot() -> dict[str, dict[str, Any]]:
    return {route_id: asdict(entry) for route_id, entry in ROUTE_REGISTRY.items()}


def get_route_entry(route_id: str | None) -> RouteRegistryEntry | None:
    normalized = _normalize_route_token(route_id)
    if not normalized:
        return None
    canonical = _ROUTE_ALIAS_TO_ID.get(normalized, normalized)
    return ROUTE_REGISTRY.get(canonical)


def resolve_route_match(value: Any) -> dict[str, Any]:
    normalized = _normalize_route_token(value)
    if not normalized:
        return {
            "supported": False,
            "route_id": None,
            "entry_node": None,
            "route_kind": None,
            "matched_value": None,
            "fallback_route": "clarification_node",
            "safety_level": None,
        }
    route_id = _ROUTE_ALIAS_TO_ID.get(normalized)
    entry = ROUTE_REGISTRY.get(route_id) if route_id is not None else None
    if entry is None:
        return {
            "supported": False,
            "route_id": None,
            "entry_node": None,
            "route_kind": None,
            "matched_value": normalized,
            "fallback_route": "clarification_node",
            "safety_level": None,
        }
    return {
        "supported": True,
        "route_id": entry.route_id,
        "entry_node": entry.entry_node,
        "route_kind": entry.route_kind,
        "matched_value": normalized,
        "fallback_route": entry.fallback_route,
        "safety_level": entry.safety_level,
    }


def resolve_top_level_route(
    intent: Any,
    *,
    route_candidate: Any = None,
    route_candidates: Iterable[Any] | None = None,
) -> dict[str, Any]:
    candidates: list[Any] = []
    if intent is not None:
        candidates.append(intent)
    if route_candidate is not None:
        candidates.append(route_candidate)
    if route_candidates is not None:
        candidates.extend(list(route_candidates))

    best_match: dict[str, Any] | None = None
    for candidate in candidates:
        match = resolve_route_match(candidate)
        if not match.get("supported"):
            continue
        entry = get_route_entry(match["route_id"])
        if entry is None or entry.route_kind != "top_level":
            continue
        return {
            **match,
            "supported_intents": list(entry.supported_intents),
            "supported_actions": list(entry.supported_actions),
            "required_context": list(entry.required_context),
            "preconditions": list(entry.preconditions),
        }
        # pragma: no cover - return above
    if intent is not None:
        normalized_intent = _normalize_route_token(intent)
        for entry in ROUTE_REGISTRY.values():
            if entry.route_kind != "top_level":
                continue
            if normalized_intent in entry.supported_intents or normalized_intent == entry.route_id:
                return {
                    "supported": True,
                    "route_id": entry.route_id,
                    "entry_node": entry.entry_node,
                    "route_kind": entry.route_kind,
                    "matched_value": normalized_intent,
                    "fallback_route": entry.fallback_route,
                    "safety_level": entry.safety_level,
                    "supported_intents": list(entry.supported_intents),
                    "supported_actions": list(entry.supported_actions),
                    "required_context": list(entry.required_context),
                    "preconditions": list(entry.preconditions),
                }
    if route_candidate is not None:
        best_match = resolve_route_match(route_candidate)
        if best_match.get("supported"):
            entry = get_route_entry(best_match["route_id"])
            if entry is not None and entry.route_kind == "top_level":
                return {
                    **best_match,
                    "supported_intents": list(entry.supported_intents),
                    "supported_actions": list(entry.supported_actions),
                    "required_context": list(entry.required_context),
                    "preconditions": list(entry.preconditions),
                }
    fallback = get_route_entry("local_life")
    assert fallback is not None
    return {
        "supported": True,
        "route_id": fallback.route_id,
        "entry_node": fallback.entry_node,
        "route_kind": fallback.route_kind,
        "matched_value": _normalize_route_token(route_candidate or intent or fallback.route_id),
        "fallback_route": fallback.fallback_route,
        "safety_level": fallback.safety_level,
        "supported_intents": list(fallback.supported_intents),
        "supported_actions": list(fallback.supported_actions),
        "required_context": list(fallback.required_context),
        "preconditions": list(fallback.preconditions),
    }


def resolve_execution_route(
    required_action: Any = None,
    *,
    route_candidate: Any = None,
    top_level_intent: Any = None,
    route_candidates: Iterable[Any] | None = None,
) -> dict[str, Any]:
    candidates: list[Any] = []
    if required_action is not None:
        candidates.append(required_action)
    if route_candidate is not None:
        candidates.append(route_candidate)
    if top_level_intent is not None:
        candidates.append(top_level_intent)
    if route_candidates is not None:
        candidates.extend(list(route_candidates))

    for candidate in candidates:
        normalized = _normalize_route_token(candidate)
        if not normalized:
            continue
        for entry in ROUTE_REGISTRY.values():
            if entry.route_kind != "execution":
                continue
            if normalized in entry.supported_actions or normalized in entry.alias_names or normalized == entry.route_id:
                return {
                    "supported": True,
                    "route_id": entry.route_id,
                    "entry_node": entry.entry_node,
                    "route_kind": entry.route_kind,
                    "matched_value": normalized,
                    "fallback_route": entry.fallback_route,
                    "safety_level": entry.safety_level,
                    "supported_intents": list(entry.supported_intents),
                    "supported_actions": list(entry.supported_actions),
                    "required_context": list(entry.required_context),
                    "preconditions": list(entry.preconditions),
                }

    normalized_intent = _normalize_route_token(top_level_intent)
    for entry in ROUTE_REGISTRY.values():
        if entry.route_kind != "execution":
            continue
        if normalized_intent and (normalized_intent in entry.supported_intents or normalized_intent in entry.alias_names):
            return {
                "supported": True,
                "route_id": entry.route_id,
                "entry_node": entry.entry_node,
                "route_kind": entry.route_kind,
                "matched_value": normalized_intent,
                "fallback_route": entry.fallback_route,
                "safety_level": entry.safety_level,
                "supported_intents": list(entry.supported_intents),
                "supported_actions": list(entry.supported_actions),
                "required_context": list(entry.required_context),
                "preconditions": list(entry.preconditions),
            }

    if normalized_intent in {"recommendation", "comparison"}:
        entry = get_route_entry("recommendation")
        if entry is not None:
            return {
                "supported": True,
                "route_id": entry.route_id,
                "entry_node": entry.entry_node,
                "route_kind": entry.route_kind,
                "matched_value": normalized_intent,
                "fallback_route": entry.fallback_route,
                "safety_level": entry.safety_level,
                "supported_intents": list(entry.supported_intents),
                "supported_actions": list(entry.supported_actions),
                "required_context": list(entry.required_context),
                "preconditions": list(entry.preconditions),
            }

    fallback_route = "direct"
    if _normalize_route_token(required_action) in {"clarify"}:
        fallback_route = "clarify"
    fallback_entry = get_route_entry(fallback_route) or get_route_entry("direct")
    assert fallback_entry is not None
    return {
        "supported": False,
        "route_id": fallback_entry.route_id,
        "entry_node": fallback_entry.entry_node,
        "route_kind": fallback_entry.route_kind,
        "matched_value": _normalize_route_token(required_action or route_candidate or top_level_intent),
        "fallback_route": fallback_entry.fallback_route,
        "safety_level": fallback_entry.safety_level,
        "supported_intents": list(fallback_entry.supported_intents),
        "supported_actions": list(fallback_entry.supported_actions),
        "required_context": list(fallback_entry.required_context),
        "preconditions": list(fallback_entry.preconditions),
    }


def route_registry_hits(*values: Any) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for value in values:
        if isinstance(value, Mapping):
            candidates = [
                value.get("route_candidate"),
                value.get("top_level_intent"),
                value.get("required_action"),
            ]
        elif isinstance(value, (list, tuple, set)):
            candidates = list(value)
        else:
            candidates = [value]
        for candidate in candidates:
            match = resolve_route_match(candidate)
            key = (match.get("route_id"), match.get("matched_value"))
            if key in seen:
                continue
            if match.get("supported"):
                hits.append(match)
                seen.add(key)
    return hits
