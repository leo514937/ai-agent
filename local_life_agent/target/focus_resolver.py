"""Deterministic focus resolver for first-layer context and rewrite trace.

This module only resolves discourse focus from session memory and local
reference signals. It does not perform entity search or canonical shop
resolution.
"""

from __future__ import annotations

import re
from typing import Any

from ..domain.contextualized_turn import ContextualizedTurn
from ..domain.focus_context import FocusContext
from ..domain.state import SessionState

_SINGLE_DEICTIC_HINTS = ("这家", "那家", "它", "这间", "那间", "这店", "刚才那个", "刚才这家", "刚刚那个", "刚刚这家")
_LIST_DEICTIC_HINTS = ("这三家", "这几家", "这几间", "这些", "上面这些", "刚才这几家", "这几个", "这三个")
_ORDINAL_RE = re.compile(r"第\s*([1-9一二两三四五六七八九十])\s*(个|家|间|店)?")
_STRONG_FACET_HINTS = ("有券", "优惠", "折扣", "营业", "开门", "距离", "多远", "远吗", "近吗", "评分", "口碑", "人均", "价格", "多少钱")
_COMPARISON_HINTS = ("对比", "比较", "哪个好", "哪个更", "谁更", "比下", "比一比", "比呢", "比一下", "和", "与")


def _session_get(session_state: dict | SessionState | None, field: str) -> Any:
    if session_state is None:
        return None
    if isinstance(session_state, SessionState):
        return getattr(session_state, field, None)
    if isinstance(session_state, dict):
        if field in session_state:
            return session_state.get(field)
        for nested_key in ("session_state_before", "session_state"):
            nested_state = session_state.get(nested_key)
            if nested_state is None:
                continue
            nested_value = _session_get(nested_state, field)
            if nested_value is not None:
                return nested_value
        return None
    return getattr(session_state, field, None)


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


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _recommendation_candidates(session_state: dict | SessionState | None) -> list[dict[str, Any]]:
    raw = _session_get(session_state, "last_recommendation_list") or []
    candidates: list[dict[str, Any]] = []
    for item in raw:
        shop = _to_dict(item)
        if shop.get("shop_id") or shop.get("shop_name"):
            candidates.append(shop)
    return candidates


def _current_shop(session_state: dict | SessionState | None) -> dict[str, Any]:
    return _to_dict(_session_get(session_state, "current_shop"))


def _comparison_targets(session_state: dict | SessionState | None, semantic_frame: dict[str, Any]) -> list[dict[str, Any]]:
    frame_targets = [_to_dict(item) for item in (semantic_frame.get("comparison_targets") or []) if item]
    if frame_targets:
        return frame_targets
    session_targets = _session_get(session_state, "comparison_targets") or []
    return [_to_dict(item) for item in session_targets if item]


def _parse_ordinal(text: str) -> int | None:
    compact = _normalized_text(text)
    match = _ORDINAL_RE.search(compact)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(token)


def _has_reference_signal(text: str) -> bool:
    compact = _normalized_text(text)
    if any(token in compact for token in _SINGLE_DEICTIC_HINTS):
        return True
    if any(token in compact for token in _LIST_DEICTIC_HINTS):
        return True
    return _ORDINAL_RE.search(compact) is not None


def _resolve_focus_candidate(
    text: str,
    *,
    session_state: dict | SessionState | None,
    semantic_frame: dict[str, Any],
    active_turn_result: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], int | None, list[dict[str, Any]], str, str, float]:
    compact = _normalized_text(text)
    active_turn = active_turn_result or {}
    selected_candidate = _to_dict(active_turn.get("selected_candidate"))
    selected_index = active_turn.get("selected_index")
    if selected_candidate:
        return (
            "recommendation_item",
            selected_candidate,
            int(selected_index) if selected_index is not None else None,
            [],
            str(active_turn.get("source", "") or "active_turn_resolver"),
            "resolved",
            float(active_turn.get("confidence", 0.0) or 0.0),
        )

    comparison_targets = _comparison_targets(session_state, semantic_frame)
    if comparison_targets and (
        semantic_frame.get("comparison_intent")
        or semantic_frame.get("comparison_structure")
        or any(token in compact for token in ("对比", "比较", "哪个好", "哪个更", "谁更"))
    ):
        first_target = comparison_targets[0] if comparison_targets else {}
        return (
            "comparison_targets",
            first_target,
            None,
            comparison_targets,
            "focus_resolver.comparison_targets",
            "resolved",
            0.75 if len(comparison_targets) >= 2 else 0.55,
        )

    current_shop = _current_shop(session_state)
    if current_shop and any(token in compact for token in _SINGLE_DEICTIC_HINTS):
        return (
            "current_shop",
            current_shop,
            None,
            [],
            "focus_resolver.current_shop",
            "resolved",
            0.7,
        )

    ordinal_index = _parse_ordinal(compact)
    recommendations = _recommendation_candidates(session_state)
    if ordinal_index is not None and recommendations:
        if 1 <= ordinal_index <= len(recommendations):
            item = recommendations[ordinal_index - 1]
            return (
                "recommendation_item",
                item,
                ordinal_index,
                [],
                "focus_resolver.last_recommendation_list",
                "resolved",
                0.8,
            )
        return (
            "none",
            {},
            ordinal_index,
            [],
            "focus_resolver.last_recommendation_list",
            "clarify",
            0.4,
        )

    if any(token in compact for token in _LIST_DEICTIC_HINTS) and recommendations:
        count = 3 if "三" in compact else 2 if "两" in compact or "二" in compact else len(recommendations)
        selected = recommendations[: max(1, min(len(recommendations), count))]
        return (
            "recommendation_list",
            selected[0] if selected else {},
            1 if selected else None,
            selected,
            "focus_resolver.last_recommendation_list",
            "resolved",
            0.72,
        )

    if _has_reference_signal(compact):
        return (
            "none",
            {},
            None,
            [],
            "focus_resolver.reference_signal",
            "clarify",
            0.25,
        )

    return ("none", {}, None, [], "focus_resolver.none", "none", 0.0)


