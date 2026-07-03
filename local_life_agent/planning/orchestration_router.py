"""Phase 4 shadow-mode orchestration router.

The router produces a structured secondary routing decision without
changing the active LangGraph execution path.
"""

from __future__ import annotations

import re
from typing import Any

from ..domain.candidate import GoalType
from ..domain.enums import TaskType, TopIntent
from ..domain.graph_state import GraphState
from ..domain.schemas import OrchestrationDecision
from ..domain.facets import build_target_resolution_result, normalize_query_facets
from .goal.goal_planner import _infer_explicit_mentions_from_text
from ..target.reference_resolver import resolve_comparison_targets, resolve_references

_DIRECT_TOP_INTENTS = {
    TopIntent.chat.value,
    TopIntent.capability.value,
    TopIntent.invalid.value,
    TopIntent.unsafe.value,
    TopIntent.out_of_scope.value,
}

_FORBIDDEN_SCOPE_HINTS = {
    "rag",
    "平台政策",
    "退款",
    "交易",
    "下单",
    "支付",
    "预约",
    "订单",
    "react",
    "future tool",
}

_ORCHESTRATION_POLICY_TABLE: dict[str, dict[str, Any]] = {
    "chat": {
        "orchestration_pattern": "direct_response",
        "workflow_name": "direct_response",
        "task_complexity": "low",
        "requires_tool": False,
        "requires_clarification": False,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
    },
    "capability": {
        "orchestration_pattern": "direct_response",
        "workflow_name": "direct_response",
        "task_complexity": "low",
        "requires_tool": False,
        "requires_clarification": False,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
    },
    "unsafe": {
        "orchestration_pattern": "direct_response",
        "workflow_name": "direct_response",
        "task_complexity": "low",
        "requires_tool": False,
        "requires_clarification": False,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
    },
    "out_of_scope": {
        "orchestration_pattern": "direct_response",
        "workflow_name": "direct_response",
        "task_complexity": "low",
        "requires_tool": False,
        "requires_clarification": False,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
    },
    "invalid": {
        "orchestration_pattern": "direct_response",
        "workflow_name": "direct_response",
        "task_complexity": "low",
        "requires_tool": False,
        "requires_clarification": False,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
    },
    "forbidden": {
        "orchestration_pattern": "direct_response",
        "workflow_name": "direct_response",
        "task_complexity": "low",
        "requires_tool": False,
        "requires_clarification": False,
        "response_mode": "direct_response",
        "next_action": "run_workflow",
    },
    "shop_status": {
        "orchestration_pattern": "deterministic_tool",
        "workflow_name": "deterministic_tool",
        "task_complexity": "low",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "tool_answer",
        "next_action": "run_workflow",
    },
    "shop_distance": {
        "orchestration_pattern": "deterministic_tool",
        "workflow_name": "deterministic_tool",
        "task_complexity": "low",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "tool_answer",
        "next_action": "run_workflow",
    },
    "shop_price": {
        "orchestration_pattern": "deterministic_tool",
        "workflow_name": "deterministic_tool",
        "task_complexity": "low",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "tool_answer",
        "next_action": "run_workflow",
    },
    "shop_coupon": {
        "orchestration_pattern": "deterministic_tool",
        "workflow_name": "deterministic_tool",
        "task_complexity": "low",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "tool_answer",
        "next_action": "run_workflow",
    },
    "shop_review_summary": {
        "orchestration_pattern": "deterministic_tool",
        "workflow_name": "deterministic_tool",
        "task_complexity": "low",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "tool_answer",
        "next_action": "run_workflow",
    },
    "shop_scene_fit": {
        "orchestration_pattern": "deterministic_tool",
        "workflow_name": "deterministic_tool",
        "task_complexity": "low",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "tool_answer",
        "next_action": "run_workflow",
    },
    "shop_search": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "search_list",
        "next_action": "run_workflow",
    },
    "recommendation": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "recommendation",
        "next_action": "run_workflow",
    },
    "comparison": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "comparison",
        "next_action": "run_workflow",
    },
    "condition_refine": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "refinement",
        "next_action": "run_workflow",
    },
    "scene_recommendation": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "recommendation",
        "next_action": "run_workflow",
    },
    "deal_compare": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "comparison",
        "next_action": "run_workflow",
    },
    "local_trip_plan": {
        "orchestration_pattern": "exploration_planning",
        "workflow_name": "exploration_planning",
        "task_complexity": "high",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "exploration_plan",
        "next_action": "run_workflow",
    },
    "date_plan": {
        "orchestration_pattern": "exploration_planning",
        "workflow_name": "exploration_planning",
        "task_complexity": "high",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "exploration_plan",
        "next_action": "run_workflow",
    },
    "family_activity_plan": {
        "orchestration_pattern": "exploration_planning",
        "workflow_name": "exploration_planning",
        "task_complexity": "high",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "exploration_plan",
        "next_action": "run_workflow",
    },
    "coffee_then_dinner": {
        "orchestration_pattern": "exploration_planning",
        "workflow_name": "exploration_planning",
        "task_complexity": "high",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "exploration_plan",
        "next_action": "run_workflow",
    },
    "eat_and_play_plan": {
        "orchestration_pattern": "exploration_planning",
        "workflow_name": "exploration_planning",
        "task_complexity": "high",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "exploration_plan",
        "next_action": "run_workflow",
    },
    "unknown": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
    "ambiguous": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
    "reference_failed": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
    "no_result": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
    "tool_failure": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
    "missing_required_slot": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
    "low_confidence": {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
    },
}

