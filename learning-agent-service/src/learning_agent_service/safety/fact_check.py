from __future__ import annotations

from typing import Sequence

from ..local_life.schemas import EvidenceClaim, RankedCandidate
from .policy import FactCheckResult


def _candidate_support_score(candidate: RankedCandidate) -> float:
    score = 0.0
    structured = candidate.structured_features
    evidence = candidate.evidence_features
    if structured.get("parking"):
        score += 0.2
    if structured.get("family_friendly"):
        score += 0.2
    if structured.get("elder_friendly"):
        score += 0.2
    if evidence.get("quiet", 0.0) >= 0.6:
        score += 0.2
    if evidence.get("family_dinner", 0.0) >= 0.6:
        score += 0.1
    if evidence.get("elder_friendly", 0.0) >= 0.6:
        score += 0.1
    return min(1.0, score)


def evaluate_fact_check(
    *,
    ranked_candidates: Sequence[RankedCandidate],
    evidence_claims: Sequence[EvidenceClaim],
) -> FactCheckResult:
    supported_claims: list[str] = []
    weak_claims: list[str] = []
    unsupported_claims: list[str] = []
    evidence_notes: list[str] = []

    if not ranked_candidates:
        return FactCheckResult(
            supported_claims=[],
            weak_claims=[],
            unsupported_claims=["no_ranked_candidates"],
            evidence_score=0.0,
            confidence=0.0,
            evidence_notes=["没有可用于事实校验的候选商户。"],
        )

    claim_lookup = {claim.chunk_id: claim for claim in evidence_claims}
    evidence_score_total = 0.0
    evidence_count = 0
    for candidate in ranked_candidates[:3]:
        support_score = _candidate_support_score(candidate)
        if support_score >= 0.6:
            supported_claims.extend(candidate.explainable_reasons[:2] or [candidate.name])
        elif support_score >= 0.25:
            weak_claims.extend(candidate.explainable_reasons[:2] or [candidate.name])
        else:
            unsupported_claims.extend(candidate.explainable_reasons[:2] or [candidate.name])
        evidence_score_total += support_score
        evidence_count += 1

    if evidence_claims:
        evidence_notes.append("已有评论摘要或证据条目支持推荐理由。")
        confidence = min(0.98, max((claim.confidence for claim in evidence_claims), default=0.0))
    else:
        evidence_notes.append("没有找到可引用的评论证据。")
        confidence = 0.0

    if claim_lookup:
        evidence_notes.append("证据条目已与候选商户完成基础对齐。")

    evidence_score = round(evidence_score_total / max(1, evidence_count), 3)
    return FactCheckResult(
        supported_claims=supported_claims[:5],
        weak_claims=weak_claims[:5],
        unsupported_claims=unsupported_claims[:5],
        evidence_score=evidence_score,
        confidence=confidence,
        evidence_notes=evidence_notes,
    )
