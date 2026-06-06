from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from learning_agent_service.domain.utils import clean_text as _clean_text


@dataclass(frozen=True)
class AnswerDepthPolicy:
    answer_style: str
    depth_level: str
    min_sections: int
    max_sections: int
    min_bullets_per_section: int
    min_chars: int
    require_summary: bool
    require_evidence_reasoning: bool
    require_risk_or_caveat: bool
    require_next_step: bool
    depth_limited_by_evidence: bool
    clean_evidence_count: int
    strong_evidence_count: int
    medium_evidence_count: int
    reason: str


def _style_from_contract(answer_contract: Any | None) -> str:
    if answer_contract is None:
        return "single_shop_review"
    if isinstance(answer_contract, dict):
        return _clean_text(answer_contract.get("answer_style")) or "single_shop_review"
    return _clean_text(getattr(answer_contract, "answer_style", "")) or "single_shop_review"


def _threshold_for_style(answer_style: str) -> int:
    if answer_style in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
        return 0
    if answer_style in {"single_shop_review", "scene_fit", "facet_multi"}:
        return 2
    if answer_style == "multi_shop_recommendation":
        return 3
    return 2


def derive_answer_depth_policy(
    answer_contract: Any | None,
    *,
    clean_evidence_count: int,
    strong_evidence_count: int = 0,
    medium_evidence_count: int = 0,
) -> AnswerDepthPolicy:
    answer_style = _style_from_contract(answer_contract)
    clean_count = max(0, int(clean_evidence_count or 0))
    strong_count = max(0, int(strong_evidence_count or 0))
    medium_count = max(0, int(medium_evidence_count or 0))

    if answer_style in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
        depth_level = "short"
        min_sections = 1
        max_sections = 2
        min_bullets = 1
        min_chars = 28
        require_summary = True
        require_evidence_reasoning = False
        require_risk_or_caveat = False
        require_next_step = False
    elif answer_style == "multi_shop_recommendation":
        if clean_count >= 4 or strong_count >= 3:
            depth_level = "detailed"
            min_chars = 220
        else:
            depth_level = "normal"
            min_chars = 160
        min_sections = 3
        max_sections = 6
        min_bullets = 2
        require_summary = True
        require_evidence_reasoning = True
        require_risk_or_caveat = True
        require_next_step = True
    else:
        if clean_count >= 4:
            depth_level = "detailed"
            min_chars = 160
        else:
            depth_level = "normal"
            min_chars = 120
        min_sections = 4 if depth_level != "short" else 2
        max_sections = 6 if depth_level == "detailed" else 5
        min_bullets = 1
        require_summary = True
        require_evidence_reasoning = True
        require_risk_or_caveat = True
        require_next_step = True

    threshold = _threshold_for_style(answer_style)
    depth_limited_by_evidence = clean_count < threshold
    if depth_limited_by_evidence and answer_style not in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
        reason = f"clean_evidence_count_{clean_count}_below_threshold_{threshold}"
    elif answer_style in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
        reason = f"answer_style_{answer_style}_requires_short_answer"
    else:
        reason = f"answer_style_{answer_style}_allows_{depth_level}"

    return AnswerDepthPolicy(
        answer_style=answer_style,
        depth_level=depth_level,
        min_sections=min_sections,
        max_sections=max_sections,
        min_bullets_per_section=min_bullets,
        min_chars=min_chars,
        require_summary=require_summary,
        require_evidence_reasoning=require_evidence_reasoning,
        require_risk_or_caveat=require_risk_or_caveat,
        require_next_step=require_next_step,
        depth_limited_by_evidence=depth_limited_by_evidence,
        clean_evidence_count=clean_count,
        strong_evidence_count=strong_count,
        medium_evidence_count=medium_count,
        reason=reason,
    )


def build_answer_structure_requirements(answer_contract: Any | None, policy: AnswerDepthPolicy | None = None) -> dict[str, Any]:
    policy = policy or derive_answer_depth_policy(answer_contract, clean_evidence_count=0)
    style = policy.answer_style
    if style == "single_shop_review":
        sections = ["总体结论", "核心优点", "可能不足", "适合场景", "到店建议"]
        per_shop_min_reasons = 2
    elif style == "multi_shop_recommendation":
        sections = ["推荐店铺", "推荐理由", "适合场景", "注意事项"]
        per_shop_min_reasons = 2
    elif style == "facet_multi":
        sections = ["优惠券", "营业状态", "环境评价", "综合建议"]
        per_shop_min_reasons = 1
    elif style == "coupon_only":
        sections = ["结论"]
        per_shop_min_reasons = 0
    elif style == "open_status_only":
        sections = ["结论"]
        per_shop_min_reasons = 0
    elif style == "distance_only":
        sections = ["结论"]
        per_shop_min_reasons = 0
    elif style == "clarification":
        sections = ["澄清问题"]
        per_shop_min_reasons = 0
    else:
        sections = ["总体结论", "核心理由", "可能不足", "建议"]
        per_shop_min_reasons = 1
    return {
        "answer_style": style,
        "depth_level": policy.depth_level,
        "sections": sections,
        "min_sections": policy.min_sections,
        "max_sections": policy.max_sections,
        "min_bullets_per_section": policy.min_bullets_per_section,
        "min_chars": policy.min_chars,
        "per_shop_min_reasons": per_shop_min_reasons,
        "require_summary": policy.require_summary,
        "require_evidence_reasoning": policy.require_evidence_reasoning,
        "require_risk_or_caveat": policy.require_risk_or_caveat,
        "require_next_step": policy.require_next_step,
    }
