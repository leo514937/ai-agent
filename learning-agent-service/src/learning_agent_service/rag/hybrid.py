from __future__ import annotations

from dataclasses import dataclass

from .retrieval import (
    CrossEncoderReranker,
    HeuristicDenseRetriever,
    HeuristicMetadataRetriever,
    HeuristicReranker,
    HeuristicSparseRetriever,
    HybridRetrieverService,
    InMemoryTokenRetriever,
    LocalBM25SparseRetriever,
    ParentChildResolver,
    QdrantOnlineDenseRetriever,
    QdrantOnlineSparseRetriever,
    ReciprocalRankFusion,
    RemoteReranker,
    RRFConfig,
)


@dataclass(frozen=True)
class HybridRetrieverConfig:
    dense_top_k: int = 10
    sparse_top_k: int = 8
    metadata_top_k: int = 8
    fusion_top_k: int = 15
    rrf_k: int = 60
    rerank_top_k: int = 8
    metadata_filter_confidence_threshold: float = 0.5


InMemoryReranker = HeuristicReranker


__all__ = [
    "HeuristicDenseRetriever",
    "HeuristicMetadataRetriever",
    "HeuristicReranker",
    "HeuristicSparseRetriever",
    "CrossEncoderReranker",
    "HybridRetrieverConfig",
    "HybridRetrieverService",
    "InMemoryReranker",
    "InMemoryTokenRetriever",
    "LocalBM25SparseRetriever",
    "ParentChildResolver",
    "QdrantOnlineDenseRetriever",
    "QdrantOnlineSparseRetriever",
    "RRFConfig",
    "ReciprocalRankFusion",
    "RemoteReranker",
]
