from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence, Tuple

from learning_agent_service.config import Settings
from learning_agent_service.domain import (
    Citation,
    CitationBuildRequest,
    EvidenceEvaluationRequest,
    EvidencePack,
    HybridRecallResult,
    HybridRetrieveRequest,
    QueryRewriteRequest,
    ReferenceResolutionRequest,
    ReferenceResolutionResult,
    RetrievalPlan,
)

from .citation import CitationBuilder
from .defaults import DEFAULT_KNOWLEDGE_CHUNKS
from .domain_adapter import DomainRagAdapter
from .evidence import EvidenceGovernanceService
from .governance import GovernanceConfig, KnowledgeGovernanceService
from .retrieval import HeuristicDenseRetriever, HeuristicMetadataRetriever, HeuristicReranker, HybridRetrieverService, LocalBM25SparseRetriever, ParentChildResolver, ReciprocalRankFusion
from .models import KnowledgeChunk, KnowledgeGovernanceDecision, RetrievalTrace, latest_version
from .protocols import DenseRetriever, HybridRetriever, MetadataRetriever, Reranker, SparseRetriever
from .reference import ReferenceResolver
from .rewrite import QueryRewriteService
from .search import KnowledgeSearchConfig, KnowledgeSearchFacade


class HybridRAGOrchestrator:
    """Thin typed facade over the concrete RAG capabilities."""

    def __init__(
        self,
        settings: Settings,
        *,
        knowledge_chunks: Optional[Iterable[KnowledgeChunk]] = None,
        dense_retriever: Optional[DenseRetriever] = None,
        sparse_retriever: Optional[SparseRetriever] = None,
        metadata_retriever: Optional[MetadataRetriever] = None,
        reranker: Optional[Reranker] = None,
        hybrid_retriever: Optional[HybridRetriever] = None,
        evidence_service: Optional[EvidenceGovernanceService] = None,
        citation_builder: Optional[CitationBuilder] = None,
        governance_service: Optional[KnowledgeGovernanceService] = None,
        reference_resolver: Optional[ReferenceResolver] = None,
        parent_child_resolver: Optional[ParentChildResolver] = None,
        rewrite_service: Optional[QueryRewriteService] = None,
        runtime_mode: str = "snapshot",
    ) -> None:
        self.settings = settings
        self.runtime_mode = runtime_mode
        self._adapter = DomainRagAdapter()
        self._policy = settings.policy_settings()
        initial_chunks = tuple(knowledge_chunks or DEFAULT_KNOWLEDGE_CHUNKS)
        self._parent_child_resolver = parent_child_resolver or ParentChildResolver(initial_chunks)
        self._rewrite = rewrite_service or QueryRewriteService(
            self._policy.query_rewrite
        )
        self._governance = governance_service or KnowledgeGovernanceService(GovernanceConfig())

        self._chunks = self._governance.deduplicate_chunks(initial_chunks)

        self._dense_retriever = dense_retriever or HeuristicDenseRetriever(self._chunks, self._parent_child_resolver)
        self._sparse_retriever = sparse_retriever or LocalBM25SparseRetriever(
            self._chunks,
            self._parent_child_resolver,
            enabled=settings.enable_bm25_sparse_retrieval,
            k1=settings.bm25_k1,
            b=settings.bm25_b,
        )
        self._metadata_retriever = metadata_retriever or HeuristicMetadataRetriever(self._chunks, self._parent_child_resolver)
        self._reranker = reranker or HeuristicReranker()
        self._retriever = hybrid_retriever or HybridRetrieverService(
            dense_retriever=self._dense_retriever,
            sparse_retriever=self._sparse_retriever,
            metadata_retriever=self._metadata_retriever,
            reranker=self._reranker,
            config=self._policy.hybrid_retriever,
            fusion=ReciprocalRankFusion(self._policy.rrf),
            parent_child_resolver=self._parent_child_resolver,
            rewrite_service=self._rewrite,
            llm_rewrite_enabled=self._policy.query_rewrite.llm_enabled,
            llm_rewrite_retry_limit=self._policy.query_rewrite.llm_retry_limit,
            hyde_enabled=self._policy.query_rewrite.hyde_enabled,
        )
        self._evidence = evidence_service or EvidenceGovernanceService(
            self._policy.evidence_governance
        )
        self._citation_builder = citation_builder or CitationBuilder()
        self._reference_resolver = reference_resolver or ReferenceResolver()
        self._search = KnowledgeSearchFacade(
            rewrite_service=self._rewrite,
            retriever=self._retriever,
            evidence_service=self._evidence,
            citation_builder=self._citation_builder,
            config=KnowledgeSearchConfig(runtime_mode=runtime_mode),
        )

    @property
    def knowledge_chunks(self) -> Tuple[KnowledgeChunk, ...]:
        return self._chunks

    def resolve_reference(self, request: ReferenceResolutionRequest) -> ReferenceResolutionResult:
        internal_request = self._adapter.build_reference_request(request)
        return self._adapter.to_domain_reference(self._reference_resolver.resolve(internal_request))

    def rewrite_query(self, request: QueryRewriteRequest) -> RetrievalPlan:
        context = self._adapter.build_query_rewrite_context(request)
        return self._adapter.to_domain_plan(self._rewrite.build_plan(context))

    def warmup_raw_query_embedding(self, raw_query: str) -> dict[str, Any]:
        dense = getattr(self, "_dense_retriever", None)
        if dense is None or not hasattr(dense, "warmup_embedding"):
            return {"cache_hit": False, "skipped": True}
        try:
            return dict(dense.warmup_embedding(raw_query))
        except Exception:
            return {"cache_hit": False, "failed": True}

    def hybrid_retrieve(self, request: HybridRetrieveRequest) -> HybridRecallResult:
        internal_plan = self._adapter.to_internal_plan(
            request,
            dense_top_k=self._policy.hybrid_retriever.dense_top_k,
            sparse_top_k=self._policy.hybrid_retriever.sparse_top_k,
            metadata_top_k=self._policy.hybrid_retriever.metadata_top_k,
            rerank_top_k=self._policy.hybrid_retriever.rerank_top_k,
            max_evidence=self._policy.evidence_governance.max_items,
        )
        return self._adapter.to_domain_hybrid(self._retriever.retrieve(internal_plan))

    def evaluate_evidence(self, request: EvidenceEvaluationRequest) -> EvidencePack:
        internal_plan = self._adapter.to_internal_plan(
            request,
            dense_top_k=self._policy.hybrid_retriever.dense_top_k,
            sparse_top_k=self._policy.hybrid_retriever.sparse_top_k,
            metadata_top_k=self._policy.hybrid_retriever.metadata_top_k,
            rerank_top_k=self._policy.hybrid_retriever.rerank_top_k,
            max_evidence=self._policy.evidence_governance.max_items,
        )
        internal_hits = self._adapter.to_internal_hits(request.hybrid_recall.reranked_hits)
        if not internal_hits:
            internal_hits = tuple(self._retriever.retrieve(internal_plan).hits)
        evidence_trace = _trace_from_payload(request.hybrid_recall.extra.get("retrieval_debug"))
        evidence = self._evidence.evaluate(internal_plan, internal_hits, trace=evidence_trace)
        return self._adapter.to_domain_evidence_pack(evidence, request.plan)

    def build_citations(self, request: CitationBuildRequest) -> Iterable[Citation]:
        internal_pack = self._adapter.to_internal_evidence_pack(request)
        return [self._adapter.to_domain_citation(item) for item in self._citation_builder.build(internal_pack)]

    def deduplicate_chunks(self, chunks: Iterable[KnowledgeChunk]) -> Tuple[KnowledgeChunk, ...]:
        return self._governance.deduplicate_chunks(tuple(chunks))

    def plan_duplicate_cleanup(
        self,
        document_id: str,
        chunks: Optional[Sequence[KnowledgeChunk]] = None,
    ) -> KnowledgeGovernanceDecision:
        candidate_chunks = tuple(chunks) if chunks is not None else self.active_chunks(document_id=document_id)
        return self._governance.plan_duplicate_cleanup(document_id=document_id, chunks=candidate_chunks)

    def plan_version_switch(
        self,
        document_id: str,
        target_version: str,
        reason: str = "activate newer version",
    ) -> KnowledgeGovernanceDecision:
        return self._governance.plan_version_switch(document_id=document_id, target_version=target_version, reason=reason)

    def plan_rebuild(self, document_id: str, reason: str = "rebuild requested") -> KnowledgeGovernanceDecision:
        return self._governance.plan_rebuild(document_id=document_id, reason=reason)

    def plan_rollback(
        self,
        document_id: str,
        target_version: str,
        reason: str = "rollback to previous active version",
    ) -> KnowledgeGovernanceDecision:
        return self._governance.plan_rollback(document_id=document_id, target_version=target_version, reason=reason)

    def active_chunks(
        self,
        *,
        document_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Tuple[KnowledgeChunk, ...]:
        chunks = tuple(chunk for chunk in self._chunks if document_id is None or chunk.document_id == document_id)
        if not chunks:
            return ()
        target_version = version or latest_version(chunks)
        if target_version is None:
            return chunks
        return tuple(chunk for chunk in chunks if chunk.version == target_version)


__all__ = [
    "DEFAULT_KNOWLEDGE_CHUNKS",
    "HybridRAGOrchestrator",
]


def _trace_from_payload(payload: object) -> RetrievalTrace | None:
    if not isinstance(payload, dict):
        return None
    try:
        return RetrievalTrace(
            raw_query=str(payload.get("raw_query") or ""),
            semantic_query=str(payload.get("semantic_query") or ""),
            keyword_query=str(payload.get("keyword_query") or ""),
            retrieval_filters=DomainRagAdapter().to_internal_filters(payload.get("retrieval_filters", {})),
            final_retrieval_filters=dict(payload.get("final_retrieval_filters", {})),
            preferred_chunk_types=tuple(payload.get("preferred_chunk_types", [])),
            metrics=dict(payload.get("metrics", {})),
            extra=dict(payload.get("extra", {})),
        )
    except Exception:
        return None
