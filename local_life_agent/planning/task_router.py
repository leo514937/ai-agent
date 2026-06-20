"""Task router for the single-shop coupon flow."""

from __future__ import annotations

from typing import Any

from ..domain.enums import TaskType


def route_task(semantic_frame: dict, resolved_target: dict) -> str:
    """Determine the task type for this turn.

    Stage 10 only supports the coupon-query path. If the frame has a
    resolved shop and the semantic intent is coupon-oriented, route to
    ``coupon_query``; otherwise keep the request in a clarification path.
    """
    if not isinstance(semantic_frame, dict):
        return TaskType.clarification_reply.value

    task_type = semantic_frame.get("task_type")
    if isinstance(task_type, TaskType):
        task_type = task_type.value

    resolved_status = ""
    if isinstance(resolved_target, dict):
        resolved_status = resolved_target.get("status", "")

    if task_type == TaskType.recommendation.value:
        return TaskType.recommendation.value

    if task_type == TaskType.comparison.value:
        return TaskType.comparison.value if resolved_status == "RESOLVED" else TaskType.clarification_reply.value

    if resolved_status != "RESOLVED":
        return TaskType.clarification_reply.value

    if task_type in (TaskType.coupon_query.value, TaskType.single_shop_query.value):
        return task_type

    facets = semantic_frame.get("facets") or []
    if facets:
        return TaskType.single_shop_query.value

    return TaskType.clarification_reply.value
