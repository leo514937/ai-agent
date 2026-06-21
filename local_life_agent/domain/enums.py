"""Core global enumerations for the local life agent."""

from enum import Enum


class TopIntent(str, Enum):
    local_life = "local_life"
    capability = "capability"
    chat = "chat"
    invalid = "invalid"
    unsafe = "unsafe"
    out_of_scope = "out_of_scope"


class TaskType(str, Enum):
    recommendation = "recommendation"
    single_shop_query = "single_shop_query"
    coupon_query = "coupon_query"
    comparison = "comparison"
    clarification_reply = "clarification_reply"
    general_chat = "general_chat"


class Facet(str, Enum):
    coupon = "coupon"
    open_status = "open_status"
    distance = "distance"
    price = "price"
    rating = "rating"
    category = "category"


class ToolResultStatus(str, Enum):
    ok = "ok"
    empty = "empty"
    unknown = "unknown"
    failed = "failed"
    circuit_open = "circuit_open"
    backend_unavailable = "backend_unavailable"


class ErrorCode(str, Enum):
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SHOP_NOT_FOUND = "SHOP_NOT_FOUND"
    AMBIGUOUS_SHOP = "AMBIGUOUS_SHOP"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    LLM_JSON_PARSE_ERROR = "LLM_JSON_PARSE_ERROR"
    LLM_ENUM_OUT_OF_RANGE = "LLM_ENUM_OUT_OF_RANGE"
    ANSWER_VERIFIER_FAILED = "ANSWER_VERIFIER_FAILED"
