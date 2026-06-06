from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from learning_agent_service.domain import (
    NormalizedToolResult,
    SseEnvelope,
    ToolExecutionCommand,
    ToolExecutionResult,
    ToolNormalizationRequest,
    ToolPlanningRequest,
    ToolSelection,
)
from learning_agent_service.domain.enums import IntentType, ToolExecutionStatus

from .builtin import build_builtin_tool_registry
from .executor import ToolExecutor as BaseToolExecutor
from .models import ToolExecutionResult as BaseExecutionResult
from .models import ToolSelection as BaseToolSelection
from .normalizer import ToolResultNormalizer as BaseToolResultNormalizer
from .planner import ToolPlanner as BaseToolPlanner
from .registry import ToolRegistry
from .transaction_store import InMemoryTransactionStore


def build_default_tool_registry(
    *,
    java_business_client: Any | None = None,
    transaction_store: InMemoryTransactionStore | None = None,
) -> ToolRegistry:
    return build_builtin_tool_registry(
        java_business_client=java_business_client,
        transaction_store=transaction_store,
    )


def _run_async_safely(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coroutine)
        except BaseException as exc:  # pragma: no cover
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _is_clarification_kind(response_kind: str | None) -> bool:
    kind = (response_kind or "").strip().lower()
    return kind in {"empty", "low_info"}


class _StreamEventRelay:
    def __init__(self, downstream: Any) -> None:
        self._downstream = downstream
        self.count = 0

    def __call__(self, envelope: SseEnvelope) -> None:
        self._forward(envelope)

    def put(self, envelope: SseEnvelope) -> None:
        self._forward(envelope)

    def _forward(self, envelope: SseEnvelope) -> None:
        self.count += 1
        downstream = self._downstream
        if callable(downstream):
            downstream(envelope)
            return
        put = getattr(downstream, "put", None)
        if callable(put):
            put(envelope)


def _map_status(result: BaseExecutionResult) -> ToolExecutionStatus:
    if result.status == "ok":
        return ToolExecutionStatus.SUCCESS
    if result.status == "pending_approval":
        return ToolExecutionStatus.PENDING_APPROVAL
    if result.status == "rejected":
        return ToolExecutionStatus.REJECTED
    if result.degraded:
        return ToolExecutionStatus.DEGRADED
    return ToolExecutionStatus.FAILED


