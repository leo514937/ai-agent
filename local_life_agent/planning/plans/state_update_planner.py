"""State update planner for session state writes.

Separates two orthogonal status systems:
- ToolResultStatus (result_status): execution outcome of a tool call
- ResolveShopResult.status (resolve_shop_status): outcome of shop resolution

These must NEVER be conflated. A tool can succeed (result_status=ok) but the
shop resolution can fail (resolve_shop_status=NOT_FOUND).
"""

from __future__ import annotations

from typing import Any

from ...domain.enums import TaskType
from ...tools.result_semantics import TOOL_FAILURE_STATUSES, get_tool_result_status


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _plan_required_by_call_id(plan: Any | None) -> dict[str, bool]:
    result: dict[str, bool] = {}
    plan_dict = _to_dict(plan)
    for call in plan_dict.get("tool_calls", []) or []:
        call_dict = _to_dict(call)
        call_id = str(call_dict.get("call_id", "")).strip()
        if call_id:
                result[call_id] = bool(call_dict.get("required", True))
    return result


def plan_state_update(
    turn_context: dict,
    task_type: str,
    resolve_shop_status: str,
    pending_check_result: str | None = None,
) -> dict:
    """Compute the session state delta for this turn.

    Args:
        turn_context: Full turn context dict.
        task_type: Normalised task type string.
        resolve_shop_status: Outcome of shop resolution — one of
            RESOLVED, AMBIGUOUS, LOW_CONFIDENCE, NOT_FOUND, or "".
            This is ResolveShopResult.status, NOT ToolResultStatus.
        pending_check_result: Optional pending-clarification check outcome.

    Returns:
        State update directive dict with set_fields, clear_fields, etc.
    """
    turn_context = turn_context or {}
    resolved_target = turn_context.get("resolved_target") or turn_context.get("resolved_shop")
    resolved_target_dict = _to_dict(resolved_target)
    resolved_shop = resolved_target_dict.get("resolved_shop") or resolved_target_dict.get("shop") or {}
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()
    if not isinstance(resolved_shop, dict):
        resolved_shop = {}

    pending = turn_context.get("pending_clarification")
    pending_dict = _to_dict(pending) if pending is not None else None
    recommendation_list = turn_context.get("last_recommendation_list")
    if recommendation_list is None:
        recommendation_list = []
    goal_dict = _to_dict(turn_context.get("local_life_goal_draft"))
    candidate_source = str(goal_dict.get("candidate_source", "") or "").strip()
    active_turn_result = _to_dict(turn_context.get("active_turn_result"))
    active_turn_route = str(active_turn_result.get("route", "") or "").strip()
    reference_resolution_source = str(turn_context.get("reference_resolution_source", "") or "").strip()
    comparison_targets = turn_context.get("comparison_targets")
    if comparison_targets is None:
        comparison_targets = []
    resolution_stage = str(turn_context.get("resolution_stage", "") or "").strip()
    comparison_result = turn_context.get("comparison_result")
    evidence_pack = turn_context.get("evidence_pack")
    if comparison_result is None and evidence_pack is not None:
        comparison_result = _to_dict(evidence_pack).get("comparison_matrix")
    tool_results = turn_context.get("tool_result_set") or turn_context.get("tool_results") or {}
    execution_plan_dict = _to_dict(turn_context.get("validated_plan") or turn_context.get("execution_plan"))
    has_tool_calls = bool(execution_plan_dict.get("tool_calls"))
    required_by_call_id = _plan_required_by_call_id(
        turn_context.get("validated_plan") or turn_context.get("execution_plan")
    )

    # Tool execution failure detection — reads ONLY ToolResultStatus.
    tool_failed = False
    if isinstance(tool_results, dict):
        observed_call_ids = {str(call_id) for call_id in tool_results.keys()}
        required_call_ids = {call_id for call_id, required in required_by_call_id.items() if required}
        for call_id, result in tool_results.items():
            required = required_by_call_id.get(str(call_id), True)
            if required and get_tool_result_status(_to_dict(result)) in TOOL_FAILURE_STATUSES:
                tool_failed = True
                break
        if has_tool_calls and required_call_ids and not tool_failed:
            missing_required_calls = required_call_ids - observed_call_ids
            if missing_required_calls:
                tool_failed = True
    elif has_tool_calls:
        tool_failed = True

    set_fields: dict[str, Any] = {}
    clear_fields: list[str] = []

    if tool_failed:
        return {
            "set_fields": {},
            "clear_fields": ["pending_clarification", "current_shop"],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if pending_check_result in {"invalid", "out_of_range"}:
        return {
            "set_fields": {},
            "clear_fields": [],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if pending_check_result in {"expired", "cancelled", "topic_switch"}:
        return {
            "set_fields": {},
            "clear_fields": ["pending_clarification"],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if pending_dict is not None and not tool_failed:
        set_fields["pending_clarification"] = pending_dict
        clear_fields = [field for field in clear_fields if field != "pending_clarification"]
        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    # Shop resolution branching — reads ResolveShopResult.status.
    # CANDIDATE_SET_RESOLVED is a valid "resolved" state (multi-candidate with no single target).
    # It follows the same RESOLVED paths for comparison/recommendation, but
    # single_shop_query must NEVER reach CANDIDATE_SET_RESOLVED (it would be AMBIGUOUS).
    is_resolved = resolve_shop_status in ("RESOLVED", "CANDIDATE_SET_RESOLVED")
    if resolve_shop_status == "AMBIGUOUS":
        set_fields["pending_clarification"] = pending_dict
        return {
            "set_fields": set_fields,
            "clear_fields": [],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if is_resolved:
        if task_type in (TaskType.single_shop_query.value, TaskType.coupon_query.value):
            # Only write current_shop for true RESOLVED (single target), never CANDIDATE_SET_RESOLVED
            if resolve_shop_status == "RESOLVED":
                should_set_current_shop = not tool_failed
                if resolved_shop and should_set_current_shop:
                    set_fields["current_shop"] = resolved_shop
            clear_fields.extend(["pending_clarification", "last_recommendation_list"])
        elif task_type == TaskType.recommendation.value:
            set_fields["last_recommendation_list"] = recommendation_list
            # CANDIDATE_SET_RESOLVED (multi-candidate): NEVER write current_shop
            # RESOLVED (single target): write current_shop only with reference_resolution_source
            if resolve_shop_status == "RESOLVED" and resolution_stage != "candidate_set_resolved" and resolved_shop and reference_resolution_source:
                set_fields["current_shop"] = resolved_shop
                clear_fields.append("pending_clarification")
            else:
                clear_fields.extend(["pending_clarification", "current_shop"])
        elif task_type == TaskType.comparison.value:
            if comparison_targets:
                set_fields["comparison_targets"] = comparison_targets
            if comparison_result is not None:
                set_fields["comparison_result"] = comparison_result
                clear_fields.append("pending_clarification")
            elif pending_dict is not None:
                set_fields["pending_clarification"] = pending_dict
            else:
                clear_fields.append("pending_clarification")
            clear_fields.append("current_shop")
        else:
            clear_fields.append("pending_clarification")

        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if resolve_shop_status in {"NOT_FOUND", ""}:
        return {
            "set_fields": {},
            "clear_fields": [],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    return {
        "set_fields": set_fields,
        "clear_fields": clear_fields,
        "task_type": task_type,
        "resolve_shop_status": resolve_shop_status,
        "pending_check_result": pending_check_result,
    }
