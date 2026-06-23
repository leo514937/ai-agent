"""Tool result normalizer — normalizes tool outputs into a uniform
ToolResult-compatible format regardless of the underlying execution
source (mock, HTTP, or DB).

The normalizer guarantees that every result dict contains ALL of:
  success, result_status, data, error_code, error_message, source, degraded,
  call_id, shop_id, tool_name, tool_backend, backend_source, fallback_from,
  http_status, endpoint

Every public normalize function uses the same internal builder so the
shape is identical across all paths.
"""

from __future__ import annotations

from typing import Any

from .result_semantics import TOOL_FAILURE_STATUSES

_VALID_STATUSES = {"ok", "partial", "empty", "failed", "error", "circuit_open", "unknown", "backend_unavailable"}


def _canonical_tool_result(
    tool_name: str,
    *,
    call_id: str = "",
    shop_id: str = "",
    success: bool = False,
    result_status: str = "unknown",
    data: Any = None,
    error_code: str | None = None,
    error_message: str = "",
    source: str = "mock",
    tool_backend: str = "mock",
    backend_source: str = "mock",
    degraded: bool = False,
    fallback_from: str | None = None,
    http_status: int | None = None,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Build a canonical ToolResult dict with every field guaranteed."""
    valid_status = result_status if result_status in _VALID_STATUSES else "unknown"
    return {
        "call_id": call_id,
        "shop_id": shop_id,
        "tool_name": tool_name,
        "success": success,
        "result_status": valid_status,
        "data": data,
        "error_code": error_code,
        "error_message": error_message,
        "source": source,
        "tool_backend": tool_backend,
        "backend_source": backend_source,
        "degraded": degraded,
        "fallback_from": fallback_from,
        "http_status": http_status,
        "endpoint": endpoint,
    }


def normalize_tool_result(tool_name: str, raw: dict) -> dict:
    """Convert a raw tool output to a canonical ToolResult dict.

    Args:
        tool_name: Name of the tool that produced the result.
        raw: Raw output from the tool (may be a dict or other type).

    Returns:
        Canonical dict with ALL 15 guaranteed keys.
    """
    if not isinstance(raw, dict):
        return _canonical_tool_result(
            tool_name=tool_name,
            success=bool(raw) if raw is not None else False,
            result_status="ok" if raw else "unknown",
            data=raw,
            source=raw.get("source", "mock") if hasattr(raw, "get") else "mock",
            tool_backend=raw.get("tool_backend", raw.get("backend_source", "mock")) if hasattr(raw, "get") else "mock",
            backend_source=raw.get("backend_source", "mock") if hasattr(raw, "get") else "mock",
        )

    result_status = raw.get("result_status", "unknown")
    if result_status not in _VALID_STATUSES:
        result_status = "unknown"

    return _canonical_tool_result(
        tool_name=tool_name,
        call_id=raw.get("call_id", ""),
        shop_id=raw.get("shop_id", ""),
        success=raw.get("success", False) if result_status not in TOOL_FAILURE_STATUSES else False,
        result_status=result_status,
        data=raw.get("data"),
        error_code=raw.get("error_code"),
        error_message=raw.get("error_message", ""),
        source=raw.get("source", "mock"),
        tool_backend=raw.get("tool_backend", raw.get("backend_source", raw.get("source", "mock"))),
        backend_source=raw.get("backend_source", raw.get("source", "mock")),
        degraded=raw.get("degraded", False),
        fallback_from=raw.get("fallback_from"),
        http_status=raw.get("http_status"),
        endpoint=raw.get("endpoint"),
    )


def normalize_timeout_result(tool_name: str, kwargs: dict, error_message: str) -> dict:
    """Create a canonical ToolResult for a timeout scenario.

    Args:
        tool_name: Name of the tool that timed out.
        kwargs: Original call arguments.
        error_message: Timeout description.

    Returns:
        Canonical ToolResult dict with result_status='unknown'.
    """
    return _canonical_tool_result(
        tool_name=tool_name,
        call_id=kwargs.get("call_id", ""),
        shop_id=kwargs.get("shop_id", ""),
        success=False,
        result_status="unknown",
        error_code="TOOL_TIMEOUT",
        error_message=error_message,
        source="mock",
        tool_backend="mock",
        backend_source="mock",
        degraded=True,
    )


def normalize_circuit_open_result(tool_name: str, kwargs: dict) -> dict:
    """Create a canonical ToolResult for a circuit-breaker open rejection.

    Args:
        tool_name: Name of the tool whose circuit is open.
        kwargs: Original call arguments.

    Returns:
        Canonical ToolResult dict with result_status='circuit_open'.
    """
    return _canonical_tool_result(
        tool_name=tool_name,
        call_id=kwargs.get("call_id", ""),
        shop_id=kwargs.get("shop_id", ""),
        success=False,
        result_status="circuit_open",
        error_code="CIRCUIT_OPEN",
        error_message=f"Circuit breaker is OPEN for tool '{tool_name}'",
        source="mock",
        tool_backend="mock",
        backend_source="mock",
        degraded=True,
    )


def normalize_validation_error(tool_name: str, kwargs: dict, errors: list[str]) -> dict:
    """Create a canonical ToolResult for a schema validation failure.

    Args:
        tool_name: Name of the tool.
        kwargs: Original call arguments.
        errors: Validation error messages.

    Returns:
        Canonical ToolResult dict with result_status='failed'.
    """
    return _canonical_tool_result(
        tool_name=tool_name,
        call_id=kwargs.get("call_id", ""),
        shop_id=kwargs.get("shop_id", ""),
        success=False,
        result_status="failed",
        error_code="SCHEMA_VALIDATION_FAILED",
        error_message="; ".join(errors),
        source="mock",
        tool_backend="mock",
        backend_source="mock",
    )
