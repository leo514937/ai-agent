from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from learning_agent_service.api.contracts import (
    ClarificationCardPayload,
    ClarificationOptionPayload,
    EventType,
    SseEnvelope,
)
from learning_agent_service.domain.contracts import (
    ChatTurnCommand,
    GraphRuntimeMeta,
)

from learning_agent_service.local_life.facet_result_bundle import FacetResultBundle
from learning_agent_service.local_life.schemas import LocalLifeIntentType, LocalLifeSlots, LocalLifeTurnState

_LOGGER = logging.getLogger(__name__)


def _clean_source(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    return text or None


def _normalize_shop_context_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _event(
    event_type: EventType,
    *,
    trace_id: str,
    session_id: str,
    turn_id: str,
    workflow_version: str,
    payload: dict[str, Any],
) -> SseEnvelope:
    return SseEnvelope(
        event_type=event_type.value,
        trace_id=trace_id,
        session_id=session_id,
        turn_id=turn_id,
        timestamp=datetime.now(UTC),
        workflow_version=workflow_version,
        payload=payload,
    )


def _runtime(command: ChatTurnCommand, workflow_version: str) -> GraphRuntimeMeta:
    return GraphRuntimeMeta(
        trace_id=command.trace_id,
        session_id=command.session_id,
        turn_id=command.turn_id,
        workflow_version=workflow_version,
        request_ts=datetime.now(UTC),
        user_id=command.user_id,
        response_mode=command.response_mode,
        topic_hint=command.topic_hint,
        history_summary=command.history_summary,
        client_context=command.client_context,
    )


def _clarification_payload(decision) -> dict[str, Any]:
    return ClarificationCardPayload(
        card_id=f"clarify-{uuid4().hex[:8]}",
        question=decision.question or "你能再补充一点偏好吗？",
        options=[
            ClarificationOptionPayload(
                id=f"opt-{index}",
                label=item.label,
                value=item.prompt,
                description=item.prompt,
            )
            for index, item in enumerate(decision.options, start=1)
        ],
        ambiguity_type=decision.ambiguity_type or "local_life",
    ).model_dump(mode="json")


def _route_decision_from_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "retrieve_then_answer",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "retrieve_then_answer",
        LocalLifeIntentType.COUPON: "retrieve_then_answer",
        LocalLifeIntentType.DETAIL: "retrieve_then_answer",
        LocalLifeIntentType.BOOKING: "tool_then_answer",
        LocalLifeIntentType.ORDER_STATUS: "tool_then_answer",
        LocalLifeIntentType.NAVIGATION: "retrieve_then_answer",
        LocalLifeIntentType.CLARIFY: "clarify",
    }
    return mapping.get(intent, "retrieve_then_answer")


def _tool_name_for_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "search_restaurants",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "search_restaurants",
        LocalLifeIntentType.DETAIL: "get_shop_detail",
        LocalLifeIntentType.NAVIGATION: "get_distance_eta",
    }
    return mapping.get(intent, "search_restaurants")


def _tool_input_summary(
    intent: LocalLifeIntentType,
    *,
    filters: Mapping[str, Any],
    slots: LocalLifeSlots,
    tool_name: str | None = None,
    selected_shop_id: int | None = None,
    selected_shop_name: str | None = None,
) -> dict[str, Any]:
    if tool_name == "get_coupon_list":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
        }
    if tool_name == "check_open_status":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
        }
    if tool_name == "get_distance_eta":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
            "lat": slots.location.lat,
            "lng": slots.location.lng,
            "mode": "drive",
        }
    if tool_name == "get_shop_detail":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
            "query": selected_shop_name or slots.shop_query or slots.category or slots.city,
        }
    if intent in {LocalLifeIntentType.RESTAURANT_RECOMMENDATION, LocalLifeIntentType.RESTAURANT_COMPARISON}:
        return dict(filters)
    if intent == LocalLifeIntentType.DETAIL:
        return {
            "shop_id": slots.shop_ids[0] if slots.shop_ids else None,
            "shop_name": slots.shop_query or slots.category or slots.city,
            "query": slots.shop_query or slots.category or slots.city,
        }
    if intent == LocalLifeIntentType.NAVIGATION:
        return {
            "shop_id": slots.shop_ids[0] if slots.shop_ids else None,
            "shop_name": slots.shop_query or slots.category or slots.city,
            "lat": slots.location.lat,
            "lng": slots.location.lng,
            "mode": "drive",
        }
    return dict(filters)


