from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _shop_label(request: Any, fallback: str = "这家店") -> str:
    if request is None:
        return fallback
    for attr in ("shop_name", "current_shop", "selected_shop_name"):
        value = getattr(request, attr, None)
        if value:
            text = str(value).strip()
            if text:
                return text
    if isinstance(request, Mapping):
        for key in ("shop_name", "current_shop", "selected_shop_name"):
            value = request.get(key)
            if value:
                text = str(value).strip()
                if text:
                    return text
    return fallback


def build_realtime_degrade_message(*, tool_name: str, failure_category: str, request: Any | None = None) -> str:
    shop_label = _shop_label(request)
    category = str(failure_category or "").strip().lower()
    if category in {"timeout"}:
        return "刚才查询超时了。你可以稍后重试，我也可以先帮你缩小范围再查。"
    if category in {"approval_required"}:
        return "这个操作还处于待确认状态。当前版本对下单、订座、取消、退款这类写操作只保留能力预留，暂时不直接代你执行。"
    if category in {"permission_error", "permission_denied"}:
        return "当前无权查看或执行这项操作。你可以先登录、补充校验信息，或者确认当前账号是否有对应权限。"
    if category in {"invalid_params"}:
        return "这次请求的参数不够完整或格式不对。你可以补充店名、城市、时间或要查询的具体对象，我再重新帮你查。"
    if category in {"service_unavailable", "dependency_unavailable"}:
        return "相关服务暂时不可用，这次还查不到结果。你可以稍后再试，或者换一个更具体的范围。"
    if category in {"not_found", "empty_result", "no_result"}:
        if tool_name == "get_coupon_list":
            return f"{shop_label}暂无可见优惠券。"
        if tool_name == "check_open_status":
            return f"{shop_label}当前营业信息暂时查不到。"
        return f"{shop_label}暂时没有查到结果。"
    return ""


__all__ = ["build_realtime_degrade_message"]
