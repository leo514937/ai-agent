from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from .models import (
    EvidenceItem,
    EvidencePack,
    EvidenceStatus,
    RecallHit,
    RetrievalPlan,
    RetrievalTrace,
    RetrievalTraceItem,
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")

_QUERY_COMPLEXITY_SIGNALS: dict[str, tuple[str, ...]] = {
    "simple": ("什么", "是", "吗", "what", "is", "do"),
    "complex": ("为什么", "怎么", "如何", "区别", "比较", "推荐", "why", "how", "compare", "recommend"),
    "factoid": ("多少", "几点", "哪里", "谁", "how much", "where", "who", "when"),
    "comparison": ("对比", "比较", "区别", "差别", "vs", "compare", "difference"),
    "recommendation": ("推荐", "建议", "哪个好", "recommend", "suggest", "best"),
    "multi_hop": ("然后", "接着", "之后", "同时", "and then", "also", "besides"),
    "procedural": ("步骤", "流程", "怎么操作", "怎么做", "step", "procedure", "how to"),
}

_REALTIME_RISK_SIGNALS: tuple[str, ...] = (
    "营业", "开门", "关门", "现在", "今天", "价格", "库存", "优惠券",
    "还能用", "可用", "过期", "实时", "open", "price", "available", "stock",
)


@dataclass(frozen=True)
class EvidenceGovernanceConfig:
    low_score_threshold: float = 0.28
    strong_score_threshold: float = 0.45
    dedup_similarity_threshold: float = 0.82
    topic_consistency_threshold: float = 0.35
    min_items: int = 4
    max_items: int = 6
    max_token_budget: int = 2000
    simple_query_max_items: int = 3
    simple_query_max_tokens: int = 800
    complex_query_max_items: int = 8
    complex_query_max_tokens: int = 3000
    enable_diversity_control: bool = True
    enable_dedup: bool = True
    diversity_penalty_factor: float = 0.1


@dataclass(frozen=True)
class QueryComplexityProfile:
    level: str = "medium"
    answer_type: str = "explanation"
    max_items: int = 6
    max_tokens: int = 2000
    needs_diversity: bool = True
    needs_strong_dedup: bool = False
    is_realtime_risk: bool = False


class QueryComplexityProfiler:
    """Lightweight query complexity profiler for evidence budget decisions."""

    def __init__(self, config: EvidenceGovernanceConfig | None = None) -> None:
        self._config = config or EvidenceGovernanceConfig()

    def profile(self, plan: RetrievalPlan) -> QueryComplexityProfile:
        raw_query = str(plan.extra.get("raw_query") or plan.semantic_query or "").lower()
        intent = str(plan.extra.get("intent") or "").lower()

        is_realtime = any(sig in raw_query for sig in _REALTIME_RISK_SIGNALS)

        complexity_level = "medium"
        answer_type = "explanation"
        max_items = self._config.max_items
        max_tokens = self._config.max_token_budget

        if any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("comparison", ())):
            complexity_level = "complex"
            answer_type = "comparison"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
        elif any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("recommendation", ())):
            answer_type = "recommendation"
            complexity_level = "complex"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
        elif any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("multi_hop", ())):
            answer_type = "multi_hop"
            complexity_level = "complex"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
        elif any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("procedural", ())):
            answer_type = "procedural"
            complexity_level = "complex"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
        elif any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("complex", ())):
            complexity_level = "complex"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
        elif any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("simple", ())):
            if len(raw_query) < 15:
                complexity_level = "simple"
                max_items = self._config.simple_query_max_items
                max_tokens = self._config.simple_query_max_tokens
                answer_type = "factoid"
        elif any(sig in raw_query for sig in _QUERY_COMPLEXITY_SIGNALS.get("factoid", ())):
            answer_type = "factoid"

        if intent in ("compare", "recommend"):
            complexity_level = "complex"
            max_items = self._config.complex_query_max_items
            max_tokens = self._config.complex_query_max_tokens
            if intent == "compare":
                answer_type = "comparison"
            elif intent == "recommend":
                answer_type = "recommendation"

        needs_diversity = self._config.enable_diversity_control and complexity_level == "complex"
        needs_strong_dedup = complexity_level == "simple"

        return QueryComplexityProfile(
            level=complexity_level,
            answer_type=answer_type,
            max_items=max_items,
            max_tokens=max_tokens,
            needs_diversity=needs_diversity,
            needs_strong_dedup=needs_strong_dedup,
            is_realtime_risk=is_realtime,
        )


