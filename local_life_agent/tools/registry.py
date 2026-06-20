"""Tool registry — central registry mapping tool names to their
implementation metadata, including JSON Schema for input/output
validation and execution policies.

Registered tools (6):
  - resolve_shop        Resolve a shop from query text / alias / location
  - search_shops        Search shops by keyword / category / tag
  - get_shop_detail     Get detailed info for a single shop
  - get_coupon_list     Get available coupons for a shop
  - check_open_status   Check whether a shop is currently open
  - get_distance_eta    Calculate distance and ETA from user location
"""

from __future__ import annotations

from typing import Any

# ── JSON Schema helpers ──────────────────────────────────────────

_ID_SCHEMA = {"type": "string", "minLength": 1, "description": "Unique shop identifier"}
_QUERY_SCHEMA = {"type": "string", "minLength": 1, "description": "Search keyword"}
_LIMIT_SCHEMA = {"type": "integer", "minimum": 1, "description": "Maximum number of search results"}
_LOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number", "description": "Latitude"},
        "lng": {"type": "number", "description": "Longitude"},
    },
    "required": ["lat", "lng"],
}
_SHOP_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "shop_id": {"type": "string"},
        "shop_name": {"type": "string"},
        "alias": {"type": "string"},
        "category": {"type": "string"},
        "address": {"type": "string"},
        "lat": {"type": "number"},
        "lng": {"type": "number"},
        "avg_price": {"type": "number"},
        "rating": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["shop_id", "shop_name"],
}
_COUPON_SCHEMA = {
    "type": "object",
    "properties": {
        "coupon_id": {"type": "string"},
        "shop_id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "discount_type": {"type": "string"},
        "discount_value": {"type": "number"},
        "min_consume": {"type": "number"},
        "valid_from": {"type": "string"},
        "valid_until": {"type": "string"},
        "stock": {"type": "integer"},
    },
}
_OPEN_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "shop_id": {"type": "string"},
        "shop_name": {"type": "string"},
        "open_status": {"type": "string", "enum": ["open", "closed", "unknown"]},
        "business_hours": {"type": "string"},
    },
}
_DISTANCE_ETA_SCHEMA = {
    "type": "object",
    "properties": {
        "shop_id": {"type": "string"},
        "shop_name": {"type": "string"},
        "distance_km": {"type": "number"},
        "eta_minutes": {"type": "integer"},
        "traffic_level": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}
_RESOLVE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "shop_id": {"type": "string"},
        "shop_name": {"type": "string"},
        "confidence": {"type": "number"},
        "matched_by": {"type": "string"},
        "alias": {"type": "string"},
        "error_code": {"type": "string"},
    },
}

# ── Output status enum per tool ─────────────────────────────────

_OUTPUT_STATUS_ENUM = ["ok", "empty", "failed", "circuit_open", "unknown"]

