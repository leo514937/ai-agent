from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import pytest

from learning_agent_service.rag.defaults import DEFAULT_KNOWLEDGE_CHUNKS
from learning_agent_service.rag.models import KnowledgeChunk, RetrievalPlan
from learning_agent_service.rag.retrieval import (
    HeuristicDenseRetriever,
    HeuristicMetadataRetriever,
    HeuristicReranker,
    LocalBM25SparseRetriever,
    HybridRetrieverService,
    ReciprocalRankFusion,
)


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    expected_chunk_ids: tuple[str, ...] = ()


def build_eval_service(chunks: Iterable[KnowledgeChunk]) -> HybridRetrieverService:
    chunks = tuple(chunks)
    return HybridRetrieverService(
        dense_retriever=HeuristicDenseRetriever(chunks),
        sparse_retriever=LocalBM25SparseRetriever(chunks),
        metadata_retriever=HeuristicMetadataRetriever(chunks),
        reranker=HeuristicReranker(),
        fusion=ReciprocalRankFusion(),
    )


def evaluate_retrieval_suite(
    service: HybridRetrieverService,
    cases: Sequence[RetrievalEvalCase],
    *,
    k: int = 3,
) -> dict[str, float | int]:
    recall_scores: list[float] = []
    mrr_scores: list[float] = []
    ndcg_scores: list[float] = []
    empty_count = 0
    degraded_count = 0

    for case in cases:
        result = service.retrieve(
            RetrievalPlan(
                semantic_query=case.query,
                keyword_query=case.query,
                extra={"raw_query": case.query},
            )
        )
        top_k = tuple(hit.chunk.chunk_id for hit in result.hits[:k])

        if not top_k:
            empty_count += 1
        if result.debug_trace is not None and result.debug_trace.degraded:
            degraded_count += 1

        if case.expected_chunk_ids:
            recall_scores.append(1.0 if any(chunk_id in top_k for chunk_id in case.expected_chunk_ids) else 0.0)
            mrr_scores.append(_mrr_at_k(top_k, case.expected_chunk_ids))
            ndcg_scores.append(_ndcg_at_k(top_k, case.expected_chunk_ids))

    expected_case_count = max(len([case for case in cases if case.expected_chunk_ids]), 1)
    total_case_count = max(len(cases), 1)
    return {
        "recall_at_k": sum(recall_scores) / expected_case_count,
        "mrr_at_k": sum(mrr_scores) / expected_case_count,
        "ndcg_at_k": sum(ndcg_scores) / expected_case_count,
        "empty_rate": empty_count / total_case_count,
        "degraded_rate": degraded_count / total_case_count,
        "case_count": len(cases),
        "expected_case_count": len([case for case in cases if case.expected_chunk_ids]),
    }


def _mrr_at_k(top_k: Sequence[str], expected_chunk_ids: Sequence[str]) -> float:
    for index, chunk_id in enumerate(top_k, start=1):
        if chunk_id in expected_chunk_ids:
            return 1.0 / float(index)
    return 0.0


def _ndcg_at_k(top_k: Sequence[str], expected_chunk_ids: Sequence[str]) -> float:
    dcg = 0.0
    for index, chunk_id in enumerate(top_k, start=1):
        if chunk_id in expected_chunk_ids:
            dcg += 1.0 / math.log2(index + 1)
    ideal_hits = min(len(expected_chunk_ids), len(top_k))
    if ideal_hits <= 0:
        return 0.0
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def test_retrieval_eval_reports_metrics_on_default_chunks() -> None:
    service = build_eval_service(DEFAULT_KNOWLEDGE_CHUNKS)
    cases = (
        RetrievalEvalCase("RAG是什么", ("rag-concept",)),
        RetrievalEvalCase("Spring AOP vs 动态代理", ("spring-aop-compare",)),
        RetrievalEvalCase("ThreadPoolExecutor 的核心参数有哪些", ("java-threadpool-concept",)),
        RetrievalEvalCase("ReAct 和 CoT 区别", ("react-cot-compare",)),
        RetrievalEvalCase("ZXCVBNM 12345"),
    )

    metrics = evaluate_retrieval_suite(service, cases, k=3)

    assert metrics["case_count"] == 5
    assert metrics["expected_case_count"] == 4
    assert metrics["recall_at_k"] >= 0.9
    assert metrics["mrr_at_k"] >= 0.9
    assert metrics["ndcg_at_k"] >= 0.9
    assert metrics["empty_rate"] == pytest.approx(0.2, abs=1e-6)
    assert metrics["degraded_rate"] == pytest.approx(0.2, abs=1e-6)
