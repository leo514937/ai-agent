from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...domain.enums import Facet


class ToolCapabilitySpec(BaseModel):
    tool_name: str
    supported_facets: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    output_facets: list[str] = Field(default_factory=list)
    retryable_failure_types: list[str] = Field(default_factory=list)
    non_retryable_failure_types: list[str] = Field(default_factory=list)
    cost_weight: int = 1
    priority: int = 100
    owner: str | None = None
    notes: str | None = None


_DISCOVERY_FACETS = [
    "nearby",
    "restaurant",
    "coffee",
    "hotpot",
    "dessert",
    "date_scene",
    "family_with_kids",
    "friends_party",
    "quiet",
    "lively",
    "business_meeting",
    "work_study",
    "late_night",
    "not_too_noisy",
    "kid_friendly",
    "parking",
    "private_room",
    "spicy",
    "light_food",
    "vegetarian",
    "budget",
    "budget_around_x",
    "scene_fit",
]

TOOL_CAPABILITY_REGISTRY: dict[str, ToolCapabilitySpec] = {
    "search_shops": ToolCapabilitySpec(
        tool_name="search_shops",
        supported_facets=[
            *_DISCOVERY_FACETS,
            "category",
            "rating",
            "price",
            "avg_price",
            "coupon",
            "open_now",
            "distance",
            "travel_time",
        ],
        required_inputs=["query"],
        optional_inputs=["location", "limit"],
        output_facets=[
            "nearby",
            "restaurant",
            "coffee",
            "hotpot",
            "dessert",
            "date_scene",
            "distance",
            "open_now",
            "coupon",
            "avg_price",
        ],
        cost_weight=1,
        priority=10,
        owner="discovery",
        notes="recall tool for candidate search",
    ),
    "get_shop_detail": ToolCapabilitySpec(
        tool_name="get_shop_detail",
        supported_facets=["detail", "price", "avg_price", "rating", "category"],
        required_inputs=["shop_id"],
        optional_inputs=[],
        output_facets=["detail", "price", "avg_price", "rating", "category"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=2,
        priority=30,
        owner="single_shop",
        notes="basic per-shop detail facts",
    ),
    "get_coupon_list": ToolCapabilitySpec(
        tool_name="get_coupon_list",
        supported_facets=["coupon", "discount", "group_buy"],
        required_inputs=["shop_id"],
        optional_inputs=[],
        output_facets=["coupon", "discount", "group_buy"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=2,
        priority=20,
        owner="deal",
        notes="coupon / discount / group-buy facts",
    ),
    "check_open_status": ToolCapabilitySpec(
        tool_name="check_open_status",
        supported_facets=["open_status", "open_now", "open_late", "reservation_available", "queue_status"],
        required_inputs=["shop_id"],
        optional_inputs=[],
        output_facets=["open_status", "open_now", "open_late"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=1,
        priority=15,
        owner="status",
        notes="current open/close facts",
    ),
    "get_distance_eta": ToolCapabilitySpec(
        tool_name="get_distance_eta",
        supported_facets=["distance", "travel_time", "nearby"],
        required_inputs=["shop_id", "from_location"],
        optional_inputs=[],
        output_facets=["distance", "travel_time"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=2,
        priority=25,
        owner="location",
        notes="distance and ETA facts",
    ),
    "get_shop_cards": ToolCapabilitySpec(
        tool_name="get_shop_cards",
        supported_facets=[
            "nearby",
            "distance",
            "open_now",
            "coupon",
            "avg_price",
            "rating",
            "category",
            "review_summary",
            "review_tags",
            "scene_fit",
            "environment",
            "taste",
            "service",
            "deal",
        ],
        required_inputs=["shop_ids"],
        optional_inputs=["need_coupon_brief", "need_open_status", "need_distance_eta"],
        output_facets=["nearby", "distance", "open_now", "coupon", "avg_price", "rating"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=3,
        priority=35,
        owner="recommendation",
        notes="batch recommendation cards",
    ),
    "get_shop_review_summary": ToolCapabilitySpec(
        tool_name="get_shop_review_summary",
        supported_facets=["review_summary", "review_tags", "taste", "service", "environment", "scene_fit", "popularity"],
        required_inputs=["shop_ids"],
        optional_inputs=[],
        output_facets=["review_summary", "review_tags", "taste", "service", "environment", "scene_fit"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=3,
        priority=40,
        owner="review",
        notes="review summary facts",
    ),
    "get_deal_list": ToolCapabilitySpec(
        tool_name="get_deal_list",
        supported_facets=["deal", "group_buy", "coupon", "discount"],
        required_inputs=["shop_id"],
        optional_inputs=[],
        output_facets=["deal", "group_buy", "coupon", "discount"],
        retryable_failure_types=["timeout", "network_error", "backend_error"],
        non_retryable_failure_types=["invalid_response", "unsupported_facet", "missing_input"],
        cost_weight=3,
        priority=50,
        owner="deal",
        notes="deal / group-buy facts",
    ),
}

_FACET_TO_PRIMARY_TOOL: dict[str, str] = {
    "coupon": "get_coupon_list",
    "discount": "get_coupon_list",
    "group_buy": "get_coupon_list",
    "open_status": "check_open_status",
    "open_now": "check_open_status",
    "open_late": "check_open_status",
    "reservation_available": "check_open_status",
    "queue_status": "check_open_status",
    "distance": "get_distance_eta",
    "travel_time": "get_distance_eta",
    "price": "get_shop_detail",
    "avg_price": "get_shop_detail",
    "rating": "get_shop_detail",
    "detail": "get_shop_detail",
    "category": "get_shop_detail",
    "review_summary": "get_shop_review_summary",
    "review_tags": "get_shop_review_summary",
    "taste": "get_shop_review_summary",
    "service": "get_shop_review_summary",
    "environment": "get_shop_review_summary",
    "scene_fit": "get_shop_review_summary",
    "popularity": "get_shop_review_summary",
    "deal": "get_deal_list",
    "nearby": "search_shops",
    "restaurant": "search_shops",
    "coffee": "search_shops",
    "hotpot": "search_shops",
    "dessert": "search_shops",
    "date_scene": "search_shops",
    "family_with_kids": "search_shops",
    "friends_party": "search_shops",
    "quiet": "search_shops",
    "lively": "search_shops",
    "business_meeting": "search_shops",
    "work_study": "search_shops",
    "late_night": "search_shops",
    "not_too_noisy": "search_shops",
    "kid_friendly": "search_shops",
    "parking": "search_shops",
    "private_room": "search_shops",
    "spicy": "search_shops",
    "light_food": "search_shops",
    "vegetarian": "search_shops",
    "budget": "search_shops",
    "budget_around_x": "search_shops",
}


def get_tool_capability(tool_name: str) -> ToolCapabilitySpec | None:
    return TOOL_CAPABILITY_REGISTRY.get(str(tool_name or "").strip())


def tool_supports_facet(tool_name: str, facet: str) -> bool:
    spec = get_tool_capability(tool_name)
    if spec is None:
        return False
    normalized = str(facet or "").strip()
    return normalized in spec.supported_facets or normalized in spec.output_facets


def preferred_tool_for_facet(facet: str, *, task_type: str = "", has_target: bool = False) -> str | None:
    normalized = str(facet or "").strip()
    if not normalized:
        return None
    if task_type in {"recommendation", "exploration_planning"} and normalized in _DISCOVERY_FACETS:
        return "search_shops"
    if task_type == "comparison" and normalized in {"review_summary", "review_tags", "taste", "service", "environment", "scene_fit", "popularity"}:
        return "get_shop_review_summary"
    if normalized == "detail" and has_target:
        return "get_shop_detail"
    return _FACET_TO_PRIMARY_TOOL.get(normalized)


def required_inputs_for_tool(tool_name: str) -> list[str]:
    spec = get_tool_capability(tool_name)
    return list(spec.required_inputs or []) if spec else []


def tool_cost_weight(tool_name: str) -> int:
    spec = get_tool_capability(tool_name)
    return int(spec.cost_weight or 1) if spec else 1


def tool_facets_for_batch(tool_name: str) -> list[str]:
    spec = get_tool_capability(tool_name)
    if spec is None:
        return []
    return list(dict.fromkeys([*(spec.supported_facets or []), *(spec.output_facets or [])]))


def build_tool_call_dict(
    tool_name: str,
    facet: str,
    *,
    call_id: str,
    target_shop_id: str = "",
    required: bool = True,
    location: dict[str, Any] | None = None,
    shop_ids: list[str] | None = None,
    query: str = "",
    limit: int | None = None,
    target_index: int | None = None,
    group_id: str = "",
) -> dict[str, Any]:
    args: dict[str, Any]
    if tool_name == "search_shops":
        args = {
            "query": query or facet,
            "location": location or {},
            "limit": int(limit or 20),
        }
        target_shop_id = ""
    elif tool_name == "get_shop_review_summary":
        args = {"shop_ids": shop_ids or ([target_shop_id] if target_shop_id else [])}
    elif tool_name == "get_shop_cards":
        args = {
            "shop_ids": shop_ids or ([target_shop_id] if target_shop_id else []),
            "need_coupon_brief": True,
            "need_open_status": True,
            "need_distance_eta": True,
        }
    elif tool_name == "get_distance_eta":
        args = {"shop_id": target_shop_id}
        if location:
            args["from_location"] = location
    else:
        args = {"shop_id": target_shop_id}
    return {
        "call_id": call_id,
        "tool_name": tool_name,
        "args": args,
        "target_shop_id": target_shop_id,
        "required": required,
        "facet": facet,
        "depends_on": [],
        "timeout_ms": 2000,
        "retry_policy": {"max_attempts": 1 if required else 0, "backoff_ms": 200},
        "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
        "group_id": group_id,
        "max_parallelism": 1,
        "priority": 100 if target_index is None else int(target_index),
    }
