from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from learning_agent_service.domain import (
    FacetPlan,
    NormalizedToolResult,
    SseEnvelope,
    ToolExecutionCommand,
    ToolExecutionResult,
    ToolNormalizationRequest,
    ToolPlanningRequest,
    ToolSelection,
)
from learning_agent_service.domain.enums import IntentType, ToolExecutionStatus
from learning_agent_service.domain.errors import WorkflowErrorCode

from .builtin import build_builtin_tool_registry
from .executor import ToolExecutor as BaseToolExecutor
from .models import ToolExecutionResult as BaseExecutionResult
from .models import ToolSelection as BaseToolSelection
from .normalizer import ToolResultNormalizer as BaseToolResultNormalizer
from .planner import ToolPlanner as BaseToolPlanner
from .tool_adapter import ToolAdapter
from .tool_call_validator import ToolCallValidationError, ToolCallValidator
from .tool_error_classifier import classify_tool_error
from .registry import ToolRegistry
from .shop_id_enforcer import ShopIdMissingError
from .transaction_store import InMemoryTransactionStore

# ── Entity resolution for local life shop tools ─────────────────────────────
# Tools that need a resolved shop_id to function properly.
_TOOLS_NEEDING_SHOP_ID: frozenset[str] = frozenset({
    "get_shop_detail", "restaurant_detail", "local_life_detail",
    "create_booking", "restaurant_booking", "local_life_booking",
    "create_order",
    "get_coupon_list", "restaurant_coupon", "local_life_coupon",
    "get_blog_list", "restaurant_blog", "local_life_blog",
    "get_distance_eta", "restaurant_distance_eta", "local_life_distance_eta",
    "restaurant_navigation", "local_life_navigation",
    "check_open_status", "restaurant_open_status", "local_life_open_status",
})