def _resolve_review_shop_ids(
    *,
    user_need,
    slots: LocalLifeSlots,
    session_context: Mapping[str, Any],
    query_route: Any | None = None,
) -> list[int]:
    shop_ids: list[int] = []
    seen: set[int] = set()

    def add(value: Any) -> None:
        try:
            shop_id = int(value)
        except Exception:
            return
        if shop_id in seen:
            return
        seen.add(shop_id)
        shop_ids.append(shop_id)

    for ref in getattr(user_need, "context_refs", []) or []:
        if getattr(ref, "type", None) == "shop" and getattr(ref, "id", None) not in (None, ""):
            add(ref.id)

    for key in ("selected_shop_id", "current_shop_id"):
        value = session_context.get(key)
        if value not in (None, ""):
            add(value)

    # 额外防御性解析：从 current_shop 和 selected_shop_name 中匹配 shop:N 提取真实数字 ID (P0-Fix)
    import re as _re
    for key in ("current_shop", "selected_shop_name"):
        val_str = str(session_context.get(key) or "").strip()
        if val_str:
            match = _re.match(r"^shop:(\d+)$", val_str)
            if match:
                add(match.group(1))

    for item in session_context.get("last_candidates") or []:
        if not isinstance(item, Mapping):
            continue
        add(item.get("shop_id") or item.get("id"))

    for shop_id in slots.shop_ids:
        add(shop_id)

    if query_route is not None:
        for shop_id in getattr(query_route, "candidate_shop_ids", ()) or ():
            add(shop_id)

    return shop_ids


def _summarize_tool_output(tool_name: str, tool_output: Mapping[str, Any], shop_name: str | None = None) -> str | None:
    import re as _re
    # 优先从 tool_output 中取 shop_name（真实业务名），防止 "shop:N" ID 泄露
    _raw_name = tool_output.get("shop_name") or shop_name or "这家店"
    _safe_name = _raw_name if not _re.match(r"^shop:\d+$", str(_raw_name)) else "这家店"
    if tool_name == "get_coupon_list":
        coupons = tool_output.get("coupons") or []
        titles: list[str] = []
        total_stock = 0
        for coupon in coupons:
            if isinstance(coupon, Mapping):
                title = coupon.get("title") or coupon.get("name")
                if title:
                    titles.append(str(title))
                stock = coupon.get("stock")
                if stock is not None:
                    try:
                        total_stock += int(stock)
                    except (TypeError, ValueError):
                        pass
        count = tool_output.get("count")  # 券的种类数
        title_text = "、".join(titles[:3])
        if count is None:
            count = len(titles)
        if count and title_text:
            if total_stock > 0:
                return f"{_safe_name}当前有{count}种券，共{total_stock}张库存：{title_text}。"
            return f"{_safe_name}当前有{count}张券：{title_text}。"
        if count:
            if total_stock > 0:
                return f"{_safe_name}当前有{count}种券，共{total_stock}张库存。"
            return f"{_safe_name}当前有{count}张券。"
        return f"{_safe_name}实时接口暂无可用券。"
    if tool_name == "check_open_status":
        open_status = tool_output.get("open_status")
        if open_status == "open":
            return f"{_safe_name}现在营业中。"
        if open_status == "closed":
            return f"{_safe_name}现在未营业。"
        return f"{_safe_name}的营业状态暂时不明确。"
    if tool_name == "get_distance_eta":
        distance_km = tool_output.get("distance_km")
        eta_minutes = tool_output.get("eta_minutes")
        if distance_km is not None and eta_minutes is not None:
            return f"{_safe_name}距离你约{distance_km}公里，开车约{eta_minutes}分钟。"
    return None


