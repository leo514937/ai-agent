from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain.contracts import (
    PersistentSessionContext,
    PlanStep,
    RoutingDecision,
    TaskPlan,
)
from .base import (
    _apply_phase1_routing_extra,
    _phase3_flags,
    _routing_from_turn,
    _update_phase3_trace,
)


_TASK_PLAN_COMPLEX_INTENTS = {"local_life_recommend", "merchant_detail", "package_or_coupon", "comparison"}
_TASK_PLAN_STATIC_FACETS = {"scene_fit", "recommendation_reason", "shop_detail"}
_TASK_PLAN_DYNAMIC_FACETS = {"coupon", "open_status", "distance_eta", "package"}


def _task_plan_required_facets(routing: RoutingDecision | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:

    if routing is None:

        return [], []

    extra = dict(getattr(routing, "extra", {}) or {})

    required_facets = [dict(item) for item in extra.get("required_facets") or [] if isinstance(item, Mapping)]

    optional_facets = [dict(item) for item in extra.get("optional_facets") or [] if isinstance(item, Mapping)]

    return required_facets, optional_facets



def _task_plan_enabled(turn: Any, routing: RoutingDecision | None) -> tuple[bool, str]:

    if not _phase3_flags():

        return False, "task_plan_disabled"

    if routing is None:

        return False, "routing_missing"

    plan_mode = str(getattr(turn, "execution_mode", "") or "").strip().lower()
    if plan_mode == "plan_execute":
        return True, "plan_execute_override"

    action = str(getattr(routing, "required_action", "") or "").strip().lower()

    if routing.blocked and plan_mode != "plan_execute":

        return False, "routing_blocked"

    if action != "rag_plus_tool" and plan_mode != "plan_execute":

        return False, "not_rag_plus_tool"

    required_facets, optional_facets = _task_plan_required_facets(routing)

    if not required_facets:

        return False, "missing_required_facets"

    if list(getattr(routing, "missing_slots", []) or []) and plan_mode != "plan_execute":

        return False, "missing_slots"

    if not (routing.should_retrieve and routing.should_call_tool):

        return False, "not_a_combined_task"

    intent_name = str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower()

    if intent_name not in _TASK_PLAN_COMPLEX_INTENTS:

        return False, "intent_not_complex"

    facet_names = {

        str(facet.get("name") or "").strip().lower()

        for facet in [*required_facets, *optional_facets]

        if str(facet.get("name") or "").strip()

    }

    if len(facet_names) < 4:

        return False, "facet_count_too_low"

    if not ({"coupon", "open_status"} <= facet_names):

        return False, "missing_dynamic_combo"

    if not (facet_names & _TASK_PLAN_STATIC_FACETS):

        return False, "insufficient_facet_mix"

    return True, "complex_local_life_combo"



def _task_plan_step_payload(turn: Any, persistent: PersistentSessionContext) -> dict[str, Any]:

    slots = dict(getattr(turn, "slots", {}) or {}) if isinstance(getattr(turn, "slots", {}), Mapping) else {}

    location = persistent.current_location if isinstance(persistent.current_location, Mapping) else {}

    preferences = slots.get("preferences")

    avoid = slots.get("avoid")

    return {

        "query": getattr(turn, "raw_query", ""),

        "city": persistent.current_city,

        "area": location.get("area") if isinstance(location, Mapping) else None,

        "location": dict(location) if isinstance(location, Mapping) else location,

        "category": slots.get("category"),

        "scene": slots.get("scene"),

        "preferences": list(preferences or []) if isinstance(preferences, (list, tuple, set)) else preferences,

        "avoid": list(avoid or []) if isinstance(avoid, (list, tuple, set)) else avoid,

        "shop_id": persistent.selected_shop_id or slots.get("shop_id"),

        "shop_name": persistent.current_shop or persistent.selected_shop_name or slots.get("shop_name"),

        "shop_query": slots.get("shop_query") or slots.get("shop") or slots.get("name"),

        "price": slots.get("price"),

        "limit": 10,

    }



def _build_task_plan(turn: Any, routing: RoutingDecision, persistent: PersistentSessionContext) -> TaskPlan | None:

    enabled, reason = _task_plan_enabled(turn, routing)

    required_facets, optional_facets = _task_plan_required_facets(routing)

    if not enabled:

        return TaskPlan(

            enabled=False,

            trigger_reason=reason,

            summary="",

            route_candidate=routing.route_candidate,

            task_complexity="simple",

            execution_mode="auto",

            can_fallback_to_legacy=True,

            required_facets=required_facets,

            optional_facets=optional_facets,

            steps=[],

            failure_reason=reason,

            extra={"source": "skipped"},

        )



    step_payload = _task_plan_step_payload(turn, persistent)

    facet_names = {

        str(facet.get("name") or "").strip().lower()

        for facet in [*required_facets, *optional_facets]

        if str(facet.get("name") or "").strip()

    }

    steps: list[PlanStep] = [

        PlanStep(

            step_id="resolve_location",

            goal="整理本轮任务的地理与店铺上下文。",

            expected_output="可用于后续规划的地点上下文。",

            input_payload=step_payload,

            risk_level="low",

        )

    ]

    if facet_names & {"scene_fit", "recommendation_reason", "shop_detail", "location", "category"}:

        steps.append(

            PlanStep(

                step_id="search_restaurants",

                goal="筛选符合场景与品类的候选门店。",

                expected_output="候选门店列表。",

                allowed_tools=["search_restaurants"],

                input_payload={

                    "query": step_payload["query"],

                    "city": step_payload["city"],

                    "area": step_payload["area"],

                    "category": step_payload["category"],

                    "scene": step_payload["scene"],

                    "preferences": step_payload["preferences"],

                    "avoid": step_payload["avoid"],

                    "limit": step_payload["limit"],

                },

                risk_level="low",

            )

        )

    if facet_names & {"scene_fit", "recommendation_reason", "shop_detail"}:

        steps.append(

            PlanStep(

                step_id="retrieve_scene_evidence",

                goal="拉取与店铺场景、环境和推荐理由相关的静态证据。",

                expected_output="静态 RAG 证据。",

                allowed_tools=["get_shop_detail"],

                input_payload={

                    "shop_id": step_payload["shop_id"],

                    "shop_name": step_payload["shop_name"],

                    "query": step_payload["query"],

                },

                risk_level="low",

            )

        )

    if "open_status" in facet_names:

        steps.append(

            PlanStep(

                step_id="check_open_status",

                goal="确认当前营业状态。",

                expected_output="营业状态结果。",

                allowed_tools=["check_open_status"],

                input_payload={

                    "shop_id": step_payload["shop_id"],

                    "shop_name": step_payload["shop_name"],

                    "open_hours": None,

                },

                risk_level="low",

            )

        )

    if "coupon" in facet_names:

        steps.append(

            PlanStep(

                step_id="get_coupon_list",

                goal="确认当前可用优惠券或套餐。",

                expected_output="优惠券列表。",

                allowed_tools=["get_coupon_list"],

                input_payload={

                    "shop_id": step_payload["shop_id"],

                    "shop_name": step_payload["shop_name"],

                    "limit": 10,

                },

                risk_level="low",

            )

        )

    if facet_names & _TASK_PLAN_STATIC_FACETS and facet_names & _TASK_PLAN_DYNAMIC_FACETS:

        steps.append(

            PlanStep(

                step_id="entity_join",

                goal="把静态证据和动态工具结果按同一实体对齐。",

                expected_output="实体一致的候选集合。",

                input_payload={

                    "required_facets": required_facets,

                    "optional_facets": optional_facets,

                },

                risk_level="low",

            )

        )

    if len(steps) > 1:

        steps.append(

            PlanStep(

                step_id="rank_candidates",

                goal="排序并选出最适合当前问题的候选门店。",

                expected_output="排序后的候选及推荐理由。",

                input_payload={

                    "query": step_payload["query"],

                    "required_facets": required_facets,

                },

                risk_level="low",

            )

        )

    steps.append(

        PlanStep(

            step_id="compose_answer",

            goal="基于 TaskPlan 结果生成最终回答。",

            expected_output="最终回答文本。",

            input_payload={

                "query": step_payload["query"],

                "task_plan_mode": "plan_execute",

            },

            risk_level="low",

        )

    )

    summary = f"复杂本地生活组合任务，覆盖 {', '.join(sorted(facet_names))}。"

    return TaskPlan(

        enabled=True,

        trigger_reason=reason,

        summary=summary,

        route_candidate=routing.route_candidate,

        task_complexity="complex",

        execution_mode="plan_execute",

        can_fallback_to_legacy=True,

        required_facets=required_facets,

        optional_facets=optional_facets,

        steps=steps,

        failure_reason=None,

        extra={

            "task_plan_step_count": len(steps),

            "task_plan_step_ids": [step.step_id for step in steps],

        },

    )



def ensure_task_plan(state: Any) -> Any:

    turn = state["turn"]

    routing = _routing_from_turn(turn)

    if routing is None:

        return state



    explicit_plan = list(getattr(turn, "plan", []) or [])
    if explicit_plan and getattr(turn, "task_plan", None) is None:
        task_plan = TaskPlan(
            enabled=True,
            trigger_reason="explicit_plan",
            summary=str(getattr(turn, "raw_query", "") or "").strip(),
            route_candidate=getattr(routing, "route_candidate", None),
            task_complexity="complex",
            execution_mode=str(getattr(turn, "execution_mode", "plan_execute") or "plan_execute"),
            can_fallback_to_legacy=True,
            required_facets=list(getattr(routing, "extra", {}).get("required_facets") or []),
            optional_facets=list(getattr(routing, "extra", {}).get("optional_facets") or []),
            steps=explicit_plan,
            failure_reason=None,
            extra={
                "source": "explicit_plan",
                "task_plan_step_count": len(explicit_plan),
                "task_plan_step_ids": [step.step_id for step in explicit_plan],
            },
        )
        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)
        turn_extra["task_plan"] = task_plan.model_dump(mode="json")
        turn_extra["task_plan_status"] = "reused"
        turn_extra["task_plan_failure_reason"] = None
        state["turn"] = turn.model_copy(
            update={
                "task_plan": task_plan,
                "plan": list(task_plan.steps),
                "task_complexity": getattr(task_plan, "task_complexity", "complex"),
                "execution_mode": getattr(task_plan, "execution_mode", "plan_execute"),
                "extra": turn_extra,
            }
        )
        state = _update_phase3_trace(
            state,
            task_plan_status="reused",
            task_plan_failure_reason=None,
            task_plan_enabled=True,
            task_plan_trigger_reason="explicit_plan",
            task_plan_step_count=len(getattr(task_plan, "steps", []) or []),
            task_plan_step_ids=[step.step_id for step in getattr(task_plan, "steps", []) or []],
            task_plan_route_candidate=getattr(task_plan, "route_candidate", None),
        )
        return state

    task_plan = getattr(turn, "task_plan", None)

    if task_plan is not None and getattr(task_plan, "steps", None):

        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)

        turn_extra["task_plan"] = task_plan.model_dump(mode="json")

        turn_extra["task_plan_status"] = "reused"

        turn_extra["task_plan_failure_reason"] = None

        state["turn"] = turn.model_copy(

            update={

                "task_plan": task_plan,

                "plan": list(task_plan.steps),

                "task_complexity": getattr(task_plan, "task_complexity", "complex"),

                "execution_mode": getattr(task_plan, "execution_mode", "plan_execute"),

                "extra": turn_extra,

            }

        )

        state = _update_phase3_trace(

            state,

            task_plan_status="reused",

            task_plan_failure_reason=None,

            task_plan_enabled=bool(getattr(task_plan, "enabled", False)),

            task_plan_trigger_reason=getattr(task_plan, "trigger_reason", None),

            task_plan_step_count=len(getattr(task_plan, "steps", []) or []),

            task_plan_step_ids=[step.step_id for step in getattr(task_plan, "steps", []) or []],

            task_plan_route_candidate=getattr(task_plan, "route_candidate", None),

        )

        return state



    task_plan = _build_task_plan(turn, routing, state["persistent"])

    if task_plan is None or not getattr(task_plan, "enabled", False) or not getattr(task_plan, "steps", None):

        reason = getattr(task_plan, "failure_reason", "task_plan_unavailable") if task_plan is not None else "task_plan_unavailable"

        turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)

        turn_extra["task_plan_status"] = "skipped"

        turn_extra["task_plan_failure_reason"] = reason

        state["turn"] = turn.model_copy(update={"extra": turn_extra})

        state = _update_phase3_trace(

            state,

            task_plan_status="skipped",

            task_plan_failure_reason=reason,

            task_plan_enabled=False,

            task_plan_step_count=0,

            task_plan_step_ids=[],

            task_plan_route_candidate=routing.route_candidate,

        )

        return state



    turn_extra = _apply_phase1_routing_extra(dict(turn.extra), routing)

    turn_extra["task_plan"] = task_plan.model_dump(mode="json")

    turn_extra["task_plan_status"] = "synthesized"

    turn_extra["task_plan_failure_reason"] = None

    turn_extra["task_plan_step_count"] = len(task_plan.steps)

    turn_extra["task_plan_step_ids"] = [step.step_id for step in task_plan.steps]

    state["turn"] = turn.model_copy(

        update={

            "task_plan": task_plan,

            "plan": list(task_plan.steps),

            "task_complexity": task_plan.task_complexity,

            "execution_mode": task_plan.execution_mode,

            "extra": turn_extra,

        }

    )

    state = _update_phase3_trace(

        state,

        task_plan_status="synthesized",

        task_plan_failure_reason=None,

        task_plan_enabled=True,

        task_plan_trigger_reason=task_plan.trigger_reason,

        task_plan_step_count=len(task_plan.steps),

        task_plan_step_ids=[step.step_id for step in task_plan.steps],

        task_plan_route_candidate=task_plan.route_candidate,

        task_plan_required_facets=task_plan.required_facets,

        task_plan_optional_facets=task_plan.optional_facets,

    )

    return state
