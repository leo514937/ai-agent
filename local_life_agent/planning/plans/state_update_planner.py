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
    comparison_targets = turn_context.get("comparison_targets")
    if comparison_targets is None:
        comparison_targets = []
    comparison_result = turn_context.get("comparison_result")
    tool_results = turn_context.get("tool_result_set") or turn_context.get("tool_results") or {}
    required_by_call_id = _plan_required_by_call_id(
        turn_context.get("validated_plan") or turn_context.get("execution_plan")
    )

    # Tool execution failure detection — reads ONLY ToolResultStatus.
    tool_failed = False
    if isinstance(tool_results, dict):
        for call_id, result in tool_results.items():
            required = required_by_call_id.get(str(call_id), True)
            if required and get_tool_result_status(_to_dict(result)) in TOOL_FAILURE_STATUSES:
                tool_failed = True
                break
    elif str(resolve_shop_status or "") == "RESOLVED" and not required_by_call_id:
        tool_failed = False

    set_fields: dict[str, Any] = {}
    clear_fields: list[str] = []

    if tool_failed:
        return {
            "set_fields": {},
            "clear_fields": ["pending_clarification"],
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

    if pending_check_result == "expired":
        return {
            "set_fields": {},
            "clear_fields": ["pending_clarification"],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    # Shop resolution branching — reads ONLY ResolveShopResult.status.
    if resolve_shop_status == "AMBIGUOUS":
        set_fields["pending_clarification"] = pending_dict
        return {
            "set_fields": set_fields,
            "clear_fields": [],
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if resolve_shop_status == "RESOLVED":
        if task_type in (TaskType.single_shop_query.value, TaskType.coupon_query.value):
            if resolved_shop:
                set_fields["current_shop"] = resolved_shop
            clear_fields.extend(["pending_clarification", "last_recommendation_list"])
        elif task_type == TaskType.recommendation.value:
            set_fields["last_recommendation_list"] = recommendation_list
            clear_fields.extend(["pending_clarification", "current_shop"])
        elif task_type == TaskType.comparison.value:
            if comparison_targets:
                set_fields["comparison_targets"] = comparison_targets
            if comparison_result is not None:
                set_fields["comparison_result"] = comparison_result
            clear_fields.append("pending_clarification")
        else:
            clear_fields.append("pending_clarification")

        return {
            "set_fields": set_fields,
            "clear_fields": clear_fields,
            "task_type": task_type,
            "resolve_shop_status": resolve_shop_status,
            "pending_check_result": pending_check_result,
        }

    if pending_check_result == "topic_switch":
        return {
            "set_fields": {},
            "clear_fields": ["pending_clarification"],
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
