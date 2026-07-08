"""Validation for the parsed semantic frame."""

from __future__ import annotations

from ..domain.enums import Facet, TaskType


_UNSUPPORTED_FACET_HINTS = (
    "服务",
    "设施",
    "宠物",
    "寄存",
    "停车",
    "包间",
    "座位",
    "储物",
    "储存",
    "洗手间",
    "wifi",
    "WIFI",
    "充电",
)

_SUPPORTED_FACET_HINTS = (
    "券",
    "优惠",
    "营业",
    "开门",
    "关门",
    "打烊",
    "距离",
    "多远",
    "多久能到",
    "评分",
    "人均",
    "评价",
    "推荐",
    "对比",
)


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
    mentions = list(frame.get("merchant_mentions") or [])
    mentions.extend([item for item in (frame.get("brand_mentions") or []) if item not in mentions])
    mentions.extend([item for item in (frame.get("branch_mentions") or []) if item not in mentions])
    forbidden_fields = [k for k in ("shop_id", "tool_name", "coupon_fact", "fake_fact") if frame.get(k)]

    if forbidden_fields:
        issues.extend(f"forbidden_field:{name}" for name in forbidden_fields)

    if task_type is None:
        issues.append("missing_task_type")
        text = str(frame.get("text", "") or frame.get("raw_text", "") or "")
        mentions = list(mentions)
        if mentions and any(token in text for token in _UNSUPPORTED_FACET_HINTS) and not any(token in text for token in _SUPPORTED_FACET_HINTS):
            clarification = "当前暂时无法确认这个服务项，请换一个更具体的问题；如果你想查优惠券、营业状态、距离或评价，也可以继续问我。"
            issues.append("unsupported_facet")
        else:
            clarification = "请补充你要查的店名或具体问题。"
    elif isinstance(task_type, TaskType):
        has_coupon = any(
            f.get("name") == Facet.coupon.value or (hasattr(f, "name") and getattr(f, "name") == Facet.coupon)
            for f in (frame.get("facets") or [])
        )
        if has_coupon and not mentions:
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
