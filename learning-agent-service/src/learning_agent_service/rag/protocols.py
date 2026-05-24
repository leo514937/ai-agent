from __future__ import annotations

from typing import Iterable, Protocol, Sequence

from .models import (
    HybridRecallResult,
    KnowledgeChunk,
    KnowledgeGovernanceDecision,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RecallHit,
    ReferenceResolution,
    ReferenceResolutionRequest,
    RetrievalPlan,
)


class DenseRetriever(Protocol):
    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        ...


class SparseRetriever(Protocol):
    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        ...


class MetadataRetriever(Protocol):
    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        ...


class Reranker(Protocol):
    def rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> Sequence[RecallHit]:
        ...


class HybridRetriever(Protocol):
    def retrieve(self, plan: RetrievalPlan) -> HybridRecallResult:
        ...


class ReferenceResolver(Protocol):
    def resolve(self, request: ReferenceResolutionRequest) -> ReferenceResolution:
        ...


class KnowledgeSearcher(Protocol):
    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        ...


class KnowledgeRepository(Protocol):
    def upsert_chunks(self, chunks: Iterable[KnowledgeChunk]) -> None:
        ...

    def mark_document_version(self, document_id: str, version: str, active: bool) -> None:
        ...


class KnowledgeGovernanceStore(Protocol):
    def apply(self, decision: KnowledgeGovernanceDecision) -> None:
        ...
