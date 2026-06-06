from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .answer_contract import AnswerContract
from .answer_linter import AnswerLintResult, lint_answer


@dataclass(frozen=True)
class FinalAnswerAudit:
    passed: bool
    severity: str
    issues: list[str] = field(default_factory=list)
    forbidden_facets: list[str] = field(default_factory=list)
    cross_shop_leak: bool = False
    unsupported_realtime_claim: bool = False
    unsolicited_recommendation: bool = False
    tool_failure_categories: list[str] = field(default_factory=list)
    evidence_pack_item_count: int = 0
    route_gate: dict[str, Any] = field(default_factory=dict)
    source_contract: dict[str, Any] = field(default_factory=dict)
    review_report: dict[str, Any] = field(default_factory=dict)
    answer_lint: dict[str, Any] = field(default_factory=dict)


def _answer_lint_payload(
    answer_text: str,
    *,
    answer_contract: AnswerContract | Mapping[str, Any] | None,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_claims: Sequence[Mapping[str, Any] | Any],
    facet_result_bundle: Any | None = None,
    user_need: Any | None = None,
) -> AnswerLintResult:
    return lint_answer(
        answer_text=answer_text,
        answer_contract=answer_contract,
        topic_name=str(_as_mapping(answer_contract).get("selected_entity") or ""),
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
    )


def audit_final_answer(
    *,
    answer_text: str,
    answer_contract: AnswerContract | Mapping[str, Any] | None,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_claims: Sequence[Mapping[str, Any] | Any],
    evidence_pack: Mapping[str, Any] | Any | None = None,
    facet_result_bundle: Any | None = None,
    user_need: Any | None = None,
    route_gate: Mapping[str, Any] | None = None,
    source_contract: Mapping[str, Any] | None = None,
    review_report: Mapping[str, Any] | None = None,
    tool_results: Sequence[Mapping[str, Any] | Any] | None = None,
) -> FinalAnswerAudit:
    lint_result = _answer_lint_payload(
        answer_text,
        answer_contract=answer_contract,
        ranked_candidates=ranked_candidates,
        evidence_claims=evidence_claims,
        facet_result_bundle=facet_result_bundle,
        user_need=user_need,
    )
    tool_failure_categories = sorted(
        {
            str(_as_mapping(result).get("failure_category") or _as_mapping(result).get("status") or "").strip().lower()
            for result in (tool_results or [])
            if str(_as_mapping(result).get("failure_category") or _as_mapping(result).get("status") or "").strip()
        }
    )
    pack_map = _as_mapping(evidence_pack)
    evidence_count = len(pack_map.get("items") or [])
    source_contract_map = _as_mapping(source_contract)
    review_report_map = _as_mapping(review_report)
    route_gate_map = _as_mapping(route_gate)
    issues = list(lint_result.issues)
    if tool_failure_categories:
        issues.append("tool_failure_observed")
    return FinalAnswerAudit(
        passed=lint_result.passed and not tool_failure_categories,
        severity=str(lint_result.severity),
        issues=issues,
        forbidden_facets=list(lint_result.forbidden_facets),
        cross_shop_leak=bool(lint_result.cross_shop_leak),
        unsupported_realtime_claim=bool(lint_result.unsupported_realtime_claim),
        unsolicited_recommendation=bool(lint_result.unsolicited_recommendation),
        tool_failure_categories=tool_failure_categories,
        evidence_pack_item_count=evidence_count,
        route_gate=route_gate_map,
        source_contract=source_contract_map,
        review_report=review_report_map,
        answer_lint=lint_result.model_dump(mode="json"),
    )


__all__ = ["FinalAnswerAudit", "audit_final_answer"]
