"""Phase 4 shadow-mode orchestration router.

The router produces a structured secondary routing decision without
changing the active LangGraph execution path.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..domain.candidate import GoalType
from ..domain.enums import ComparisonStructure, GroundingStatus, MissingSlotType, SemanticParseSource, TaskType, TopIntent
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
        "workflow_entry_name": "recommendation_decision_workflow",
        "task_complexity": "medium",
        "requires_tool": True,
        "requires_clarification": False,
        "response_mode": "recommendation",
        "next_action": "run_workflow",
    },
    "comparison": {
        "orchestration_pattern": "discovery_decision",
        "workflow_name": "discovery_decision",
        "workflow_entry_name": "comparison_decision_workflow",
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
    "super_complex": {
        "orchestration_pattern": "complex_orchestrator_workflow",
        "workflow_name": "complex_orchestrator_workflow",
        "task_complexity": "super_complex",
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
_SEMANTIC_LOW_CONFIDENCE_FLOOR = 0.5
_STRUCTURED_COMPARISON_STRUCTURES = {
    ComparisonStructure.pairwise.value,
    ComparisonStructure.multi_target.value,
    ComparisonStructure.ordinal.value,
    ComparisonStructure.deictic.value,
    ComparisonStructure.explicit.value,
    ComparisonStructure.mixed.value,
}
_CLARIFICATION_SLOT_TYPES = {
    MissingSlotType.missing_location.value,
    MissingSlotType.missing_shop.value,
    MissingSlotType.missing_shop_target.value,
    MissingSlotType.missing_comparison_targets.value,
    MissingSlotType.missing_exploration_location.value,
    MissingSlotType.missing_category.value,
    MissingSlotType.unresolved_reference.value,
}
_GROUNDING_CLARIFICATION_STATUSES = {
    GroundingStatus.ungrounded.value,
    GroundingStatus.partially_grounded.value,
}


@dataclass(frozen=True)
class RouterRuleSignal:
    """Weak rule-layer signal emitted for router policy evaluation."""

    name: str
    category: str
    confidence: float
    source: str
    evidence: str
    positive: bool = True


def _semantic_frame(state: GraphState) -> dict[str, Any]:
    return _to_dict(state.get("semantic_frame"))


def _semantic_text_field(semantic_frame: dict[str, Any], *names: str) -> str:
    for name in names:
        value = _as_str(semantic_frame.get(name))
        if value:
            return value
    return ""


def _semantic_cancel_intent(state: GraphState) -> bool:
    semantic_frame = _semantic_frame(state)
    return bool(semantic_frame.get("cancel_intent"))


def _semantic_new_task_override(state: GraphState) -> bool:
    semantic_frame = _semantic_frame(state)
    return bool(semantic_frame.get("new_task_override"))


def _semantic_route_confidence(state: GraphState) -> float:
    return _extract_confidence(state)


def _semantic_parse_source_value(state: GraphState) -> str:
    semantic_frame = _semantic_frame(state)
    return _as_str(
        semantic_frame.get("semantic_parse_source")
        or semantic_frame.get("parse_source")
        or semantic_frame.get("semantic_source")
    )


def _semantic_grounding_status(state: GraphState) -> str:
    semantic_frame = _semantic_frame(state)
    return _as_str(semantic_frame.get("grounding_status"))


def _semantic_missing_slot_type(state: GraphState) -> str:
    semantic_frame = _semantic_frame(state)
    return _as_str(semantic_frame.get("missing_slot_type"))


def _semantic_exploration_count(state: GraphState) -> int:
    semantic_frame = _semantic_frame(state)
    stages = semantic_frame.get("exploration_stages") or []
    return len([item for item in stages if item])


def _semantic_comparison_count(state: GraphState) -> int:
    semantic_frame = _semantic_frame(state)
    comparison_targets = [item for item in (semantic_frame.get("comparison_targets") or []) if item]
    ordinal_references = [item for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
    deictic_references = [item for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
    merchant_mentions = [item for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    return max(len(comparison_targets), len(ordinal_references), len(deictic_references), len(merchant_mentions))


def _make_rule_signal(
    name: str,
    category: str,
    confidence: float,
    source: str,
    evidence: str,
    *,
    positive: bool = True,
) -> RouterRuleSignal:
    return RouterRuleSignal(
        name=name,
        category=category,
        confidence=max(0.0, min(1.0, confidence)),
        source=source,
        evidence=evidence,
        positive=positive,
    )


def _collect_router_rule_signals(state: GraphState) -> list[RouterRuleSignal]:
    """Collect weak rule signals without letting them own workflow selection."""

    text = _extract_text(state)
    semantic_frame = _to_dict(state.get("semantic_frame"))
    signals: list[RouterRuleSignal] = []

    if any(token in text for token in ("推荐", "附近", "找", "搜", "探店")):
        signals.append(_make_rule_signal("discovery_keyword", "discovery", 0.7, "text", text))
    semantic_exploration_count = _semantic_exploration_count(state)
    semantic_workflow_hint = _semantic_text_field(semantic_frame, "workflow_hint")
    if semantic_exploration_count > 0:
        signals.append(
            _make_rule_signal(
                "exploration_structured",
                "exploration",
                0.9,
                "semantic_frame",
                f"exploration_stages={semantic_exploration_count};workflow_hint={semantic_workflow_hint}",
            )
        )

    comparison_targets = list(semantic_frame.get("comparison_targets") or [])
    if len(comparison_targets) >= 2 or semantic_frame.get("comparison_intent") is True:
        signals.append(
            _make_rule_signal(
                "comparison_targets",
                "comparison",
                0.95 if len(comparison_targets) >= 2 else 0.85,
                "semantic_frame",
                "comparison_targets" if comparison_targets else "comparison_intent",
            )
        )

    structural_comparison_hints = (
        "对比",
        "比较一下",
        "比一下",
        "哪个更",
        "哪家更",
        "哪一个更",
        "哪间更",
        "A vs B",
        "vs",
        "二选一",
        "两家里",
        "两个里",
        "这两家",
        "这两个",
        "第一家和第二家",
        "第一家第二家",
    )
    if any(token in text for token in structural_comparison_hints):
        signals.append(_make_rule_signal("comparison_keyword", "comparison", 0.9, "text", text))

    if any(token in text for token in ("这家", "那家", "它", "这间", "那间", "第一家", "第二家", "第三家")):
        signals.append(_make_rule_signal("clarification_reference_keyword", "clarification", 0.6, "text", text))

    return signals


def _find_rule_signal(signals: list[RouterRuleSignal], *, category: str, min_confidence: float = 0.0) -> RouterRuleSignal | None:
    for signal in signals:
        if signal.category == category and signal.confidence >= min_confidence:
            return signal
    return None


def _has_strong_comparison_context(state: GraphState) -> bool:
    semantic_frame = _to_dict(state.get("semantic_frame"))
    merchant_mentions = [item for item in (semantic_frame.get("merchant_mentions") or []) if str(item).strip()]
    comparison_targets = [item for item in (semantic_frame.get("comparison_targets") or []) if item]
    ordinal_references = [item for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
    deictic_references = [item for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
    if len(comparison_targets) >= 2 or len(merchant_mentions) >= 2 or len(ordinal_references) >= 2 or len(deictic_references) >= 2:
        return True
    if len(comparison_targets) >= 2:
        return True
    text = _extract_text(state)
    if re.search(r"[A-Za-z0-9一二三四五六七八九十]+\s*(vs|VS|和|与)\s*[A-Za-z0-9一二三四五六七八九十]+", text):
        return True
    if re.search(r"第\s*[1-9一二三四五六七八九十]\s*(个|家|间|店)?\s*和\s*第\s*[1-9一二三四五六七八九十]\s*(个|家|间|店)?", text):
        return True
    if any(
        token in text
        for token in (
            "这两家",
            "这两个",
            "两家里",
            "两个里",
            "第一家和第二家",
            "第一家第二家",
            "对比",
            "比较一下",
            "比一下",
            "哪家更",
            "哪个更",
            "哪间更",
            "哪个",
            "哪家",
            "哪一个",
            "哪间",
        )
    ):
        return bool(
            comparison_targets
            or merchant_mentions
            or ordinal_references
            or deictic_references
            or _session_value(state, "last_recommendation_list")
            or _session_value(state, "current_shop")
        )
    return False


def _comparison_signal_is_strong(state: GraphState, signals: list[RouterRuleSignal]) -> bool:
    signal = _find_rule_signal(signals, category="comparison", min_confidence=0.8)
    return signal is not None and _has_strong_comparison_context(state)


def _comparison_signal_conflict_note(state: GraphState, signals: list[RouterRuleSignal], route_task: str) -> str:
    semantic_task = _extract_task_type(state) or _extract_goal_type(state)
    comparison_signal = _find_rule_signal(signals, category="comparison", min_confidence=0.0)
    if comparison_signal is None:
        return ""
    if semantic_task in {"recommendation", "shop_search"} and comparison_signal.confidence < 0.8:
        return (
            "router_policy_conflict:"
            f"semantic_intent={semantic_task or 'unknown'};"
            f"rule_signal={comparison_signal.name};"
            "resolution=semantic_intent_wins;"
            "reason=weak_keyword_without_targets"
        )
    if route_task in {"recommendation", "shop_search"} and comparison_signal.confidence < 0.8:
        return (
            "router_policy_conflict:"
            f"semantic_intent={semantic_task or 'unknown'};"
            f"rule_signal={comparison_signal.name};"
            "resolution=semantic_intent_wins;"
            "reason=weak_keyword_without_targets"
        )
    return ""


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
    comparison_targets = [item for item in (semantic_frame.get("comparison_targets") or []) if item]
    ordinal_references = [item for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
    deictic_references = [item for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
    comparison_structure = _as_str(semantic_frame.get("comparison_structure"))
    return bool(
        semantic_frame.get("comparison_intent")
        and (
            len(comparison_targets) >= 2
            or comparison_structure in _STRUCTURED_COMPARISON_STRUCTURES
            or len(ordinal_references) >= 2
            or len(deictic_references) >= 2
        )
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
    raw_text = _extract_text(state)
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

    rule_signals = _collect_router_rule_signals(state)
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
    semantic_confidence = _semantic_route_confidence(state)
    semantic_parse_source = _semantic_parse_source_value(state)
    semantic_grounding_status = _semantic_grounding_status(state)
    semantic_missing_slot_type = _semantic_missing_slot_type(state)
    semantic_category = _semantic_text_field(semantic_frame, "category")
    semantic_comparison_targets = [item for item in (semantic_frame.get("comparison_targets") or []) if item]
    semantic_ordinal_references = [item for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
    semantic_deictic_references = [item for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
    semantic_comparison_structure = _as_str(semantic_frame.get("comparison_structure"))
    semantic_exploration_count = _semantic_exploration_count(state)
    semantic_workflow_hint = _semantic_text_field(semantic_frame, "workflow_hint")
    semantic_task_complexity = _semantic_text_field(semantic_frame, "task_complexity")
    semantic_has_cancel = _semantic_cancel_intent(state)
    semantic_has_new_task_override = _semantic_new_task_override(state)
    state_comparison_targets = [item for item in (state.get("comparison_targets") or []) if item]
    session_last_recommendations = list(_session_value(state, "last_recommendation_list") or [])
    comparison_resolution = resolve_comparison_targets(raw_text_original, state, semantic_frame)
    resolved_targets = list(comparison_resolution.get("targets") or [])
    recommendation_has_anchor = bool(
        task_type == "recommendation"
        and (
            semantic_category
            or semantic_frame.get("filters")
            or semantic_frame.get("soft_preferences")
            or semantic_frame.get("ranking_signals")
            or facets
        )
    )
    recommendation_reference_anchor = bool(
        task_type == "recommendation"
        and (
            _has_reference_signal(state)
            or _has_deterministic_target_hints(state)
        )
    )
    comparison_has_context_anchor = bool(
        len(session_last_recommendations) >= 2
        or len(state_comparison_targets) >= 2
    )
    comparison_has_multi_target_signal = bool(
        len(semantic_comparison_targets) >= 2
        or len(semantic_ordinal_references) >= 2
        or len(semantic_deictic_references) >= 2
        or semantic_comparison_structure in _STRUCTURED_COMPARISON_STRUCTURES
        or any(token in raw_text_original for token in ("这三家", "这几家", "这两家", "第一家和第二家", "第一家第二家"))
    )

    if semantic_has_cancel:
        return "invalid"

    if semantic_task_complexity == "super_complex" or semantic_workflow_hint in {"complex_orchestrator", "complex_orchestrator_workflow"} or task_type in {"complex_orchestrator", "super_complex"}:
        return "super_complex"

    typed_missing_slots = {
        MissingSlotType.missing_location.value,
        MissingSlotType.missing_shop.value,
        MissingSlotType.missing_shop_target.value,
        MissingSlotType.missing_comparison_targets.value,
        MissingSlotType.missing_exploration_location.value,
        MissingSlotType.missing_category.value,
        MissingSlotType.unresolved_reference.value,
    }
    comparison_requested = bool(
        semantic_frame.get("comparison_intent")
        or len(semantic_comparison_targets) >= 2
        or semantic_comparison_structure in _STRUCTURED_COMPARISON_STRUCTURES
        or len(semantic_ordinal_references) >= 2
        or len(semantic_deictic_references) >= 2
        or len(resolved_targets) >= 2
        or (comparison_resolution.get("status") == "RESOLVED" and len(resolved_targets) >= 1 and len(state_comparison_targets) >= 2)
    )
    single_shop_task = task_type == TaskType.single_shop_query.value or goal_type == TaskType.single_shop_query.value
    if single_shop_task:
        comparison_requested = False
    recommendation_has_anchor = bool(
        task_type == "recommendation"
        and (
            semantic_category
            or semantic_frame.get("filters")
            or semantic_frame.get("soft_preferences")
            or semantic_frame.get("ranking_signals")
            or facets
        )
    )
    if single_shop_task and _has_single_shop_anchor(state):
        route_task = _route_task_from_single_shop(state, facets)
        if route_task != "unknown":
            return route_task
    if task_type == TaskType.recommendation.value and _has_reference_signal(state):
        reference_resolution = resolve_references(raw_text_original, state, semantic_frame)
        reference_status = str(reference_resolution.get("status", "") or "").lower()
        if reference_status in {"resolved", "resolved_list"} or _has_deterministic_target_hints(state):
            route_task = _route_task_from_single_shop(state, facets)
            if route_task != "unknown":
                return route_task
            return task_type
    if task_type == TaskType.coupon_query.value:
        # 序数跟进“第一家有券吗”应优先继承上轮推荐列表，直接落到单店券查询。
        if (semantic_ordinal_references or bool(re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", raw_text_original))) and has_session_recommendations:
            return "shop_coupon"
    if (
        semantic_confidence < _SEMANTIC_LOW_CONFIDENCE_FLOOR
        and semantic_parse_source in {SemanticParseSource.fallback_rules.value, SemanticParseSource.diagnostic_rules.value, ""}
        and not semantic_has_new_task_override
        and not comparison_requested
        and not recommendation_has_anchor
        and not recommendation_reference_anchor
    ):
        return "low_confidence"

    if (
        semantic_missing_slot_type in typed_missing_slots
        or (semantic_grounding_status in _GROUNDING_CLARIFICATION_STATUSES and semantic_confidence < 0.85)
    ) and not semantic_has_new_task_override and not recommendation_has_anchor and not recommendation_reference_anchor:
        return "missing_required_slot"

    if _has_pending_clarification(state) and not semantic_has_new_task_override:
        return "reference_failed"

    if comparison_requested:
        single_shop_followup_hint = any(
            token in raw_text_original
            for token in ("有券", "优惠券", "营业", "开门", "距离", "多远", "评价", "价格", "人均")
        )
        if single_shop_followup_hint and len(semantic_ordinal_references) <= 1 and len(semantic_comparison_targets) <= 1:
            comparison_requested = False
        else:
            if len(semantic_comparison_targets) >= 2 or len(state_comparison_targets) >= 2 or len(resolved_targets) >= 2:
                if task_type in {"comparison", "deal_compare"}:
                    return task_type
                if goal_type in {"comparison", "deal_compare"}:
                    return goal_type
                return "comparison"
            if comparison_has_context_anchor and comparison_has_multi_target_signal and comparison_resolution.get("status") in {"NEED_CLARIFICATION", "NOT_FOUND", "TOO_MANY", "PARTIAL"}:
                if task_type in {"comparison", "deal_compare"}:
                    return task_type
                if goal_type in {"comparison", "deal_compare"}:
                    return goal_type
                return "comparison"
            if comparison_resolution.get("unresolved_targets") or comparison_resolution.get("ambiguous_target"):
                return "missing_required_slot"
    elif task_type in {"comparison", "deal_compare"} or goal_type in {"comparison", "deal_compare"}:
        if comparison_resolution.get("status") == "RESOLVED" and len(resolved_targets) >= 2:
            if task_type in {"comparison", "deal_compare"}:
                return task_type
            if goal_type in {"comparison", "deal_compare"}:
                return goal_type
            return "comparison"
        return "missing_required_slot"

    if semantic_exploration_count > 0 or goal_type in _EXPLORATION_TASKS or task_type in _EXPLORATION_TASKS or semantic_workflow_hint in _EXPLORATION_TASKS:
        if semantic_exploration_count > 0:
            if goal_type in _EXPLORATION_TASKS:
                return goal_type
            if task_type in _EXPLORATION_TASKS:
                return task_type
            if semantic_workflow_hint in _EXPLORATION_TASKS:
                return semantic_workflow_hint
            return "local_trip_plan"
        if goal_type in _EXPLORATION_TASKS:
            return goal_type
        if task_type in _EXPLORATION_TASKS:
            return task_type
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
        if (has_verified_explicit_mention or (has_raw_deictic and has_session_current_shop) or (has_raw_ordinal and has_session_recommendations)) and not _has_strong_comparison_context(state):
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

    if task_type in _DETERMINISTIC_TASKS:
        if task_type == "shop_coupon":
            return "shop_coupon"
        if task_type == "shop_review_summary":
            return "shop_review_summary"
        if task_type == "shop_scene_fit":
            return "shop_scene_fit"
        return task_type

    if task_type in {"comparison", "recommendation"}:
        # 纯推荐请求里出现“有券/营业/距离”等修饰词时，不能直接把整句收敛成单店确定性任务。
        # 只有已经存在单店锚点时，才允许这类修饰词把路由收回到单店工具流。
        if task_type == "comparison":
            return "comparison" if comparison_requested else "missing_required_slot"
        if _has_reference_signal(state):
            pass
        if task_type == "recommendation" and _has_deterministic_target_hints(state) and _count_single_shop_signal_groups(state) <= 1 and _has_single_shop_anchor(state):
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
        if _has_reference_signal(state):
            pass
        else:
            return task_type

    if goal_type in _DISCOVERY_TASKS:
        return goal_type

    if task_type == TaskType.coupon_query.value:
        return "shop_coupon"

    reference_requested = (
        task_type == TaskType.single_shop_query.value
        or goal_type == TaskType.single_shop_query.value
        or _has_reference_signal(state)
        or (task_type == TaskType.recommendation.value and _has_reference_signal(state))
    )
    if reference_requested:
        reference_resolution = resolve_references(raw_text_original, state, semantic_frame)
        reference_status = str(reference_resolution.get("status", "") or "").lower()
        if reference_status in {"resolved", "resolved_list"} or _has_verified_single_shop_anchor(state) or _has_deterministic_target_hints(state):
            if len({facet for facet in facets if facet}) > 1:
                return "recommendation"
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
            route_task = _route_task_from_single_shop(state, facets)
            if route_task != "unknown":
                return route_task
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
        if _has_strong_comparison_context(state):
            return "comparison"
        return "recommendation"

    if "行程" in raw_text or "安排" in raw_text or "计划" in raw_text:
        return "unknown"

    if task_type in _CLARIFICATION_TASKS:
        return task_type

    return "unknown"


def _build_missing_fields(state: GraphState, route_task: str) -> list[str]:
    missing_fields: list[str] = []
    semantic_frame = _to_dict(state.get("semantic_frame"))
    if not _extract_text(state):
        missing_fields.append("semantic_frame")
    task_type = _extract_task_type(state)
    goal_type = _extract_goal_type(state)
    semantic_missing_slot_type = _as_str(semantic_frame.get("missing_slot_type"))
    semantic_grounding_status = _as_str(semantic_frame.get("grounding_status"))
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
    if route_task in {"missing_required_slot", "low_confidence"}:
        missing_fields.append("semantic_frame")
    if semantic_missing_slot_type in _CLARIFICATION_SLOT_TYPES:
        missing_fields.append(semantic_missing_slot_type)
    if semantic_grounding_status in _GROUNDING_CLARIFICATION_STATUSES and route_task in {"missing_required_slot", "low_confidence"}:
        missing_fields.append("grounding_status")
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
    rule_signals: list[RouterRuleSignal] | None = None,
) -> str:
    parts: list[str] = []
    top_intent = _extract_top_intent(state)
    task_type = _extract_task_type(state)
    goal_type = _extract_goal_type(state)
    semantic_frame = _semantic_frame(state)
    semantic_parse_source = _semantic_parse_source_value(state)
    grounding_status = _semantic_grounding_status(state)
    if top_intent:
        parts.append(f"top_intent={top_intent}")
    if task_type:
        parts.append(f"task_type={task_type}")
    if goal_type:
        parts.append(f"goal_type={goal_type}")
    if semantic_frame.get("comparison_intent") is not None:
        parts.append(f"comparison_intent={bool(semantic_frame.get('comparison_intent'))}")
    if semantic_frame.get("comparison_structure"):
        parts.append(f"comparison_structure={semantic_frame.get('comparison_structure')}")
    if semantic_parse_source:
        parts.append(f"semantic_parse_source={semantic_parse_source}")
    if grounding_status:
        parts.append(f"grounding_status={grounding_status}")
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
    conflict_note = _comparison_signal_conflict_note(state, rule_signals or [], route_task)
    if conflict_note:
        parts.append(conflict_note)
    if route_task == "forbidden":
        parts.append("unsupported/forbidden scope")
    return "; ".join(parts)


def _build_decision_from_policy(state: GraphState, route_task: str, policy: dict[str, Any]) -> OrchestrationDecision:
    rule_signals = _collect_router_rule_signals(state)
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
        rule_signals=rule_signals,
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
    semantic_frame = _to_dict(state.get("semantic_frame"))
    session_last_recommendations = list(_session_value(state, "last_recommendation_list") or [])
    session_current_shop = _to_dict(_session_value(state, "current_shop"))
    semantic_ordinal_references = [item for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
    semantic_deictic_references = [item for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
    semantic_coupon_facets = [
        item
        for item in (semantic_frame.get("facets") or [])
        if str(_to_dict(item).get("name", "") or _to_dict(item).get("facet", "") or "").strip() == "coupon"
    ]
    coupon_requested = bool(
        "有券" in str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
        or "优惠券" in str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
        or "团购" in str(state.get("raw_text", "") or state.get("normalized_text", "") or "")
        or "coupon" in str(state.get("raw_text", "") or state.get("normalized_text", "") or "").lower()
        or bool(semantic_coupon_facets)
    )
    recommendation_anchor_present = bool(
        semantic_frame.get("category")
        or semantic_frame.get("ranking_signals")
        or semantic_frame.get("soft_preferences")
        or semantic_frame.get("facets")
        or semantic_frame.get("focused_facets")
        or semantic_frame.get("current_shop")
        or semantic_frame.get("comparison_targets")
        or session_last_recommendations
        or session_current_shop
    )
    comparison_anchor_present = _has_strong_comparison_context(state)
    coupon_follow_up_with_history = (
        coupon_requested
        and (semantic_ordinal_references or bool(re.search(r"第\s*([1-9一二三四五六七八九十])\s*(个|家|间|店)?", str(state.get("raw_text", "") or state.get("normalized_text", "") or ""))))
        and bool(session_last_recommendations)
    )
    comparison_deictic_needs_clarify = (
        route_task == "comparison"
        and bool(semantic_deictic_references)
        and not (session_current_shop.get("shop_id") or session_current_shop.get("shop_name"))
    )
    if route_task in {"recommendation", "comparison"} or (route_task == "missing_required_slot" and _extract_task_type(state) in {"recommendation", "comparison"}):
        if route_task == "comparison":
            anchor_present = comparison_anchor_present
        elif route_task == "recommendation":
            anchor_present = recommendation_anchor_present
        else:
            anchor_present = recommendation_anchor_present or comparison_anchor_present
        if anchor_present and not comparison_deictic_needs_clarify:
            if normalized.workflow_name == "clarification_fallback":
                normalized = normalized.model_copy(
                    update={
                        "workflow_name": "discovery_decision",
                        "orchestration_pattern": "discovery_decision",
                        "workflow_entry_name": "recommendation_decision_workflow" if route_task == "recommendation" else "comparison_decision_workflow",
                        "requires_tool": True,
                        "requires_clarification": False,
                        "response_mode": "answer",
                        "next_action": "run_workflow",
                        "task_complexity": "medium",
                        "workflow_reason": f"{normalized.workflow_reason}; anchor_present_for_{route_task}",
                    }
                )
            if normalized.missing_fields:
                normalized = normalized.model_copy(update={"missing_fields": []})
        elif route_task in {"recommendation", "comparison"} and normalized.workflow_name == "discovery_decision":
            normalized = normalized.model_copy(
                update={
                    "workflow_name": "discovery_decision",
                    "orchestration_pattern": "discovery_decision",
                    "workflow_entry_name": "recommendation_decision_workflow" if route_task == "recommendation" else "comparison_decision_workflow",
                    "requires_tool": True,
                    "requires_clarification": False,
                    "response_mode": "recommendation" if route_task == "recommendation" else "comparison",
                    "next_action": "run_workflow",
                }
            )
    if coupon_follow_up_with_history and normalized.workflow_name == "clarification_fallback":
        normalized = normalized.model_copy(
            update={
                "workflow_name": "deterministic_tool",
                "orchestration_pattern": "deterministic_tool",
                "requires_tool": True,
                "requires_clarification": False,
                "response_mode": "tool_answer",
                "next_action": "run_workflow",
                "task_complexity": "low",
                "missing_fields": [],
            }
        )
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
        elif normalized.confidence < _LOW_CONFIDENCE_FLOOR and route_task != "comparison":
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

    if route_task in _CLARIFICATION_TASKS and not (
        route_task == "missing_required_slot"
        and (recommendation_anchor_present or comparison_anchor_present or coupon_follow_up_with_history)
    ):
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


def resolve_workflow_with_policy(
    semantic_frame: dict[str, Any] | Any | None,
    rule_signals: list[RouterRuleSignal] | None,
    session_context: dict[str, Any] | Any | None,
    state: GraphState,
) -> OrchestrationDecision:
    """Central policy guard for workflow selection."""

    working_state: dict[str, Any] = dict(state)
    if semantic_frame is not None:
        working_state["semantic_frame"] = semantic_frame
    if session_context is not None:
        working_state["session_state"] = session_context
        working_state["session_state_before"] = session_context
    route_task = normalize_route_task(working_state)
    policy = _policy_for_route_task(route_task)
    if policy is None:
        return OrchestrationDecision(
            **_fallback_policy(f"policy table missing route_task={route_task or 'unknown'}"),
            confidence=0.35,
            missing_fields=["semantic_frame"] if not _extract_text(working_state) else [],
        )

    decision = _build_decision_from_policy(working_state, route_task, policy)
    if rule_signals:
        conflict_note = _comparison_signal_conflict_note(working_state, rule_signals, route_task)
        if conflict_note and conflict_note not in decision.workflow_reason:
            decision = decision.model_copy(update={"workflow_reason": f"{decision.workflow_reason}; {conflict_note}"})
    return validate_orchestration_decision(decision, working_state)


def build_orchestration_decision(state: GraphState) -> OrchestrationDecision:
    """Build a shadow routing decision without changing execution."""

    rule_signals = _collect_router_rule_signals(state)
    decision = resolve_workflow_with_policy(
        state.get("semantic_frame"),
        rule_signals,
        state.get("session_state_before") or state.get("session_state"),
        state,
    )
    route_task = normalize_route_task(state)
    semantic_frame = _to_dict(state.get("semantic_frame"))
    session_last_recommendations = list(_session_value(state, "last_recommendation_list") or [])
    session_current_shop = _to_dict(_session_value(state, "current_shop"))
    recommendation_anchor_present = bool(
        semantic_frame.get("category")
        or semantic_frame.get("ranking_signals")
        or semantic_frame.get("soft_preferences")
        or semantic_frame.get("facets")
        or semantic_frame.get("focused_facets")
        or semantic_frame.get("current_shop")
        or semantic_frame.get("comparison_targets")
        or session_last_recommendations
        or session_current_shop
    )
    comparison_anchor_present = _has_strong_comparison_context(state)

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
        if _extract_task_type(state) not in {"recommendation", "comparison"} or not (recommendation_anchor_present or comparison_anchor_present):
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
    if route_task in {"recommendation", "comparison"} or (route_task == "missing_required_slot" and _extract_task_type(state) in {"recommendation", "comparison"}):
        if route_task == "comparison":
            anchor_present = comparison_anchor_present
        elif route_task == "recommendation":
            anchor_present = recommendation_anchor_present
        else:
            anchor_present = recommendation_anchor_present or comparison_anchor_present
        if anchor_present and decision.workflow_name == "clarification_fallback":
            decision = decision.model_copy(
                update={
                    "workflow_name": "discovery_decision",
                    "orchestration_pattern": "discovery_decision",
                    "requires_tool": True,
                    "requires_clarification": False,
                    "response_mode": "answer",
                    "next_action": "run_workflow",
                    "task_complexity": "medium",
                    "missing_fields": [],
                    "workflow_reason": f"{decision.workflow_reason}; anchor_present_for_{route_task}",
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
        "workflow_entry_name": getattr(decision, "workflow_entry_name", ""),
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
        rule_signals = _collect_router_rule_signals(state)
        raw_decision = build_orchestration_decision(state)
        decision = validate_orchestration_decision(raw_decision, state)
        error_code = ""
        error_message = ""
        semantic_frame = _to_dict(state.get("semantic_frame"))
        raw_text_original = _extract_text(state)
        session_last_recommendations = list(_session_value(state, "last_recommendation_list") or [])
        state_comparison_targets = [item for item in (state.get("comparison_targets") or []) if item]
        semantic_comparison_targets = [item for item in (semantic_frame.get("comparison_targets") or []) if item]
        semantic_ordinal_references = [item for item in (semantic_frame.get("ordinal_references") or []) if str(item).strip()]
        semantic_deictic_references = [item for item in (semantic_frame.get("deictic_references") or []) if str(item).strip()]
        semantic_comparison_structure = _as_str(semantic_frame.get("comparison_structure"))
        comparison_resolution = resolve_comparison_targets(raw_text_original, state, semantic_frame)
        resolved_targets = list(comparison_resolution.get("targets") or [])
        comparison_requested = bool(
            semantic_frame.get("comparison_intent")
            or len(semantic_comparison_targets) >= 2
            or semantic_comparison_structure in _STRUCTURED_COMPARISON_STRUCTURES
            or len(semantic_ordinal_references) >= 2
            or len(semantic_deictic_references) >= 2
            or len(resolved_targets) >= 2
            or (comparison_resolution.get("status") == "RESOLVED" and len(resolved_targets) >= 1 and len(state_comparison_targets) >= 2)
        )
        comparison_context_anchor = bool(len(session_last_recommendations) >= 2 or len(state_comparison_targets) >= 2)
        comparison_multi_target_signal = bool(
            len(semantic_comparison_targets) >= 2
            or len(semantic_ordinal_references) >= 2
            or len(semantic_deictic_references) >= 2
            or semantic_comparison_structure in _STRUCTURED_COMPARISON_STRUCTURES
            or any(token in raw_text_original for token in ("这三家", "这几家", "这两家", "第一家和第二家", "第一家第二家"))
        )
        comparison_resolution_status = str(comparison_resolution.get("status", "") or "").upper()
        if comparison_requested:
            if len(semantic_comparison_targets) >= 2 or len(state_comparison_targets) >= 2 or len(resolved_targets) >= 2:
                comparison_route_reason = (
                    f"comparison_requested; comparison_targets={len(semantic_comparison_targets)};"
                    f"state_targets={len(state_comparison_targets)}; resolved_targets={len(resolved_targets)}"
                )
            elif comparison_context_anchor and comparison_multi_target_signal and comparison_resolution_status in {"NEED_CLARIFICATION", "NOT_FOUND", "TOO_MANY", "PARTIAL"}:
                comparison_route_reason = (
                    f"comparison_recovered_from_context; context_anchor={comparison_context_anchor};"
                    f"multi_target_signal={comparison_multi_target_signal}; resolution_status={comparison_resolution_status}"
                )
            elif comparison_resolution.get("unresolved_targets") or comparison_resolution.get("ambiguous_target"):
                comparison_route_reason = (
                    f"comparison_needs_clarification; resolution_status={comparison_resolution_status};"
                    f"unresolved_targets={len(comparison_resolution.get('unresolved_targets') or [])}"
                )
            else:
                comparison_route_reason = (
                    f"comparison_requested_but_insufficient; resolution_status={comparison_resolution_status};"
                    f"context_anchor={comparison_context_anchor}; multi_target_signal={comparison_multi_target_signal}"
                )
        else:
            comparison_route_reason = (
                f"comparison_not_selected; resolution_status={comparison_resolution_status};"
                f"context_anchor={comparison_context_anchor}; multi_target_signal={comparison_multi_target_signal}"
            )
        if raw_decision.model_dump() != decision.model_dump():
            error_code = "ORCHESTRATION_VALIDATION_FALLBACK"
            error_message = decision.workflow_reason or "orchestration decision normalized by validator"
        facet_set = normalize_query_facets(state.get("semantic_frame"), state.get("session_state_before") or state.get("session_state"), _extract_text(state))
        router_policy_conflicts = [
            note
            for note in (
                _comparison_signal_conflict_note(state, rule_signals, normalize_route_task(state)),
            )
            if note
        ]
        router_policy_decision = {
            "route_task": normalize_route_task(state),
            "workflow_name": decision.workflow_name,
            "orchestration_pattern": decision.orchestration_pattern,
            "response_mode": decision.response_mode,
            "confidence": decision.confidence,
            "semantic_parse_source": _semantic_parse_source_value(state),
            "grounding_status": _semantic_grounding_status(state),
            "comparison_requested": comparison_requested,
            "comparison_context_anchor": comparison_context_anchor,
            "comparison_multi_target_signal": comparison_multi_target_signal,
            "comparison_resolution_status": comparison_resolution_status,
            "comparison_route_reason": comparison_route_reason,
        }
        patch = _decision_patch(decision, error_code=error_code, error_message=error_message)
        patch.update(
            {
                "facet_set": facet_set,
                "facets": facet_set.facets,
                "target_resolution": facet_set.target_resolution or build_target_resolution_result(state.get("semantic_frame"), session_state=state.get("session_state_before") or state.get("session_state"), raw_text=_extract_text(state)),
                "conflicting_facets": facet_set.conflicting_facets,
                "ranking_policy": facet_set.ranking_policy,
                "router_policy_decision": router_policy_decision,
                "router_policy_conflicts": router_policy_conflicts,
                "rule_pattern_signals": [signal.__dict__ for signal in rule_signals],
                "workflow_candidate_reason": decision.workflow_reason,
                "comparison_requested": comparison_requested,
                "comparison_context_anchor": comparison_context_anchor,
                "comparison_multi_target_signal": comparison_multi_target_signal,
                "comparison_resolution_status": comparison_resolution_status,
                "comparison_route_reason": comparison_route_reason,
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
        patch.update({"facet_set": None, "facets": [], "target_resolution": None, "conflicting_facets": [], "ranking_policy": None, "router_policy_decision": {}, "router_policy_conflicts": [f"router exception: {exc}"], "rule_pattern_signals": [], "workflow_candidate_reason": fallback.workflow_reason})
        return patch


def build_orchestration_shadow_patch(state: GraphState) -> dict[str, Any]:
    """Backward-compatible alias for the Phase 4 shadow routing patch."""

    return route_orchestration(state)
