from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .citation import CitationBuilder
from .evidence import EvidenceGovernanceService
from .models import (
    Citation,
    EvidencePack,
    KnowledgeSearchMatch,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RetrievalFilters,
)
from .protocols import HybridRetriever
from .rewrite import QueryRewriteContext, QueryRewriteService


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
        config: Optional[KnowledgeSearchConfig] = None,
    ) -> None:
        self._rewrite = rewrite_service
        self._retriever = retriever
        self._evidence = evidence_service
        self._citation_builder = citation_builder
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
