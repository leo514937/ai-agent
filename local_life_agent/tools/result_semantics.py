"""Semantic helpers for tool result and resolve-shop status.

Provides:
1. Constants for status classification
2. Helper functions to safely read tool results and resolve-shop results
3. Clear separation between ToolResultStatus and ResolveShopResult.status
"""

from __future__ import annotations

from typing import Any

# ======================================================================
# ToolResultStatus — execution status classification
# ======================================================================

TOOL_FAILURE_STATUSES = frozenset(
    {
        "failed",
        "error",
        "timeout",
        "unsupported",
        "circuit_open",
        "backend_unavailable",
        "unknown",
    }
)

TOOL_DEGRADED_STATUSES = frozenset(
    {
        "partial",
    }
)

TOOL_EMPTY_STATUSES = frozenset(
    {
        "empty",
    }
)

# ======================================================================
# ResolveShopResult.status — resolution result values
# ======================================================================

RESOLVE_STATUS_RESOLVED = "RESOLVED"
RESOLVE_STATUS_AMBIGUOUS = "AMBIGUOUS"
RESOLVE_STATUS_LOW_CONFIDENCE = "LOW_CONFIDENCE"
RESOLVE_STATUS_NOT_FOUND = "NOT_FOUND"


# ======================================================================
# Helpers — ToolResultStatus
# ======================================================================


def get_tool_result_status(result: dict) -> str:
    """Extract ToolResultStatus from a normalized tool result dict."""
    if not isinstance(result, dict):
        return "unknown"
    raw = result.get("result_status", "unknown")
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw or "unknown")


def get_tool_data(result: dict) -> dict:
    """Extract the inner data payload from a normalized tool result."""
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def is_tool_failed(result: dict) -> bool:
    """Check whether the tool execution itself failed."""
    status = get_tool_result_status(result)
    return status in TOOL_FAILURE_STATUSES


def is_tool_partial(result: dict) -> bool:
    """Check whether the tool returned a partial/degraded result."""
    status = get_tool_result_status(result)
    return status in TOOL_DEGRADED_STATUSES


def is_tool_empty(result: dict) -> bool:
    """Check whether the tool succeeded but returned no data."""
    status = get_tool_result_status(result)
    return status in TOOL_EMPTY_STATUSES


def is_tool_success(result: dict) -> bool:
    """Check whether the tool execution was successful (ok or partial)."""
    status = get_tool_result_status(result)
    return status in ("ok", "partial")


# ======================================================================
# Helpers — ResolveShopResult.status
# ======================================================================


def get_resolve_shop_status(result: dict) -> str | None:
    """Extract ResolveShopResult.status from a normalized tool result.

    The resolve-shop status lives inside ``data.status`` because the outer
    ``result_status`` is a ToolResultStatus (execution status), not a
    resolution status.

    Returns None if the result doesn't contain a resolve-shop payload.
    """
    data = get_tool_data(result)
    raw = data.get("status") if isinstance(data, dict) else None
    return str(raw) if raw is not None else None


def is_shop_resolved(result: dict) -> bool:
    """Check whether the shop was successfully resolved.

    This checks ``data.status == "RESOLVED"``, NOT ``result_status == "ok"``.
    A tool can execute successfully (result_status=ok) but fail to resolve
    (data.status=NOT_FOUND).
    """
    rs_status = get_resolve_shop_status(result)
    return rs_status == RESOLVE_STATUS_RESOLVED


def is_shop_not_found(result: dict) -> bool:
    """Check whether the shop was not found during resolution."""
    rs_status = get_resolve_shop_status(result)
    return rs_status == RESOLVE_STATUS_NOT_FOUND


def is_shop_ambiguous(result: dict) -> bool:
    """Check whether the shop resolution returned ambiguous candidates."""
    rs_status = get_resolve_shop_status(result)
    return rs_status == RESOLVE_STATUS_AMBIGUOUS


def is_shop_low_confidence(result: dict) -> bool:
    """Check whether the shop resolution returned low confidence."""
    rs_status = get_resolve_shop_status(result)
    return rs_status == RESOLVE_STATUS_LOW_CONFIDENCE
