from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolErrorClassification:
    category: str | None
    reason: str | None = None
    retryable: bool = False


def _message_text(errors: Mapping[str, Any] | None) -> str:
    if not errors:
        return ""
    return str(errors.get("message") or errors.get("error_message") or "").strip().lower()


def _payload_data(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    data = payload.get("data")
    if isinstance(data, Mapping):
        return dict(data)
    return dict(payload)


def _payload_text(payload: Mapping[str, Any] | None) -> str:
    if not payload:
        return ""
    chunks: list[str] = []
    for key in ("message", "error_message", "reason", "status", "status_text"):
        value = payload.get(key)
        if value:
            chunks.append(str(value))
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("message", "error_message", "reason", "status", "status_text"):
            value = data.get(key)
            if value:
                chunks.append(str(value))
    return " ".join(chunks).strip().lower()


def classify_tool_error(
    *,
    tool_name: str | None,
    status: Any,
    payload: Mapping[str, Any] | None = None,
    errors: Mapping[str, Any] | None = None,
    approval_required: bool = False,
    approval_status: str | None = None,
) -> ToolErrorClassification:
    status_text = str(status or "").strip().lower()
    approval_state = str(approval_status or "").strip().lower()
    error_message = " ".join(part for part in (_message_text(errors), _payload_text(payload)) if part).strip().lower()
    data = _payload_data(payload)

    if approval_required and status_text == "pending_approval":
        return ToolErrorClassification(category="approval_required", reason="tool_waiting_for_approval", retryable=False)
    if approval_required and approval_state in {"forbidden", "unauthorized"}:
        return ToolErrorClassification(category="permission_error", reason="approval_denied", retryable=False)
    if status_text == "rejected" or approval_state in {"rejected", "deny", "denied"}:
        return ToolErrorClassification(category="permission_error", reason="tool_rejected", retryable=False)
    if status_text == "timeout" or "timeout" in error_message or "timed out" in error_message:
        return ToolErrorClassification(category="timeout", reason="tool_timeout", retryable=True)
    if any(token in error_message for token in ("unavailable", "not configured", "dependency", "backend is missing", "service temporarily unavailable")):
        return ToolErrorClassification(category="service_unavailable", reason="dependency_unavailable", retryable=True)
    if any(token in error_message for token in ("invalid", "parameter", "missing required", "bad request", "malformed")):
        return ToolErrorClassification(category="invalid_params", reason="tool_payload_invalid", retryable=False)
    if any(token in error_message for token in ("not found", "missing", "no result")):
        return ToolErrorClassification(category="not_found", reason="tool_returned_no_result", retryable=False)

    if tool_name == "get_coupon_list":
        coupons = data.get("coupons") or []
        count = data.get("count")
        if count in (None, ""):
            count = len(coupons)
        try:
            count = int(count)
        except Exception:
            count = len(coupons)
        if count <= 0 and status_text in {"success", "empty"}:
            return ToolErrorClassification(category="empty_result", reason="no_coupons_returned", retryable=False)

    if tool_name == "check_open_status":
        open_status = str(data.get("open_status") or "").strip().lower()
        open_now = data.get("open_now")
        if open_status not in {"open", "closed"} and open_now in (None, ""):
            return ToolErrorClassification(category="service_unavailable", reason="open_status_unknown", retryable=True)

    if tool_name == "get_distance_eta":
        if data.get("distance_km") in (None, "") and data.get("eta_minutes") in (None, ""):
            return ToolErrorClassification(category="service_unavailable", reason="distance_unavailable", retryable=True)

    if tool_name == "get_order_status":
        order = data.get("order")
        found = data.get("found")
        status_value = ""
        if isinstance(order, Mapping):
            status_value = str(order.get("status") or "").strip().lower()
        elif isinstance(data, Mapping):
            status_value = str(data.get("status") or "").strip().lower()
        if found is False or status_value in {"not_found", "missing", "unknown"}:
            return ToolErrorClassification(category="not_found", reason="order_not_found", retryable=False)

    if status_text == "empty":
        return ToolErrorClassification(category="empty_result", reason="empty_payload", retryable=False)
    if status_text == "degraded":
        return ToolErrorClassification(category="service_unavailable", reason="degraded_tool_output", retryable=True)

    if status_text == "unsupported":
        return ToolErrorClassification(category="service_unavailable", reason="unsupported_tool", retryable=False)

    return ToolErrorClassification(category=None, reason=None, retryable=status_text in {"error", "degraded"})


__all__ = ["ToolErrorClassification", "classify_tool_error"]
