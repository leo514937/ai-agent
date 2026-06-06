from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ....domain.contracts import RoutingDecision


_CLARIFY_ACTIONS = {"clarify", "reject"}
_SIMPLE_TOP_LEVELS = {"identity", "capability", "direct_chat", "out_of_scope"}
_SIMPLE_ACTIONS = {"direct_answer", "memory_update", "no_op"}
_COMPLEX_ROUTE_CANDIDATES = {"recommendation", "local_life.nearby_recommend", "nearby_recommend", "local_life_recommend"}


@dataclass
class ComplexityRoutingResult:
    execution_mode: str = "simple"
    reason: str = ""
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "reason": self.reason,
            "signals": list(self.signals),
        }


def _count_non_empty(values: Any) -> int:
    if not isinstance(values, list):
        return 0
    count = 0
    for item in values:
        if isinstance(item, Mapping):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            count += 1
    return count


def route_execution_mode(routing: RoutingDecision | None) -> ComplexityRoutingResult:
    if routing is None:
        return ComplexityRoutingResult(execution_mode="simple", reason="no_routing_decision", signals=["missing_routing"])

    action = str(routing.required_action or "").strip().lower()
    extra = dict(getattr(routing, "extra", {}) or {})
    top_level_intent = str(extra.get("top_level_intent") or "").strip().lower()
    route_candidate = str(routing.route_candidate or "").strip().lower()
    route_review = extra.get("route_review_decision")
    if isinstance(route_review, Mapping):
        semantic_route = route_review.get("semantic_route")
        if isinstance(semantic_route, Mapping):
            route_candidate = str(semantic_route.get("route_candidate") or route_candidate or "").strip().lower()

    required_facets = extra.get("required_facets")
    required_facet_count = _count_non_empty(required_facets)
    required_slots = len([slot for slot in list(getattr(routing.intent, "required_slots", []) or []) if str(slot or "").strip()])
    mixed_tool_retrieval = bool(routing.should_call_tool and routing.should_retrieve)
    recommendation_like = bool(
        route_candidate in _COMPLEX_ROUTE_CANDIDATES
        or "recommend" in route_candidate
        or top_level_intent == "recommendation"
        or bool(extra.get("recommendation_mode"))
    )

    if action in _CLARIFY_ACTIONS or routing.blocked:
        return ComplexityRoutingResult(
            execution_mode="clarify",
            reason=str(routing.blocked_reason or routing.route_reason or "clarify"),
            signals=["clarify_action", *(["blocked"] if routing.blocked else [])],
        )

    if top_level_intent in _SIMPLE_TOP_LEVELS or action in _SIMPLE_ACTIONS:
        return ComplexityRoutingResult(
            execution_mode="simple",
            reason=top_level_intent or action or "simple_route",
            signals=[token for token in (top_level_intent, action) if token],
        )

    if recommendation_like and (mixed_tool_retrieval or required_facet_count >= 2 or required_slots >= 3):
        return ComplexityRoutingResult(
            execution_mode="complex",
            reason="multi_stage_recommendation",
            signals=["recommendation_like", "multi_stage"],
        )

    if mixed_tool_retrieval or required_facet_count >= 2 or required_slots >= 2:
        return ComplexityRoutingResult(
            execution_mode="standard",
            reason="multi_facet_or_multi_capability",
            signals=[
                *(["tool_and_rag"] if mixed_tool_retrieval else []),
                *(["multi_facet"] if required_facet_count >= 2 else []),
                *(["multi_slot"] if required_slots >= 2 else []),
            ],
        )

    if recommendation_like:
        return ComplexityRoutingResult(
            execution_mode="standard",
            reason="recommendation_like",
            signals=["recommendation_like"],
        )

    if routing.should_call_tool or routing.should_retrieve:
        return ComplexityRoutingResult(
            execution_mode="simple",
            reason="single_capability",
            signals=[
                *(["tool"] if routing.should_call_tool else []),
                *(["rag"] if routing.should_retrieve else []),
            ],
        )

    return ComplexityRoutingResult(
        execution_mode="simple",
        reason="default_simple",
        signals=["default"],
    )