def resolve_focus_context(
    text: str,
    *,
    session_state: dict | SessionState | None = None,
    semantic_frame: dict | Any | None = None,
    active_turn_result: dict[str, Any] | None = None,
) -> FocusContext:
    frame = _to_dict(semantic_frame)
    focus_type, focus_object, focus_index, comparison_targets, focus_source, resolution_status, confidence = _resolve_focus_candidate(
        text,
        session_state=session_state,
        semantic_frame=frame,
        active_turn_result=active_turn_result,
    )
    clarification_needed = resolution_status == "clarify"
    recommendation_item = focus_object if focus_type == "recommendation_item" else {}
    return FocusContext.from_trace(
        focus_type=focus_type,
        focus_object=focus_object,
        focus_index=focus_index,
        recommendation_item=recommendation_item,
        comparison_targets=comparison_targets,
        focus_source=focus_source,
        resolution_status=resolution_status,
        clarification_needed=clarification_needed,
        confidence=confidence,
    )


def build_contextualized_turn(
    text: str,
    *,
    session_state: dict | SessionState | None = None,
    semantic_frame: dict | Any | None = None,
    active_turn_result: dict[str, Any] | None = None,
    top_intent: Any = None,
) -> ContextualizedTurn:
    raw_text = str(text or "")
    normalized_text = raw_text
    focus_context = resolve_focus_context(
        raw_text,
        session_state=session_state,
        semantic_frame=semantic_frame,
        active_turn_result=active_turn_result,
    )
    focus_object = focus_context.focus_object or {}
    contextualized_query = normalized_text
    rewrite_type = "none"
    context_used: list[str] = []
    confidence = 0.0
    mixed_intent = False

    top_intent_value = str(getattr(top_intent, "value", top_intent or "") or "").strip()
    if top_intent_value and top_intent_value != "local_life" and focus_context.focus_type != "none":
        mixed_intent = True

    comparison_like = _has_comparison_signal(normalized_text)

    if not comparison_like and focus_context.focus_type == "current_shop" and focus_object.get("shop_name"):
        contextualized_query = _replace_reference_token(normalized_text, focus_object.get("shop_name", ""))
        rewrite_type = "current_shop_reference"
        context_used.append("focus.current_shop")
        confidence = max(confidence, focus_context.confidence)
    elif not comparison_like and focus_context.focus_type == "recommendation_item" and focus_object.get("shop_name"):
        if not _has_strong_facet_signal(normalized_text):
            contextualized_query = _replace_reference_token(normalized_text, focus_object.get("shop_name", ""))
        rewrite_type = "recommendation_item_reference"
        context_used.append("focus.recommendation_item")
        confidence = max(confidence, focus_context.confidence)
    elif not comparison_like and focus_context.focus_type == "comparison_targets" and focus_context.comparison_targets:
        first = focus_context.comparison_targets[0]
        shop_name = str(first.get("shop_name", "") or first.get("name", "") or "")
        if shop_name:
            contextualized_query = _replace_reference_token(normalized_text, shop_name)
            rewrite_type = "comparison_reference"
            context_used.append("focus.comparison_targets")
            confidence = max(confidence, focus_context.confidence)

    if focus_context.clarification_needed:
        context_used.append("focus.clarification_needed")

    terminal_policy = "local_life" if focus_context.focus_type != "none" else "inherit"
    return ContextualizedTurn.from_trace(
        original_text=raw_text,
        normalized_text=normalized_text,
        contextualized_query=contextualized_query,
        rewrite_type=rewrite_type,
        mixed_intent=mixed_intent,
        terminal_policy=terminal_policy,
        context_used=context_used or (["focus.none"] if focus_context.focus_type == "none" else []),
        confidence=confidence,
    )


def _replace_reference_token(text: str, replacement: str) -> str:
    compact = str(text or "")
    if not replacement:
        return compact
    for token in _SINGLE_DEICTIC_HINTS + _LIST_DEICTIC_HINTS:
        if token in compact:
            return compact.replace(token, str(replacement))
    ordinal = _ORDINAL_RE.search(compact)
    if ordinal:
        return _ORDINAL_RE.sub(str(replacement), compact, count=1)
    return compact


def _has_strong_facet_signal(text: str) -> bool:
    compact = str(text or "")
    return any(token in compact for token in _STRONG_FACET_HINTS)


def _has_comparison_signal(text: str) -> bool:
    compact = str(text or "")
    return any(token in compact for token in _COMPARISON_HINTS)
