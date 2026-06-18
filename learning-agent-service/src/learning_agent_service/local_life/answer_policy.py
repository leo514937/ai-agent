from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from learning_agent_service.domain.utils import clean_text as _clean_text


AnswerBranch = Literal["strict_template", "strict_natural", "grounded", "ask_clarification", "no_answer"]


@dataclass(frozen=True)
class AnswerPolicy:
    branch: AnswerBranch
    risk_level: Literal["high", "medium", "low"]
    requires_realtime: bool
    allowed_fact_sources: tuple[str, ...]
    can_use_history_summary: bool
    response_mode: str
    answer_style: str


_STRICT_TEMPLATE_STYLES = {"coupon_only", "open_status_only", "distance_only", "single_shop_review"}
_STRICT_NATURAL_STYLES = {"comparison", "multi_shop_recommendation", "facet_multi"}


def derive_answer_policy(
    *,
    response_mode: str | None,
    answer_style: str | None,
    realtime_required: bool = False,
    answer_context: Any | None = None,
) -> AnswerPolicy:
    normalized_mode = (_clean_text(response_mode) or "").lower()
    normalized_style = (_clean_text(answer_style) or "").lower()
    context = answer_context if isinstance(answer_context, dict) else {}
    context_branch = (_clean_text(context.get("answer_branch")) or "").lower()

    if normalized_mode == "ask_clarification":
        return AnswerPolicy(
            branch="ask_clarification",
            risk_level="low",
            requires_realtime=False,
            allowed_fact_sources=("confirmed_slots",),
            can_use_history_summary=False,
            response_mode=normalized_mode,
            answer_style=normalized_style,
        )
    if normalized_mode == "no_answer":
        return AnswerPolicy(
            branch="no_answer",
            risk_level="low",
            requires_realtime=False,
            allowed_fact_sources=("confirmed_slots",),
            can_use_history_summary=False,
            response_mode=normalized_mode,
            answer_style=normalized_style,
        )

    if normalized_mode == "grounded_strict":
        if context_branch in {"strict_template", "strict_natural", "grounded"}:
            branch = context_branch  # type: ignore[assignment]
        elif normalized_style in _STRICT_TEMPLATE_STYLES:
            branch = "strict_template"
        elif normalized_style in _STRICT_NATURAL_STYLES:
            branch = "strict_natural"
        else:
            branch = "grounded"
    elif normalized_mode in {"grounded", "partial_grounded"}:
        branch = "grounded"
    else:
        branch = "grounded"

    if branch == "strict_template":
        risk_level: Literal["high", "medium", "low"] = "high"
        allowed_fact_sources = ("evidence_pack", "tool_result", "confirmed_slots")
        can_use_history_summary = False
    elif branch == "strict_natural":
        risk_level = "medium"
        allowed_fact_sources = ("evidence_pack", "tool_result", "confirmed_slots")
        can_use_history_summary = False
    else:
        risk_level = "low"
        allowed_fact_sources = ("evidence_pack", "tool_result", "confirmed_slots", "history_summary")
        can_use_history_summary = True

    return AnswerPolicy(
        branch=branch,  # type: ignore[arg-type]
        risk_level=risk_level,
        requires_realtime=bool(realtime_required),
        allowed_fact_sources=allowed_fact_sources,
        can_use_history_summary=can_use_history_summary,
        response_mode=normalized_mode,
        answer_style=normalized_style,
    )
