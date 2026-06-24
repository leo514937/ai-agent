"""Task router compatibility shell for P2.

P2: ``task_router`` is degraded to a compatibility shell.
The authoritative routing is now handled by ``GoalPlanner`` + ``GoalReview``.

This file is kept for backward compatibility during the transition period.
It should not be used as the primary routing source for new code.
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import TaskType


def route_task(semantic_frame: dict, resolved_target: dict) -> str:
    """Determine the legacy task type for backward compat.

    P2: This is a compatibility shell.  The authoritative routing is
    handled by ``GoalPlanner`` + ``GoalReview``.  This function is kept
    for code paths that still reference ``task_type`` directly.

    Returns a TaskType string to satisfy existing downstream consumers.
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

    if task_type == TaskType.coupon_query.value:
        return TaskType.single_shop_query.value
    if task_type == TaskType.single_shop_query.value:
        return task_type

    facets = semantic_frame.get("facets") or []
    if facets:
        return TaskType.single_shop_query.value

    return TaskType.clarification_reply.value