_EXPLORATION_TASKS = {
    "local_trip_plan",
    "date_plan",
    "family_activity_plan",
    "coffee_then_dinner",
    "eat_and_play_plan",
}

_DISCOVERY_TASKS = {
    "shop_search",
    "recommendation",
    "comparison",
    "condition_refine",
    "scene_recommendation",
    "deal_compare",
}

_DETERMINISTIC_TASKS = {
    "shop_status",
    "shop_distance",
    "shop_price",
    "shop_coupon",
    "shop_review_summary",
    "shop_scene_fit",
}

_CLARIFICATION_TASKS = {
    "unknown",
    "ambiguous",
    "reference_failed",
    "no_result",
    "tool_failure",
    "missing_required_slot",
    "low_confidence",
}

_LOW_CONFIDENCE_FLOOR = 0.5


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw or "").strip()


def _extract_text(state: GraphState) -> str:
    raw = _as_str(state.get("normalized_text") or state.get("raw_text"))
    if raw:
        return raw
    semantic_frame = _to_dict(state.get("semantic_frame"))
    return _as_str(semantic_frame.get("primary_task") or semantic_frame.get("goal_summary"))


def _extract_task_type(state: GraphState) -> str:
    task_type = _as_str(state.get("task_type"))
    if task_type:
        return task_type
    semantic_frame = _to_dict(state.get("semantic_frame"))
    task_type = _as_str(semantic_frame.get("task_type"))
    if task_type:
        return task_type
    goal_plan = _to_dict(state.get("goal_plan"))
    return _as_str(goal_plan.get("goal_type"))


def _extract_goal_type(state: GraphState) -> str:
    goal_plan = _to_dict(state.get("goal_plan"))
    return _as_str(goal_plan.get("goal_type"))


def _extract_top_intent(state: GraphState) -> str:
    return _as_str(state.get("top_intent"))


def _extract_confidence(state: GraphState) -> float:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    goal_plan = _to_dict(state.get("goal_plan"))
    for raw in (
        semantic_frame.get("confidence"),
        goal_plan.get("planner_confidence"),
        goal_plan.get("confidence"),
    ):
        if raw is None:
            continue
        try:
            confidence = float(raw)
        except Exception:
            continue
        if confidence > 0:
            return min(1.0, max(0.0, confidence))
    return 0.0


def _session_value(state: GraphState, field: str) -> Any:
    session_state = state.get("session_state")
    if isinstance(session_state, dict):
        value = session_state.get(field)
        if value:
            return value
    elif session_state is not None:
        value = getattr(session_state, field, None)
        if value:
            return value
    session_state_before = state.get("session_state_before")
    if isinstance(session_state_before, dict):
        return session_state_before.get(field)
    if session_state_before is not None:
        return getattr(session_state_before, field, None)
    return state.get(field)


def _extract_facets(state: GraphState) -> list[str]:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    facet_set = _to_dict(semantic_frame.get("facet_set"))
    raw_facets = facet_set.get("facets") or semantic_frame.get("facets") or state.get("facets") or []
    facets: list[str] = []
    for item in raw_facets:
        if isinstance(item, str):
            if item.strip():
                facets.append(item.strip())
            continue
        if isinstance(item, dict):
            name = _as_str(item.get("name") or item.get("facet"))
            if name:
                facets.append(name)
            elif item.get("group") and item.get("value"):
                facets.append(_as_str(item.get("value")))
            continue
        name = _as_str(getattr(item, "name", "") or getattr(item, "facet", ""))
        if name:
            facets.append(name)
    return facets


def _extract_primary_task(state: GraphState) -> str:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    return _as_str(semantic_frame.get("primary_task"))


def _is_forbidden_scope(state: GraphState) -> bool:
    text = f"{_extract_text(state)} {_extract_primary_task(state)} {_extract_goal_type(state)}"
    lowered = text.lower()
    return any(token in lowered for token in _FORBIDDEN_SCOPE_HINTS)


def _has_pending_clarification(state: GraphState) -> bool:
    return state.get("pending_clarification") is not None or state.get("clarification_request") is not None