# ── Tool definitions ─────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "resolve_shop",
        "description": "Resolve a shop mention from user text to a known shop_id",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": _QUERY_SCHEMA,
                "location": _LOCATION_SCHEMA,
                "session_shop_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Shop IDs mentioned earlier in the session",
                },
            },
            "required": ["query"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["RESOLVED", "AMBIGUOUS", "NOT_FOUND"]},
                "shop": _SHOP_RESULT_SCHEMA,
                "candidates": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/ShopCandidate"},
                },
                "confidence": {"type": "number"},
            },
        },
        "timeout_ms": 3000,
        "max_retries": 1,
        "circuit_breaker_enabled": False,
        "output_status_enum": _OUTPUT_STATUS_ENUM,
    },
    {
        "name": "search_shops",
        "description": "Search shops by keyword, category, or tag",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": _QUERY_SCHEMA,
                "location": _LOCATION_SCHEMA,
                "limit": _LIMIT_SCHEMA,
            },
            "required": ["query"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": _SHOP_RESULT_SCHEMA},
                "total": {"type": "integer"},
            },
        },
        "timeout_ms": 5000,
        "max_retries": 2,
        "circuit_breaker_enabled": True,
        "output_status_enum": _OUTPUT_STATUS_ENUM,
    },
    {
        "name": "get_shop_detail",
        "description": "Get detailed information for a shop by ID",
        "input_schema": {
            "type": "object",
            "properties": {"shop_id": _ID_SCHEMA},
            "required": ["shop_id"],
        },
        "output_schema": _SHOP_RESULT_SCHEMA,
        "timeout_ms": 3000,
        "max_retries": 1,
        "circuit_breaker_enabled": False,
        "output_status_enum": _OUTPUT_STATUS_ENUM,
    },
    {
        "name": "get_coupon_list",
        "description": "Get available coupons for a shop",
        "input_schema": {
            "type": "object",
            "properties": {"shop_id": _ID_SCHEMA},
            "required": ["shop_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": _COUPON_SCHEMA},
                "total": {"type": "integer"},
            },
        },
        "timeout_ms": 5000,
        "max_retries": 2,
        "circuit_breaker_enabled": True,
        "output_status_enum": _OUTPUT_STATUS_ENUM,
    },
    {
        "name": "check_open_status",
        "description": "Check whether a shop is currently open",
        "input_schema": {
            "type": "object",
            "properties": {"shop_id": _ID_SCHEMA},
            "required": ["shop_id"],
        },
        "output_schema": _OPEN_STATUS_SCHEMA,
        "timeout_ms": 3000,
        "max_retries": 1,
        "circuit_breaker_enabled": False,
        "output_status_enum": _OUTPUT_STATUS_ENUM,
    },
    {
        "name": "get_distance_eta",
        "description": "Calculate distance and ETA from user location to a shop",
        "input_schema": {
            "type": "object",
            "properties": {
                "shop_id": _ID_SCHEMA,
                "from_location": _LOCATION_SCHEMA,
            },
            "required": ["shop_id", "from_location"],
        },
        "output_schema": _DISTANCE_ETA_SCHEMA,
        "timeout_ms": 5000,
        "max_retries": 2,
        "circuit_breaker_enabled": True,
        "output_status_enum": _OUTPUT_STATUS_ENUM,
    },
]

# ── Registry class ──────────────────────────────────────────────


class ToolRegistry:
    """Central registry for all available tools with metadata."""

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._load_definitions()

    def _load_definitions(self) -> None:
        for tdef in TOOL_DEFINITIONS:
            self._tools[tdef["name"]] = dict(tdef)

    def register(self, name: str, metadata: dict) -> None:
        """Register or override a tool definition."""
        self._tools[name] = dict(metadata)

    def get(self, name: str) -> dict | None:
        """Look up a tool definition by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def validate_args(self, tool_name: str, args: dict) -> list[str]:
        """Validate tool arguments against the input schema.

        Returns a list of error messages. Empty list means valid.
        """
        tdef = self._tools.get(tool_name)
        if tdef is None:
            return [f"Tool '{tool_name}' not registered"]
        schema = tdef.get("input_schema", {})
        required = schema.get("required", [])
        errors: list[str] = []
        for field in required:
            if field not in args or args[field] is None or (isinstance(args[field], str) and not args[field].strip()):
                errors.append(f"Missing required argument '{field}' for tool '{tool_name}'")
        # Type checks for known fields
        props = schema.get("properties", {})
        for field, value in args.items():
            if field not in props:
                continue
            prop_schema = props[field]
            if prop_schema.get("type") == "string" and not isinstance(value, str):
                errors.append(f"Argument '{field}' must be a string")
            elif prop_schema.get("type") == "number" and not isinstance(value, (int, float)):
                errors.append(f"Argument '{field}' must be a number")
            elif prop_schema.get("type") == "object" and not isinstance(value, dict):
                errors.append(f"Argument '{field}' must be a dict")
        return errors


# Module-level singleton for convenience
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
