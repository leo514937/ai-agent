from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str
    facet: str | None = None
    shop_id: str | None = None
    shop_name: str | None = None
    status: Literal["success", "empty", "timeout", "error", "unsupported", "degraded"] = "success"
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    source: str = "realtime_tool"
    fetched_at: str
    ttl_seconds: int | None = None
    is_realtime: bool = True
    confidence: float = 1.0


def _tool_facet(tool_name: str) -> str | None:
    mapping = {
        "get_coupon_list": "coupon",
        "check_open_status": "open_status",
        "get_distance_eta": "distance_eta",
    }
    return mapping.get(str(tool_name or "").strip())


def _tool_confidence(status: str) -> float:
    mapping = {
        "success": 1.0,
        "empty": 0.9,
        "degraded": 0.45,
        "timeout": 0.0,
        "error": 0.0,
        "unsupported": 0.0,
    }
    return mapping.get(status, 0.0)


def normalize_tool_result(
    *,
    tool_name: str,
    raw_output: dict[str, Any] | None = None,
    shop_id: Any = None,
    shop_name: Any = None,
    source: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    status: str | None = None,
    ttl_seconds: int | None = None,
    fetched_at: str | None = None,
) -> ToolResult:
    payload = dict(raw_output or {})
    tool_name = str(tool_name or "").strip()
    facet = _tool_facet(tool_name)
    normalized_status = str(status or "").strip().lower()
    normalized_error_code = str(error_code or "").strip() or None
    normalized_error_message = str(error_message or "").strip() or None

    if facet is None:
        normalized_status = normalized_status or "unsupported"
        normalized_error_code = normalized_error_code or "unsupported_tool"
        normalized_error_message = normalized_error_message or f"unsupported tool: {tool_name}"
    elif tool_name == "get_coupon_list":
        coupons = list(payload.get("coupons") or [])
        coupon_count = payload.get("count")
        if coupon_count in (None, ""):
            coupon_count = len(coupons)
        try:
            coupon_count = int(coupon_count)
        except Exception:
            coupon_count = len(coupons)
        if not normalized_status:
            normalized_status = "success" if coupon_count > 0 else "empty"
        payload["count"] = coupon_count
    elif tool_name == "check_open_status":
        open_status = str(payload.get("open_status") or "").strip().lower()
        open_now = payload.get("open_now")
        if not normalized_status:
            if open_status in {"open", "closed"} or open_now is not None:
                normalized_status = "success"
            else:
                normalized_status = "degraded"
                normalized_error_code = normalized_error_code or "open_status_unknown"
                normalized_error_message = normalized_error_message or "open status is unavailable"
    elif tool_name == "get_distance_eta":
        distance_km = payload.get("distance_km")
        eta_minutes = payload.get("eta_minutes")
        if not normalized_status:
            if distance_km is None and eta_minutes is None:
                normalized_status = "degraded"
                normalized_error_code = normalized_error_code or "distance_unavailable"
                normalized_error_message = normalized_error_message or "distance eta is unavailable"
            else:
                normalized_status = "success"

    if normalized_error_code and not normalized_status:
        normalized_status = "error"
    if not normalized_status:
        normalized_status = "success"

    if normalized_status == "timeout":
        normalized_error_code = normalized_error_code or "tool_timeout"
        normalized_error_message = normalized_error_message or "tool execution timeout"
    elif normalized_status == "error":
        normalized_error_code = normalized_error_code or "tool_error"
        normalized_error_message = normalized_error_message or "tool execution error"

    shop_id_text = None if shop_id in (None, "") else str(shop_id)
    shop_name_text = None if shop_name in (None, "") else str(shop_name)
    payload.setdefault("shop_id", shop_id if shop_id not in (None, "") else payload.get("shop_id"))
    payload.setdefault("shop_name", shop_name if shop_name not in (None, "") else payload.get("shop_name"))

    return ToolResult(
        tool_name=tool_name,
        facet=facet,
        shop_id=shop_id_text,
        shop_name=shop_name_text,
        status=normalized_status,
        data=payload,
        error_code=normalized_error_code,
        error_message=normalized_error_message,
        source=str(source or payload.get("source") or "realtime_tool"),
        fetched_at=fetched_at or datetime.now(UTC).isoformat(),
        ttl_seconds=ttl_seconds,
        is_realtime=facet is not None,
        confidence=_tool_confidence(normalized_status),
    )