def _has_single_shop_anchor(state: GraphState) -> bool:
    current_shop = _to_dict(state.get("current_shop") or _session_value(state, "current_shop"))
    if current_shop.get("shop_id") or current_shop.get("shop_name"):
        return True
    resolved_target = _to_dict(state.get("resolve_shop_result") or state.get("resolved_target"))
    if str(resolved_target.get("status", "") or "").upper() == "RESOLVED":
        shop = _to_dict(resolved_target.get("resolved_shop") or resolved_target.get("shop"))
        if shop.get("shop_id") or shop.get("shop_name"):
            return True
    return False


def _has_verified_single_shop_anchor(state: GraphState) -> bool:
    if _has_single_shop_anchor(state):
        return True
    resolved_target = _to_dict(state.get("resolved_target") or _session_value(state, "resolved_target"))
    if str(resolved_target.get("status", "") or "").upper() == "RESOLVED":
        shop = _to_dict(resolved_target.get("resolved_shop") or resolved_target.get("shop"))
        if shop.get("shop_id") or shop.get("shop_name"):
            return True
    return False


def _looks_like_specific_shop_mention(mention: str) -> bool:
    text = str(mention or "").strip()
    if not text:
        return False
    if text.startswith(("这家", "那家", "这间", "那间", "它", "第一家", "第二家", "第三家")):
        return False
    if any(token in text for token in ("(", "（", ")", "）")):
        return True
    return any(token in text for token in ("店", "馆", "轩", "居", "坊", "楼", "城", "中心", "广场"))