def _stage_entry(
    stage: str,
    status: str,
    *,
    route_decision: str | None = None,
    route_reason: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "route_decision": route_decision,
        "route_reason": route_reason,
        "detail": dict(detail or {}),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _mark_stage(
    state: LocalLifeTurnState,
    stage: str,
    status: str,
    *,
    route_decision: str | None = None,
    route_reason: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    if route_decision is not None:
        state.route_decision = route_decision
    if route_reason is not None:
        state.route_reason = route_reason
    state.current_stage = stage
    state.stage_status = status
    state.stage_timeline.append(
        _stage_entry(
            stage,
            status,
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            detail=detail,
        )
    )
def _is_name_match(query_name: str, shop_name: str) -> bool:
    q_name = str(query_name or "").lower().strip()
    s_name = str(shop_name or "").lower().strip()
    for brand in ["海底捞", "巴奴", "新白鹿", "蔡馬洪涛", "Mamala", "幸福里", "炉鱼", "浅草屋", "羊老三", "开乐迪", "INLOVE", "星聚会"]:
        brand_lower = brand.lower()
        if brand_lower in q_name and brand_lower in s_name:
            area_words = ["水晶城", "运河上街", "丝联", "万达", "乐堤港", "北城天地", "城西", "武林广场"]
            query_area = next((w for w in area_words if w.lower() in q_name), None)
            if query_area:
                return query_area.lower() in s_name
            return True
    return q_name in s_name or s_name in q_name


def _filter_recommendation_candidates_by_realtime(
    ranked_candidates: Sequence[Any],
    *,
    facet_bundle: FacetResultBundle,
    answer_contract: Any | None,
) -> tuple[list[Any], dict[str, Any]]:
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    if not ranked_candidates or not realtime_facets:
        return list(ranked_candidates), {
            "enabled": False,
            "requested_realtime_facets": realtime_facets,
            "kept_shop_ids": [getattr(candidate, "shop_id", None) for candidate in ranked_candidates],
            "dropped": [],
        }

    filtered: list[Any] = []
    dropped: list[dict[str, Any]] = []
    for candidate in ranked_candidates:
        shop_id = getattr(candidate, "shop_id", None)
        keep = True
        reasons: list[str] = []
        if "coupon" in realtime_facets:
            coupon_result = facet_bundle.find_tool_result("coupon", shop_id=shop_id)
            coupon_count = 0
            if coupon_result is not None:
                try:
                    coupon_count = int(coupon_result.data.get("count") or 0)
                except Exception:
                    coupon_count = 0
            if coupon_result is None or coupon_result.status != "success" or coupon_count <= 0:
                keep = False
                reasons.append("coupon")
        if "open_status" in realtime_facets:
            open_result = facet_bundle.find_tool_result("open_status", shop_id=shop_id)
            open_status = str(open_result.data.get("open_status") or "").strip().lower() if open_result is not None else ""
            is_open = open_result is not None and open_result.status == "success" and (
                open_status == "open" or open_result.data.get("open_now") is True
            )
            if not is_open:
                keep = False
                reasons.append("open_status")
        if keep:
            filtered.append(candidate)
        else:
            dropped.append(
                {
                    "shop_id": shop_id,
                    "shop_name": getattr(candidate, "name", None),
                    "reasons": reasons,
                }
            )

    return filtered, {
        "enabled": True,
        "requested_realtime_facets": realtime_facets,
        "kept_shop_ids": [getattr(candidate, "shop_id", None) for candidate in filtered],
        "dropped": dropped,
    }


def _clean_source(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    return text or None


def _normalize_shop_context_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _event(
    event_type: EventType,
    *,
    trace_id: str,
    session_id: str,
    turn_id: str,
    workflow_version: str,
    payload: dict[str, Any],
) -> SseEnvelope:
    return SseEnvelope(
        event_type=event_type.value,
        trace_id=trace_id,
        session_id=session_id,
        turn_id=turn_id,
        timestamp=datetime.now(UTC),
        workflow_version=workflow_version,
        payload=payload,
    )


def _runtime(command: ChatTurnCommand, workflow_version: str) -> GraphRuntimeMeta:
    return GraphRuntimeMeta(
        trace_id=command.trace_id,
        session_id=command.session_id,
        turn_id=command.turn_id,
        workflow_version=workflow_version,
        request_ts=datetime.now(UTC),
        user_id=command.user_id,
        response_mode=command.response_mode,
        topic_hint=command.topic_hint,
        history_summary=command.history_summary,
        client_context=command.client_context,
    )


def _clarification_payload(decision) -> dict[str, Any]:
    return ClarificationCardPayload(
        card_id=f"clarify-{uuid4().hex[:8]}",
        question=decision.question or "你能再补充一点偏好吗？",
        options=[
            ClarificationOptionPayload(
                id=f"opt-{index}",
                label=item.label,
                value=item.prompt,
                description=item.prompt,
            )
            for index, item in enumerate(decision.options, start=1)
        ],
        ambiguity_type=decision.ambiguity_type or "local_life",
    ).model_dump(mode="json")


def _route_decision_from_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "retrieve_then_answer",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "retrieve_then_answer",
        LocalLifeIntentType.COUPON: "retrieve_then_answer",
        LocalLifeIntentType.DETAIL: "retrieve_then_answer",
        LocalLifeIntentType.BOOKING: "tool_then_answer",
        LocalLifeIntentType.ORDER_STATUS: "tool_then_answer",
        LocalLifeIntentType.NAVIGATION: "retrieve_then_answer",
        LocalLifeIntentType.CLARIFY: "clarify",
    }
    return mapping.get(intent, "retrieve_then_answer")


def _tool_name_for_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "search_restaurants",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "search_restaurants",
        LocalLifeIntentType.DETAIL: "get_shop_detail",
        LocalLifeIntentType.NAVIGATION: "get_distance_eta",
    }
    return mapping.get(intent, "search_restaurants")


def _tool_input_summary(
    intent: LocalLifeIntentType,
    *,
    filters: Mapping[str, Any],
    slots: LocalLifeSlots,
    tool_name: str | None = None,
    selected_shop_id: int | None = None,
    selected_shop_name: str | None = None,
) -> dict[str, Any]:
    if tool_name == "get_coupon_list":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
        }
    if tool_name == "check_open_status":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
        }
    if tool_name == "get_distance_eta":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
            "lat": slots.location.lat,
            "lng": slots.location.lng,
            "mode": "drive",
        }
    if tool_name == "get_shop_detail":
        return {
            "shop_id": selected_shop_id or (slots.shop_ids[0] if slots.shop_ids else None),
            "shop_name": selected_shop_name or slots.shop_query or slots.category or slots.city,
            "query": selected_shop_name or slots.shop_query or slots.category or slots.city,
        }
    if intent in {LocalLifeIntentType.RESTAURANT_RECOMMENDATION, LocalLifeIntentType.RESTAURANT_COMPARISON}:
        return dict(filters)
    if intent == LocalLifeIntentType.DETAIL:
        return {
            "shop_id": slots.shop_ids[0] if slots.shop_ids else None,
            "shop_name": slots.shop_query or slots.category or slots.city,
            "query": slots.shop_query or slots.category or slots.city,
        }
    if intent == LocalLifeIntentType.NAVIGATION:
        return {
            "shop_id": slots.shop_ids[0] if slots.shop_ids else None,
            "shop_name": slots.shop_query or slots.category or slots.city,
            "lat": slots.location.lat,
            "lng": slots.location.lng,
            "mode": "drive",
        }
    return dict(filters)


