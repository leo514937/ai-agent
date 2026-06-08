from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .answer_linter import lint_answer
from .final_answer_audit import FinalAnswerAudit, audit_final_answer
from .answer_sanitizer import sanitize_local_life_text


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
    issues: list[str] = field(default_factory=list)
    repaired_text: str | None = None
    sanitized: bool = False
    blocked: bool = False
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
) -> FinalAnswerSafetyResult:
    original_text = str(answer_text or "").strip()
    sanitized_text = sanitize_local_life_text(original_text, shop_lookup=shop_lookup)
    sanitized_text = str(sanitized_text or "").strip()

    lint_result = lint_answer(
        answer_text=sanitized_text,
        answer_contract=answer_contract,
        topic_name=str(_as_mapping(answer_contract).get("selected_entity") or ""),
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
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
    )

    issues = _dedupe_issues(audit.issues, repaired_lint.issues)
    severity = _merge_severity(audit.severity, repaired_lint.severity)
    blocked = severity == "block"
    passed = bool(audit.passed and repaired_lint.passed)
    sanitized = repaired_text != original_text

    return FinalAnswerSafetyResult(
        answer_text=repaired_text,
        passed=passed,
        severity=severity,
        issues=issues,
        repaired_text=lint_result.repaired_text,
        sanitized=sanitized,
        blocked=blocked,
        answer_lint=repaired_lint.model_dump(mode="json"),
        final_answer_audit=asdict(audit),
    )


__all__ = ["FinalAnswerSafetyResult", "apply_final_answer_safety"]
