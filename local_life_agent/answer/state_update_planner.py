"""State update planner for the single-shop coupon flow."""

from __future__ import annotations


def plan_state_update(
    turn_context: dict, task_type: str, resolve_status: str
) -> dict:
    """Compute the session state delta for this turn.

    Stage 10 does not implement multi-turn recovery, so the planner
    only records the resolved current shop when available.
    """
    turn_context = turn_context or {}
    resolved_shop = turn_context.get("resolved_shop") or {}
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()

    set_fields = {}
    if resolve_status == "RESOLVED" and isinstance(resolved_shop, dict):
        set_fields["current_shop"] = resolved_shop

    return {
        "set_fields": set_fields,
        "clear_fields": [],
        "task_type": task_type,
        "resolve_status": resolve_status,
    }