def _resolve_review_shop_ids(
    *,
    user_need,
    slots: LocalLifeSlots,
    session_context: Mapping[str, Any],
    query_route: Any | None = None,
) -> list[int]:
    shop_ids: list[int] = []
    seen: set[int] = set()

    def add(value: Any) -> None:
        try:
            shop_id = int(value)
        except Exception:
            return
        if shop_id in seen:
            return
        seen.add(shop_id)
        shop_ids.append(shop_id)

    for ref in getattr(user_need, "context_refs", []) or []:
        if getattr(ref, "type", None) == "shop" and getattr(ref, "id", None) not in (None, ""):
            add(ref.id)

    for key in ("selected_shop_id", "current_shop_id"):
        value = session_context.get(key)
        if value not in (None, ""):
            add(value)

    # 额外防御性解析：从 current_shop 和 selected_shop_name 中匹配 shop:N 提取真实数字 ID (P0-Fix)
    import re as _re
    for key in ("current_shop", "selected_shop_name"):
        val_str = str(session_context.get(key) or "").strip()
        if val_str:
            match = _re.match(r"^shop:(\d+)$", val_str)
            if match:
                add(match.group(1))

    for item in session_context.get("last_candidates") or []:
        if not isinstance(item, Mapping):
            continue
        add(item.get("shop_id") or item.get("id"))

    for shop_id in slots.shop_ids:
        add(shop_id)

    if query_route is not None:
        for shop_id in getattr(query_route, "candidate_shop_ids", ()) or ():
            add(shop_id)

    return shop_ids


