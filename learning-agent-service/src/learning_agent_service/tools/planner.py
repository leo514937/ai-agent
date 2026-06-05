from __future__ import annotations

from typing import Any

from .models import ToolSelection


def _normalize_intent_key(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    text = str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")
    return text or None


class ToolPlanner:
    APPROVAL_REQUIRED_TOOLS = {
        "create_booking",
        "create_order",
        "cancel_order",
        "refund_order",
    }

    DEFAULT_INTENT_TOOL_MAP = {
        "recommend": "search_restaurants",
        "compare": "search_restaurants",
        "detail": "get_shop_detail",
        "navigation": "get_distance_eta",
        "restaurant_recommendation": "search_restaurants",
        "local_life_recommendation": "search_restaurants",
        "restaurant_comparison": "search_restaurants",
        "local_life_comparison": "search_restaurants",
        "restaurant_detail": "get_shop_detail",
        "local_life_detail": "get_shop_detail",
        "restaurant_coupon": "get_coupon_list",
        "local_life_coupon": "get_coupon_list",
        "restaurant_blog": "get_blog_list",
        "local_life_blog": "get_blog_list",
        "restaurant_shop_type": "get_shop_type_list",
        "local_life_shop_type": "get_shop_type_list",
        "restaurant_distance_eta": "get_distance_eta",
        "local_life_distance_eta": "get_distance_eta",
        "restaurant_open_status": "check_open_status",
        "local_life_open_status": "check_open_status",
        "restaurant_navigation": "get_distance_eta",
        "local_life_navigation": "get_distance_eta",
        "restaurant_booking": "get_shop_detail",
        "local_life_booking": "get_shop_detail",
        "restaurant_order_status": "get_shop_detail",
        "local_life_order_status": "get_shop_detail",
    }

    def __init__(self, intent_tool_map: dict[str, str] | None = None) -> None:
        self._intent_tool_map = dict(self.DEFAULT_INTENT_TOOL_MAP)
        if intent_tool_map:
            for key, value in intent_tool_map.items():
                normalized_key = _normalize_intent_key(key)
                if normalized_key:
                    self._intent_tool_map[normalized_key] = value

    def plan(
        self,
        intent: str | None,
        need_tool: bool,
        slots: dict[str, object] | None = None,
    ) -> ToolSelection | None:
        if not need_tool:
            return None

        slot_data = dict(slots or {})
        tool_name = slot_data.pop("tool_name", None)
        intent_key = _normalize_intent_key(intent)
        if not tool_name and intent_key:
            tool_name = self._intent_tool_map.get(intent_key)
        if not tool_name:
            return None

        explicit_payload = slot_data.pop("tool_input", None)
        if isinstance(explicit_payload, dict):
            input_payload = explicit_payload
        else:
            input_payload = slot_data

        return ToolSelection(
            tool_name=tool_name,
            input_payload=input_payload,
            reason="planned_from_intent:{intent}".format(intent=intent_key or "unknown"),
            approval_required=tool_name in self.APPROVAL_REQUIRED_TOOLS,
            approval_status="pending_approval" if tool_name in self.APPROVAL_REQUIRED_TOOLS else None,
            approval_request={
                "tool_name": tool_name,
                "reason": "planned_from_intent:{intent}".format(intent=intent_key or "unknown"),
                "risk_level": "high" if tool_name in {"cancel_order", "refund_order"} else "medium",
                "approval_state": "pending_approval",
                "tool_input": dict(input_payload),
            }
            if tool_name in self.APPROVAL_REQUIRED_TOOLS
            else {},
        )
