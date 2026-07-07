"""Tool metadata authority for the tool layer."""

from __future__ import annotations

from typing import Any

from .schemas import TOOL_SCHEMA_BY_NAME

_OUTPUT_STATUS_ENUM = ["ok", "empty", "failed", "circuit_open", "unsupported", "unknown"]


def _tool_definition(
    *,
    name: str,
    description: str,
    timeout_ms: int,
    max_retries: int,
    circuit_breaker_enabled: bool,
    output_status_enum: list[str] | None = None,
) -> dict[str, Any]:
    schema = TOOL_SCHEMA_BY_NAME[name]
    definition = {
        "name": name,
        "description": description,
        "input_schema": schema["input_schema"],
        "output_schema": schema["output_schema"],
        "timeout_ms": timeout_ms,
        "max_retries": max_retries,
        "circuit_breaker_enabled": circuit_breaker_enabled,
        "output_status_enum": output_status_enum or _OUTPUT_STATUS_ENUM,
    }
    return definition


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool_definition(
        name="resolve_shop",
        description="Resolve a shop mention from user text to a known shop_id",
        timeout_ms=3000,
        max_retries=1,
        circuit_breaker_enabled=False,
    ),
    _tool_definition(
        name="search_shops",
        description="Search shops by keyword, category, or tag",
        timeout_ms=5000,
        max_retries=2,
        circuit_breaker_enabled=True,
    ),
    _tool_definition(
        name="get_shop_detail",
        description="Get detailed information for a shop by ID",
        timeout_ms=3000,
        max_retries=1,
        circuit_breaker_enabled=False,
    ),
    _tool_definition(
        name="get_coupon_list",
        description="Get available coupons for a shop",
        timeout_ms=5000,
        max_retries=2,
        circuit_breaker_enabled=True,
    ),
    _tool_definition(
        name="check_open_status",
        description="Check whether a shop is currently open",
        timeout_ms=3000,
        max_retries=1,
        circuit_breaker_enabled=False,
    ),
    _tool_definition(
        name="get_distance_eta",
        description="Calculate distance and ETA from user location to a shop",
        timeout_ms=5000,
        max_retries=2,
        circuit_breaker_enabled=True,
    ),
    _tool_definition(
        name="calculate_distance_km",
        description="Calculate straight-line distance between an origin and destination using the Haversine formula",
        timeout_ms=2000,
        max_retries=1,
        circuit_breaker_enabled=False,
    ),
    _tool_definition(
        name="get_shop_cards",
        description="Batch fetch lightweight shop card facts for recommendation and comparison",
        timeout_ms=5000,
        max_retries=1,
        circuit_breaker_enabled=False,
        output_status_enum=["ok", "partial", "empty", "error", "unsupported", "unknown"],
    ),
    _tool_definition(
        name="get_shop_review_summary",
        description="Batch fetch structured review summary, scene fit, and risk highlights",
        timeout_ms=5000,
        max_retries=1,
        circuit_breaker_enabled=False,
        output_status_enum=["ok", "partial", "empty", "error", "unsupported", "unknown"],
    ),
    _tool_definition(
        name="get_deal_list",
        description="List group-buy / set-meal deals for a shop",
        timeout_ms=5000,
        max_retries=1,
        circuit_breaker_enabled=False,
        output_status_enum=["ok", "partial", "empty", "error", "unsupported", "unknown"],
    ),
]