def _summarize_tool_output(tool_name: str, tool_output: Mapping[str, Any], shop_name: str | None = None) -> str | None:
    import re as _re
    # 优先从 tool_output 中取 shop_name（真实业务名），防止 "shop:N" ID 泄露
    _raw_name = tool_output.get("shop_name") or shop_name or "这家店"
    _safe_name = _raw_name if not _re.match(r"^shop:\d+$", str(_raw_name)) else "这家店"
    if tool_name == "get_coupon_list":
        coupons = tool_output.get("coupons") or []
        titles: list[str] = []
        total_stock = 0
        for coupon in coupons:
            if isinstance(coupon, Mapping):
                title = coupon.get("title") or coupon.get("name")
                if title:
                    titles.append(str(title))
                stock = coupon.get("stock")
                if stock is not None:
                    try:
                        total_stock += int(stock)
                    except (TypeError, ValueError):
                        pass
        count = tool_output.get("count")  # 券的种类数
        title_text = "、".join(titles[:3])
        if count is None:
            count = len(titles)
        if count and title_text:
            if total_stock > 0:
                return f"{_safe_name}当前有{count}种券，共{total_stock}张库存：{title_text}。"
            return f"{_safe_name}当前有{count}张券：{title_text}。"
        if count:
            if total_stock > 0:
                return f"{_safe_name}当前有{count}种券，共{total_stock}张库存。"
            return f"{_safe_name}当前有{count}张券。"
        return f"{_safe_name}实时接口暂无可用券。"
    if tool_name == "check_open_status":
        open_status = tool_output.get("open_status")
        if open_status == "open":
            return f"{_safe_name}现在营业中。"
        if open_status == "closed":
            return f"{_safe_name}现在未营业。"
        return f"{_safe_name}的营业状态暂时不明确。"
    if tool_name == "get_distance_eta":
        distance_km = tool_output.get("distance_km")
        eta_minutes = tool_output.get("eta_minutes")
        if distance_km is not None and eta_minutes is not None:
            return f"{_safe_name}距离你约{distance_km}公里，开车约{eta_minutes}分钟。"
    return None


