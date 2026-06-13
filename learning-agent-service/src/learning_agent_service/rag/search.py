from __future__ import annotations

from dataclasses import dataclass

from .citation import CitationBuilder
from .evidence import EvidenceGovernanceService
from .models import (
    KnowledgeSearchMatch,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RetrievalFilters,
)
from .protocols import HybridRetriever
from .rewrite import QueryRewriteContext, QueryRewriteService
from .quality_guard import RetrievalQualityGuard
from dataclasses import replace


@dataclass(frozen=True)
class KnowledgeSearchConfig:
    runtime_mode: str = "snapshot"


class KnowledgeSearchFacade:
    def __init__(
        self,
        *,
        rewrite_service: QueryRewriteService,
        retriever: HybridRetriever,
        evidence_service: EvidenceGovernanceService,
        citation_builder: CitationBuilder,
        quality_guard: RetrievalQualityGuard | None = None,
        config: KnowledgeSearchConfig | None = None,
    ) -> None:
        self._rewrite = rewrite_service
        self._retriever = retriever
        self._evidence = evidence_service
        self._citation_builder = citation_builder
        self._quality_guard = quality_guard
        self._config = config or KnowledgeSearchConfig()

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        filters = self._filters_from_request(request)
        plan = self._rewrite.build_plan(
            QueryRewriteContext(
                raw_query=request.query,
                filters=filters,
                extra=dict(request.query_context),
            )
        )
        recall = self._retriever.retrieve(plan)
        evidence = self._evidence.evaluate(plan, recall.hits, trace=recall.debug_trace)
        
        if self._quality_guard:
            query_context = dict(request.query_context) if request.query_context else {}
            has_tool_evidence = bool(query_context.get("has_tool_evidence") or query_context.get("tool_evidence"))
            context_slots = query_context.get("slots") or query_context
            
            quality_result = self._quality_guard.check(
                evidence_pack=evidence,
                plan=plan,
                has_tool_evidence=has_tool_evidence,
                context_slots=context_slots,
            )
            evidence = replace(
                evidence,
                metrics={
                    **dict(evidence.metrics),
                    "quality_verdict": quality_result.verdict.value,
                    "quality_confidence": quality_result.confidence,
                    "quality_reason": quality_result.reason,
                    "quality_is_realtime_risk": quality_result.is_realtime_risk,
                }
            )

        citations = self._citation_builder.build(evidence)
        citation_map = {citation.chunk_id: citation for citation in citations}
        matches = tuple(
            KnowledgeSearchMatch(
                chunk=item.chunk,
                score=item.score,
                citation=citation_map.get(item.chunk.chunk_id),
                metadata={
                    "routes": tuple(item.routes),
                    "reasons": tuple(item.reasons),
                    **dict(item.metadata),
                },
            )
            for item in evidence.items[: max(request.limit, 0)]
        )
        metrics = dict(recall.metrics)
        metrics["evidence_used_count"] = len(evidence.items)
        return KnowledgeSearchResult(
            query=request.query,
            retrieval_strategy=self._retrieval_strategy(recall.retrieval_strategy),
            runtime_mode=self._config.runtime_mode,
            plan=plan,
            recall=recall,
            evidence=evidence,
            citations=tuple(citations),
            matches=matches,
            metrics=metrics,
            extra={
                "retrieval_debug": recall.debug_trace.to_dict() if recall.debug_trace is not None else None,
                "evidence_debug": evidence.debug_trace.to_dict() if evidence.debug_trace is not None else None,
                "rejected_items": [item.to_dict() for item in evidence.rejected_items],
            },
        )

    @staticmethod
    def _filters_from_request(request: KnowledgeSearchRequest) -> RetrievalFilters:
        if not request.category:
            return RetrievalFilters()
        return RetrievalFilters(category=(request.category,))

    @staticmethod
    def _retrieval_strategy(strategy: str) -> str:
        if strategy.endswith("->evidence"):
            return strategy
        return strategy + "->evidence"
