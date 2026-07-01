from __future__ import annotations

from typing import Any

from local_life_agent.tools.gateway import dispatch_tool_call


def resolve_shop(query: str, location: dict[str, float] | None = None, session_shop_ids: list[str] | None = None) -> dict[str, Any]:
    return dispatch_tool_call(
        "resolve_shop",
        {"query": query, "location": location, "session_shop_ids": session_shop_ids},
    )


def search_shops(query: str, location: dict[str, float] | None = None, limit: int | None = None) -> dict[str, Any]:
    return dispatch_tool_call(
        "search_shops",
        {"query": query, "location": location, "limit": limit},
    )


def get_shop_detail(shop_id: str) -> dict[str, Any]:
    return dispatch_tool_call("get_shop_detail", {"shop_id": shop_id})


def check_open_status(shop_id: str) -> dict[str, Any]:
    return dispatch_tool_call("check_open_status", {"shop_id": shop_id})


def get_coupon_list(shop_id: str) -> dict[str, Any]:
    return dispatch_tool_call("get_coupon_list", {"shop_id": shop_id})


def get_distance_eta(shop_id: str, from_location: dict[str, float]) -> dict[str, Any]:
    return dispatch_tool_call("get_distance_eta", {"shop_id": shop_id, "from_location": from_location})


def get_shop_cards(
    shop_ids: list[str],
    user_location: dict[str, float] | None = None,
    need_coupon_brief: bool = True,
    need_open_status: bool = True,
    need_distance_eta: bool = True,
    max_items: int | None = None,
) -> dict[str, Any]:
    return dispatch_tool_call(
        "get_shop_cards",
        {
            "shop_ids": shop_ids,
            "user_location": user_location,
            "need_coupon_brief": need_coupon_brief,
            "need_open_status": need_open_status,
            "need_distance_eta": need_distance_eta,
            "max_items": max_items,
        },
    )


def get_shop_review_summary(
    shop_ids: list[str],
    aspects: list[str] | None = None,
    scene: str | None = None,
    max_reviews: int | None = None,
) -> dict[str, Any]:
    return dispatch_tool_call(
        "get_shop_review_summary",
        {"shop_ids": shop_ids, "aspects": aspects, "scene": scene, "max_reviews": max_reviews},
    )


def get_deal_list(
    shop_id: str,
    people_count: int | None = None,
    budget_per_person: float | None = None,
    deal_type: str | None = None,
    only_available: bool = True,
) -> dict[str, Any]:
    return dispatch_tool_call(
        "get_deal_list",
        {
            "shop_id": shop_id,
            "people_count": people_count,
            "budget_per_person": budget_per_person,
            "deal_type": deal_type,
            "only_available": only_available,
        },
    )
