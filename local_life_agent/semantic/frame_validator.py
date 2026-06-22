"""Validation for the parsed semantic frame."""

from __future__ import annotations

from typing import Any

from ..domain.enums import Facet, TaskType


def validate_frame(frame: dict) -> dict:
    """Check that a semantic frame is valid and actionable.

    Stage-10 only supports the single-shop coupon flow. A frame is
    considered valid when:
    - the top intent is local-life;
    - the task type is present; and
    - coupon queries mention at least one shop name.
    """
    if not isinstance(frame, dict):
        return {
            "valid": False,
            "issues": ["invalid_frame_type"],
            "clarification": "请补充你要查询的店名。",
        }

    issues: list[str] = []
    clarification = ""

    task_type = frame.get("task_type")
    mentions = frame.get("merchant_mentions") or []
    forbidden_fields = [k for k in ("shop_id", "tool_name", "coupon_fact", "fake_fact") if frame.get(k)]

    if forbidden_fields:
        issues.extend(f"forbidden_field:{name}" for name in forbidden_fields)

    if task_type is None:
        issues.append("missing_task_type")
        clarification = "请补充你要查的店名和优惠券需求。"
    elif isinstance(task_type, TaskType):
        has_coupon = any(
            f.get("name") == Facet.coupon.value or (hasattr(f, "name") and getattr(f, "name") == Facet.coupon)
            for f in (frame.get("facets") or [])
        )
        if has_coupon and not mentions:
            issues.append("missing_merchant_mentions")
            clarification = "请告诉我你想查哪家店的优惠券。"
    else:
        issues.append("invalid_task_type")
        clarification = "请用明确的本地生活问题重新描述。"

    if frame.get("need_context"):
        issues.append("needs_context")
        clarification = clarification or "请提供更完整的店名。"

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "clarification": clarification,
    }
