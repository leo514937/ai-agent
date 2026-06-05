from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.contracts import (
    RetrievalEligibility,
    RoutingDecision,
)
from ..routing_signals import (
    synthesize_retrieval_plan,
)
from ..routing_primitives import (
    _intent_allows_retrieval,
    _is_retrieval_action,
)
from .base import (
    _apply_phase1_routing_extra,
    _phase1_plan_flags,
    _routing_from_turn,
    _update_phase0_trace,
    _RETRIEVAL_ACTIONS,
    _RETRIEVAL_SCORE_THRESHOLD,
)
from .phase2_slots import build_clarification_question


def ensure_retrieval_plan(state: Any) -> Any:

    turn = state["turn"]

    routing = _routing_from_turn(turn)

    if routing is None:

        return state

    plan_facet_metadata_enabled = _phase1_plan_flags()

    if routing.blocked or str(routing.required_action).strip().lower() not in _RETRIEVAL_ACTIONS or not routing.should_retrieve:

        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)

        turn_extra["retrieval_skipped_reason"] = routing.blocked_reason or routing.retrieval_skipped_reason or "retrieval_not_allowed"

        state["turn"] = turn.model_copy(update={"extra": turn_extra})

        state = _update_phase0_trace(

            state,

            retrieval_plan_status="skipped",

            retrieval_plan_failure_reason=turn_extra["retrieval_skipped_reason"],

        )

        return state

    current_plan = getattr(turn, "retrieval_plan", None)

    current_semantic_query = str(getattr(current_plan, "semantic_query", "") or "").strip()

    if current_plan is not None and current_semantic_query:

        current_plan_extra = dict(current_plan.extra)

        for key in ("route_review_decision",):

            if key in routing.extra and key not in current_plan_extra:

                current_plan_extra[key] = routing.extra[key]

        if plan_facet_metadata_enabled:

            for key in ("required_facets", "optional_facets", "required_facets_source_constraints", "user_need"):

                if key in routing.extra and key not in current_plan_extra:

                    current_plan_extra[key] = routing.extra[key]

        if not getattr(current_plan, "preferred_chunk_roles", None) and routing.preferred_chunk_roles:

            current_plan_extra["preferred_chunk_roles"] = list(routing.preferred_chunk_roles)

            current_plan_extra["source"] = "synthesized"

            current_plan = current_plan.model_copy(

                update={

                    "preferred_chunk_roles": list(routing.preferred_chunk_roles),

                    "extra": current_plan_extra,

                }

            )

            state["turn"] = turn.model_copy(update={"retrieval_plan": current_plan})

        elif current_plan_extra != dict(current_plan.extra):

            current_plan = current_plan.model_copy(update={"extra": current_plan_extra})

            state["turn"] = turn.model_copy(update={"retrieval_plan": current_plan})

        state = _update_phase0_trace(

            state,

            retrieval_plan_status="reused",

            retrieval_plan_failure_reason=None,

        )

        return state

    plan = synthesize_retrieval_plan(routing, turn, state["persistent"], state["runtime"].client_context)

    if plan is None:

        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)

        turn_extra["retrieval_skipped_reason"] = routing.route_reason or routing.required_action or "retrieval_plan_missing"

        if routing.required_action in {"rag_retrieval", "rag_plus_tool"} and routing.required_action != "clarify":

            routing = routing.model_copy(

                update={

                    "required_action": "clarify",

                    "should_retrieve": False,

                    "should_call_tool": False,

                    "should_rewrite_query": False,

                    "retrieval_skipped_reason": "retrieval_plan_missing",

                    "clarification_question": routing.clarification_question

                    or build_clarification_question(routing.missing_slots, query_text=turn.raw_query),

                }

            )

            turn_extra["routing_decision"] = routing.model_dump(mode="json")

        state["turn"] = turn.model_copy(update={"extra": turn_extra, "routing_decision": routing})

        state = _update_phase0_trace(

            state,

            retrieval_plan_status="missing",

            retrieval_plan_failure_reason=turn_extra["retrieval_skipped_reason"],

        )

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

    turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)

    turn_extra["retrieval_plan"] = plan.model_dump(mode="json")

    turn_extra["routing_decision"] = routing.model_dump(mode="json")

    state["turn"] = turn.model_copy(update={"retrieval_plan": plan, "routing_decision": routing, "extra": turn_extra})

    state = _update_phase0_trace(

        state,

        retrieval_plan_status="synthesized",

        retrieval_plan_failure_reason=None,

    )

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

    if routing is None:

        return RetrievalEligibility(

            allowed=False,

            blocked=True,

            reason="missing_routing_decision",

            blocked_reason="missing_routing_decision",

            failure_reasons=["missing_routing_decision"],

        )

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
