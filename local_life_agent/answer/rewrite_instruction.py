from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.schemas import DecisionPlan


_BOUNDARY_FAILURE_CODES = {
    "empty_evidence_or_draft",
    "template_fallback",
    "llm_disabled",
    "llm_client_unavailable",
    "llm_call_failed",
    "llm_verbalizer_error",
    "prompt_load_failed",
}

_UNCERTAINTY_FAILURE_CODES = {
    "unknown_as_false",
    "grounded_fact_downgraded_to_unknown",
    "partial_as_complete",
    "open_status_needs_uncertain_notice",
    "coupon_status_missing_positive_claim",
    "coupon_status_missing_empty_notice",
    "distance_missing_numeric_claim",
    "distance_needs_uncertain_notice",
    "exploration_stage_needs_uncertain_notice",
    "exploration_stage_partial_as_complete",
}

_RANKING_FAILURE_CODES = {
    "ranking_changed_by_llm",
    "unsupported_comparison_winner",
    "missing_comparison_targets",
    "missing_recommendation_targets",
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


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _claim_texts_from_plan(plan: DecisionPlan | None) -> list[str]:
    if plan is None:
        return []
    plan_dict = _to_dict(plan)
    texts: list[str] = []
    for item in list(plan_dict.get("allowed_claims") or []) + list(plan_dict.get("required_claims") or []):
        item_dict = _to_dict(item)
        for key in ("verbalization_hint", "value", "claim_id", "facet"):
            text = str(item_dict.get(key, "") or "").strip()
            if text:
                texts.append(text)
                break
    for point in list(plan_dict.get("factual_points") or []):
        text = str(point or "").strip()
        if text:
            texts.append(text)
    for target in list(plan_dict.get("selected_targets") or []) + list(plan_dict.get("omitted_targets") or []):
        item_dict = _to_dict(target)
        name = str(item_dict.get("shop_name") or item_dict.get("alias") or item_dict.get("shop_id") or "").strip()
        if name:
            texts.append(name)
    return _dedupe(texts)


class RewriteInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    violation_codes: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    contradicted_claims: list[str] = Field(default_factory=list)
    required_additions: list[str] = Field(default_factory=list)
    claims_to_keep: list[str] = Field(default_factory=list)
    fallback_mode: str = ""
    tone: str = "neutral"
    max_length: int = 0

    @classmethod
    def from_violation_codes(
        cls,
        violation_codes: list[str] | None = None,
        *,
        fallback_mode: str = "",
        tone: str = "neutral",
        max_length: int = 0,
    ) -> "RewriteInstruction":
        codes = _dedupe([str(item).strip() for item in (violation_codes or []) if str(item).strip()])
        required_additions: list[str] = []
        claims_to_keep: list[str] = []
        unsupported_claims: list[str] = []
        contradicted_claims: list[str] = []
        for code in codes:
            if code in _BOUNDARY_FAILURE_CODES:
                required_additions.append("请基于已知证据回答，不要编造")
            if code in _UNCERTAINTY_FAILURE_CODES:
                required_additions.append("把不确定内容改成暂时无法确认，不要写成确定事实")
            if code in _RANKING_FAILURE_CODES:
                required_additions.append("严格保留原有排序、赢家和对比顺序，不要重排")
            if code.startswith("forbidden_claim:"):
                unsupported_claims.append(code.split(":", 1)[1].strip())
            elif code.startswith("unsupported_"):
                unsupported_claims.append(code)
            elif code.startswith("failed_") or code.startswith("unknown_"):
                contradicted_claims.append(code)
            else:
                claims_to_keep.append(code)
        return cls(
            violation_codes=codes,
            unsupported_claims=_dedupe(unsupported_claims),
            contradicted_claims=_dedupe(contradicted_claims),
            required_additions=_dedupe(required_additions),
            claims_to_keep=_dedupe(claims_to_keep),
            fallback_mode=fallback_mode,
            tone=tone,
            max_length=max_length,
        )

    @classmethod
    def from_verifier_report(
        cls,
        report: dict[str, Any] | None = None,
        *,
        plan: DecisionPlan | None = None,
        fallback_mode: str = "",
        tone: str = "neutral",
        max_length: int = 0,
    ) -> "RewriteInstruction":
        report_dict = _to_dict(report)
        violation_codes = report_dict.get("violations") or report_dict.get("issues") or []
        if not violation_codes and report_dict.get("failure_code"):
            violation_codes = [report_dict.get("failure_code")]
        if not violation_codes and report_dict.get("violation"):
            violation_codes = [report_dict.get("violation")]
        instruction = cls.from_violation_codes(
            list(violation_codes),
            fallback_mode=fallback_mode,
            tone=tone,
            max_length=max_length,
        )
        unsupported_claims = _dedupe(
            list(instruction.unsupported_claims)
            + [str(item).strip() for item in (report_dict.get("unsupported_claims") or []) if str(item).strip()]
            + [str(item).strip() for item in (report_dict.get("false_fields") or []) if str(item).strip()]
            + [str(item).strip() for item in (report_dict.get("forbidden_claims") or []) if str(item).strip()]
        )
        contradicted_claims = _dedupe(
            list(instruction.contradicted_claims)
            + [str(item).strip() for item in (report_dict.get("false_fields") or []) if str(item).strip()]
        )
        required_additions = list(instruction.required_additions)
        if any(code in _RANKING_FAILURE_CODES for code in instruction.violation_codes):
            required_additions.append("严格保留原有排序、赢家和对比顺序，不要重排")
        if any(code in _UNCERTAINTY_FAILURE_CODES for code in instruction.violation_codes):
            required_additions.append("把不确定内容改成暂时无法确认，不要写成确定事实")
        if any(code in _BOUNDARY_FAILURE_CODES for code in instruction.violation_codes):
            required_additions.append("请基于已知证据回答，不要编造")
        claims_to_keep = _dedupe(list(instruction.claims_to_keep) + _claim_texts_from_plan(plan))
        unknown_fields = [str(item).strip() for item in (report_dict.get("unknown_fields") or []) if str(item).strip()]
        if unknown_fields:
            required_additions.append(f"保留不确定字段：{', '.join(_dedupe(unknown_fields))}")
        if report_dict.get("suggested_fix"):
            required_additions.append(str(report_dict["suggested_fix"]).strip())
        return cls(
            violation_codes=instruction.violation_codes,
            unsupported_claims=unsupported_claims,
            contradicted_claims=contradicted_claims,
            required_additions=_dedupe(required_additions),
            claims_to_keep=claims_to_keep,
            fallback_mode=fallback_mode or str(report_dict.get("fallback_mode", "") or ""),
            tone=tone,
            max_length=max_length,
        )