def _normalize_key(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if raw_value is None:
        return None
    text = str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")
    return text or None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slot_value(slots: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in slots:
            value = slots.get(key)
            if value not in (None, "", [], {}, ()):
                return value
    return None


def _slot_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            return {}
    return {}


def _slot_text(slots: Mapping[str, Any], *keys: str) -> str | None:
    value = _slot_value(slots, *keys)
    return _normalize_key(value)


def _slot_list(slots: Mapping[str, Any], *keys: str) -> list[Any]:
    value = _slot_value(slots, *keys)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        if not value.strip():
            return []
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value.strip()]
    return [value]


_LOCAL_LIFE_CANONICAL_INTENTS = {
    "restaurant_recommendation",
    "local_life_recommendation",
    "restaurant_comparison",
    "local_life_comparison",
    "restaurant_detail",
    "local_life_detail",
    "restaurant_coupon",
    "local_life_coupon",
    "restaurant_blog",
    "local_life_blog",
    "restaurant_shop_type",
    "local_life_shop_type",
    "restaurant_distance_eta",
    "local_life_distance_eta",
    "restaurant_open_status",
    "local_life_open_status",
    "restaurant_navigation",
    "local_life_navigation",
    "restaurant_booking",
    "local_life_booking",
    "restaurant_order_status",
    "local_life_order_status",
}

_LOCAL_LIFE_GENERIC_ACTION_MAP = {
    "recommend": "restaurant_recommendation",
    "compare": "restaurant_comparison",
    "detail": "restaurant_detail",
    "coupon": "restaurant_coupon",
    "blog": "restaurant_blog",
    "shop_type": "restaurant_shop_type",
    "distance_eta": "restaurant_distance_eta",
    "open_status": "restaurant_open_status",
    "navigation": "restaurant_navigation",
    "book": "restaurant_booking",
    "booking": "restaurant_booking",
    "order_status": "get_order_status",
    "order": "create_order",
    "create_order": "create_order",
    "create_booking": "create_booking",
    "cancel": "cancel_order",
    "cancel_order": "cancel_order",
    "refund": "refund_order",
    "refund_order": "refund_order",
    "status": "get_order_status",
    "get_order_status": "get_order_status",
}

_LOCAL_LIFE_TOOL_NAMES = {
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

_APPROVAL_REQUIRED_TOOLS = {
    "create_booking",
    "create_order",
    "cancel_order",
    "refund_order",
}

_P0_RESERVED_WRITE_TOOLS = {
    "create_booking",
    "create_order",
    "cancel_order",
    "refund_order",
}

_LEGACY_INTENT_MAP = {
    IntentType.RECOMMEND.value: "recommend",
    IntentType.FOLLOW_UP.value: "detail",
}


def _looks_like_local_life_slots(slots: Mapping[str, Any]) -> bool:
    if not slots:
        return False
    if _normalize_key(slots.get("domain")) in {"local_life", "local-life", "local"}:
        return True
    for key in ("city", "location", "price", "scene", "preferences", "avoid", "shop_ids", "shop_id", "shop_name", "category"):
        if key in slots and slots.get(key) not in (None, "", [], {}, ()):
            return True
    return False


def _detect_transaction_tool_name(raw_query: str) -> str | None:
    text = (raw_query or "").replace(" ", "")
    if any(token in text for token in ("退款", "退钱", "退回")):
        return "refund_order"
    if any(token in text for token in ("取消", "撤销", "退订")):
        return "cancel_order"
    if any(token in text for token in ("下单", "购买", "买单", "支付")):
        return "create_order"
    if any(token in text for token in ("订座", "预约", "预订", "订位")):
        return "create_booking"
    if "订单" in text:
        return "get_order_status"
    return None


def _resolve_planner_intent(request: ToolPlanningRequest, slots: Mapping[str, Any]) -> str | None:
    transaction_tool_name = _detect_transaction_tool_name(request.raw_query)
    if transaction_tool_name:
        return transaction_tool_name

    slot_tool_name = _normalize_key(_slot_value(slots, "tool_name"))
    slot_intent = _normalize_key(_slot_value(slots, "local_life_intent", "local_life_action", "intent", "action", "mode"))
    request_intent = _normalize_key(request.intent)

    if slot_tool_name in _LOCAL_LIFE_TOOL_NAMES:
        return slot_tool_name
    if slot_intent in _LOCAL_LIFE_TOOL_NAMES:
        return slot_intent
    if request_intent in _LOCAL_LIFE_TOOL_NAMES:
        return request_intent

    if slot_intent in _LOCAL_LIFE_CANONICAL_INTENTS:
        return slot_intent
    if request_intent in _LOCAL_LIFE_CANONICAL_INTENTS:
        return request_intent

    direct_local_life_intents = {
        "recommend": "restaurant_recommendation",
        "compare": "restaurant_comparison",
        "detail": "restaurant_detail",
        "coupon": "restaurant_coupon",
        "blog": "restaurant_blog",
        "shop_type": "restaurant_shop_type",
        "distance_eta": "restaurant_distance_eta",
        "open_status": "restaurant_open_status",
        "navigation": "restaurant_navigation",
        "booking": "restaurant_booking",
        "book": "restaurant_booking",
        "order_status": "restaurant_order_status",
        "order": "restaurant_order_status",
    }
    if slot_intent in direct_local_life_intents:
        return direct_local_life_intents[slot_intent]
    if request_intent in direct_local_life_intents:
        return direct_local_life_intents[request_intent]

    if _looks_like_local_life_slots(slots):
        if slot_intent in _LOCAL_LIFE_GENERIC_ACTION_MAP:
            return _LOCAL_LIFE_GENERIC_ACTION_MAP[slot_intent]
        if request_intent in _LOCAL_LIFE_GENERIC_ACTION_MAP:
            return _LOCAL_LIFE_GENERIC_ACTION_MAP[request_intent]

    if request_intent in _LEGACY_INTENT_MAP:
        return _LEGACY_INTENT_MAP[request_intent]
    if slot_intent in _LEGACY_INTENT_MAP:
        return _LEGACY_INTENT_MAP[slot_intent]

    return request_intent or slot_intent


def _build_local_life_tool_input(tool_name: str, request: ToolPlanningRequest, slots: Mapping[str, Any]) -> dict[str, Any]:
    normalized_tool_name = _normalize_key(tool_name) or tool_name
    if normalized_tool_name in {"search_restaurants", "restaurant_recommendation", "local_life_recommendation", "restaurant_comparison", "local_life_comparison"}:
        location = _slot_mapping(_slot_value(slots, "location"))
        price = _slot_mapping(_slot_value(slots, "price"))
        preferences = list(_slot_list(slots, "preferences"))
        avoid = list(_slot_list(slots, "avoid"))
        scene = _slot_value(slots, "scene")
        if isinstance(scene, str):
            scene = scene.strip() or None
        city = _slot_value(slots, "city") or location.get("city")
        lat = _slot_value(slots, "lat") or location.get("lat")
        lng = _slot_value(slots, "lng") or location.get("lng")
        radius_km = _slot_value(slots, "radius_km") or location.get("radius_km") or 3.0
        shop_ids = _slot_list(slots, "shop_ids")
        scene_tags = list(_slot_list(slots, "scene_tags"))
        if _normalize_key(scene) and _normalize_key(scene) not in scene_tags:
            scene_tags.append(_normalize_key(scene))
        if "quiet" in preferences and "quiet" not in scene_tags:
            scene_tags.append("quiet")
        if "parking_available" in preferences and "parking" not in scene_tags:
            scene_tags.append("parking")
        return {
            "query": _slot_value(slots, "query") or request.raw_query,
            "city": city,
            "lat": lat,
            "lng": lng,
            "radius_km": float(radius_km or 3.0),
            "category": _slot_value(slots, "category"),
            "shop_query": _slot_value(slots, "shop_query", "shop_name", "name"),
            "shop_ids": [
                int(value)
                for value in shop_ids
                if str(value).strip() != "" and str(value).strip().lstrip("-").isdigit()
            ],
            "price_min": _slot_value(slots, "price_min") or price.get("per_person_min"),
            "price_max": _slot_value(slots, "price_max") or price.get("per_person_max"),
            "target_price": _slot_value(slots, "target_price") or price.get("target"),
            "scene": scene,
            "scene_tags": scene_tags,
            "companions": list(_slot_list(slots, "companions")),
            "preferences": preferences,
            "avoid": avoid,
            "need_open_now": bool(_slot_value(slots, "need_open_now") or _slot_value(slots, "open_now")),
            "need_parking": bool(_slot_value(slots, "need_parking") or ("parking_available" in preferences)),
            "need_quiet": bool(_slot_value(slots, "need_quiet") or ("quiet" in preferences)),
            "need_family_friendly": bool(_slot_value(slots, "need_family_friendly") or _normalize_key(scene) == "family_dinner"),
            "need_elder_friendly": bool(_slot_value(slots, "need_elder_friendly") or ("elder_friendly" in preferences)),
            "limit": int(_slot_value(slots, "limit") or 5),
            "page": _slot_value(slots, "page"),
        }

    if normalized_tool_name in {"get_shop_detail", "restaurant_detail", "local_life_detail"}:
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "query": _slot_value(slots, "query") or request.raw_query,
            "lat": _slot_value(slots, "lat"),
            "lng": _slot_value(slots, "lng"),
            "current": int(_slot_value(slots, "current") or 1),
        }

    if normalized_tool_name in {"create_booking", "restaurant_booking", "local_life_booking"}:
        time_slot = _slot_mapping(_slot_value(slots, "time"))
        companions = _slot_list(slots, "companions")
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "booking_time": _slot_value(slots, "booking_time") or time_slot.get("preferred_time") or time_slot.get("date"),
            "party_size": int(_slot_value(slots, "party_size") or (len(companions) + 1 if companions else 2)),
            "contact_name": _slot_value(slots, "contact_name"),
            "contact_phone": _slot_value(slots, "contact_phone"),
            "note": _slot_value(slots, "note") or request.raw_query,
            "current": int(_slot_value(slots, "current") or 1),
        }

    if normalized_tool_name in {"create_order"}:
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "amount": _slot_value(slots, "amount") or _slot_value(slots, "target_price"),
            "note": _slot_value(slots, "note") or request.raw_query,
            "contact_name": _slot_value(slots, "contact_name"),
            "contact_phone": _slot_value(slots, "contact_phone"),
            "current": int(_slot_value(slots, "current") or 1),
        }

    if normalized_tool_name in {"cancel_order", "refund_order", "get_order_status"}:
        return {
            "order_id": _slot_value(slots, "order_id", "selected_order_id", "booking_id", "selected_booking_id"),
            "reason": _slot_value(slots, "reason") or request.raw_query,
        }

    if normalized_tool_name in {"get_shop_type_list", "restaurant_shop_type", "local_life_shop_type"}:
        return {"limit": int(_slot_value(slots, "limit") or 20)}

    if normalized_tool_name in {"get_coupon_list", "restaurant_coupon", "local_life_coupon"}:
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "limit": int(_slot_value(slots, "limit") or 10),
        }

    if normalized_tool_name in {"get_blog_list", "restaurant_blog", "local_life_blog"}:
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "user_id": _slot_value(slots, "user_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "current": int(_slot_value(slots, "current") or 1),
            "limit": int(_slot_value(slots, "limit") or 5),
        }

    if normalized_tool_name in {"get_distance_eta", "restaurant_distance_eta", "local_life_distance_eta", "restaurant_navigation", "local_life_navigation"}:
        location = _slot_mapping(_slot_value(slots, "location"))
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "lat": _slot_value(slots, "lat") or location.get("lat"),
            "lng": _slot_value(slots, "lng") or location.get("lng"),
            "shop_lat": _slot_value(slots, "shop_lat"),
            "shop_lng": _slot_value(slots, "shop_lng"),
            "mode": _slot_value(slots, "mode") or "drive",
            "speed_kmh": _slot_value(slots, "speed_kmh"),
        }

    if normalized_tool_name in {"check_open_status", "restaurant_open_status", "local_life_open_status"}:
        return {
            "shop_id": _slot_value(slots, "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "open_hours": _slot_value(slots, "open_hours"),
        }

    topic = _slot_value(slots, "topic") or request.current_topic or request.raw_query
    return {"topic": topic}


def _build_approval_request(tool_name: str, input_payload: Mapping[str, Any], reason: str | None = None) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "reason": reason or "approval_required",
        "risk_level": "high" if tool_name in {"cancel_order", "refund_order"} else "medium",
        "approval_state": "pending_approval",
        "tool_input": dict(input_payload),
    }


