"""RetrievalQualityGuard - checks retrieval quality before answer generation.

This module validates evidence quality before it enters the final LLM
Answer Generation step, preventing low-quality evidence from producing
unreliable answers.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import EvidencePack, EvidenceStatus, RecallHit, RetrievalPlan

_LOGGER = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")


class QualityVerdict(str, Enum):
    OK = "ok"
    RETRY_RETRIEVAL = "retry_retrieval"
    CLARIFY = "clarify"
    CONSERVATIVE_ANSWER = "conservative_answer"
    TOOL_REQUIRED = "tool_required"


_REALTIME_RISK_KEYWORDS: frozenset[str] = frozenset({
    "营业", "开门", "关门", "营业时间", "现在", "今天",
    "价格", "多少钱", "人均", "库存", "优惠券", "还能用",
    "可用", "过期", "实时", "open", "price", "available",
    "stock", "coupon", "discount", "deal", "business_hours",
})


@dataclass(frozen=True)
class RetrievalQualityGuardConfig:
    enabled: bool = True
    min_top_score: float = 0.15
    min_evidence_count: int = 1
    degraded_evidence_threshold: float = 0.8
    realtime_risk_requires_tool: bool = True
    low_confidence_threshold: float = 0.3
    require_slot_coverage: bool = True


@dataclass(frozen=True)
class RetrievalQualityResult:
    verdict: QualityVerdict
    confidence: float
    evidence_count: int
    top_score: float
    all_degraded: bool
    is_realtime_risk: bool
    missing_slots: tuple[str, ...] = ()
    conflicting_evidence: bool = False
    reason: str = ""
    debug_metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalQualityGuard:
    """Checks retrieval quality before answer generation.

    Prevents low-quality evidence from producing unreliable answers,
    especially for realtime risk queries that require tool evidence.
    """

    def __init__(self, config: RetrievalQualityGuardConfig | None = None) -> None:
        self._config = config or RetrievalQualityGuardConfig()

    def check(
        self,
        evidence_pack: EvidencePack,
        plan: RetrievalPlan,
        *,
        has_tool_evidence: bool = False,
        context_slots: dict[str, Any] | None = None,
    ) -> RetrievalQualityResult:
        if not self._config.enabled:
            return RetrievalQualityResult(
                verdict=QualityVerdict.OK,
                confidence=1.0,
                evidence_count=len(evidence_pack.items),
                top_score=0.0,
                all_degraded=False,
                is_realtime_risk=False,
            )

        raw_query = str(plan.extra.get("raw_query") or plan.semantic_query or "").lower()
        evidence_items = list(evidence_pack.items)
        evidence_count = len(evidence_items)

        top_score = 0.0
        if evidence_items:
            top_score = max(item.score for item in evidence_items)

        all_degraded = evidence_pack.evidence_status is not EvidenceStatus.OK
        all_empty = evidence_pack.evidence_status is EvidenceStatus.EMPTY

        is_realtime_risk = any(kw in raw_query for kw in _REALTIME_RISK_KEYWORDS)

        missing_slots = self._check_slot_coverage(raw_query, context_slots or {})
        has_conflicts = self._detect_conflicting_evidence(evidence_items)

        debug = {
            "evidence_count": evidence_count,
            "top_score": round(top_score, 4),
            "all_degraded": all_degraded,
            "all_empty": all_empty,
            "is_realtime_risk": is_realtime_risk,
            "missing_slots": list(missing_slots),
            "has_conflicts": has_conflicts,
            "has_tool_evidence": has_tool_evidence,
        }

        verdict, confidence, reason = self._decide_verdict(
            evidence_count=evidence_count,
            top_score=top_score,
            all_degraded=all_degraded,
            all_empty=all_empty,
            is_realtime_risk=is_realtime_risk,
            has_tool_evidence=has_tool_evidence,
            missing_slots=missing_slots,
            has_conflicts=has_conflicts,
        )

        result = RetrievalQualityResult(
            verdict=verdict,
            confidence=confidence,
            evidence_count=evidence_count,
            top_score=top_score,
            all_degraded=all_degraded,
            is_realtime_risk=is_realtime_risk,
            missing_slots=missing_slots,
            conflicting_evidence=has_conflicts,
            reason=reason,
            debug_metadata=debug,
        )

        if verdict is not QualityVerdict.OK:
            _LOGGER.info(
                "retrieval_quality_guard verdict=%s reason=%s evidence_count=%s top_score=%.3f",
                verdict.value,
                reason,
                evidence_count,
                top_score,
            )

        return result

    def _decide_verdict(
        self,
        *,
        evidence_count: int,
        top_score: float,
        all_degraded: bool,
        all_empty: bool,
        is_realtime_risk: bool,
        has_tool_evidence: bool,
        missing_slots: tuple[str, ...],
        has_conflicts: bool,
    ) -> tuple[QualityVerdict, float, str]:
        if all_empty:
            return QualityVerdict.RETRY_RETRIEVAL, 0.0, "empty_evidence"

        if is_realtime_risk and self._config.realtime_risk_requires_tool and not has_tool_evidence:
            return QualityVerdict.TOOL_REQUIRED, 0.2, "realtime_risk_no_tool"

        if evidence_count < self._config.min_evidence_count:
            return QualityVerdict.RETRY_RETRIEVAL, 0.3, f"insufficient_evidence:{evidence_count}"

        if top_score < self._config.min_top_score:
            return QualityVerdict.CONSERVATIVE_ANSWER, 0.4, f"low_top_score:{top_score:.3f}"

        if all_degraded and evidence_count <= 2:
            return QualityVerdict.CONSERVATIVE_ANSWER, 0.5, "degraded_low_count"

        degraded_ratio = 1.0 if all_degraded else 0.0
        if degraded_ratio > self._config.degraded_evidence_threshold:
            return QualityVerdict.CONSERVATIVE_ANSWER, 0.5, "mostly_degraded"

        if missing_slots and self._config.require_slot_coverage:
            return QualityVerdict.CLARIFY, 0.6, f"missing_slots:{','.join(missing_slots)}"

        if has_conflicts:
            return QualityVerdict.CONSERVATIVE_ANSWER, 0.6, "conflicting_evidence"

        if top_score < self._config.low_confidence_threshold:
            return QualityVerdict.CONSERVATIVE_ANSWER, 0.6, f"low_confidence:{top_score:.3f}"

        return QualityVerdict.OK, 0.9, ""

    def _check_slot_coverage(
        self,
        query: str,
        context_slots: dict[str, Any],
    ) -> tuple[str, ...]:
        missing: list[str] = []

        for slot_name in ("shop_name", "city", "domain"):
            slot_value = context_slots.get(slot_name)
            if slot_value not in (None, "", [], {}, ()):
                slot_str = str(slot_value).lower()
                if slot_str not in query:
                    missing.append(slot_name)

        return tuple(missing)

    @staticmethod
    def _detect_conflicting_evidence(evidence_items: list) -> bool:
        if len(evidence_items) < 2:
            return False

        texts = [item.chunk.text.lower() for item in evidence_items]
        conflict_pairs = [
            ("开门", "关门"),
            ("营业", "歇业"),
            ("推荐", "不推荐"),
            ("好吃", "难吃"),
            ("贵", "便宜"),
            ("好", "差"),
        ]

        for neg1, neg2 in conflict_pairs:
            has_pos = any(neg1 in text for text in texts)
            has_neg = any(neg2 in text for text in texts)
            if has_pos and has_neg:
                return True

        return False


__all__ = [
    "QualityVerdict",
    "RetrievalQualityGuard",
    "RetrievalQualityGuardConfig",
    "RetrievalQualityResult",
]
