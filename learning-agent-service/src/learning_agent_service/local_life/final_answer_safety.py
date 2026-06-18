from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .answer_linter import lint_answer
from .final_answer_audit import FinalAnswerAudit, audit_final_answer
from .answer_sanitizer import sanitize_local_life_text
from .claim_grounding import (
    build_claim_bindings,
    build_high_risk_fallback_message,
    is_high_risk_answer_context,
    summarize_claim_bindings,
)


def _dedupe_issues(*issue_groups: Sequence[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for group in issue_groups:
        for issue in group:
            text = str(issue or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
    return ordered


def _merge_severity(*severities: str) -> str:
    order = {"pass": 0, "warn": 1, "block": 2}
    merged = "pass"
    for severity in severities:
        text = str(severity or "").strip().lower()
        if order.get(text, 0) > order.get(merged, 0):
            merged = text
    return merged


@dataclass(frozen=True)
class FinalAnswerSafetyResult:
    answer_text: str
    passed: bool
    severity: str
    suggested_response_mode: str = "grounded"
    issues: list[str] = field(default_factory=list)
    repaired_text: str | None = None
    sanitized: bool = False
    blocked: bool = False
    claim_bindings: list[dict[str, Any]] = field(default_factory=list)
    claim_count: int = 0
    supported_claim_count: int = 0
    partial_claim_count: int = 0
    unsupported_claim_count: int = 0
    conflicted_claim_count: int = 0
    answer_lint: dict[str, Any] = field(default_factory=dict)
    final_answer_audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_final_answer_safety(
    *,
    answer_text: str,
    answer_contract: Any | None,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_claims: Sequence[Mapping[str, Any] | Any],
    evidence_pack: Mapping[str, Any] | Any | None = None,
    facet_result_bundle: Any | None = None,
    user_need: Any | None = None,
    route_gate: Mapping[str, Any] | None = None,
    source_contract: Mapping[str, Any] | None = None,
    review_report: Mapping[str, Any] | None = None,
    tool_results: Sequence[Mapping[str, Any] | Any] | None = None,
    shop_lookup: Mapping[int, str] | None = None,
    answer_context: Mapping[str, Any] | None = None,
) -> FinalAnswerSafetyResult:
    original_text = str(answer_text or "").strip()
    sanitized_text = sanitize_local_life_text(original_text, shop_lookup=shop_lookup)
    sanitized_text = str(sanitized_text or "").strip()
    high_risk = is_high_risk_answer_context(
        answer_contract=answer_contract,
        answer_context=answer_context,
        route_gate=route_gate,
        review_report=review_report,
        tool_results=tool_results,
    )
    claim_bindings = build_claim_bindings(
        answer_text=sanitized_text,
        answer_contract=answer_contract,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        evidence_pack=evidence_pack,
        facet_result_bundle=facet_result_bundle,
        tool_results=tool_results,
        answer_context=answer_context,
        route_gate=route_gate,
        review_report=review_report,
    )

    lint_result = lint_answer(
        answer_text=sanitized_text,
        answer_contract=answer_contract,
        topic_name=str(_as_mapping(answer_contract).get("selected_entity") or ""),
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
        answer_context=answer_context,
        claim_bindings=claim_bindings,
    )
    repaired_text = str(lint_result.repaired_text or sanitized_text).strip()
    if not repaired_text:
        repaired_text = sanitized_text or original_text

    repaired_lint = lint_answer(
        answer_text=repaired_text,
        answer_contract=answer_contract,
        topic_name=str(_as_mapping(answer_contract).get("selected_entity") or ""),
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
        answer_context=answer_context,
        claim_bindings=claim_bindings,
    )
    audit = audit_final_answer(
        answer_text=repaired_text,
        answer_contract=answer_contract,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        evidence_pack=evidence_pack,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
        route_gate=route_gate,
        source_contract=source_contract,
        review_report=review_report,
        tool_results=tool_results,
        answer_context=answer_context,
    )
    claim_bindings = list(audit.claim_bindings or claim_bindings)

    issues = _dedupe_issues(audit.issues, repaired_lint.issues)
    severity = _merge_severity(audit.severity, repaired_lint.severity)
    blocked = severity == "block"
    passed = bool(audit.passed and repaired_lint.passed)
    sanitized = repaired_text != original_text
    suggested_response_mode = str(_as_mapping(answer_context).get("final_response_mode") or "grounded").strip().lower() or "grounded"
    fallback_triggered = high_risk and (
        blocked
        or not passed
        or bool(audit.unsupported_claim_count)
        or any(
            str(binding.get("support_status") or "").strip().lower() in {"unsupported", "conflicted"}
            for binding in claim_bindings
        )
    )
    if fallback_triggered:
        fallback_text = build_high_risk_fallback_message(
            answer_contract=answer_contract,
            answer_context=answer_context,
            issues=issues,
        )
        if fallback_text:
            repaired_text = fallback_text
        severity = "block"
        blocked = True
        passed = False
        if "请告诉我" in repaired_text or "补充" in repaired_text:
            suggested_response_mode = "ask_clarification"
        elif str(_as_mapping(answer_contract).get("answer_style") or "").strip().lower() in {"coupon_only", "open_status_only", "distance_only"}:
            suggested_response_mode = "partial_grounded"
        else:
            suggested_response_mode = "no_answer"
    claim_summary = summarize_claim_bindings(claim_bindings)

    return FinalAnswerSafetyResult(
        answer_text=repaired_text,
        passed=passed,
        severity=severity,
        suggested_response_mode=suggested_response_mode,
        issues=issues,
        repaired_text=repaired_text,
        sanitized=sanitized,
        blocked=blocked,
        claim_bindings=claim_bindings,
        claim_count=int(claim_summary.get("claim_count") or 0),
        supported_claim_count=int(claim_summary.get("supported_claim_count") or 0),
        partial_claim_count=int(claim_summary.get("partial_claim_count") or 0),
        unsupported_claim_count=int(claim_summary.get("unsupported_claim_count") or 0),
        conflicted_claim_count=int(claim_summary.get("conflicted_claim_count") or 0),
        answer_lint=repaired_lint.model_dump(mode="json"),
        final_answer_audit=asdict(audit),
    )


__all__ = ["FinalAnswerSafetyResult", "apply_final_answer_safety"]