def _build_reserved_p0_approval_request(tool_name: str, input_payload: Mapping[str, Any]) -> dict[str, Any]:
    request = _build_approval_request(tool_name, input_payload, reason="not_enabled_in_p0")
    request["approval_state"] = "not_enabled_in_p0"
    request["message"] = "当前 P0 版本仅保留写工具能力定义，暂不直接执行该操作。"
    return request


def _tool_data(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _looks_like_no_result(tool_name: str | None, payload: Mapping[str, Any] | None) -> bool:
    data = _tool_data(payload)
    if not data:
        return False
    status = str(data.get("status") or "").strip().lower()
    if status in {"not_found", "empty", "no_result"}:
        return True
    if data.get("found") is False:
        return True
    if tool_name == "search_restaurants":
        return int(data.get("candidate_count") or 0) <= 0
    if tool_name == "get_coupon_list":
        return int(data.get("count") or 0) <= 0
    if tool_name == "get_blog_list":
        return int(data.get("count") or 0) <= 0
    if tool_name == "get_shop_type_list":
        return int(data.get("count") or 0) <= 0
    if tool_name == "get_shop_detail":
        return not isinstance(data.get("shop"), Mapping)
    if tool_name == "get_order_status":
        order = data.get("order")
        if not isinstance(order, Mapping):
            return True
        return str(order.get("status") or "").strip().lower() in {"not_found", "missing", "unknown"}
    return False


def _has_business_evidence(tool_name: str | None, payload: Mapping[str, Any] | None) -> bool:
    data = _tool_data(payload)
    if not data or _looks_like_no_result(tool_name, payload):
        return False
    if tool_name == "search_restaurants":
        return int(data.get("candidate_count") or 0) > 0
    if tool_name == "get_shop_detail":
        return isinstance(data.get("shop"), Mapping)
    if tool_name == "get_coupon_list":
        return int(data.get("count") or 0) > 0
    if tool_name == "get_order_status":
        order = data.get("order")
        return isinstance(order, Mapping) and bool(order)
    if tool_name == "get_shop_type_list":
        return int(data.get("count") or 0) > 0
    if tool_name == "get_blog_list":
        return int(data.get("count") or 0) > 0
    if tool_name in {"get_distance_eta", "check_open_status"}:
        return bool(data)
    return bool(data)


def _classify_tool_failure(
    *,
    tool_name: str | None,
    status: ToolExecutionStatus,
    payload: Mapping[str, Any] | None,
    errors: Mapping[str, Any] | None,
    approval_required: bool,
    approval_status: str | None,
) -> str | None:
    approval_state = str(approval_status or "").strip().lower()
    if status == ToolExecutionStatus.PENDING_APPROVAL or approval_state == "not_enabled_in_p0":
        return "approval_required"
    if status == ToolExecutionStatus.REJECTED or approval_state in {"rejected", "deny", "denied"}:
        return "permission_denied"
    if _looks_like_no_result(tool_name, payload):
        return "no_result"

    error_code = str((errors or {}).get("code") or "").strip().upper()
    error_message = str((errors or {}).get("message") or "").strip().lower()
    if error_code == "LEARN-5301" or "timed out" in error_message or "timeout" in error_message:
        return "timeout"
    if "not found" in error_message:
        return "no_result"
    if approval_required and approval_state in {"forbidden", "unauthorized"}:
        return "permission_denied"
    if any(
        token in error_message
        for token in (
            "unavailable",
            "not configured",
            "dependency",
            "backend is missing",
            "write failed",
            "service temporarily unavailable",
        )
    ):
        return "dependency_unavailable"
    return None


@dataclass
class ToolPlanner:
    planner: BaseToolPlanner | None = None

    def __post_init__(self) -> None:
        if self.planner is None:
            self.planner = BaseToolPlanner(
                {
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
                    "booking": "create_booking",
                    "order": "create_order",
                    "cancel": "cancel_order",
                    "refund": "refund_order",
                    "status": "get_order_status",
                }
            )

    def plan(self, request: ToolPlanningRequest) -> ToolSelection:
        routing = getattr(request, "routing_decision", None)
        required_action = str(getattr(routing, "required_action", "") or "").strip().lower()
        legacy_decision = str(getattr(request, "decision", "") or "").strip().lower()
        need_tool = required_action in {"tool_call", "rag_plus_tool"} or legacy_decision == "tool_then_answer"
        slots = dict(request.slots)
        slots.setdefault("topic", request.current_topic or request.raw_query)
        slot_approval_status = str(_slot_value(slots, "approval_status", "approval_decision") or "").strip().lower() or None
        slot_approval_request = dict(_slot_mapping(_slot_value(slots, "approval_request")))
        resolved_intent = _resolve_planner_intent(request, slots)
        slots.setdefault("tool_input", {"topic": slots.get("topic")})
        planning_meta = {
            "decision": required_action or str(request.decision),
            "requested_intent": _normalize_key(request.intent),
            "resolved_intent": resolved_intent,
            "need_tool": need_tool,
            "current_topic": request.current_topic,
            "raw_query": request.raw_query,
        }
        if not need_tool:
            return ToolSelection(
                tool_name=None,
                should_execute=False,
                reason="decision_not_tool_then_answer",
                approval_status=None,
                approval_request={},
                extra={**planning_meta, "planning_state": "not_required"},
            )
        planner = self.planner
        assert planner is not None
        selection = planner.plan(resolved_intent, need_tool, slots)
        if selection is None and resolved_intent in _LOCAL_LIFE_TOOL_NAMES:
            approval_required = resolved_intent in _APPROVAL_REQUIRED_TOOLS
            input_payload: dict[str, Any] = _build_local_life_tool_input(resolved_intent, request, slots)
            approval_request: dict[str, Any] = slot_approval_request or _build_approval_request(
                resolved_intent,
                input_payload,
                reason="planned_from_local_life_intent",
            )
            return ToolSelection(
                tool_name=resolved_intent,
                should_execute=True,
                input_payload=input_payload,
                reason="direct-local-life-tool",
                approval_required=approval_required,
                approval_status=slot_approval_status if approval_required else None,
                approval_request=approval_request,
                extra={
                    **planning_meta,
                    "planning_state": "direct_local_life_tool",
                    "selection_source": "direct_local_life_tool",
                    "tool_call_id": str(uuid.uuid4()),
                    "approval_required": approval_required,
                    "approval_request": approval_request,
                    "approval_status": (
                        slot_approval_status
                        if approval_required and slot_approval_status
                        else ("pending_approval" if approval_required else None)
                    ),
                },
            )
        if selection is None:
            return ToolSelection(
                tool_name=None,
                should_execute=False,
                reason="no_tool_mapping",
                approval_status=None,
                approval_request={},
                extra={**planning_meta, "planning_state": "no_tool_mapping", "selection_source": "base_planner"},
            )
        if resolved_intent and selection.tool_name in _LOCAL_LIFE_TOOL_NAMES:
            selection = selection.model_copy(
                update={
                    "input_payload": _build_local_life_tool_input(selection.tool_name, request, slots),
                }
            )
        approval_required = selection.tool_name in _APPROVAL_REQUIRED_TOOLS
        approval_request = slot_approval_request or _build_approval_request(selection.tool_name, selection.input_payload, reason=selection.reason)
        approval_status = slot_approval_status or getattr(selection, "approval_status", None)
        return ToolSelection(
            tool_name=selection.tool_name,
            should_execute=True,
            input_payload=selection.input_payload,
            reason=selection.reason,
            approval_required=approval_required or bool(getattr(selection, "approval_required", False)),
            approval_status=approval_status,
            approval_request=approval_request if approval_required else dict(getattr(selection, "approval_request", {}) or {}),
            extra={
                **planning_meta,
                "planning_state": "mapped",
                "selection_source": "base_planner",
                "tool_call_id": str(uuid.uuid4()),
                "timeout_ms": selection.timeout_ms,
                "degrade_to": selection.degrade_to,
                "approval_required": approval_required or bool(getattr(selection, "approval_required", False)),
                "approval_request": approval_request if approval_required else dict(getattr(selection, "approval_request", {}) or {}),
                "approval_status": (
                    approval_status
                    if approval_required and approval_status
                    else ("pending_approval" if approval_required else getattr(selection, "approval_status", None))
                ),
            },
        )

    def plan_from_name(self, tool_name: str, input_payload: dict[str, Any]) -> ToolSelection:
        approval_required = tool_name in _APPROVAL_REQUIRED_TOOLS
        return ToolSelection(
            tool_name=tool_name,
            should_execute=True,
            input_payload=input_payload,
            reason="direct-endpoint",
            approval_required=approval_required,
            approval_status="pending_approval" if approval_required else None,
            approval_request=_build_approval_request(tool_name, input_payload, reason="direct-endpoint") if approval_required else {},
            extra={
                "tool_call_id": str(uuid.uuid4()),
                "approval_required": approval_required,
                "approval_request": _build_approval_request(tool_name, input_payload, reason="direct-endpoint") if approval_required else {},
                "approval_status": "pending_approval" if approval_required else None,
            },
        )


@dataclass(kw_only=True)
class ToolExecutor:
    java_business_client: Any | None = None
    transaction_store: InMemoryTransactionStore | None = None
    registry: ToolRegistry | None = None
    executor: BaseToolExecutor | None = None

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = build_default_tool_registry(
                java_business_client=self.java_business_client,
                transaction_store=self.transaction_store,
            )
        if self.executor is None:
            self.executor = BaseToolExecutor(self.registry)

    def execute(self, command: ToolExecutionCommand) -> ToolExecutionResult:
        selection = command.selection
        if not selection.tool_name or not selection.should_execute:
            return ToolExecutionResult(
                tool_name=selection.tool_name or "",
                status=ToolExecutionStatus.SKIPPED,
                output_payload={},
                degraded_to=None,
                error=None,
                approval_required=False,
                approval_status=None,
                approval_request={},
            )
        if selection.tool_name in _P0_RESERVED_WRITE_TOOLS:
            approval_request = _build_reserved_p0_approval_request(
                selection.tool_name,
                selection.input_payload,
            )
            return ToolExecutionResult(
                status=ToolExecutionStatus.PENDING_APPROVAL,
                tool_name=selection.tool_name,
                output_payload={},
                degraded_to=None,
                error=None,
                approval_required=True,
                approval_status="not_enabled_in_p0",
                approval_request=approval_request,
                extra={
                    "tool_call_id": (selection.extra or {}).get("tool_call_id"),
                    "error_code": "LEARN-5305",
                    "error_message": "Tool is reserved and not enabled in P0",
                    "retryable": False,
                    "degraded": False,
                    "degrade_to": None,
                    "duration_ms": 0,
                    "approval_required": True,
                    "approval_status": "not_enabled_in_p0",
                    "approval_request": approval_request,
                    "failure_category": "approval_required",
                    "reserved": True,
                    "p0_enabled": False,
                },
            )

        base_selection = BaseToolSelection(
            tool_name=selection.tool_name,
            input_payload=selection.input_payload,
            reason=selection.reason,
            degrade_to=(selection.extra or {}).get("degrade_to"),
            timeout_ms=(selection.extra or {}).get("timeout_ms"),
            approval_required=bool(getattr(selection, "approval_required", False) or (selection.extra or {}).get("approval_required")),
            approval_status=getattr(selection, "approval_status", None) or (selection.extra or {}).get("approval_status"),
            approval_request=dict(getattr(selection, "approval_request", {}) or (selection.extra or {}).get("approval_request", {})),
        )
        executor = self.executor
        assert executor is not None
        result = _run_async_safely(executor.execute(base_selection))
        extra = {
            "tool_call_id": (selection.extra or {}).get("tool_call_id"),
            "error_code": result.error_code,
            "error_message": result.error_message,
            "retryable": result.retryable,
            "degraded": result.degraded,
            "degrade_to": result.degrade_to,
            "duration_ms": result.duration_ms,
            "approval_required": result.approval_required,
            "approval_status": result.approval_status,
            "approval_request": result.approval_request,
        }
        return ToolExecutionResult(
            status=_map_status(result),
            tool_name=selection.tool_name,
            output_payload=result.output,
            degraded_to=result.degrade_to,
            error=None,
            approval_required=result.approval_required,
            approval_status=result.approval_status,
            approval_request=result.approval_request,
            extra=extra,
        )


@dataclass
class ToolResultNormalizer:
    normalizer: BaseToolResultNormalizer | None = None

    def __post_init__(self) -> None:
        if self.normalizer is None:
            self.normalizer = BaseToolResultNormalizer()

    def normalize(self, request: ToolNormalizationRequest) -> NormalizedToolResult:
        result = request.result
        extra = dict(result.extra)
        payload = BaseExecutionResult(
            tool_name=result.tool_name or "",
            status="ok" if result.status == ToolExecutionStatus.SUCCESS else str(result.status),
            output=result.output_payload,
            error_code=extra.get("error_code"),
            error_message=extra.get("error_message"),
            retryable=bool(extra.get("retryable")),
            degraded=bool(extra.get("degraded")) or result.status == ToolExecutionStatus.DEGRADED,
            degrade_to=extra.get("degrade_to"),
            duration_ms=int(extra.get("duration_ms") or 0),
            approval_required=bool(extra.get("approval_required")),
            approval_status=extra.get("approval_status"),
            approval_request=dict(extra.get("approval_request") or {}),
        )
        normalizer = self.normalizer
        assert normalizer is not None
        normalized = normalizer.normalize(payload)
        normalized_payload = dict(normalized.payload or {})
        if normalized.tool_name == "get_coupon_list":
            data = normalized_payload.get("data")
            if isinstance(data, Mapping):
                data_dict = dict(data)
                couponsns = data_dict.pop("couponsns", None)
                if "coupons" not in data_dict and couponsns is not None:
                    data_dict["coupons"] = couponsns
                if "count" not in data_dict:
                    coupons_value = data_dict.get("coupons")
                    if isinstance(coupons_value, list):
                        data_dict["count"] = len(coupons_value)
                normalized_payload["data"] = data_dict
        normalized = normalized.model_copy(update={"payload": normalized_payload})
        normalized_status = result.status if result.status in {
            ToolExecutionStatus.PENDING_APPROVAL,
            ToolExecutionStatus.REJECTED,
        } else ToolExecutionStatus.SUCCESS if normalized.ok else result.status
        used_tools = [normalized.tool_name] if normalized.tool_name else []
        failure_category = _classify_tool_failure(
            tool_name=normalized.tool_name,
            status=normalized_status,
            payload=normalized.payload,
            errors=normalized.errors,
            approval_required=payload.approval_required,
            approval_status=payload.approval_status,
        )
        grounding_source = "business_evidence" if _has_business_evidence(normalized.tool_name, normalized.payload) else "not_grounded"
        return NormalizedToolResult(
            status=normalized_status,
            tool_name=normalized.tool_name,
            normalized_output=normalized.payload,
            used_tools=used_tools,
            approval_required=payload.approval_required,
            approval_status=payload.approval_status,
            approval_request=payload.approval_request,
            extra={
                "errors": normalized.errors,
                "degraded": normalized.degraded,
                "retryable": normalized.retryable,
                "degrade_to": normalized.degrade_to,
                "approval_required": payload.approval_required,
                "approval_status": payload.approval_status,
                "approval_request": payload.approval_request,
                "failure_category": failure_category,
                "grounding_source": grounding_source,
                "reserved": bool(extra.get("reserved")),
                "p0_enabled": extra.get("p0_enabled", True),
            },
        )
__all__ = [name for name in globals() if not name.startswith("__")]
