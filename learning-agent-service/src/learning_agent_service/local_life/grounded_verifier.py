from __future__ import annotations

from typing import Any, Mapping, Sequence

from .answer_planner import (
    CandidateEvidenceSummary,
    CouponAdvice,
    EvidencePack,
    GroundedVerificationResult,
    LocalLifeAnswerPlan,
    SceneFitSummary,
    parse_answer_plan_payload,
)
from .coupon_result import CouponResult


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _evidence_index(pack: EvidencePack | Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    evidence_pack = _as_mapping(pack)
    index: dict[str, dict[str, Any]] = {}
    for item in evidence_pack.get("items") or []:
        item_map = _as_mapping(item)
        evidence_id = str(item_map.get("evidence_id") or item_map.get("chunk_id") or "").strip()
        if evidence_id:
            index[evidence_id] = item_map
    return index


def _candidate_shop_ids(ranked_candidates: Sequence[Mapping[str, Any] | Any]) -> set[int]:
    ids: set[int] = set()
    for candidate in ranked_candidates:
        candidate_map = _as_mapping(candidate)
        raw_id = candidate_map.get("shop_id") or candidate_map.get("id")
        if raw_id in (None, ""):
            continue
        try:
            ids.add(int(raw_id))
        except Exception:
            continue
    return ids


def _plan_from_any(answer_plan: LocalLifeAnswerPlan | Mapping[str, Any] | None) -> LocalLifeAnswerPlan | None:
    if answer_plan is None:
        return None
    if isinstance(answer_plan, LocalLifeAnswerPlan):
        return answer_plan
    return parse_answer_plan_payload(answer_plan)


class GroundedVerifier:
    def verify(
        self,
        *,
        answer_plan: LocalLifeAnswerPlan | Mapping[str, Any] | None,
        evidence_pack: EvidencePack | Mapping[str, Any] | None,
        ranked_candidates: Sequence[Mapping[str, Any] | Any],
        safety_result: Mapping[str, Any] | Any,
        coupon_result: CouponResult | Mapping[str, Any] | None = None,
    ) -> GroundedVerificationResult:
        plan = _plan_from_any(answer_plan)
        if plan is None:
            return GroundedVerificationResult(
                passed=False,
                issues=["answer_plan_missing_or_invalid"],
                warnings=[],
                suggested_response_mode="fallback",
                degraded_reason="answer_plan_missing_or_invalid",
                normalized_plan={},
                evidence_pack_item_count=len((_as_mapping(evidence_pack).get("items") or [])),
                confidence="low",
            )

        evidence_index = _evidence_index(evidence_pack)
        ranked_shop_ids = _candidate_shop_ids(ranked_candidates)
        normalized_plan = plan.model_dump(mode="json")
        issues: list[str] = []
        warnings: list[str] = []

        normalized_evidence_used: list[str] = []
        for evidence_id in plan.evidence_used:
            if evidence_id not in evidence_index:
                issues.append("unknown_evidence_id")
            else:
                normalized_evidence_used.append(evidence_id)
        normalized_plan["evidence_used"] = normalized_evidence_used

        candidate_reasons: list[dict[str, Any]] = []
        for candidate in plan.candidate_reasons:
            candidate_map = candidate.model_dump(mode="json")
            try:
                shop_id = int(candidate_map.get("shop_id") or 0)
            except Exception:
                shop_id = 0
            if shop_id not in ranked_shop_ids:
                issues.append("unknown_candidate_shop_id")
                continue
            candidate_reasons.append(candidate_map)
        normalized_plan["candidate_reasons"] = candidate_reasons

        top_choice = plan.top_choice.model_dump(mode="json") if plan.top_choice is not None else None
        if top_choice is not None:
            try:
                top_choice_shop_id = int(top_choice.get("shop_id") or 0)
            except Exception:
                top_choice_shop_id = 0
            if top_choice_shop_id not in ranked_shop_ids:
                issues.append("unknown_top_choice_shop_id")
                top_choice = None
        if top_choice is None and candidate_reasons:
            top_choice = candidate_reasons[0]
        normalized_plan["top_choice"] = top_choice

        safety = _as_mapping(safety_result)
        approval_required = bool(safety.get("approval_required"))
        if approval_required and plan.decision_type in {"booking", "order"}:
            answer_text = str(normalized_plan.get("answer_text") or "")
            has_confirmation = any(token in answer_text for token in ("确认", "草案", "再继续", "继续执行", "等待你确认"))
            if not has_confirmation:
                issues.append("approval_required_violation")
        elif approval_required and plan.decision_type not in {"booking", "order"}:
            warnings.append("approval_required_but_non_transactional_plan")

        coupon_advice = plan.coupon_advice.model_dump(mode="json")
        has_coupon_evidence = any(
            str(item.get("source_type") or "").lower() in {"coupon", "voucher", "package_description"}
            or "券" in str(item.get("claim") or "")
            for item in evidence_index.values()
        )
        if coupon_advice.get("has_coupon") is True and not has_coupon_evidence:
            coupon_advice["has_coupon"] = False
            coupon_advice["worth_it"] = "unknown"
            coupon_advice["reason"] = (
                str(coupon_advice.get("reason") or "").strip()
                or "当前证据里没有看到可直接确认的券信息。"
            )
            warnings.append("coupon_evidence_missing")
        normalized_plan["coupon_advice"] = coupon_advice

        evidence_count = len(evidence_index)
        if len(normalized_evidence_used) <= 1 or evidence_count <= 1:
            warnings.append("evidence_insufficient")
            confidence = "low" if plan.confidence == "high" else plan.confidence
        elif len(normalized_evidence_used) == 2 and plan.confidence == "high":
            confidence = "medium"
        else:
            confidence = plan.confidence

        # GroundedVerifier 校验券数量: 防止最终文本与 tool 不一致
        if coupon_result is not None:
            realtime_count = 0
            if hasattr(coupon_result, "realtime_available_count"):
                realtime_count = coupon_result.realtime_available_count
            elif isinstance(coupon_result, dict):
                realtime_count = coupon_result.get("realtime_available_count", 0)

            import re
            answer_text = str(normalized_plan.get("answer_text") or "")
            match = re.search(r"(\d+|[一二三四五六七八九十]|两)\s*张(?:券|优惠券)", answer_text)
            if match:
                num_str = match.group(1)
                num_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                try:
                    num = int(num_str)
                except ValueError:
                    num = num_map.get(num_str, 0)
                
                if num != realtime_count:
                    warnings.append("coupon_count_mismatch")
                    corrected_text = re.sub(
                        r"(\d+|[一二三四五六七八九十]|两)(\s*张(?:券|优惠券))", 
                        f"{realtime_count}\\2", 
                        answer_text
                    )
                    normalized_plan["answer_text"] = corrected_text

        absolute_tokens = ("一定", "肯定", "绝对", "百分百", "100%")
        answer_text_value = str(normalized_plan.get("answer_text") or "")
        if any(token in answer_text_value for token in absolute_tokens) and evidence_count <= 1:
            warnings.append("absolute_language_without_strong_evidence")
            degraded_reason = "evidence_insufficient"
        else:
            degraded_reason = None

        passed = not issues
        suggested_response_mode = "grounded" if passed else "partial_grounded"
        if issues:
            degraded_reason = degraded_reason or "verifier_failed"

        return GroundedVerificationResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            suggested_response_mode=suggested_response_mode,
            degraded_reason=degraded_reason,
            normalized_plan=normalized_plan,
            evidence_pack_item_count=evidence_count,
            confidence=confidence,
        )


__all__ = ["GroundedVerifier"]
