from __future__ import annotations

from typing import Any

from ...domain.contracts import (
    RetrievalEligibility,
)
from ..routing_signals import (
    synthesize_tool_selection,
)
from .base import (
    _apply_phase1_routing_extra,
    _phase1_plan_flags,
    _routing_from_turn,
    _update_phase0_trace,
    _RETRIEVAL_SCORE_THRESHOLD,
)
from .phase2_slots import build_clarification_question


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

    if routing is None:

        return RetrievalEligibility(

            allowed=False,

            blocked=True,

            reason="missing_routing_decision",

            blocked_reason="missing_routing_decision",

            failure_reasons=["missing_routing_decision"],

        )

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