def _stage_entry(
    stage: str,
    status: str,
    *,
    route_decision: str | None = None,
    route_reason: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "route_decision": route_decision,
        "route_reason": route_reason,
        "detail": dict(detail or {}),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _mark_stage(
    state: LocalLifeTurnState,
    stage: str,
    status: str,
    *,
    route_decision: str | None = None,
    route_reason: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    if route_decision is not None:
        state.route_decision = route_decision
    if route_reason is not None:
        state.route_reason = route_reason
    state.current_stage = stage
    state.stage_status = status
    state.stage_timeline.append(
        _stage_entry(
            stage,
            status,
            route_decision=state.route_decision,
            route_reason=state.route_reason,
            detail=detail,
        )
    )


def _is_name_match(query_name: str, shop_name: str) -> bool:
    q_name = str(query_name or "").lower().strip()
    s_name = str(shop_name or "").lower().strip()
    for brand in ["海底捞", "巴奴", "新白鹿", "蔡馬洪涛", "Mamala", "幸福里", "炉鱼", "浅草屋", "羊老三", "开乐迪", "INLOVE", "星聚会"]:
        brand_lower = brand.lower()
        if brand_lower in q_name and brand_lower in s_name:
            area_words = ["水晶城", "运河上街", "丝联", "万达", "乐堤港", "北城天地", "城西", "武林广场"]
            query_area = next((w for w in area_words if w.lower() in q_name), None)
            if query_area:
                return query_area.lower() in s_name
            return True
    return q_name in s_name or s_name in q_name


def _filter_recommendation_candidates_by_realtime(
    ranked_candidates: Sequence[Any],
    *,
    facet_bundle: FacetResultBundle,
    answer_contract: Any | None,
) -> tuple[list[Any], dict[str, Any]]:
    realtime_facets = list(getattr(answer_contract, "realtime_facets", []) or [])
    if not ranked_candidates or not realtime_facets:
        return list(ranked_candidates), {
            "enabled": False,
            "requested_realtime_facets": realtime_facets,
            "kept_shop_ids": [getattr(candidate, "shop_id", None) for candidate in ranked_candidates],
            "dropped": [],
        }

    filtered: list[Any] = []
    dropped: list[dict[str, Any]] = []
    for candidate in ranked_candidates:
        shop_id = getattr(candidate, "shop_id", None)
        keep = True
        reasons: list[str] = []
        if "coupon" in realtime_facets:
            coupon_result = facet_bundle.find_tool_result("coupon", shop_id=shop_id)
            coupon_count = 0
            if coupon_result is not None:
                try:
                    coupon_count = int(coupon_result.data.get("count") or 0)
                except Exception:
                    coupon_count = 0
            if coupon_result is None or coupon_result.status != "success" or coupon_count <= 0:
                keep = False
                reasons.append("coupon")
        if "open_status" in realtime_facets:
            open_result = facet_bundle.find_tool_result("open_status", shop_id=shop_id)
            open_status = str(open_result.data.get("open_status") or "").strip().lower() if open_result is not None else ""
            is_open = open_result is not None and open_result.status == "success" and (
                open_status == "open" or open_result.data.get("open_now") is True
            )
            if not is_open:
                keep = False
                reasons.append("open_status")
        if keep:
            filtered.append(candidate)
        else:
            dropped.append(
                {
                    "shop_id": shop_id,
                    "shop_name": getattr(candidate, "name", None),
                    "reasons": reasons,
                }
            )

    return filtered, {
        "enabled": True,
        "requested_realtime_facets": realtime_facets,
        "kept_shop_ids": [getattr(candidate, "shop_id", None) for candidate in filtered],
        "dropped": dropped,
    }


def _mode_from_intent(intent: LocalLifeIntentType) -> str:
    mapping = {
        LocalLifeIntentType.RESTAURANT_RECOMMENDATION: "recommend",
        LocalLifeIntentType.RESTAURANT_COMPARISON: "compare",
        LocalLifeIntentType.COUPON: "coupon",
        LocalLifeIntentType.DETAIL: "detail",
        LocalLifeIntentType.BOOKING: "booking",
        LocalLifeIntentType.ORDER_STATUS: "order_status",
        LocalLifeIntentType.NAVIGATION: "navigation",
        LocalLifeIntentType.CLARIFY: "clarify",
    }
    return mapping.get(intent, "recommend")


__all__ = [name for name in globals() if not name.startswith("__")]