# Tools that benefit from entity decomposition for search enrichment.
_TOOLS_WITH_SEARCH: frozenset[str] = frozenset({
    "search_restaurants", "restaurant_recommendation", "local_life_recommendation",
    "restaurant_comparison", "local_life_comparison",
})


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
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
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
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
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
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
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
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "limit": int(_slot_value(slots, "limit") or 10),
        }

    if normalized_tool_name in {"get_blog_list", "restaurant_blog", "local_life_blog"}:
        return {
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
            "user_id": _slot_value(slots, "user_id"),
            "shop_name": _slot_value(slots, "shop_name", "shop_query", "name"),
            "current": int(_slot_value(slots, "current") or 1),
            "limit": int(_slot_value(slots, "limit") or 5),
        }

    if normalized_tool_name in {"get_distance_eta", "restaurant_distance_eta", "local_life_distance_eta", "restaurant_navigation", "local_life_navigation"}:
        location = _slot_mapping(_slot_value(slots, "location"))
        return {
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
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
            "shop_id": _slot_value(slots, "resolved_shop_id", "shop_id", "selected_shop_id"),
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


def _has_rag_evidence(request: Any) -> bool:
    """检查是否有 RAG evidence"""
    if request is None:
        return False
    rag_result = getattr(request, "rag_result", None)
    if rag_result is None:
        return False
    evidence_pack = getattr(rag_result, "evidence_pack", None)
    if evidence_pack is None:
        return False
    items = getattr(evidence_pack, "items", [])
    return bool(items)


def _classify_grounding_source(
    tool_name: str | None,
    payload: Mapping[str, Any] | None,
    request: Any = None,
) -> str:
    """
    分类 grounding source，支持 4 种类型：
    - business_evidence: Tool 返回了有效数据
    - rag_evidence: RAG 返回了有效 evidence
    - mixed_evidence: Tool + RAG 都有
    - not_grounded: 都没有
    """
    has_tool = _has_business_evidence(tool_name, payload)
    has_rag = _has_rag_evidence(request)
    
    if has_tool and has_rag:
        return "mixed_evidence"
    elif has_tool:
        return "business_evidence"
    elif has_rag:
        return "rag_evidence"
    else:
        return "not_grounded"


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
    classification = classify_tool_error(
        tool_name=tool_name,
        status=status.value if hasattr(status, "value") else status,
        payload=payload,
        errors=errors,
        approval_required=approval_required,
        approval_status=approval_state,
    )
    category = classification.category
    
    if category is None and _looks_like_no_result(tool_name, payload):
        category = "no_result"
        
    if category is None:
        return None
    mapping = {
        "timeout": "timeout",
        "not_found": "no_result",
        "empty_result": "no_result",
        "permission_error": "permission_denied",
        "invalid_params": "invalid_params",
        "service_unavailable": "dependency_unavailable",
        "approval_required": "approval_required",
    }
    return mapping.get(category, category)


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

    def plan(self, request: ToolPlanningRequest, facet_plans: list[FacetPlan] | None = None) -> ToolSelection:
        routing = getattr(request, "routing_decision", None)
        required_action = str(getattr(routing, "required_action", "") or "").strip().lower()
        legacy_decision = str(getattr(request, "decision", "") or "").strip().lower()
        need_tool = required_action in {"tool_call", "rag_plus_tool"} or legacy_decision == "tool_then_answer"
        slots = dict(request.slots)
        slots.setdefault("topic", request.current_topic or request.raw_query)
        slot_approval_status = str(_slot_value(slots, "approval_status", "approval_decision") or "").strip().lower() or None
        slot_approval_request = dict(_slot_mapping(_slot_value(slots, "approval_request")))

        planning_meta: dict[str, Any] = {
            "decision": required_action or str(request.decision),
            "requested_intent": _normalize_key(request.intent),
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

        # facet_plan 新路径：当 facet_plans 非空时，直接从 FacetPlan 生成 ToolSelection
        if facet_plans:
            planner = self.planner
            assert planner is not None
            facet_selections = planner.plan_from_facets(facet_plans, slots)
            if facet_selections:
                sel = facet_selections[0]
                approval_required = sel.tool_name in _APPROVAL_REQUIRED_TOOLS if sel.tool_name else False
                approval_request = slot_approval_request or _build_approval_request(
                    sel.tool_name, sel.input_payload, reason=sel.reason,
                )
                return ToolSelection(
                    tool_name=sel.tool_name,
                    should_execute=True,
                    input_payload=sel.input_payload,
                    reason=sel.reason,
                    approval_required=approval_required or bool(getattr(sel, "approval_required", False)),
                    approval_status=slot_approval_status if approval_required else None,
                    approval_request=approval_request if approval_required else {},
                    extra={
                        **planning_meta,
                        "resolved_intent": f"facet_plan:{[fp.name for fp in facet_plans]}",
                        "planning_state": "facet_plan",
                        "selection_source": "facet_planner",
                        "tool_call_id": str(uuid.uuid4()),
                        "approval_required": approval_required,
                        "approval_request": approval_request if approval_required else {},
                    },
                )

        # 旧路径：通过 intent 解析链
        resolved_intent = _resolve_planner_intent(request, slots)
        planning_meta["resolved_intent"] = resolved_intent
        slots.setdefault("tool_input", {"topic": slots.get("topic")})
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


# ── Shop resolution: decompose → recall → bind ──────────────────────────────
import logging as _logging

_shop_resolution_logger = _logging.getLogger(__name__)


def _resolve_shop_from_query(
    client: Any,
    tool_name: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """Resolve shop_query → shop_id via entity decomposition + recall + bind.

    For tools needing shop_id: if shop_id is absent but shop_query exists,
    decompose the query, recall candidates, and bind a single shop_id.
    Enriches the input_payload with resolved_shop_id and entity metadata.

    Returns the (possibly enriched) input_payload.
    On error, returns the original input_payload unchanged.
    """
    from ..local_life.entity_decomposer import decompose_shop_query
    from ..local_life.recall_service import recall_candidates
    from ..local_life.shop_binding import bind_shop_id

    shop_query = input_payload.get("shop_query") or input_payload.get("shop_name") or ""
    if not shop_query or not isinstance(shop_query, str) or not shop_query.strip():
        return input_payload

    # Gather known brands/areas from client (with fallback to hardcoded lists)
    known_brands: list[str] | None = None
    known_areas: list[str] | None = None
    if client is not None:
        try:
            if hasattr(client, "get_brand_list"):
                known_brands = client.get_brand_list()
        except Exception:
            pass
        try:
            if hasattr(client, "get_area_list"):
                known_areas = client.get_area_list()
        except Exception:
            pass

    entity = decompose_shop_query(
        raw_query=shop_query,
        known_brands=known_brands,
        known_areas=known_areas,
    )

    _shop_resolution_logger.debug(
        "entity_resolved: tool=%s brand=%s area=%s category=%s",
        tool_name, entity.brand, entity.area, entity.category,
    )

    if client is None:
        return input_payload

    try:
        recall = recall_candidates(client, entity)
    except Exception as exc:
        _shop_resolution_logger.warning("recall_candidates failed: %s", exc)
        return input_payload

    shop_id, clarification_card = bind_shop_id(recall, allow_clarification=True)

    enriched = dict(input_payload)

    # Always attach entity metadata for downstream use
    enriched["entity_brand"] = entity.brand
    enriched["entity_area"] = entity.area
    enriched["entity_category"] = entity.category
    enriched["recall_strategy"] = recall.strategy
    enriched["recall_count"] = len(recall.candidates)

    if shop_id is not None:
        enriched["resolved_shop_id"] = shop_id
        if "shop_id" not in enriched or not enriched.get("shop_id"):
            enriched["shop_id"] = shop_id
        _shop_resolution_logger.info(
            "shop_bound: tool=%s shop_id=%d strategy=%s",
            tool_name, shop_id, recall.strategy,
        )

    if clarification_card is not None:
        enriched["clarification_card"] = clarification_card.model_dump(mode="json")
        _shop_resolution_logger.info(
            "clarification_needed: tool=%s candidates=%d",
            tool_name, len(recall.candidates),
        )

    return enriched


def _build_tool_failure_result(
    selection: BaseToolSelection,
    *,
    error_code: WorkflowErrorCode,
    message: str,
    status: ToolExecutionStatus = ToolExecutionStatus.FAILED,
    clarification_needed: bool = False,
) -> ToolExecutionResult:
    extra: dict[str, Any] = {
        "tool_call_id": (getattr(selection, "extra", {}) or {}).get("tool_call_id"),
        "error_code": error_code.value,
        "error_message": message,
        "retryable": False,
        "degraded": False,
        "degrade_to": None,
        "duration_ms": 0,
        "clarification_needed": clarification_needed,
    }
    output_payload: dict[str, Any] = {}
    if clarification_needed:
        output_payload = {
            "clarification_needed": True,
            "clarification_question": "请补充店铺信息后再试。",
        }
    return ToolExecutionResult(
        status=status,
        tool_name=selection.tool_name,
        output_payload=output_payload,
        degraded_to=None,
        error=error_code,
        approval_required=False,
        approval_status=None,
        approval_request={},
        extra=extra,
    )


@dataclass
class ToolExecutor:
    java_business_client: Any | None = None
    transaction_store: InMemoryTransactionStore | None = None
    registry: ToolRegistry | None = None
    executor: BaseToolExecutor | None = None
    tool_call_validator: ToolCallValidator | None = None
    tool_adapter: ToolAdapter | None = None

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = build_default_tool_registry(
                java_business_client=self.java_business_client,
                transaction_store=self.transaction_store,
            )
        if self.executor is None:
            self.executor = BaseToolExecutor(self.registry)
        if self.tool_call_validator is None:
            self.tool_call_validator = ToolCallValidator(self.registry)
        if self.tool_adapter is None:
            self.tool_adapter = ToolAdapter()

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

        validator = self.tool_call_validator
        adapter = self.tool_adapter
        assert validator is not None
        assert adapter is not None

        try:
            validator.validate(selection.tool_name, dict(selection.input_payload))
        except ToolCallValidationError as exc:
            return _build_tool_failure_result(
                selection,
                error_code=WorkflowErrorCode.INVALID_REQUEST,
                message=str(exc),
            )

        try:
            adapted_selection = adapter.adapt(
                BaseToolSelection(
                    tool_name=selection.tool_name,
                    input_payload=dict(selection.input_payload),
                    reason=selection.reason,
                    degrade_to=selection.extra.get("degrade_to") if selection.extra else None,
                    timeout_ms=selection.extra.get("timeout_ms") if selection.extra else None,
                    approval_required=bool(getattr(selection, "approval_required", False) or (selection.extra or {}).get("approval_required")),
                    approval_status=getattr(selection, "approval_status", None) or (selection.extra or {}).get("approval_status"),
                    approval_request=dict(getattr(selection, "approval_request", {}) or (selection.extra or {}).get("approval_request", {})),
                ),
                resolved_shop=(selection.extra or {}).get("resolved_shop"),
                shop_id=selection.input_payload.get("shop_id"),
            )
        except ShopIdMissingError as exc:
            return _build_tool_failure_result(
                selection,
                error_code=WorkflowErrorCode.CLARIFICATION_PENDING,
                message=str(exc),
                status=ToolExecutionStatus.FAILED,
                clarification_needed=True,
            )

        selection = selection.model_copy(
            update={"input_payload": adapted_selection.input_payload}
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
        grounding_source = _classify_grounding_source(normalized.tool_name, normalized.payload, request)
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
                "retry_reason": failure_category if normalized.retryable else None,
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
