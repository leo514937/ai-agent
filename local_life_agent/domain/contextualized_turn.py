"""Trace-only contextualized turn DTO.

P5 先把上下文改写的痕迹显式化，但不接管语义解析和路由决策。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContextualFollowUp(BaseModel):
    """Lightweight follow-up protocol for trace and routing hints."""

    model_config = ConfigDict(extra="forbid")

    kind: str = ""
    source_context: str = ""
    ordinal_index: int | None = None
    facet: str = ""
    constraint_delta: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0

    @classmethod
    def from_trace(
        cls,
        *,
        kind: str = "",
        source_context: str = "",
        ordinal_index: int | None = None,
        facet: str = "",
        constraint_delta: dict[str, Any] | None = None,
        confidence: float = 0.0,
    ) -> ContextualFollowUp:
        return cls(
            kind=str(kind or ""),
            source_context=str(source_context or ""),
            ordinal_index=ordinal_index if ordinal_index is None else int(ordinal_index),
            facet=str(facet or ""),
            constraint_delta=dict(constraint_delta or {}),
            confidence=max(float(confidence or 0.0), 0.0),
        )

    def trace_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ContextualizedTurn(BaseModel):
    """Trace-only record of how a turn was contextualized."""

    model_config = ConfigDict(extra="forbid")

    original_text: str = ""
    normalized_text: str = ""
    contextualized_query: str = ""
    rewrite_type: str = ""
    mixed_intent: bool = False
    terminal_policy: str = "inherit"
    context_used: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_trace(
        cls,
        *,
        original_text: str = "",
        normalized_text: str = "",
        contextualized_query: str = "",
        rewrite_type: str = "",
        mixed_intent: bool = False,
        terminal_policy: str = "inherit",
        context_used: list[str] | None = None,
        confidence: float = 0.0,
    ) -> ContextualizedTurn:
        return cls(
            original_text=str(original_text or ""),
            normalized_text=str(normalized_text or ""),
            contextualized_query=str(contextualized_query or ""),
            rewrite_type=str(rewrite_type or ""),
            mixed_intent=bool(mixed_intent),
            terminal_policy=str(terminal_policy or "inherit"),
            context_used=[str(item).strip() for item in (context_used or []) if str(item).strip()],
            confidence=max(float(confidence or 0.0), 0.0),
        )

    def trace_dict(self) -> dict[str, Any]:
        return self.model_dump()


_ORDINAL_RE = re.compile(r"第\s*([1-9一二两三四五六七八九十])\s*(个|家|间|店)?")
_CHINESE_ORDINAL_MAP: dict[str, int] = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


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


def _session_value(state: Any, field: str) -> Any:
    if state is None:
        return None
    if isinstance(state, dict):
        value = state.get(field)
        if value is not None:
            return value
        for nested_key in ("session_state_before", "session_state"):
            nested_state = state.get(nested_key)
            if nested_state is None:
                continue
            nested_value = _session_value(nested_state, field)
            if nested_value is not None:
                return nested_value
        return None
    value = getattr(state, field, None)
    if value is not None:
        return value
    for nested_attr in ("session_state_before", "session_state"):
        nested_state = getattr(state, nested_attr, None)
        if nested_state is None:
            continue
        nested_value = _session_value(nested_state, field)
        if nested_value is not None:
            return nested_value
    return None


def _ordinal_index_from_text(text: str) -> int | None:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return None
    match = _ORDINAL_RE.search(compact)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return _CHINESE_ORDINAL_MAP.get(token)


def build_contextual_follow_up(
    *,
    semantic_frame: dict[str, Any] | Any | None = None,
    session_state: dict[str, Any] | Any | None = None,
    raw_text: str = "",
) -> ContextualFollowUp | None:
    """Derive a lightweight follow-up protocol from text and session context.

    This is intentionally trace-oriented. It does not own routing by itself,
    but it gives the router / target resolver a stable, shared signal.
    """

    frame = _to_dict(semantic_frame)
    text = str(raw_text or frame.get("primary_task", "") or frame.get("goal_summary", "") or "").strip()
    lowered = text.lower()
    follow_up = _to_dict(frame.get("follow_up"))
    session_last_recommendations = list(_session_value(session_state, "last_recommendation_list") or [])
    session_current_shop = _to_dict(_session_value(session_state, "current_shop"))
    session_comparison_targets = list(_session_value(session_state, "comparison_targets") or [])
    session_comparison_result = _to_dict(_session_value(session_state, "comparison_result"))

    cheaper_cues = ("便宜一点", "便宜点", "更便宜", "更便宜点", "便宜些", "比较便宜", "便宜一点的呢")
    has_cheaper_follow_up = bool(
        follow_up.get("is_follow_up") is True
        and str(follow_up.get("refine_action", "") or "").strip() == "cheaper"
    ) or any(token in text for token in cheaper_cues)
    if has_cheaper_follow_up and session_last_recommendations:
        return ContextualFollowUp.from_trace(
            kind="recommendation_refine",
            source_context="last_recommendation_list",
            facet="price",
            constraint_delta={"price_preference": "lower_price"},
            confidence=max(float(frame.get("confidence", 0.0) or 0.0), 0.85),
        )

    ordinal_index = _ordinal_index_from_text(text)
    has_coupon_facet = any(token in text or token in lowered for token in ("有券", "优惠券", "coupon", "团购", "套餐"))
    has_comparison_context = bool(session_comparison_targets or session_comparison_result.get("rows") or frame.get("comparison_targets"))
    if ordinal_index and has_coupon_facet and has_comparison_context:
        source_context = "comparison_result" if session_comparison_result.get("rows") else "comparison_targets"
        return ContextualFollowUp.from_trace(
            kind="comparison_followup",
            source_context=source_context,
            ordinal_index=ordinal_index,
            facet="coupon",
            constraint_delta={"facet": "coupon"},
            confidence=max(float(frame.get("confidence", 0.0) or 0.0), 0.9),
        )

    if ordinal_index and session_last_recommendations:
        return ContextualFollowUp.from_trace(
            kind="ordinal_fact",
            source_context="last_recommendation_list",
            ordinal_index=ordinal_index,
            confidence=max(float(frame.get("confidence", 0.0) or 0.0), 0.9),
        )

    if ordinal_index and session_current_shop:
        return ContextualFollowUp.from_trace(
            kind="ordinal_fact",
            source_context="current_shop",
            ordinal_index=ordinal_index,
            confidence=max(float(frame.get("confidence", 0.0) or 0.0), 0.8),
        )

    return None