def _has_deterministic_target_hints(state: GraphState) -> bool:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    merchant_mentions = [str(item).strip() for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    ordinal_references = [str(item).strip() for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
    comparison_targets = list(semantic_frame.get("comparison_targets") or [])
    deictic_references = [str(item).strip() for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
    raw_text = _extract_text(state)
    inferred_mentions = _infer_explicit_mentions_from_text(raw_text)
    has_raw_ordinal = bool(re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", raw_text))
    has_raw_deictic = any(token in raw_text for token in ("这家", "那家", "它", "这间", "那间"))
    has_current_shop = bool(_to_dict(state.get("current_shop") or _session_value(state, "current_shop")).get("shop_id") or _to_dict(state.get("current_shop") or _session_value(state, "current_shop")).get("shop_name"))
    has_last_recommendations = bool(state.get("last_recommendation_list") or _session_value(state, "last_recommendation_list"))
    has_specific_merchant_mention = any(_looks_like_specific_shop_mention(mention) for mention in merchant_mentions)
    has_verified_explicit_mention = any(
        _looks_like_specific_shop_mention(mention)
        for mention in inferred_mentions
    )

    if has_specific_merchant_mention or comparison_targets or has_verified_explicit_mention:
        return True
    if (ordinal_references or has_raw_ordinal) and has_last_recommendations:
        return True
    if (deictic_references or has_raw_deictic) and has_current_shop:
        return True
    return False


def _count_single_shop_signal_groups(state: GraphState) -> int:
    text = _extract_text(state)
    groups = [
        ("coupon", ("有券", "优惠券", "优惠", "团购", "coupon")),
        ("status", ("营业", "开门", "打烊", "open")),
        ("distance", ("距离", "多远", "多久", "eta", "几分钟")),
        ("review", ("评价", "口碑", "review")),
        ("price", ("价格", "多少钱", "人均", "price")),
    ]
    count = 0
    lowered = text.lower()
    for _name, tokens in groups:
        if any(token in text or token in lowered for token in tokens):
            count += 1
    return count


def _has_reference_failure(state: GraphState) -> bool:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    if semantic_frame.get("need_context") is True:
        return True
    if semantic_frame.get("reference_mentions"):
        return not _has_single_shop_anchor(state)
    if _has_pending_clarification(state):
        return True
    task_type = _extract_task_type(state)
    if task_type == TaskType.clarification_reply.value:
        return True
    return False


def _has_comparison_signal(state: GraphState) -> bool:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    raw_text = _extract_text(state)
    return bool(
        semantic_frame.get("comparison_targets")
        or state.get("comparison_targets")
        or semantic_frame.get("comparison_focus")
        or any(token in raw_text for token in ("比", "对比"))
    )


def _has_reference_signal(state: GraphState) -> bool:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    raw_text = _extract_text(state)
    return bool(
        semantic_frame.get("reference_mentions")
        or semantic_frame.get("ordinal_references")
        or semantic_frame.get("deictic_references")
        or any(token in raw_text for token in ("这家", "那家", "它", "这间", "那间", "第一家", "第二家", "第三家"))
    )


def _route_task_from_single_shop(state: GraphState, facets: list[str]) -> str:
    if not facets:
        primary_task = _extract_primary_task(state).lower()
        if "coupon" in primary_task:
            return "shop_coupon"
        if "distance" in primary_task or "eta" in primary_task:
            return "shop_distance"
        if "price" in primary_task or "cost" in primary_task:
            return "shop_price"
        if "review" in primary_task or "summary" in primary_task:
            return "shop_review_summary"
        if "scene" in primary_task or "fit" in primary_task:
            return "shop_scene_fit"
        if "status" in primary_task or "open" in primary_task:
            return "shop_status"
        return "unknown"

    facet_priority = [
        ("coupon", "shop_coupon"),
        ("distance", "shop_distance"),
        ("price", "shop_price"),
        ("review_summary", "shop_review_summary"),
        ("scene_fit", "shop_scene_fit"),
        ("open_status", "shop_status"),
        ("status", "shop_status"),
    ]
    for facet_name, route_task in facet_priority:
        if facet_name in facets:
            return route_task
    return "unknown"


def normalize_route_task(state: GraphState) -> str:
    """Normalize the current turn into a router task label."""

    top_intent = _extract_top_intent(state)
    if top_intent in _DIRECT_TOP_INTENTS:
        return top_intent
    if _is_forbidden_scope(state):
        return "forbidden"

    task_type = _extract_task_type(state)
    goal_type = _extract_goal_type(state)
    facets = _extract_facets(state)
    semantic_frame = _to_dict(state.get("semantic_frame"))
    primary_task = _extract_primary_task(state).lower()
    raw_text = _extract_text(state).lower()
    raw_text_original = _extract_text(state)
    raw_explicit_mentions = _infer_explicit_mentions_from_text(raw_text_original)
    has_session_current_shop = bool(_to_dict(_session_value(state, "current_shop")).get("shop_id") or _to_dict(_session_value(state, "current_shop")).get("shop_name"))
    has_session_recommendations = bool(_session_value(state, "last_recommendation_list"))

    if _has_pending_clarification(state):
        return "reference_failed"

    comparison_requested = task_type in {"comparison", "deal_compare"} or goal_type in {"comparison", "deal_compare"} or _has_comparison_signal(state)
    if comparison_requested:
        semantic_comparison_targets = [item for item in (semantic_frame.get("comparison_targets") or []) if item]
        state_comparison_targets = [item for item in (state.get("comparison_targets") or []) if item]
        comparison_resolution = resolve_comparison_targets(raw_text_original, state, semantic_frame)
        resolved_targets = list(comparison_resolution.get("targets") or [])
        if len(semantic_comparison_targets) >= 2 or len(state_comparison_targets) >= 2 or len(resolved_targets) >= 2:
            if task_type in {"comparison", "deal_compare"}:
                return task_type
            if goal_type in {"comparison", "deal_compare"}:
                return goal_type
            return "comparison"
        if comparison_resolution.get("unresolved_targets") or comparison_resolution.get("ambiguous_target") or _has_comparison_signal(state):
            return "missing_required_slot"

    if _count_single_shop_signal_groups(state) <= 1:
        has_raw_deictic = any(token in raw_text_original for token in ("这家", "那家", "它", "这间", "那间"))
        has_raw_ordinal = bool(re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", raw_text_original))
        has_verified_explicit_mention = any(
            mention
            and not mention.startswith(("这家", "那家", "第一家", "第二家", "第三家"))
            and not re.fullmatch(r"[这那它]\S*", mention)
            for mention in raw_explicit_mentions
        )
        if (has_verified_explicit_mention or (has_raw_deictic and has_session_current_shop) or (has_raw_ordinal and has_session_recommendations)) and "比" not in raw_text and "对比" not in raw_text:
            if "营业" in raw_text or "开门" in raw_text or "open" in raw_text:
                return "shop_status"
            if "有券" in raw_text or "优惠券" in raw_text or "coupon" in raw_text or "团购" in raw_text:
                return "shop_coupon"
            if "距离" in raw_text or "多远" in raw_text or "eta" in raw_text or "多久" in raw_text:
                return "shop_distance"
            if "评价" in raw_text or "review" in raw_text:
                return "shop_review_summary"
            if "价格" in raw_text or "多少钱" in raw_text or "price" in raw_text:
                return "shop_price"

    if goal_type in _EXPLORATION_TASKS or task_type in _EXPLORATION_TASKS:
        return goal_type or task_type

    if task_type in _DETERMINISTIC_TASKS:
        if task_type == "shop_coupon":
            return "shop_coupon"
        if task_type == "shop_review_summary":
            return "shop_review_summary"
        if task_type == "shop_scene_fit":
            return "shop_scene_fit"
        return task_type

    if task_type in {"comparison", "recommendation"}:
        if task_type == "recommendation" and _has_deterministic_target_hints(state) and _count_single_shop_signal_groups(state) <= 1:
            if "营业" in raw_text or "开门" in raw_text or "open" in raw_text:
                return "shop_status"
            if "有券" in raw_text or "优惠券" in raw_text or "coupon" in raw_text or "团购" in raw_text:
                return "shop_coupon"
            if "距离" in raw_text or "多远" in raw_text or "eta" in raw_text:
                return "shop_distance"
            if "评价" in raw_text or "review" in raw_text:
                return "shop_review_summary"
            if "价格" in raw_text or "多少钱" in raw_text or "price" in raw_text:
                return "shop_price"
            route_task = _route_task_from_single_shop(state, facets)
            if route_task != "unknown":
                return route_task
        return task_type

    if goal_type in _DISCOVERY_TASKS:
        return goal_type

    if task_type == TaskType.coupon_query.value:
        return "shop_coupon"

    reference_requested = task_type == TaskType.single_shop_query.value or goal_type == TaskType.single_shop_query.value or _has_reference_signal(state)
    if reference_requested:
        reference_resolution = resolve_references(raw_text_original, state, semantic_frame)
        reference_status = str(reference_resolution.get("status", "") or "").lower()
        if reference_status in {"resolved", "resolved_list"} or _has_verified_single_shop_anchor(state) or _has_deterministic_target_hints(state):
            if len({facet for facet in facets if facet}) > 1:
                return "recommendation"
            route_task = _route_task_from_single_shop(state, facets)
            if route_task != "unknown":
                return route_task
            if "有券" in raw_text or "优惠券" in raw_text or "coupon" in raw_text:
                return "shop_coupon"
            if "营业" in raw_text or "开门" in raw_text or "open" in raw_text:
                return "shop_status"
            if "距离" in raw_text or "多远" in raw_text or "eta" in raw_text:
                return "shop_distance"
            if "评价" in raw_text or "review" in raw_text:
                return "shop_review_summary"
            if "场景" in raw_text or "适合" in raw_text or "scene" in raw_text:
                return "shop_scene_fit"
            if "价格" in raw_text or "多少钱" in raw_text or "price" in raw_text:
                return "shop_price"
            if primary_task:
                if any(token in primary_task for token in ("coupon", "券")):
                    return "shop_coupon"
                if any(token in primary_task for token in ("status", "open", "营业")):
                    return "shop_status"
                if any(token in primary_task for token in ("distance", "eta", "距离")):
                    return "shop_distance"
                if any(token in primary_task for token in ("review", "summary", "评价")):
                    return "shop_review_summary"
                if any(token in primary_task for token in ("scene", "fit", "场景")):
                    return "shop_scene_fit"
                if any(token in primary_task for token in ("price", "价格", "费用")):
                    return "shop_price"
            return "unknown"
        if reference_status in {"ambiguous", "out_of_range", "unresolved"} or _has_reference_signal(state):
            return "missing_required_slot"

    if task_type == TaskType.single_shop_query.value or goal_type == TaskType.single_shop_query.value:
        if _has_reference_signal(state) and not _has_single_shop_anchor(state):
            return "missing_required_slot"
        if not _has_verified_single_shop_anchor(state) and not _has_deterministic_target_hints(state):
            return "missing_required_slot"
        if _has_reference_failure(state) and not _has_single_shop_anchor(state):
            return "reference_failed"
        if not _has_verified_single_shop_anchor(state) and not _has_deterministic_target_hints(state) and _count_single_shop_signal_groups(state) <= 1:
            return "missing_required_slot"
        if len({facet for facet in facets if facet}) > 1:
            return "recommendation"
        route_task = _route_task_from_single_shop(state, facets)
        if route_task != "unknown":
            return route_task
        if "有券" in raw_text or "优惠券" in raw_text or "coupon" in raw_text:
            return "shop_coupon"
        if "营业" in raw_text or "开门" in raw_text or "open" in raw_text:
            return "shop_status"
        if "距离" in raw_text or "多远" in raw_text or "eta" in raw_text:
            return "shop_distance"
        if "评价" in raw_text or "review" in raw_text:
            return "shop_review_summary"
        if "场景" in raw_text or "适合" in raw_text or "scene" in raw_text:
            return "shop_scene_fit"
        if "价格" in raw_text or "多少钱" in raw_text or "price" in raw_text:
            return "shop_price"
        if primary_task:
            if any(token in primary_task for token in ("coupon", "券")):
                return "shop_coupon"
            if any(token in primary_task for token in ("status", "open", "营业")):
                return "shop_status"
            if any(token in primary_task for token in ("distance", "eta", "距离")):
                return "shop_distance"
            if any(token in primary_task for token in ("review", "summary", "评价")):
                return "shop_review_summary"
            if any(token in primary_task for token in ("scene", "fit", "场景")):
                return "shop_scene_fit"
            if any(token in primary_task for token in ("price", "价格", "费用")):
                return "shop_price"
        return "unknown"

    if task_type == TaskType.general_chat.value:
        return "chat"

    if semantic_frame.get("candidate_category") or semantic_frame.get("hard_constraints"):
        return "shop_search"

    if "推荐" in raw_text or "附近" in raw_text or "找" in raw_text:
        if "比" in raw_text or "对比" in raw_text:
            return "comparison"
        return "recommendation"

    if "行程" in raw_text or "安排" in raw_text or "计划" in raw_text:
        return "unknown"

    if task_type in _CLARIFICATION_TASKS:
        return task_type

    return "unknown"


def _build_missing_fields(state: GraphState, route_task: str) -> list[str]:
    missing_fields: list[str] = []
    if not _extract_text(state):
        missing_fields.append("semantic_frame")
    task_type = _extract_task_type(state)
    goal_type = _extract_goal_type(state)
    if route_task in {"missing_required_slot", "reference_failed"} and (task_type == TaskType.single_shop_query.value or goal_type == TaskType.single_shop_query.value):
        if not _has_verified_single_shop_anchor(state) and "current_shop" not in missing_fields:
            missing_fields.append("current_shop")
    if route_task in _DETERMINISTIC_TASKS and not _has_single_shop_anchor(state) and not _has_deterministic_target_hints(state):
        missing_fields.append("current_shop")
    if route_task in _DISCOVERY_TASKS and not _extract_text(state):
        missing_fields.append("semantic_frame")
    if route_task in _EXPLORATION_TASKS and not _extract_text(state):
        missing_fields.append("semantic_frame")
    if route_task in _CLARIFICATION_TASKS and not _has_pending_clarification(state) and not _has_reference_failure(state):
        missing_fields.append("pending_clarification")
    seen: set[str] = set()
    deduped: list[str] = []
    for field in missing_fields:
        if field not in seen:
            seen.add(field)
            deduped.append(field)
    return deduped


def _policy_for_route_task(route_task: str) -> dict[str, Any] | None:
    return _ORCHESTRATION_POLICY_TABLE.get(route_task)


def _fallback_policy(reason: str) -> dict[str, Any]:
    return {
        "orchestration_pattern": "clarification_fallback",
        "workflow_name": "clarification_fallback",
        "task_complexity": "medium",
        "requires_tool": False,
        "requires_clarification": True,
        "response_mode": "clarify",
        "next_action": "clarify",
        "workflow_reason": reason,
    }


def _score_confidence(state: GraphState, route_task: str, requires_tool: bool, requires_clarification: bool) -> float:
    confidence = _extract_confidence(state)
    if confidence <= 0:
        confidence = {
            "chat": 0.65,
            "capability": 0.65,
            "unsafe": 0.6,
            "out_of_scope": 0.55,
            "invalid": 0.45,
            "shop_status": 0.8,
            "shop_distance": 0.8,
            "shop_price": 0.78,
            "shop_coupon": 0.8,
            "shop_review_summary": 0.76,
            "shop_scene_fit": 0.75,
            "shop_search": 0.72,
            "recommendation": 0.7,
            "comparison": 0.7,
            "condition_refine": 0.68,
            "scene_recommendation": 0.7,
            "deal_compare": 0.68,
            "local_trip_plan": 0.58,
            "date_plan": 0.58,
            "family_activity_plan": 0.58,
            "coffee_then_dinner": 0.58,
            "eat_and_play_plan": 0.58,
        }.get(route_task, 0.35)
    if requires_tool:
        confidence = min(1.0, confidence + 0.05)
    if requires_clarification:
        confidence = max(0.0, confidence - 0.1)
    return round(confidence, 3)


def _workflow_reason(
    state: GraphState,
    *,
    route_task: str,
    missing_fields: list[str],
    policy: dict[str, Any],
    requires_tool: bool,
    requires_clarification: bool,
) -> str:
    parts: list[str] = []
    top_intent = _extract_top_intent(state)
    task_type = _extract_task_type(state)
    goal_type = _extract_goal_type(state)
    if top_intent:
        parts.append(f"top_intent={top_intent}")
    if task_type:
        parts.append(f"task_type={task_type}")
    if goal_type:
        parts.append(f"goal_type={goal_type}")
    if route_task:
        parts.append(f"route_task={route_task}")
    if missing_fields:
        parts.append(f"missing={','.join(missing_fields)}")
    if requires_tool:
        parts.append("requires_tool")
    if requires_clarification:
        parts.append("requires_clarification")
    reason = str(policy.get("workflow_reason", "") or "").strip()
    if reason:
        parts.append(reason)
    if route_task == "forbidden":
        parts.append("unsupported/forbidden scope")
    return "; ".join(parts)


def _build_decision_from_policy(state: GraphState, route_task: str, policy: dict[str, Any]) -> OrchestrationDecision:
    missing_fields = _build_missing_fields(state, route_task)
    requires_tool = bool(policy.get("requires_tool", False))
    requires_clarification = bool(policy.get("requires_clarification", False))
    confidence = _score_confidence(state, route_task, requires_tool, requires_clarification)
    workflow_reason = _workflow_reason(
        state,
        route_task=route_task,
        missing_fields=missing_fields,
        policy=policy,
        requires_tool=requires_tool,
        requires_clarification=requires_clarification,
    )
    return OrchestrationDecision(
        orchestration_pattern=str(policy.get("orchestration_pattern", "clarification_fallback") or "clarification_fallback"),
        workflow_name=str(policy.get("workflow_name", "clarification_fallback") or "clarification_fallback"),
        workflow_reason=workflow_reason,
        task_complexity=str(policy.get("task_complexity", "medium") or "medium"),
        requires_tool=requires_tool,
        requires_clarification=requires_clarification,
        response_mode=str(policy.get("response_mode", "clarify") or "clarify"),
        confidence=confidence,
        missing_fields=missing_fields,
        next_action=str(policy.get("next_action", "clarify") or "clarify"),
    )


def validate_orchestration_decision(decision: OrchestrationDecision, state: GraphState) -> OrchestrationDecision:
    """Validate and normalize a shadow orchestration decision."""

    route_task = normalize_route_task(state)
    policy = _policy_for_route_task(route_task)
    if policy is None:
        return OrchestrationDecision(
            **_fallback_policy(f"policy table missing route_task={route_task or 'unknown'}"),
            confidence=min(decision.confidence, 0.35),
            missing_fields=list(decision.missing_fields or []) or (["semantic_frame"] if not _extract_text(state) else []),
        )

    normalized = decision.model_copy(deep=True)
    if normalized.workflow_name != normalized.orchestration_pattern:
        normalized = OrchestrationDecision(
            **_fallback_policy("workflow_name must match orchestration_pattern"),
            confidence=min(normalized.confidence, 0.35),
            missing_fields=list(dict.fromkeys((normalized.missing_fields or []) + ["policy_mismatch"])),
        )
        return normalized

    if normalized.requires_clarification and normalized.next_action not in {"clarify", "fallback"}:
        normalized = normalized.model_copy(
            update={
                "workflow_name": "clarification_fallback",
                "orchestration_pattern": "clarification_fallback",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "next_action": "clarify",
                "task_complexity": "medium",
            }
        )

    if normalized.workflow_name in {"discovery_decision", "deterministic_tool", "exploration_planning"}:
        if normalized.missing_fields:
            normalized = normalized.model_copy(
                update={
                    "workflow_name": "clarification_fallback",
                    "orchestration_pattern": "clarification_fallback",
                    "requires_tool": False,
                    "requires_clarification": True,
                    "response_mode": "clarify",
                    "next_action": "clarify",
                    "task_complexity": "medium",
                }
            )
        elif normalized.confidence < _LOW_CONFIDENCE_FLOOR:
            normalized = normalized.model_copy(
                update={
                    "workflow_name": "clarification_fallback",
                    "orchestration_pattern": "clarification_fallback",
                    "requires_tool": False,
                    "requires_clarification": True,
                    "response_mode": "clarify",
                    "next_action": "clarify",
                    "task_complexity": "medium",
                }
            )

    if route_task == "reference_failed" and normalized.workflow_name == "deterministic_tool":
        normalized = normalized.model_copy(
            update={
                "workflow_name": "clarification_fallback",
                "orchestration_pattern": "clarification_fallback",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "next_action": "clarify",
                "task_complexity": "medium",
            }
        )

    if route_task in _CLARIFICATION_TASKS:
        normalized = normalized.model_copy(
            update={
                "workflow_name": "clarification_fallback",
                "orchestration_pattern": "clarification_fallback",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "next_action": "clarify",
                "task_complexity": "medium",
            }
        )

    if route_task in {"chat", "capability", "unsafe", "out_of_scope", "invalid"}:
        normalized = normalized.model_copy(
            update={
                "workflow_name": "direct_response",
                "orchestration_pattern": "direct_response",
                "requires_tool": False,
                "requires_clarification": False,
                "response_mode": "direct_response",
                "next_action": "run_workflow",
                "task_complexity": "low",
            }
        )

    if route_task == "forbidden" and normalized.workflow_name not in {"direct_response", "clarification_fallback"}:
        normalized = normalized.model_copy(
            update={
                "workflow_name": "direct_response",
                "orchestration_pattern": "direct_response",
                "requires_tool": False,
                "requires_clarification": False,
                "response_mode": "direct_response",
                "next_action": "run_workflow",
                "task_complexity": "low",
            }
        )

    return normalized


def build_orchestration_decision(state: GraphState) -> OrchestrationDecision:
    """Build a shadow routing decision without changing execution."""

    route_task = normalize_route_task(state)
    policy = _policy_for_route_task(route_task)
    if policy is None:
        return OrchestrationDecision(
            **_fallback_policy(f"policy table missing route_task={route_task or 'unknown'}"),
            confidence=0.35,
            missing_fields=["semantic_frame"] if not _extract_text(state) else [],
        )

    decision = _build_decision_from_policy(state, route_task, policy)

    # Route-specific fallbacks and guard rails before the validator runs.
    if route_task == "forbidden":
        decision = decision.model_copy(
            update={
                "workflow_name": "direct_response",
                "orchestration_pattern": "direct_response",
                "requires_tool": False,
                "requires_clarification": False,
                "response_mode": "direct_response",
                "next_action": "run_workflow",
                "task_complexity": "low",
                "workflow_reason": f"{decision.workflow_reason}; unsupported/forbidden scope",
            }
        )
    if route_task in _DETERMINISTIC_TASKS and "current_shop" in decision.missing_fields:
        decision = decision.model_copy(
            update={
                "workflow_name": "clarification_fallback",
                "orchestration_pattern": "clarification_fallback",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "next_action": "clarify",
                "task_complexity": "medium",
            }
        )
    if route_task == "missing_required_slot":
        decision = decision.model_copy(
            update={
                "workflow_name": "clarification_fallback",
                "orchestration_pattern": "clarification_fallback",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "next_action": "clarify",
                "task_complexity": "medium",
            }
        )
    if route_task == "reference_failed" and route_task not in _DETERMINISTIC_TASKS:
        decision = decision.model_copy(
            update={
                "workflow_name": "clarification_fallback",
                "orchestration_pattern": "clarification_fallback",
                "requires_tool": False,
                "requires_clarification": True,
                "response_mode": "clarify",
                "next_action": "clarify",
                "task_complexity": "medium",
            }
        )

    validated = validate_orchestration_decision(decision, state)
    return validated


def _decision_patch(decision: OrchestrationDecision, *, error_code: str = "", error_message: str = "") -> dict[str, Any]:
    return {
        "orchestration_decision": decision,
        "orchestration_pattern": decision.orchestration_pattern,
        "workflow_name": decision.workflow_name,
        "workflow_reason": decision.workflow_reason,
        "task_complexity": decision.task_complexity,
        "requires_tool": decision.requires_tool,
        "requires_clarification": decision.requires_clarification,
        "response_mode": decision.response_mode,
        "next_action": decision.next_action,
        "orchestration_error_code": error_code,
        "orchestration_error_message": error_message,
    }


def route_orchestration(state: GraphState) -> dict[str, Any]:
    """Safe public entry point for Phase 4 shadow routing."""

    try:
        raw_decision = build_orchestration_decision(state)
        decision = validate_orchestration_decision(raw_decision, state)
        error_code = ""
        error_message = ""
        if raw_decision.model_dump() != decision.model_dump():
            error_code = "ORCHESTRATION_VALIDATION_FALLBACK"
            error_message = decision.workflow_reason or "orchestration decision normalized by validator"
        facet_set = normalize_query_facets(state.get("semantic_frame"), state.get("session_state_before") or state.get("session_state"), _extract_text(state))
        patch = _decision_patch(decision, error_code=error_code, error_message=error_message)
        patch.update(
            {
                "facet_set": facet_set,
                "facets": facet_set.facets,
                "target_resolution": facet_set.target_resolution or build_target_resolution_result(state.get("semantic_frame"), session_state=state.get("session_state_before") or state.get("session_state"), raw_text=_extract_text(state)),
                "conflicting_facets": facet_set.conflicting_facets,
                "ranking_policy": facet_set.ranking_policy,
            }
        )
        return patch
    except Exception as exc:
        fallback = OrchestrationDecision(
            orchestration_pattern="clarification_fallback",
            workflow_name="clarification_fallback",
            workflow_reason=f"router exception: {exc}",
            task_complexity="medium",
            requires_tool=False,
            requires_clarification=True,
            response_mode="clarify",
            confidence=0.0,
            missing_fields=["semantic_frame"],
            next_action="clarify",
        )
        patch = _decision_patch(
            fallback,
            error_code="ORCHESTRATION_ROUTER_EXCEPTION",
            error_message=str(exc),
        )
        patch.update({"facet_set": None, "facets": [], "target_resolution": None, "conflicting_facets": [], "ranking_policy": None})
        return patch


def build_orchestration_shadow_patch(state: GraphState) -> dict[str, Any]:
    """Backward-compatible alias for the Phase 4 shadow routing patch."""

    return route_orchestration(state)
