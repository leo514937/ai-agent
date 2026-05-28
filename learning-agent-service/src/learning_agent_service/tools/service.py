from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from learning_agent_service.config import Settings
from learning_agent_service.application.rag_gate import compose_direct_response_text
from learning_agent_service.application.routing import build_clarification_question
from learning_agent_service.domain import (
    AnswerComposeRequest,
    AnswerComposeResult,
    EvidenceQualityDecision,
    NormalizedToolResult,
    SseEnvelope,
    ToolExecutionCommand,
    ToolExecutionResult,
    ToolNormalizationRequest,
    ToolPlanningRequest,
    ToolSelection,
)
from learning_agent_service.domain.enums import IntentType, OutputStyle, ToolExecutionStatus

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

    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}

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


def _is_clarification_kind(response_kind: Optional[str]) -> bool:
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


def _normalize_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if raw_value is None:
        return None
    text = str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")
    return text or None


def _slot_value(slots: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in slots:
            value = slots.get(key)
            if value not in (None, "", [], {}, ()):
                return value
    return None


def _slot_mapping(value: Any) -> Dict[str, Any]:
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


def _slot_text(slots: Mapping[str, Any], *keys: str) -> Optional[str]:
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


def _detect_transaction_tool_name(raw_query: str) -> Optional[str]:
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


def _resolve_planner_intent(request: ToolPlanningRequest, slots: Mapping[str, Any]) -> Optional[str]:
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


def _build_local_life_tool_input(tool_name: str, request: ToolPlanningRequest, slots: Mapping[str, Any]) -> Dict[str, Any]:
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


def _build_approval_request(tool_name: str, input_payload: Mapping[str, Any], reason: str | None = None) -> Dict[str, Any]:
    return {
        "tool_name": tool_name,
        "reason": reason or "approval_required",
        "risk_level": "high" if tool_name in {"cancel_order", "refund_order"} else "medium",
        "approval_state": "pending_approval",
        "tool_input": dict(input_payload),
    }


def _build_reserved_p0_approval_request(tool_name: str, input_payload: Mapping[str, Any]) -> Dict[str, Any]:
    request = _build_approval_request(tool_name, input_payload, reason="not_enabled_in_p0")
    request["approval_state"] = "not_enabled_in_p0"
    request["message"] = "当前 P0 版本仅保留写工具能力定义，暂不直接执行该操作。"
    return request


def _tool_data(payload: Mapping[str, Any] | None) -> Dict[str, Any]:
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
                extra={**planning_meta, "planning_state": "not_required"},
            )
        selection = self.planner.plan(resolved_intent, need_tool, slots)
        if selection is None and resolved_intent in _LOCAL_LIFE_TOOL_NAMES:
            approval_required = resolved_intent in _APPROVAL_REQUIRED_TOOLS
            input_payload = _build_local_life_tool_input(resolved_intent, request, slots)
            approval_request = slot_approval_request or _build_approval_request(
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

    def plan_from_name(self, tool_name: str, input_payload: Dict[str, Any]) -> ToolSelection:
        approval_required = tool_name in _APPROVAL_REQUIRED_TOOLS
        return ToolSelection(
            tool_name=tool_name,
            should_execute=True,
            input_payload=input_payload,
            reason="direct-endpoint",
            approval_required=approval_required,
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
            return ToolExecutionResult(status=ToolExecutionStatus.SKIPPED)
        if selection.tool_name in _P0_RESERVED_WRITE_TOOLS:
            approval_request = _build_reserved_p0_approval_request(
                selection.tool_name,
                selection.input_payload,
            )
            return ToolExecutionResult(
                status=ToolExecutionStatus.PENDING_APPROVAL,
                tool_name=selection.tool_name,
                output_payload={},
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
        result = _run_async_safely(self.executor.execute(base_selection))
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
        normalized = self.normalizer.normalize(payload)
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


@dataclass
class AnswerComposer:
    llm_answerer: Optional[Callable[[AnswerComposeRequest], Mapping[str, Any] | str]] = None
    max_citations: int = 4

    def compose(self, request: AnswerComposeRequest) -> AnswerComposeResult:
        if request.allow_direct_response:
            routing = request.routing_decision
            if routing is not None and str(routing.required_action).strip().lower() == "clarify":
                answer_text = self._compose_clarify_response(request, routing)
            elif str(request.direct_response_kind or "").strip().lower() == "conversation_recap":
                answer_text = self._compose_conversation_recap_response(request)
            else:
                answer_text = compose_direct_response_text(
                    request.raw_query,
                    request.direct_response_kind,
                )
            confidence = 0.24 if (routing is not None and routing.required_action == "clarify") else 0.82
            return self._build_result(request, answer_text, confidence, already_streamed=False)

        routing = request.routing_decision
        rag_result = request.rag_result
        evidence_status = self._evidence_status(rag_result)
        evidence_quality = request.evidence_quality
        response_mode = str(
            request.final_response_mode
            or getattr(evidence_quality, "response_mode", "")
            or ""
        ).strip().lower()
        if response_mode == "ask_clarification":
            answer_text = self._compose_clarify_response(request, routing)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.2, already_streamed=False)
        if response_mode == "partial_grounded" and request.tool_result is None and rag_result is not None:
            answer_text = self._compose_partial_grounded_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.55, already_streamed=False)

        mixed_answer = self._compose_rag_plus_tool_answer(request)
        if mixed_answer is not None:
            confidence = 0.88 if request.tool_result is not None and request.rag_result is not None else 0.62
            return self._build_result(request, mixed_answer, confidence, already_streamed=False)

        tool_answer = self._compose_tool_answer(request)
        if tool_answer is not None:
            confidence = 0.86 if request.tool_result and request.tool_result.extra.get("grounding_source") == "business_evidence" else 0.42
            return self._build_result(request, tool_answer, confidence, already_streamed=False)

        if response_mode == "no_answer":
            answer_text = self._compose_no_answer(request, evidence_quality)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.08, already_streamed=False)
        if response_mode == "weak_answer":
            answer_text = self._compose_weak_answer(request)
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.38, already_streamed=False)

        if (
            self.llm_answerer is not None
            and evidence_status in {"EMPTY", "WEAK"}
            and request.plan_summary is None
            and request.tool_result is None
            and request.memory_injection_plan is None
            and not response_mode
        ):
            answer, already_streamed = self._compose_open_answer(request)
            if answer:
                confidence = 0.74 if evidence_status == "EMPTY" else 0.62
                return self._build_result(request, answer, confidence, already_streamed=already_streamed)
        if evidence_status == "EMPTY":
            action = str(getattr(routing, "required_action", "") or "").strip().lower()
            if action == "rag_plus_tool" or (request.tool_result is not None and request.tool_result.status == ToolExecutionStatus.SUCCESS):
                mixed_answer = self._compose_rag_plus_tool_answer(request)
                if mixed_answer is not None:
                    return self._build_result(request, mixed_answer, 0.62, already_streamed=False)
                tool_answer = self._compose_tool_answer(request)
                if tool_answer is not None:
                    return self._build_result(request, tool_answer, 0.42, already_streamed=False)
                fallback_ans = "我这边暂时没有查到这家店的详细评价依据或可用券信息。你可以放宽筛选范围，我继续帮你找。"
                return self._build_result(request, fallback_ans, 0.1, already_streamed=False)

            if self.llm_answerer is None:
                answer_text = self._compose_weak_answer(request)
            else:
                answer_text = "关于这部分业务数据，我暂时没有查到相关依据。要不我们先聊点别的？我知道很多好吃的店铺和省钱优惠券哦～ [Code: RAG_EMPTY_REFUSED]"
            if request.plan_summary is not None or request.tool_result is not None or request.memory_injection_plan is not None:
                answer_text = self._append_auxiliary_sections(request, answer_text, include_auxiliary=True)
            return self._build_result(request, answer_text, 0.05, already_streamed=False)

        if evidence_status == "OK":
            answer, already_streamed = self._compose_grounded_answer(request)
            if not answer:
                answer = self._grounded_fallback(request)
                already_streamed = False
            return self._build_result(
                request,
                answer,
                0.9 if self.llm_answerer is not None else 0.84,
                already_streamed=already_streamed,
            )

        answer = self._compose_weak_answer(request)
        return self._build_result(request, answer, 0.58, already_streamed=False)

    def _compose_open_answer(self, request: AnswerComposeRequest) -> tuple[str | None, bool]:
        payload = None
        already_streamed = False
        if self.llm_answerer is not None:
            try:
                stream_relay = _StreamEventRelay(request.stream_event_sink)
                request_with_relay = request.model_copy(update={"stream_event_sink": stream_relay})
                payload = self.llm_answerer(request_with_relay)
                already_streamed = stream_relay.count > 0
            except Exception:
                payload = None
        answer_text = self._extract_answer_text(payload)
        if not answer_text:
            return None, already_streamed
        return self._append_auxiliary_sections(request, answer_text, include_auxiliary=False), already_streamed

    def _compose_grounded_answer(self, request: AnswerComposeRequest) -> tuple[str, bool]:
        payload = None
        already_streamed = False
        if self.llm_answerer is not None:
            try:
                stream_relay = _StreamEventRelay(request.stream_event_sink)
                request_with_relay = request.model_copy(update={"stream_event_sink": stream_relay})
                payload = self.llm_answerer(request_with_relay)
                already_streamed = stream_relay.count > 0
            except Exception:
                payload = None
        answer_text = self._extract_answer_text(payload)
        if not answer_text:
            answer_text = self._grounded_fallback(request)
        citations = self._collect_citations(request)
        if citations:
            answer_text = self._ensure_citations(answer_text, citations)
        return self._append_auxiliary_sections(request, answer_text, include_auxiliary=True), already_streamed

    def _build_result(
        self,
        request: AnswerComposeRequest,
        answer_text: str,
        confidence: float,
        *,
        already_streamed: bool = False,
    ) -> AnswerComposeResult:
        normalized = str(answer_text or "").strip()

        if normalized and not already_streamed:
            self._emit_fallback_answer_stream(request, normalized)
        return AnswerComposeResult(answer_text=normalized, confidence=confidence)

    def _emit_fallback_answer_stream(self, request: AnswerComposeRequest, answer_text: str) -> None:
        stream_sink = request.stream_event_sink
        if stream_sink is None:
            return

        meta = dict(request.stream_event_meta or {})
        chunks = self._chunk_answer_text(answer_text)
        if not chunks:
            return

        accumulated = []
        for chunk in chunks:
            chunk = str(chunk or "")
            if not chunk.strip():
                continue
            accumulated.append(chunk)
            envelope = SseEnvelope(
                event_type="delta",
                trace_id=str(meta.get("trace_id") or ""),
                session_id=str(meta.get("session_id") or ""),
                turn_id=str(meta.get("turn_id") or ""),
                timestamp=datetime.now(timezone.utc),
                workflow_version=str(meta.get("workflow_version") or "learn-agent/v1"),
                payload={
                    "delta": chunk,
                    "answer_text": "".join(accumulated),
                    "current_stage": str(meta.get("current_stage") or "compose"),
                    "stage_status": str(meta.get("stage_status") or "streaming"),
                    "route_decision": meta.get("route_decision"),
                    "route_reason": meta.get("route_reason"),
                },
            )
            if callable(stream_sink):
                stream_sink(envelope)
                time.sleep(0.05)
                continue
            put = getattr(stream_sink, "put", None)
            if callable(put):
                put(envelope)
                time.sleep(0.05)

    @staticmethod
    def _chunk_answer_text(answer_text: str) -> List[str]:
        text = str(answer_text or "").strip()
        if not text:
            return []

        pieces = [piece for piece in re.split(r"(?<=[。！？!?；;\n])", text) if piece]
        if len(pieces) <= 1:
            size = 24
            return [text[i : i + size] for i in range(0, len(text), size)]

        chunks: List[str] = []
        for piece in pieces:
            if len(piece) <= 24:
                chunks.append(piece)
                continue
            chunks.extend(piece[i : i + 24] for i in range(0, len(piece), 24))
        return chunks

    def _compose_tool_answer(self, request: AnswerComposeRequest) -> str | None:
        tool_result = request.tool_result
        if tool_result is None or not tool_result.tool_name:
            return None
        failure_category = str(tool_result.extra.get("failure_category") or "").strip().lower()
        if failure_category == "no_tool_mapping":
            return (
                "这次我没能把这类本地生活请求稳定映射到具体工具，所以先不继续执行，避免误路由。"
                "你可以补充店名、城市、距离或想比较的对象，我再重新走一次工具链。"
            )
        if failure_category == "approval_required" or tool_result.status == ToolExecutionStatus.PENDING_APPROVAL:
            return (
                "这个操作还处于待确认状态。当前 P0 版本对下单、订座、取消、退款这类写操作只保留能力预留，"
                "暂时不直接代你执行。你可以先告诉我想确认的店铺或订单信息，我先帮你把可查的信息整理清楚。"
            )
        if failure_category == "permission_denied" or tool_result.status == ToolExecutionStatus.REJECTED:
            return "当前无权查看或执行这项操作。你可以先登录、补充校验信息，或确认当前账号是否有对应权限。"
        if failure_category == "timeout":
            return "刚才查询超时了。你可以稍后重试，我也可以先帮你缩小范围再查。"
        if failure_category == "dependency_unavailable":
            return "相关服务暂时不可用，这次还查不到结果。你可以稍后再试。"
        if failure_category == "no_result":
            return self._compose_no_result_answer(tool_result.tool_name, tool_result.normalized_output, request)
        if tool_result.status == ToolExecutionStatus.SUCCESS and tool_result.extra.get("grounding_source") == "business_evidence":
            return self._compose_tool_success_answer(tool_result.tool_name, tool_result.normalized_output, request)
        return None

    def _compose_rag_plus_tool_answer(self, request: AnswerComposeRequest) -> str | None:
        routing = request.routing_decision
        action = str(getattr(routing, "required_action", "") or "").strip().lower()
        if action != "rag_plus_tool":
            return None

        sections: list[str] = []
        coupon_answer = self._compose_tool_answer(request)
        if coupon_answer:
            sections.append(f"券信息：{coupon_answer}")

        environment_answer = self._compose_environment_answer(request)
        if environment_answer:
            sections.append(f"环境评价：{environment_answer}")

        if not sections:
            return None
        return "\n".join(sections)

    def _compose_environment_answer(self, request: AnswerComposeRequest) -> str | None:
        rag_result = request.rag_result
        if rag_result is None:
            return None

        evidence_pack = rag_result.evidence_pack
        items = list(evidence_pack.items if evidence_pack else [])
        evidence_status = self._evidence_status(rag_result)
        if not items:
            if evidence_status == "OK":
                return "评价证据有限，暂时没有足够信息判断环境。"
            return "评价证据有限，暂时不敢硬说环境好坏。"

        joined_text = " ".join(str(item.content or "") for item in items[:4]).strip()
        signals: list[str] = []
        if any(token in joined_text for token in ("安静", "不吵", "静")):
            signals.append("环境偏安静")
        if any(token in joined_text for token in ("包间", "私密", "隔音")):
            signals.append("私密性还可以")
        if any(token in joined_text for token in ("家庭聚餐", "聚餐", "带父母", "带长辈", "约会")):
            signals.append("比较适合家庭聚餐或约会")
        if any(token in joined_text for token in ("口碑", "评价不错", "氛围", "体验不错", "服务不错")):
            signals.append("整体口碑还不错")
        if any(token in joined_text for token in ("吵", "排队", "拥挤")):
            signals.append("高峰期可能会偏吵或偏挤")

        if signals:
            return "从评价看，" + "；".join(signals) + "。"

        snippets: list[str] = []
        for item in items[:2]:
            content = str(item.content or "").strip().replace("\n", " ")
            if not content:
                continue
            if len(content) > 96:
                content = content[:93].rstrip() + "..."
            snippets.append(content)
        if not snippets:
            return "评价证据有限，暂时没有足够信息判断环境。"
        if len(snippets) == 1:
            return f"评价里能看到：{snippets[0]}。"
        return f"评价里能看到：{snippets[0]}；{snippets[1]}。"

    def _compose_clarify_response(self, request: AnswerComposeRequest, routing: Any) -> str:
        question = str(getattr(routing, "clarification_question", "") or "").strip()
        if question:
            return question
        clarification_slot = str(getattr(routing, "clarification_slot", "") or getattr(request.evidence_quality, "clarification_slot", "") or request.clarification_slot or "").strip()
        missing_slots = list(getattr(routing, "missing_slots", None) or request.missing_slots or getattr(request.evidence_quality, "missing_slots", None) or [])
        slot_question = build_clarification_question(
            missing_slots,
            clarification_slot=clarification_slot or None,
            query_text=request.raw_query,
        )
        if slot_question:
            return slot_question
        kind = str(request.direct_response_kind or "").strip().lower()
        if kind:
            return compose_direct_response_text(request.raw_query, kind)
        return compose_direct_response_text(request.raw_query, "low_info")

    def _compose_conversation_recap_response(self, request: AnswerComposeRequest) -> str:
        summary = str(request.history_summary or "").strip()
        meta = dict(request.stream_event_meta or {})
        current_shop = str(meta.get("current_shop") or "").strip()
        if not current_shop and request.answer_contract is not None:
            current_shop = str(request.answer_contract.selected_entity or "").strip()
        if not current_shop and request.entity_join_result is not None:
            current_shop = str(request.entity_join_result.selected_entity or "").strip()
        if current_shop and summary:
            return f"我们刚才主要在聊{current_shop}：{summary}。如果你愿意，我可以继续接着这个话题说。"
        if current_shop:
            return f"我们刚才主要在聊{current_shop}。如果你愿意，我可以继续接着这个话题说。"
        if summary:
            return f"我们刚才主要在聊：{summary}。如果你愿意，我可以继续接着这个话题说。"
        return "我能记住我们刚才的上下文，但这一轮还没沉淀出可回顾的摘要。你可以再问我刚才那家店、刚才的券，或者让我继续接着说。"

    def _compose_partial_grounded_answer(self, request: AnswerComposeRequest) -> str:
        evidence_quality = request.evidence_quality
        covered_facets = list(getattr(evidence_quality, "covered_facets", None) or [])
        missing_facets = list(getattr(evidence_quality, "missing_facets", None) or [])
        slot_notes: list[str] = []
        if covered_facets:
            slot_notes.append(f"已确认：{'、'.join(covered_facets[:3])}")
        if missing_facets:
            slot_notes.append(f"暂未确认：{'、'.join(missing_facets[:3])}")
        intro = "目前只能先给你一个部分判断。"
        if slot_notes:
            intro = f"{intro} {'；'.join(slot_notes)}。"
        body = self._grounded_fallback(request)
        if body.startswith("噢，系统服务出现了一点小状况呢"):
            return body
        return self._append_auxiliary_sections(request, f"{intro}\n{body}", include_auxiliary=True)

    def _compose_no_result_answer(self, tool_name: str, payload: Mapping[str, Any], request: AnswerComposeRequest | None = None) -> str:
        data = _tool_data(payload)
        shop_name = str(data.get("shop_name") or "这家店").strip() or "这家店"
        concrete_shop_name = ""
        has_static_vouchers = False
        static_info = ""
        
        if request is not None:
            if request.answer_contract:
                if hasattr(request.answer_contract, "extra") and isinstance(request.answer_contract.extra, dict):
                    concrete_shop_name = request.answer_contract.extra.get("selected_shop_name") or request.answer_contract.extra.get("current_shop")
            if not concrete_shop_name and request.entity_join_result:
                extra_data = getattr(request.entity_join_result, "extra", {}) or {}
                if isinstance(extra_data, dict):
                    concrete_shop_name = extra_data.get("selected_shop_name") or extra_data.get("current_shop")
            if not concrete_shop_name and request.stream_event_meta:
                meta = dict(request.stream_event_meta)
                concrete_shop_name = meta.get("current_shop") or meta.get("selected_shop_name")
            if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
                for ev_item in request.rag_result.evidence_pack.items:
                    meta = getattr(ev_item, "metadata", {}) or {}
                    if isinstance(meta, dict) and (meta.get("shop_name") or meta.get("shopName")):
                        concrete_shop_name = meta.get("shop_name") or meta.get("shopName")
                        break

            if request.rag_result and request.rag_result.evidence_pack:
                for item in request.rag_result.evidence_pack.items:
                    content = str(item.content or "").strip()
                    meta = getattr(item, "metadata", {}) or {}
                    v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                    pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                    if v_count or pkg_desc:
                        has_static_vouchers = True
                        if v_count:
                            static_info += f"优惠券数量：{v_count}张 "
                        if pkg_desc:
                            static_info += f"套餐说明：{pkg_desc}"
                        break
                    elif "券" in content or "优惠" in content or "套餐" in content:
                        has_static_vouchers = True
                        static_info = "知识库中包含相关优惠或套餐描述"
                        break

        if concrete_shop_name:
            shop_name = concrete_shop_name

        if tool_name == "get_order_status":
            return "我这边还没查到对应的订单信息。你可以补充订单号，或者确认一下是不是查错了门店和订单。"
        if tool_name == "get_coupon_list":
            if has_static_vouchers:
                return f"{shop_name} 实时未查到可用券，可参考券存在（{static_info}）但需以实时接口为准。"
            return f"我这边还没查到 {shop_name} 可用的券。你可以换一家店，或者告诉我想看的店名和区域。"
        if tool_name == "get_shop_detail":
            return "我这边还没定位到你要看的门店。你可以补充店名、区域，或者直接给我店铺 id。"
        if tool_name == "search_restaurants":
            return "我这边暂时没筛到符合条件的门店。你可以放宽预算、距离或口味条件，我继续帮你找。"
        return "我这边还没查到对应结果。你可以补充更具体的对象、范围或条件，我继续帮你查。"

    def _compose_tool_success_answer(self, tool_name: str, payload: Mapping[str, Any], request: AnswerComposeRequest | None = None) -> str:
        data = _tool_data(payload)
        
        concrete_shop_name = ""
        has_static_vouchers = False
        static_info = ""
        
        if request is not None:
            if request.answer_contract:
                if hasattr(request.answer_contract, "extra") and isinstance(request.answer_contract.extra, dict):
                    concrete_shop_name = request.answer_contract.extra.get("selected_shop_name") or request.answer_contract.extra.get("current_shop")
            if not concrete_shop_name and request.entity_join_result:
                extra_data = getattr(request.entity_join_result, "extra", {}) or {}
                if isinstance(extra_data, dict):
                    concrete_shop_name = extra_data.get("selected_shop_name") or extra_data.get("current_shop")
            if not concrete_shop_name and request.stream_event_meta:
                meta = dict(request.stream_event_meta)
                concrete_shop_name = meta.get("current_shop") or meta.get("selected_shop_name")
            if not concrete_shop_name and request.rag_result and request.rag_result.evidence_pack:
                for ev_item in request.rag_result.evidence_pack.items:
                    meta = getattr(ev_item, "metadata", {}) or {}
                    if isinstance(meta, dict) and (meta.get("shop_name") or meta.get("shopName")):
                        concrete_shop_name = meta.get("shop_name") or meta.get("shopName")
                        break

            if request.rag_result and request.rag_result.evidence_pack:
                for item in request.rag_result.evidence_pack.items:
                    content = str(item.content or "").strip()
                    meta = getattr(item, "metadata", {}) or {}
                    v_count = meta.get("voucher_count") if isinstance(meta, dict) else None
                    pkg_desc = meta.get("package_description") if isinstance(meta, dict) else None
                    if v_count or pkg_desc:
                        has_static_vouchers = True
                        if v_count:
                            static_info += f"优惠券数量：{v_count}张 "
                        if pkg_desc:
                            static_info += f"套餐说明：{pkg_desc}"
                        break
                    elif "券" in content or "优惠" in content or "套餐" in content:
                        has_static_vouchers = True
                        static_info = "知识库中包含相关优惠或套餐描述"
                        break

        if tool_name == "search_restaurants":
            candidates = list(data.get("candidates") or [])
            names = [str(item.get("name") or "").strip() for item in candidates[:3] if isinstance(item, Mapping)]
            lead = "我先帮你筛到这些更匹配的门店："
            if names:
                lead = f"{lead}{'、'.join(name for name in names if name)}。"
            count = int(data.get('candidate_count') or len(candidates))
            return f"{lead} 当前一共命中 {count} 家，如果你愿意，我可以继续帮你细化到距离、价格或适合的场景。"
        if tool_name == "get_shop_detail":
            shop = data.get("shop") if isinstance(data.get("shop"), Mapping) else {}
            shop_name = str(shop.get("name") or "这家店").strip() or "这家店"
            if concrete_shop_name:
                shop_name = concrete_shop_name
            score = shop.get("score")
            avg_price = shop.get("avgPrice") or shop.get("avg_price")
            parts = [f"{shop_name} 的门店信息我查到了"]
            if score not in (None, ""):
                parts.append(f"评分大约 {score}")
            if avg_price not in (None, ""):
                parts.append(f"人均约 {avg_price} 元")
            open_status = data.get("open_status") if isinstance(data.get("open_status"), Mapping) else {}
            if str(open_status.get("open_status") or "").strip():
                parts.append(f"当前状态是 {open_status.get('open_status')}")
            return "，".join(parts) + "。"
        if tool_name == "get_coupon_list":
            shop_name = str(data.get("shop_name") or "这家店").strip() or "这家店"
            if concrete_shop_name:
                shop_name = concrete_shop_name
            coupons = list(data.get("coupons") or [])
            count = int(data.get("count") or len(coupons) or 0)
            if count <= 0 or not coupons:
                if has_static_vouchers:
                    return f"{shop_name} 实时未查到可用券，可参考券存在（{static_info}）但需以实时接口为准。"
                return f"{shop_name} 目前还没有可用券。你可以换一家店，或者告诉我想看的店名和区域。"
            summaries: list[str] = []
            for coupon in coupons[:3]:
                if not isinstance(coupon, Mapping):
                    continue
                title = str(coupon.get("title") or "").strip()
                pay_value = coupon.get("payValue")
                actual_value = coupon.get("actualValue")
                if title and pay_value not in (None, "") and actual_value not in (None, ""):
                    summaries.append(f"{title}（{pay_value} 元代 {actual_value} 元）")
                elif title:
                    summaries.append(title)
            body = "、".join(summaries) if summaries else "我已经查到可用券"
            return f"{shop_name} 当前能看到这些券：{body}。"
        if tool_name == "get_order_status":
            order = data.get("order") if isinstance(data.get("order"), Mapping) else {}
            order_id = str(order.get("order_id") or order.get("transaction_id") or "").strip()
            status = str(order.get("status") or data.get("status") or "unknown").strip()
            if order_id:
                return f"我查到订单 {order_id} 当前状态是 {status}。"
            return f"我查到这笔订单当前状态是 {status}。"
        if tool_name == "get_distance_eta":
            distance = data.get("distance_km")
            eta = data.get("eta_minutes")
            mode = str(data.get("mode") or "drive")
            return f"按 {mode} 方式估算，距离大约 {distance} 公里，预计 {eta} 分钟左右到。"
        if tool_name == "check_open_status":
            status = str(data.get("open_status") or "unknown")
            return f"我查到这家店当前状态是 {status}。"
        return "我已经根据业务数据查到结果了，如果你愿意，我可以继续往下帮你细化。"

    def _compose_weak_answer(self, request: AnswerComposeRequest) -> str:
        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        items = list(evidence_pack.items if evidence_pack else [])
        snippets = [item.content.strip() for item in items[:2] if item.content.strip()]
        if snippets:
            body = "根据当前知识库里的有限证据，我只能给出谨慎判断：{snippets}。如果你希望我继续，建议补充具体范围、版本或背景。".format(
                snippets="；".join(snippets)
            )
        else:
            body = compose_direct_response_text(request.raw_query, "empty")
        return self._append_auxiliary_sections(request, body, include_auxiliary=False)

    def _compose_no_answer(self, request: AnswerComposeRequest, evidence_quality: EvidenceQualityDecision | None) -> str:
        reason = str(getattr(evidence_quality, "reason", "") or "").strip()
        fallback_reason = str(getattr(evidence_quality, "fallback_reason", "") or "").strip()
        if reason in {"shop_mismatch", "geo_mismatch"}:
            body = "我暂时没有找到足够匹配的依据，没法可靠地直接下结论。你可以补充更具体的店名、区域或目标，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        elif reason == "required_role_missing":
            body = "目前缺少足够关键的证据类型，不能给出可信结论。你可以补充更具体的问题、店名、套餐或评价维度，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        elif fallback_reason:
            body = f"我暂时没有找到足够可靠的依据来回答这个问题。你可以补充更多上下文，我再继续帮你查。 [Code: RAG_NO_ANSWER:{fallback_reason}]"
        else:
            body = "我暂时没有找到足够可靠的依据来回答这个问题。你可以补充更多上下文，我再继续帮你查。 [Code: RAG_NO_ANSWER]"
        return self._append_auxiliary_sections(request, body, include_auxiliary=False)

    def _grounded_fallback(self, request: AnswerComposeRequest) -> str:
        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        items = list(evidence_pack.items if evidence_pack else [])
        citations = self._collect_citations(request)
        if not items:
            return "噢，系统服务出现了一点小状况呢，请稍后再试一下吧～ [Code: RAG_REFUSED_SHIELD]"
        lead = "根据知识库中的证据，可以得到以下结论："
        bullets: List[str] = []
        for item, citation in zip(items[: self.max_citations], citations or items):
            marker = self._citation_marker(citation)
            snippet = item.content.strip().replace("\n", " ")
            if len(snippet) > 140:
                snippet = snippet[:137].rstrip() + "..."
            bullets.append(f"- {snippet} {marker}".rstrip())
        return "\n".join([lead, *bullets])

    def _append_auxiliary_sections(self, request: AnswerComposeRequest, answer: str, *, include_auxiliary: bool) -> str:
        return answer

    @staticmethod
    def _format_memory_section(title: str, memories: Sequence[Any], *, limit: int) -> str:
        summaries: List[str] = []
        for memory in memories[:limit]:
            summary = getattr(memory, "summary", None) or str(getattr(memory, "content", ""))
            summary = str(summary).strip()
            if summary:
                summaries.append(summary)
        if not summaries:
            return ""
        return f"{title}: {' | '.join(summaries)}"

    def _evidence_status(self, rag_result) -> str:
        if rag_result is None:
            return "EMPTY"
        pack = getattr(rag_result, "evidence_pack", None)
        if pack is None:
            return str(getattr(rag_result, "evidence_status", "EMPTY") or "EMPTY").upper()
        return str(getattr(pack, "evidence_status", getattr(rag_result, "evidence_status", "EMPTY")) or "EMPTY").upper()

    def _collect_citations(self, request: AnswerComposeRequest) -> List[Any]:
        rag_result = request.rag_result
        citations = list(rag_result.citations if rag_result else [])
        if citations:
            return citations[: self.max_citations]
        evidence_pack = rag_result.evidence_pack if rag_result else None
        if evidence_pack is None:
            return []
        collected = []
        for item in evidence_pack.items[: self.max_citations]:
            collected.append(
                {
                    "chunk_id": getattr(item, "citation_chunk_id", None) or item.chunk_id,
                    "document_id": item.document_id,
                    "title": item.metadata.get("title") if isinstance(item.metadata, Mapping) else None,
                }
            )
        return collected

    def _ensure_citations(self, answer_text: str, citations: Sequence[Any]) -> str:
        if any(token in answer_text for token in ("[", "(", "【")):
            return answer_text
        marker_text = " ".join(self._citation_marker(citation) for citation in citations[: self.max_citations])
        if not marker_text:
            return answer_text
        return f"{answer_text}\n\n证据引用：{marker_text}"

    @staticmethod
    def _extract_answer_text(payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, Mapping):
            for key in ("answer_text", "answer", "text", "output", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _citation_marker(citation: Any) -> str:
        if isinstance(citation, Mapping):
            chunk_id = str(citation.get("chunk_id") or citation.get("citation_chunk_id") or "").strip()
            title = str(citation.get("title") or "").strip()
        else:
            chunk_id = str(getattr(citation, "chunk_id", "") or getattr(citation, "citation_chunk_id", "") or "").strip()
            title = str(getattr(citation, "title", "") or "").strip()
        if title:
            return f"[{chunk_id}:{title}]" if chunk_id else f"[{title}]"
        return f"[{chunk_id}]" if chunk_id else ""


@dataclass
class Finalizer:
    settings: Settings

    def finalize(self, *args, **kwargs) -> SseEnvelope | None:
        return None
