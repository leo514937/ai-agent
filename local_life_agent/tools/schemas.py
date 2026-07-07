"""Tool input/output schema authority for the tool layer."""

from __future__ import annotations

from typing import Any

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
        "raw": {"type": "string", "description": "Unresolved location text"},
        "status": {"type": "string", "description": "Location resolution status"},
    },
}
_DISTANCE_POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number", "description": "Latitude"},
        "lng": {"type": "number", "description": "Longitude"},
        "label": {"type": "string", "description": "Human readable location label"},
        "raw": {"type": "string", "description": "Unresolved location text"},
        "status": {"type": "string", "description": "Location resolution status"},
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
        "pay_value": {"type": "number"},
        "actual_value": {"type": "number"},
        "status": {"type": "string", "enum": ["available", "unavailable"]},
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
_DISTANCE_KM_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success", "unknown", "failed"]},
        "distance_km": {"type": ["number", "null"]},
        "eta_minutes": {"type": ["integer", "null"]},
        "method": {"type": "string"},
        "blocked_reason": {"type": ["string", "null"]},
        "error_code": {"type": ["string", "null"]},
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


def resolve_shop_input_schema() -> dict[str, Any]:
    return {
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
    }


def resolve_shop_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["RESOLVED", "AMBIGUOUS", "NOT_FOUND"]},
            "shop": _SHOP_RESULT_SCHEMA,
            "candidates": {"type": "array", "items": {"$ref": "#/definitions/ShopCandidate"}},
            "confidence": {"type": "number"},
        },
    }


def search_shops_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": _QUERY_SCHEMA,
            "location": _LOCATION_SCHEMA,
            "limit": _LIMIT_SCHEMA,
        },
        "required": ["query"],
    }


def search_shops_output_schema() -> dict[str, Any]:
    return {"type": "array", "items": _SHOP_RESULT_SCHEMA}


def get_shop_detail_input_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"shop_id": _ID_SCHEMA}, "required": ["shop_id"]}


def get_shop_detail_output_schema() -> dict[str, Any]:
    return _SHOP_RESULT_SCHEMA


def get_coupon_list_input_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"shop_id": _ID_SCHEMA}, "required": ["shop_id"]}


def get_coupon_list_output_schema() -> dict[str, Any]:
    return {"type": "array", "items": _COUPON_SCHEMA}


def check_open_status_input_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"shop_id": _ID_SCHEMA}, "required": ["shop_id"]}


def check_open_status_output_schema() -> dict[str, Any]:
    return _OPEN_STATUS_SCHEMA


def get_distance_eta_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "shop_id": _ID_SCHEMA,
            "from_location": _LOCATION_SCHEMA,
        },
        "required": ["shop_id", "from_location"],
    }


def get_distance_eta_output_schema() -> dict[str, Any]:
    return _DISTANCE_ETA_SCHEMA


def calculate_distance_km_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "origin": _DISTANCE_POINT_SCHEMA,
            "destination": _DISTANCE_POINT_SCHEMA,
            "mode": {"type": "string", "enum": ["straight_line"]},
        },
    }


def calculate_distance_km_output_schema() -> dict[str, Any]:
    return _DISTANCE_KM_SCHEMA


def get_shop_cards_input_schema() -> dict[str, Any]:
    return {
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
    }


def get_shop_cards_output_schema() -> dict[str, Any]:
    return _SHOP_CARDS_SCHEMA


def get_shop_review_summary_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "shop_ids": _SHOP_IDS_SCHEMA,
            "aspects": _STRING_ARRAY_SCHEMA,
            "scene": _SCENE_SCHEMA,
            "max_reviews": _INT_SCHEMA,
        },
        "required": ["shop_ids"],
    }


def get_shop_review_summary_output_schema() -> dict[str, Any]:
    return _REVIEW_SUMMARY_RESPONSE_SCHEMA


def get_deal_list_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "shop_id": _ID_SCHEMA,
            "people_count": _INT_SCHEMA,
            "budget_per_person": _NUMBER_SCHEMA,
            "deal_type": {"type": ["string", "null"]},
            "only_available": _BOOL_SCHEMA,
        },
        "required": ["shop_id"],
    }


def get_deal_list_output_schema() -> dict[str, Any]:
    return _DEAL_LIST_SCHEMA


TOOL_SCHEMA_BY_NAME: dict[str, dict[str, Any]] = {
    "resolve_shop": {
        "input_schema": resolve_shop_input_schema(),
        "output_schema": resolve_shop_output_schema(),
    },
    "search_shops": {
        "input_schema": search_shops_input_schema(),
        "output_schema": search_shops_output_schema(),
    },
    "get_shop_detail": {
        "input_schema": get_shop_detail_input_schema(),
        "output_schema": get_shop_detail_output_schema(),
    },
    "get_coupon_list": {
        "input_schema": get_coupon_list_input_schema(),
        "output_schema": get_coupon_list_output_schema(),
    },
    "check_open_status": {
        "input_schema": check_open_status_input_schema(),
        "output_schema": check_open_status_output_schema(),
    },
    "get_distance_eta": {
        "input_schema": get_distance_eta_input_schema(),
        "output_schema": get_distance_eta_output_schema(),
    },
    "calculate_distance_km": {
        "input_schema": calculate_distance_km_input_schema(),
        "output_schema": calculate_distance_km_output_schema(),
    },
    "get_shop_cards": {
        "input_schema": get_shop_cards_input_schema(),
        "output_schema": get_shop_cards_output_schema(),
    },
    "get_shop_review_summary": {
        "input_schema": get_shop_review_summary_input_schema(),
        "output_schema": get_shop_review_summary_output_schema(),
    },
    "get_deal_list": {
        "input_schema": get_deal_list_input_schema(),
        "output_schema": get_deal_list_output_schema(),
    },
}

