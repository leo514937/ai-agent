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
  - get_shop_cards      Batch shop card facts for recommendation / compare
  - get_shop_review_summary
                        Structured review summary for a shop or shops
  - get_deal_list       Deal / group-buy / set-meal facts for a shop
"""

from __future__ import annotations

from typing import Any

# ── JSON Schema helpers ──────────────────────────────────────────

_ID_SCHEMA = {"type": "string", "minLength": 1, "description": "Unique shop identifier"}
_QUERY_SCHEMA = {"type": "string", "minLength": 1, "description": "Search keyword"}
_TEXT_SCHEMA = {"type": "string", "description": "Optional text field"}
_LIMIT_SCHEMA = {"type": "integer", "minimum": 1, "description": "Maximum number of search results"}
_BOOL_SCHEMA = {"type": "boolean"}
_INT_SCHEMA = {"type": "integer"}
_NUMBER_SCHEMA = {"type": "number"}
_STRING_ARRAY_SCHEMA = {"type": "array", "items": {"type": "string"}}
_LOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number", "description": "Latitude"},
        "lng": {"type": "number", "description": "Longitude"},
        "label": {"type": "string", "description": "Human readable location label"},
    },
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
_TRACE_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string"},
        "backend_source": {"type": "string"},
        "duration_ms": {"type": ["integer", "null"]},
        "input": {"type": "object"},
        "status": {"type": "string"},
        "item_count": {"type": ["integer", "null"]},
        "missing_shop_ids": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "error_type": {"type": ["string", "null"]},
        "error_message": {"type": ["string", "null"]},
    },
}
_STATUS_SCHEMA = {"type": "string", "enum": ["ok", "partial", "empty", "error"]}
_SHOP_IDS_SCHEMA = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10}
_SCENE_SCHEMA = {"type": ["string", "null"]}
_ITEM_SOURCE_SCHEMA = {"type": "array", "items": {"type": "string"}}
_TAG_SCHEMA = {"type": "array", "items": {"type": "string"}}
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
_SHOP_CARDS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "shop_id": {"type": "string"},
        "name": {"type": "string"},
        "alias": {"type": "array", "items": {"type": "string"}},
        "category": {"type": ["string", "null"]},
        "address": {"type": ["string", "null"]},
        "rating": {"type": ["number", "null"]},
        "avg_price": {"type": ["number", "null"]},
        "price_level": {"type": ["string", "null"]},
        "distance_m": {"type": ["integer", "null"]},
        "eta_minutes": {"type": ["integer", "null"]},
        "is_open": {"type": ["boolean", "null"]},
        "open_status_text": {"type": ["string", "null"]},
        "coupon_count": {"type": ["integer", "null"]},
        "has_coupon": {"type": ["boolean", "null"]},
        "top_coupon_title": {"type": ["string", "null"]},
        "top_tags": _TAG_SCHEMA,
        "scene_tags": _TAG_SCHEMA,
        "source_fields": _ITEM_SOURCE_SCHEMA,
    },
    "required": ["shop_id", "name", "alias", "top_tags", "scene_tags", "source_fields"],
}
_SHOP_CARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": _STATUS_SCHEMA,
        "items": {"type": "array", "items": _SHOP_CARDS_ITEM_SCHEMA},
        "missing_shop_ids": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "trace": _TRACE_SCHEMA,
    },
    "required": ["status", "items", "missing_shop_ids", "warnings", "trace"],
}
_REVIEW_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "shop_id": {"type": "string"},
        "name": {"type": "string"},
        "rating": {"type": ["number", "null"]},
        "review_count": {"type": ["integer", "null"]},
        "taste_score": {"type": ["number", "null"]},
        "environment_score": {"type": ["number", "null"]},
        "service_score": {"type": ["number", "null"]},
        "price_score": {"type": ["number", "null"]},
        "positive_tags": _TAG_SCHEMA,
        "negative_tags": _TAG_SCHEMA,
        "scene_tags": _TAG_SCHEMA,
        "scene_fit": {
            "type": "object",
            "properties": {
                "scene": {"type": ["string", "null"]},
                "score": {"type": ["number", "null"]},
                "label": {"type": ["string", "null"]},
                "reasons": _TAG_SCHEMA,
            },
        },
        "highlights": _TAG_SCHEMA,
        "risks": _TAG_SCHEMA,
        "summary": {"type": ["string", "null"]},
        "source_fields": _ITEM_SOURCE_SCHEMA,
    },
    "required": ["shop_id", "name", "positive_tags", "negative_tags", "scene_tags", "highlights", "risks", "source_fields"],
}
_REVIEW_SUMMARY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": _STATUS_SCHEMA,
        "items": {"type": "array", "items": _REVIEW_SUMMARY_SCHEMA},
        "missing_shop_ids": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "trace": _TRACE_SCHEMA,
    },
    "required": ["status", "items", "missing_shop_ids", "warnings", "trace"],
}
_DEAL_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "deal_id": {"type": "string"},
        "title": {"type": "string"},
        "deal_type": {"type": ["string", "null"]},
        "price": {"type": ["number", "null"]},
        "original_price": {"type": ["number", "null"]},
        "discount_rate": {"type": ["number", "null"]},
        "people_count_min": {"type": ["integer", "null"]},
        "people_count_max": {"type": ["integer", "null"]},
        "avg_price_per_person": {"type": ["number", "null"]},
        "available": {"type": ["boolean", "null"]},
        "valid_time_text": {"type": ["string", "null"]},
        "use_time_rules": _TAG_SCHEMA,
        "limitations": _TAG_SCHEMA,
        "included_items": _TAG_SCHEMA,
        "recommend_tags": _TAG_SCHEMA,
        "source_fields": _ITEM_SOURCE_SCHEMA,
    },
    "required": ["deal_id", "title", "use_time_rules", "limitations", "included_items", "recommend_tags", "source_fields"],
}
_DEAL_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "status": _STATUS_SCHEMA,
        "shop_id": {"type": "string"},
        "shop_name": {"type": ["string", "null"]},
        "items": {"type": "array", "items": _DEAL_ITEM_SCHEMA},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "trace": _TRACE_SCHEMA,
    },
    "required": ["status", "shop_id", "items", "warnings", "trace"],
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
    {
        "name": "get_shop_cards",
        "description": "Batch fetch lightweight shop card facts for recommendation and comparison",
        "input_schema": {
            "type": "object",
            "properties": {
                "shop_ids": _SHOP_IDS_SCHEMA,
                "user_location": _LOCATION_SCHEMA,
                "need_coupon_brief": _BOOL_SCHEMA,
                "need_open_status": _BOOL_SCHEMA,
                "need_distance_eta": _BOOL_SCHEMA,
                "max_items": _INT_SCHEMA,
            },
            "required": ["shop_ids"],
        },
        "output_schema": _SHOP_CARDS_SCHEMA,
        "timeout_ms": 5000,
        "max_retries": 1,
        "circuit_breaker_enabled": False,
        "output_status_enum": ["ok", "partial", "empty", "error", "unknown"],
    },
    {
        "name": "get_shop_review_summary",
        "description": "Batch fetch structured review summary, scene fit, and risk highlights",
        "input_schema": {
            "type": "object",
            "properties": {
                "shop_ids": _SHOP_IDS_SCHEMA,
                "aspects": _STRING_ARRAY_SCHEMA,
                "scene": _SCENE_SCHEMA,
                "max_reviews": _INT_SCHEMA,
            },
            "required": ["shop_ids"],
        },
        "output_schema": _REVIEW_SUMMARY_RESPONSE_SCHEMA,
        "timeout_ms": 5000,
        "max_retries": 1,
        "circuit_breaker_enabled": False,
        "output_status_enum": ["ok", "partial", "empty", "error", "unknown"],
    },
    {
        "name": "get_deal_list",
        "description": "List group-buy / set-meal deals for a shop",
        "input_schema": {
            "type": "object",
            "properties": {
                "shop_id": _ID_SCHEMA,
                "people_count": _INT_SCHEMA,
                "budget_per_person": _NUMBER_SCHEMA,
                "deal_type": {"type": ["string", "null"]},
                "only_available": _BOOL_SCHEMA,
            },
            "required": ["shop_id"],
        },
        "output_schema": _DEAL_LIST_SCHEMA,
        "timeout_ms": 5000,
        "max_retries": 1,
        "circuit_breaker_enabled": False,
        "output_status_enum": ["ok", "partial", "empty", "error", "unknown"],
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
            prop_type = prop_schema.get("type")
            if prop_type == "string" and not isinstance(value, str):
                errors.append(f"Argument '{field}' must be a string")
            elif prop_type == "number" and not isinstance(value, (int, float)) and not isinstance(value, bool):
                errors.append(f"Argument '{field}' must be a number")
            elif prop_type == "integer" and not isinstance(value, int) and not isinstance(value, bool):
                errors.append(f"Argument '{field}' must be an integer")
            elif prop_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Argument '{field}' must be a boolean")
            elif prop_type == "array" and not isinstance(value, list):
                errors.append(f"Argument '{field}' must be a list")
            elif prop_type == "object" and not isinstance(value, dict):
                errors.append(f"Argument '{field}' must be a dict")
        return errors


# Module-level singleton for convenience
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
