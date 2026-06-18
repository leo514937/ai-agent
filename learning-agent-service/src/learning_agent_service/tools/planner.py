from __future__ import annotations

from typing import Any

from ..domain.contracts import FacetPlan
from .models import ToolSelection


def _normalize_intent_key(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    text = str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")
    return text or None


_CANONICAL_TOOL_NAMES = {
    "search_restaurants",
    "get_shop_detail",
    "get_shop_type_list",
    "get_coupon_list",
    "get_blog_list",
    "get_distance_eta",
    "check_open_status",
    "create_booking",
    "create_order",
    "cancel_order",
    "refund_order",
    "get_order_status",
}

_TOOL_NAME_ALIAS_MAP = {
    "recommendation": "search_restaurants",
    "comparison": "search_restaurants",
    "detail": "get_shop_detail",
    "shop_info": "get_shop_detail",
    "shop_type": "get_shop_type_list",
    "coupon": "get_coupon_list",
    "blog": "get_blog_list",
    "distance_eta": "get_distance_eta",
    "navigation": "get_distance_eta",
    "open_status": "check_open_status",
    "booking": "create_booking",
    "book": "create_booking",
    "book_restaurant": "create_booking",
    "order": "create_order",
    "create_order": "create_order",
    "cancel": "cancel_order",
    "refund": "refund_order",
    "status": "get_order_status",
    "order_status": "get_order_status",
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
    "restaurant_booking": "create_booking",
    "local_life_booking": "create_booking",
    "restaurant_order_status": "get_order_status",
    "local_life_order_status": "get_order_status",
}


def _canonical_tool_name(value: Any) -> str | None:
    normalized = _normalize_intent_key(value)
    if not normalized:
        return None
    canonical = _TOOL_NAME_ALIAS_MAP.get(normalized, normalized)
    return canonical if canonical in _CANONICAL_TOOL_NAMES else None


def _canonical_tool_name_from_facet(facet: FacetPlan) -> str | None:
    tool_name = _canonical_tool_name(getattr(facet, "tool_name", None))
    if tool_name:
        return tool_name

    source = _normalize_intent_key(getattr(facet, "source", None))
    facet_name = _normalize_intent_key(getattr(facet, "name", None))
    execution_mode = _normalize_intent_key(getattr(facet, "execution_mode", None))
    required_target = _normalize_intent_key(getattr(facet, "required_target", None))

    if source == "recommendation" or required_target == "multi_shop" or execution_mode in {"recommendation_tool", "comparison_tool"}:
        return "search_restaurants"

    return _canonical_tool_name(facet_name)


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
        "restaurant_booking": "create_booking",
        "local_life_booking": "create_booking",
        "booking": "create_booking",
        "book": "create_booking",
        "restaurant_order_status": "get_order_status",
        "local_life_order_status": "get_order_status",
        "order_status": "get_order_status",
        "order": "create_order",
        "cancel": "cancel_order",
        "refund": "refund_order",
        "status": "get_order_status",
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
        tool_name = _canonical_tool_name(slot_data.pop("tool_name", None))
        intent_key = _normalize_intent_key(intent)
        if not tool_name and intent_key:
            tool_name = _canonical_tool_name(self._intent_tool_map.get(intent_key))
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

    def plan_from_facets(
        self,
        facet_plans: list[FacetPlan],
        slots: dict[str, object] | None = None,
    ) -> list[ToolSelection]:
        """直接从 FacetPlan 列表生成 ToolSelection，绕过 intent 映射。

        这里不再信任 FacetPlan.tool_name 作为最终决策，只按 facet 名称、
        source、execution_mode 和 required_target 做 canonical 映射。
        """
        selections: list[ToolSelection] = []
        slot_data = dict(slots or {})
        for fp in facet_plans:
            if fp.source not in {"tool", "recommendation"} and _normalize_intent_key(fp.execution_mode) not in {"single_shop_tool", "recommendation_tool", "comparison_tool", "transaction_tool"}:
                continue
            canonical_tool_name = _canonical_tool_name_from_facet(fp)
            if not canonical_tool_name:
                continue
            input_payload = dict(slot_data)
            input_payload.pop("tool_name", None)
            input_payload.pop("tool_input", None)
            selections.append(ToolSelection(
                tool_name=canonical_tool_name,
                input_payload=input_payload,
                reason=f"facet_plan:{fp.name}",
                approval_required=canonical_tool_name in self.APPROVAL_REQUIRED_TOOLS,
                approval_status="pending_approval" if canonical_tool_name in self.APPROVAL_REQUIRED_TOOLS else None,
                approval_request={
                    "tool_name": canonical_tool_name,
                    "reason": f"facet_plan:{fp.name}",
                    "risk_level": "high" if canonical_tool_name in {"cancel_order", "refund_order"} else "medium",
                    "approval_state": "pending_approval",
                    "tool_input": dict(input_payload),
                }
                if canonical_tool_name in self.APPROVAL_REQUIRED_TOOLS
                else {},
            ))
        return selections