class EvidenceGovernanceService:
    def __init__(self, config: EvidenceGovernanceConfig | None = None) -> None:
        self._config = config or EvidenceGovernanceConfig()
        self._profiler = QueryComplexityProfiler(self._config)

    def evaluate(
        self,
        plan: RetrievalPlan,
        hits: Sequence[RecallHit],
        trace: RetrievalTrace | None = None,
    ) -> EvidencePack:
        original_count = len(hits)
        kept: list[RecallHit] = list(hits)
        rejected: list[RetrievalTraceItem] = []

        complexity = self._profiler.profile(plan)

        kept, low_score_rejected = self._low_score_filter(kept)
        rejected.extend(low_score_rejected)
        if self._config.enable_dedup:
            kept, dedup_rejected = self._deduplicate(kept, complexity)
            rejected.extend(dedup_rejected)
        kept, topic_rejected = self._topic_consistency_filter(plan, kept)
        rejected.extend(topic_rejected)
        kept, version_rejected = self._version_filter(plan, kept)
        rejected.extend(version_rejected)
        kept, answer_view_rejected = self._answer_view_filter(plan, kept)
        rejected.extend(answer_view_rejected)

        limit = min(
            plan.max_evidence or complexity.max_items,
            complexity.max_items,
            self._config.max_items,
        )
        final_hits = tuple(kept[:limit])
        limit_rejected = tuple(self._to_trace_item(hit, rejected_reason="chunk_type_mismatch") for hit in kept[limit:])
        rejected.extend(limit_rejected)

        strong_items: list[EvidenceItem] = []
        weak_items: list[EvidenceItem] = []
        evidence_items: list[EvidenceItem] = []
        for hit in final_hits:
            tier = self._classify_tier(hit)
            item = EvidenceItem(
                chunk=hit.chunk,
                score=hit.score,
                routes=tuple(sorted(hit.route_scores)) if hit.route_scores else (hit.route,),
                reasons=(
                    "passed_low_score_filter",
                    "passed_dedup_filter",
                    "passed_topic_consistency_filter",
                    "passed_version_filter",
                    "passed_answer_view_filter",
                ),
                tier=tier,
                citation_chunk_id=self._citation_chunk_id(hit),
                source_chunk_id=self._source_chunk_id(hit),
                parent_chunk_id=hit.chunk.parent_id,
                metadata={
                    "source_routes": tuple(sorted(hit.route_scores)),
                    "rrf_score": hit.fused_score or hit.rrf_score,
                    "fused_score": hit.fused_score or hit.rrf_score,
                    "rerank_score": hit.rerank_score,
                    "rerank_rank": hit.rerank_rank,
                    "rerank_model": hit.rerank_model,
                    "citation_chunk_id": self._citation_chunk_id(hit),
                    "source_chunk_id": self._source_chunk_id(hit),
                    "parent_chunk_id": hit.chunk.parent_id,
                },
            )
            evidence_items.append(item)
            if tier == "strong":
                strong_items.append(item)
            elif tier == "weak":
                weak_items.append(item)

        if not evidence_items:
            evidence_status = EvidenceStatus.EMPTY
        elif strong_items:
            evidence_status = EvidenceStatus.OK
        else:
            evidence_status = EvidenceStatus.WEAK

        if evidence_status is EvidenceStatus.EMPTY:
            status = "empty"
        elif evidence_status is EvidenceStatus.OK:
            status = "ok"
        else:
            status = "degraded"

        metrics: dict[str, Any] = {
            "evidence_used_count": len(evidence_items),
            "evidence_filtered_out": max(original_count - len(evidence_items), 0),
            "evidence_rejected_count": len(rejected),
            "evidence_strong_count": len(strong_items),
            "evidence_weak_count": len(weak_items),
            "evidence_status": evidence_status.value,
            "evidence_quality": "strong" if strong_items else "weak" if evidence_items else "empty",
            "evidence_strong_threshold": self._config.strong_score_threshold,
            "policy_snapshot": self._policy_snapshot(),
            "complexity_level": complexity.level,
            "complexity_answer_type": complexity.answer_type,
            "complexity_max_items": complexity.max_items,
            "complexity_max_tokens": complexity.max_tokens,
            "complexity_needs_diversity": complexity.needs_diversity,
            "complexity_is_realtime_risk": complexity.is_realtime_risk,
        }
        rejection_counts = Counter(item.rejected_reason or "unknown" for item in rejected)
        if rejection_counts:
            metrics["evidence_rejected_reasons"] = dict(rejection_counts)
        kept_routes = tuple(sorted({route for item in evidence_items for route in item.routes}))
        if not evidence_items:
            if original_count <= 0:
                retention_reason = "no_hits_retrieved"
            elif rejection_counts:
                top_reasons = rejection_counts.most_common(3)
                retention_reason = ";".join(f"{reason}:{count}" for reason, count in top_reasons)
            else:
                retention_reason = "all_hits_filtered"
        else:
            retention_reason = ""
        retention_summary = {
            "input_hit_count": original_count,
            "kept_hit_count": len(evidence_items),
            "rejected_hit_count": len(rejected),
            "kept_routes": list(kept_routes),
            "status": status,
            "status_value": evidence_status.value,
            "retention_reason": retention_reason,
            "rejection_reasons": dict(rejection_counts),
        }

        evidence_trace = trace or RetrievalTrace(
            raw_query=str(plan.extra.get("raw_query", "")),
            semantic_query=plan.semantic_query,
            keyword_query=plan.keyword_query,
            retrieval_filters=plan.retrieval_filters,
            final_retrieval_filters={
                "category": list(plan.retrieval_filters.category),
                "subcategory": list(plan.retrieval_filters.subcategory),
                "difficulty": list(plan.retrieval_filters.difficulty),
                "source_type": list(plan.retrieval_filters.source_type),
                "chunk_type": list(plan.retrieval_filters.chunk_type),
                "version": list(plan.retrieval_filters.version),
                "tags": list(plan.retrieval_filters.tags),
                "extra": dict(plan.retrieval_filters.extra),
            },
            preferred_chunk_types=plan.preferred_chunk_types,
        )
        evidence_trace = replace(
            evidence_trace,
            evidence_kept=tuple(self._to_trace_item(hit) for hit in final_hits),
            evidence_rejected=tuple(rejected),
            degraded=evidence_status is not EvidenceStatus.OK,
            empty=status == "empty",
            metrics={**dict(evidence_trace.metrics), **metrics},
            extra={
                **dict(evidence_trace.extra),
                "evidence_stage": "post_evidence_governance",
                "evidence_status": evidence_status.value,
                "retention_summary": retention_summary,
                "policy_snapshot": self._policy_snapshot(),
            },
        )

        return EvidencePack(
            items=tuple(evidence_items),
            status=status,
            evidence_status=evidence_status,
            strong_items=tuple(strong_items),
            weak_items=tuple(weak_items),
            filtered_out=max(original_count - len(evidence_items), 0),
            rationale=(
                "low_score_filter",
                "deduplication",
                "topic_consistency_filter",
                "version_filter",
                "answer_view_filter",
            ),
            metrics=metrics,
            rejected_items=tuple(rejected),
            debug_trace=evidence_trace,
        )

    def _classify_tier(self, hit: RecallHit) -> str:
        rerank_score = float(hit.rerank_score if hit.rerank_score is not None else 0.0)
        fused_score = float(hit.fused_score or hit.rrf_score or hit.score or 0.0)
        if rerank_score >= self._config.strong_score_threshold and fused_score >= self._config.low_score_threshold:
            return "strong"
        if rerank_score >= self._config.low_score_threshold or fused_score >= self._config.low_score_threshold:
            return "weak"
        return "rejected"

    @staticmethod
    def _citation_chunk_id(hit: RecallHit) -> str:
        return str(hit.citation_chunk_id or hit.metadata.get("citation_chunk_id") or hit.chunk.chunk_id)

    @staticmethod
    def _source_chunk_id(hit: RecallHit) -> str:
        return str(hit.source_chunk_id or hit.metadata.get("source_chunk_id") or hit.chunk.chunk_id)

    def _policy_snapshot(self) -> dict[str, float | int]:
        return {
            "low_score_threshold": self._config.low_score_threshold,
            "strong_score_threshold": self._config.strong_score_threshold,
            "dedup_similarity_threshold": self._config.dedup_similarity_threshold,
            "topic_consistency_threshold": self._config.topic_consistency_threshold,
            "min_items": self._config.min_items,
            "max_items": self._config.max_items,
        }

    def _low_score_filter(self, hits: Sequence[RecallHit]) -> tuple[list[RecallHit], list[RetrievalTraceItem]]:
        kept: list[RecallHit] = []
        rejected: list[RetrievalTraceItem] = []
        for hit in hits:
            if hit.score >= self._config.low_score_threshold:
                kept.append(hit)
            else:
                rejected.append(self._to_trace_item(hit, rejected_reason="low_score"))
        return kept, rejected

    def _deduplicate(
        self,
        hits: Sequence[RecallHit],
        complexity: QueryComplexityProfile | None = None,
    ) -> tuple[list[RecallHit], list[RetrievalTraceItem]]:
        threshold = self._config.dedup_similarity_threshold
        if complexity and complexity.needs_strong_dedup:
            threshold = max(0.6, threshold - 0.15)
        kept: list[RecallHit] = []
        rejected: list[RetrievalTraceItem] = []
        for hit in hits:
            if any(self._text_similarity(hit.chunk.text, other.chunk.text) >= threshold for other in kept):
                rejected.append(self._to_trace_item(hit, rejected_reason="duplicate"))
                continue
            kept.append(hit)
        return kept, rejected

    def _topic_consistency_filter(
        self,
        plan: RetrievalPlan,
        hits: Sequence[RecallHit],
    ) -> tuple[list[RecallHit], list[RetrievalTraceItem]]:
        query_text = " ".join(
            filter(
                None,
                [
                    plan.semantic_query,
                    plan.keyword_query,
                    plan.step_back_query or "",
                    " ".join(plan.rewritten_queries),
                    " ".join(plan.supplemental_queries),
                ],
            )
        )
        query_tokens = self._tokenize(query_text)
        if not query_tokens:
            return list(hits), []

        kept: list[RecallHit] = []
        rejected: list[RetrievalTraceItem] = []
        for hit in hits:
            if bool(hit.metadata.get("expanded_from_parent")) and hit.metadata.get("expanded_from_chunk_id"):
                kept.append(hit)
                continue
            chunk_tokens = self._tokenize(hit.chunk.searchable_text())
            score = self._jaccard(query_tokens, chunk_tokens)
            if score >= self._config.topic_consistency_threshold or hit.chunk.chunk_type in plan.preferred_chunk_types:
                kept.append(hit)
            else:
                rejected.append(self._to_trace_item(hit, rejected_reason="topic_mismatch"))
        return kept or list(hits[: self._config.min_items]), rejected

    def _version_filter(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> tuple[list[RecallHit], list[RetrievalTraceItem]]:
        if plan.retrieval_filters.version:
            allowed = set(plan.retrieval_filters.version)
            kept = [hit for hit in hits if hit.chunk.version in allowed]
            rejected = [self._to_trace_item(hit, rejected_reason="old_version") for hit in hits if hit.chunk.version not in allowed]
            return kept, rejected

        latest_by_document: dict[str, str] = {}
        for hit in hits:
            version = hit.chunk.version or ""
            current = latest_by_document.get(hit.chunk.document_id)
            if current is None or version > current:
                latest_by_document[hit.chunk.document_id] = version

        kept: list[RecallHit] = []
        rejected: list[RetrievalTraceItem] = []
        for hit in hits:
            latest_version = latest_by_document.get(hit.chunk.document_id)
            if not latest_version or (hit.chunk.version or "") == latest_version:
                kept.append(hit)
            else:
                rejected.append(self._to_trace_item(hit, rejected_reason="old_version"))
        return kept, rejected

    def _answer_view_filter(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> tuple[list[RecallHit], list[RetrievalTraceItem]]:
        if not plan.preferred_chunk_types:
            return list(hits), []

        preferred = [hit for hit in hits if hit.chunk.chunk_type in plan.preferred_chunk_types]
        fallback = [hit for hit in hits if hit.chunk.chunk_type not in plan.preferred_chunk_types]
        merged = preferred + fallback
        rejected: list[RetrievalTraceItem] = []
        if fallback and len(preferred) < len(merged):
            for hit in fallback:
                if hit not in merged[: self._config.max_items]:
                    rejected.append(self._to_trace_item(hit, rejected_reason="chunk_type_mismatch"))
        return merged[: self._config.max_items], rejected

    def _to_trace_item(self, hit: RecallHit, rejected_reason: str | None = None) -> RetrievalTraceItem:
        return RetrievalTraceItem.from_hit(hit, rejected_reason=rejected_reason)

    @staticmethod
    def _tokenize(text: str) -> tuple[str, ...]:
        return tuple(token.lower() for token in _TOKEN_PATTERN.findall(text or ""))

    @classmethod
    def _text_similarity(cls, left: str, right: str) -> float:
        return cls._jaccard(cls._tokenize(left), cls._tokenize(right))

    @staticmethod
    def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
        left_set = set(left)
        right_set = set(right)
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / float(len(left_set | right_set) or 1)
