from __future__ import annotations

import statistics
import time
from dataclasses import replace
from types import SimpleNamespace

from learning_agent_service.rag.models import KnowledgeChunk, RecallHit, RetrievalPlan
from learning_agent_service.rag.retrieval import (
    HybridRetrieverService,
    ParentChildResolver,
    ReciprocalRankFusion,
)


class _SleepRetriever:
    def __init__(self, route_name: str, delay_seconds: float, hit: RecallHit):
        self.route_name = route_name
        self._delay_seconds = delay_seconds
        self._hit = hit

    def retrieve(self, plan):  # noqa: ANN001
        time.sleep(self._delay_seconds)
        return (self._hit,)


def _chunk(chunk_id: str, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        text=text,
        title=text[:16],
        summary=text[:32],
        chunk_type="concept",
        version="v1",
        tags=("perf",),
    )


def _hit(chunk: KnowledgeChunk, route: str, score: float) -> RecallHit:
    return RecallHit(
        chunk=chunk,
        score=score,
        route=route,
        rank=1,
        route_scores={route: score},
        matched_routes=(route,),
    )


def _serial_retrieve(service: HybridRetrieverService, plan: RetrievalPlan) -> float:
    started_at = time.perf_counter()
    dense_hits, _dense_stats = service._collect_route_hits_for_route("dense", service._dense_retriever, plan)  # noqa: SLF001
    sparse_hits, _sparse_stats = service._collect_route_hits_for_route("sparse", service._sparse_retriever, plan)  # noqa: SLF001
    metadata_hits, _metadata_stats = service._collect_route_hits_for_route("metadata", service._metadata_retriever, plan)  # noqa: SLF001
    route_hits = {"dense": dense_hits, "sparse": sparse_hits, "metadata": metadata_hits}
    fused = service._limit_fused_hits(service._fusion.fuse(route_hits))  # noqa: SLF001
    _ = service._rerank(plan, fused)  # noqa: SLF001
    return (time.perf_counter() - started_at) * 1000.0


def _parallel_retrieve(service: HybridRetrieverService, plan: RetrievalPlan) -> float:
    started_at = time.perf_counter()
    _ = service.retrieve(plan)
    return (time.perf_counter() - started_at) * 1000.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * p))))
    return ordered[index]


def test_parallel_retrieval_p95_better_than_serial_baseline() -> None:
    rag_chunk = _chunk("rag-1", "RAG retrieves evidence and grounds answers.")
    dense = _SleepRetriever("dense", 0.12, _hit(rag_chunk, "dense", 0.92))
    sparse = _SleepRetriever("sparse", 0.12, _hit(rag_chunk, "sparse", 0.88))
    metadata = _SleepRetriever("metadata", 0.12, _hit(rag_chunk, "metadata", 0.81))
    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=8, fusion_top_k=15),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag_chunk,)),
    )
    plan = RetrievalPlan(
        semantic_query="RAG 检索",
        keyword_query="RAG 检索",
        dense_top_k=10,
        sparse_top_k=8,
        metadata_top_k=8,
        rerank_top_k=8,
        extra={"raw_query": "RAG 检索"},
    )

    serial_ms: list[float] = []
    parallel_ms: list[float] = []
    for _ in range(8):
        serial_ms.append(_serial_retrieve(service, replace(plan)))
        parallel_ms.append(_parallel_retrieve(service, replace(plan)))

    serial_p50 = statistics.median(serial_ms)
    parallel_p50 = statistics.median(parallel_ms)
    serial_p95 = _percentile(serial_ms, 0.95)
    parallel_p95 = _percentile(parallel_ms, 0.95)

    print(
        "perf_compare serial_p50_ms={:.1f} serial_p95_ms={:.1f} parallel_p50_ms={:.1f} parallel_p95_ms={:.1f}".format(
            serial_p50,
            serial_p95,
            parallel_p50,
            parallel_p95,
        )
    )

    assert parallel_p50 < serial_p50
    assert parallel_p95 < serial_p95
