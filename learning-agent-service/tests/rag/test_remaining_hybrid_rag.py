from __future__ import annotations

from types import SimpleNamespace

from learning_agent_service.config import Settings
from learning_agent_service.rag.defaults import DEFAULT_KNOWLEDGE_CHUNKS
from learning_agent_service.rag.models import KnowledgeChunk, RecallHit, RetrievalPlan
from learning_agent_service.rag.retrieval import HybridRetrieverService, ParentChildResolver, ReciprocalRankFusion
from learning_agent_service.rag.service import HybridRAGOrchestrator
from learning_agent_service.rag.retrieval import (
    HeuristicDenseRetriever,
    HeuristicMetadataRetriever,
    HeuristicSparseRetriever,
    LocalBM25SparseRetriever,
    QdrantOnlineSparseRetriever,
    RemoteReranker,
)
from unittest.mock import patch


class FixedRetriever:
    def __init__(self, hits):
        self._hits = tuple(hits)

    def retrieve(self, plan):  # noqa: ANN001
        return self._hits


def _chunk(
    chunk_id: str,
    *,
    text: str,
    document_id: str = "doc-1",
    title: str = "title",
    version: str = "v1",
    chunk_type: str = "concept",
    parent_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title=title,
        summary=text[:32],
        chunk_type=chunk_type,
        version=version,
        parent_id=parent_id,
        tags=("rag",),
        metadata=metadata or {},
    )


def _hit(chunk: KnowledgeChunk, *, route: str = "sparse", score: float = 0.42, rank: int = 1) -> RecallHit:
    return RecallHit(
        chunk=chunk,
        score=score,
        route=route,
        rank=rank,
        route_scores={route: score},
        matched_routes=(route,),
    )


def test_local_bm25_sparse_retriever_prefers_term_frequency() -> None:
    strong = _chunk("strong", text="RAG retrieval retrieval retrieval uses evidence.")
    weak = _chunk("weak", text="RAG answers use evidence.")
    retriever = LocalBM25SparseRetriever((strong, weak))

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG retrieval"},
        )
    )

    assert hits
    assert hits[0].chunk.chunk_id == "strong"
    assert hits[0].score >= hits[-1].score
    assert hits[0].metadata.get("retrieval_type") == "sparse_bm25"
    assert hits[0].metadata.get("source") == "local_bm25"


def test_hybrid_rag_orchestrator_defaults_sparse_to_bm25() -> None:
    chunk = _chunk("bm25-default", text="BM25 keyword retrieval should rank this chunk first.")
    orchestrator = HybridRAGOrchestrator(Settings(), knowledge_chunks=(chunk,))

    assert isinstance(orchestrator._sparse_retriever, LocalBM25SparseRetriever)


def test_hybrid_service_records_latency_and_final_filters() -> None:
    allowed = _chunk(
        "allowed",
        text="RAG retrieval uses evidence and grounding.",
        metadata={
            "tenant_id": "tenant-a",
            "permission_tags": ["reader"],
            "is_active": True,
        },
    )
    service = HybridRetrieverService(
        dense_retriever=HeuristicSparseRetriever((allowed,)),  # intentionally shared heuristic path
        sparse_retriever=LocalBM25SparseRetriever((allowed,)),
        metadata_retriever=HeuristicSparseRetriever((allowed,)),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((allowed,)),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={
                "raw_query": "RAG retrieval",
                "tenant_id": "tenant-a",
                "permission_tags": ["reader"],
                "is_active": True,
            },
        )
    )

    assert result.debug_trace is not None
    metrics = result.debug_trace.metrics
    assert metrics["dense_latency_ms"] >= 0.0
    assert metrics["sparse_latency_ms"] >= 0.0
    assert metrics["metadata_latency_ms"] >= 0.0
    assert metrics["rrf_latency_ms"] >= 0.0
    assert metrics["degraded_rate"] == 0.0
    assert result.debug_trace.final_retrieval_filters["extra"]["tenant_id"] == "tenant-a"
    assert result.debug_trace.final_retrieval_filters["extra"]["permission_tags"] == ["reader"]


def test_hybrid_service_reports_sparse_fallback_reason_when_bm25_disabled() -> None:
    allowed = _chunk(
        "allowed",
        text="RAG retrieval uses evidence and grounding.",
        metadata={
            "tenant_id": "tenant-a",
            "permission_tags": ["reader"],
            "is_active": True,
        },
    )
    service = HybridRetrieverService(
        dense_retriever=HeuristicDenseRetriever((allowed,)),
        sparse_retriever=LocalBM25SparseRetriever((allowed,), enabled=False),
        metadata_retriever=HeuristicMetadataRetriever((allowed,)),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((allowed,)),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={
                "raw_query": "RAG retrieval",
                "tenant_id": "tenant-a",
                "permission_tags": ["reader"],
                "is_active": True,
            },
        )
    )

    assert result.debug_trace is not None
    assert result.debug_trace.metrics["fallback_reason"]
    assert "bm25_disabled" in str(result.debug_trace.metrics["fallback_reason"])
    assert result.debug_trace.metrics["degraded_rate"] > 0.0


def test_hybrid_service_excludes_permission_mismatched_chunks_from_rrf() -> None:
    allowed = _chunk(
        "allowed",
        text="RAG retrieval uses evidence and grounding.",
        metadata={
            "tenant_id": "tenant-a",
            "permission_tags": ["reader"],
            "is_active": True,
        },
    )
    blocked = _chunk(
        "blocked",
        text="RAG retrieval uses hidden evidence.",
        metadata={
            "tenant_id": "tenant-b",
            "permission_tags": ["admin"],
            "is_active": True,
        },
    )
    service = HybridRetrieverService(
        dense_retriever=HeuristicDenseRetriever((allowed, blocked)),
        sparse_retriever=LocalBM25SparseRetriever((allowed, blocked)),
        metadata_retriever=HeuristicMetadataRetriever((allowed, blocked)),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((allowed, blocked)),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={
                "raw_query": "RAG retrieval",
                "tenant_id": "tenant-a",
                "permission_tags": ["reader"],
                "is_active": True,
            },
        )
    )

    assert result.hits
    assert all(hit.chunk.chunk_id != "blocked" for hit in result.hits)


def test_hybrid_service_combines_bm25_sparse_hits_with_rrf() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    weak = _chunk("weak", text="Spring proxies are different.", title="Weak")

    dense = FixedRetriever((_hit(rag, route="dense", score=0.91, rank=1),))
    sparse = LocalBM25SparseRetriever((rag, weak))
    metadata = FixedRetriever(())

    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag, weak)),
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            preferred_chunk_types=("concept",),
            extra={"raw_query": "RAG"},
        )
    )

    assert result.sparse_hits
    assert any(hit.chunk.chunk_id == "rag-concept" for hit in result.sparse_hits)
    assert result.hits
    assert result.hits[0].chunk.chunk_id == "rag-concept"
    assert "sparse" in result.hits[0].matched_routes


def test_local_bm25_sparse_retriever_can_fallback_to_heuristic_sparse() -> None:
    retriever = LocalBM25SparseRetriever(
        tuple(DEFAULT_KNOWLEDGE_CHUNKS),
        fallback=HeuristicSparseRetriever(DEFAULT_KNOWLEDGE_CHUNKS),
        enabled=False,
    )

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG是什么",
            keyword_query="RAG是什么",
            extra={"raw_query": "RAG是什么"},
        )
    )

    assert hits


def test_remote_reranker_falls_back_when_disabled_or_unconfigured() -> None:
    hit = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    reranker = RemoteReranker(
        endpoint="",
        fallback=None,
        enabled=False,
    )

    reranked = reranker.rerank(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG"},
        ),
        (
            _hit(_chunk("another", text="Another RAG chunk.", title="Another")),
        ),
    )

    assert reranked


def test_remote_reranker_respects_remote_order() -> None:
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "hits": [
                    {"chunk_id": "b", "score": 0.98, "rerank_model": "remote"},
                    {"chunk_id": "a", "score": 0.5, "rerank_model": "remote"},
                ]
            }

    hits = (
        _hit(_chunk("a", text="A chunk"), score=0.3, rank=1),
        _hit(_chunk("b", text="B chunk"), score=0.2, rank=2),
    )
    reranker = RemoteReranker(
        endpoint="https://reranker.example.com",
        fallback=None,
        enabled=True,
        model="cross-encoder",
    )
    with patch("learning_agent_service.rag.retrieval.httpx.post", return_value=FakeResponse()):
        reranked = reranker.rerank(
            RetrievalPlan(
                semantic_query="RAG retrieval",
                keyword_query="RAG retrieval",
                extra={"raw_query": "RAG"},
            ),
            hits,
        )

    assert reranked[0].chunk.chunk_id == "b"
    assert reranked[0].rerank_model == "cross-encoder"
    assert reranked[0].rerank_score == 0.98


def test_remote_reranker_timeout_falls_back_to_heuristic() -> None:
    class TimeoutErrorStub(Exception):
        pass

    hits = (
        _hit(_chunk("a", text="RAG retrieval retrieval."), score=0.3, rank=2),
        _hit(_chunk("b", text="RAG retrieval."), score=0.2, rank=1),
    )
    reranker = RemoteReranker(
        endpoint="https://reranker.example.com",
        fallback=None,
        enabled=True,
        model="cross-encoder",
    )
    with patch("learning_agent_service.rag.retrieval.httpx.post", side_effect=TimeoutErrorStub("timeout")):
        reranked = reranker.rerank(
            RetrievalPlan(
                semantic_query="RAG retrieval",
                keyword_query="RAG retrieval",
                extra={"raw_query": "RAG"},
            ),
            hits,
        )

    assert reranked
    assert reranked[0].chunk.chunk_id == "a" or reranked[0].chunk.chunk_id == "b"
    assert reranked[0].rerank_model == "heuristic"


def test_retrieval_eval_module_exports_default_cases_and_metrics() -> None:
    from learning_agent_service.rag.eval import build_eval_service, build_default_eval_cases, evaluate_retrieval_suite

    service = build_eval_service(DEFAULT_KNOWLEDGE_CHUNKS)
    metrics = evaluate_retrieval_suite(service, build_default_eval_cases(), k=3)

    assert metrics["case_count"] > 0
    assert metrics["expected_case_count"] > 0
    assert metrics["recall_at_k"] >= 0.0
    assert metrics["mrr_at_k"] >= 0.0
    assert metrics["ndcg_at_k"] >= 0.0


def test_backfill_module_plans_missing_parent_child_fields() -> None:
    from learning_agent_service.rag.backfill import plan_knowledge_chunk_backfill

    payload = {
        "chunk_id": "child",
        "document_id": "doc-1",
        "text": "child text",
        "title": "Child",
    }
    plan = plan_knowledge_chunk_backfill(payload)

    assert plan.normalized_payload["chunk_id"] == "child"
    assert plan.normalized_payload["doc_id"] == "doc-1"
    assert plan.needs_backfill is True


def test_qdrant_sparse_retriever_falls_back_when_disabled() -> None:
    fallback = HeuristicSparseRetriever(DEFAULT_KNOWLEDGE_CHUNKS)
    retriever = QdrantOnlineSparseRetriever(
        client=object(),
        collection_name="knowledge_chunks",
        sparse_vector_name="sparse_embedding",
        sparse_query_adapter=None,
        fallback=fallback,
        enabled=False,
    )

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG是什么",
            keyword_query="RAG是什么",
            extra={"raw_query": "RAG是什么"},
        )
    )

    assert hits


def test_qdrant_sparse_retriever_uses_query_adapter_when_enabled() -> None:
    class FakePoint:
        def __init__(self, payload, score):
            self.payload = payload
            self.score = score

    class FakeQdrantClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def query_points(self, **kwargs):  # noqa: ANN001
            self.calls.append(kwargs)
            return {"points": [FakePoint(payload=_chunk("qdrant", text="RAG retrieval").to_payload(), score=0.88)]}

    class FakeSparseAdapter:
        def encode(self, text: str):  # noqa: ANN001
            return {"indices": [1, 2], "values": [1.0, 1.0], "query": text}

    client = FakeQdrantClient()
    retriever = QdrantOnlineSparseRetriever(
        client=client,
        collection_name="knowledge_chunks",
        sparse_vector_name="sparse_embedding",
        sparse_query_adapter=FakeSparseAdapter(),
        fallback=HeuristicSparseRetriever(DEFAULT_KNOWLEDGE_CHUNKS),
        enabled=True,
    )

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG retrieval"},
        )
    )

    assert client.calls
    assert hits[0].chunk.chunk_id == "qdrant"
    assert hits[0].score == 0.88


def test_backfill_job_normalizes_and_upserts_payloads() -> None:
    from learning_agent_service.rag.backfill import execute_knowledge_chunk_backfill

    class FakeQdrantClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def upsert(self, **kwargs):  # noqa: ANN001
            self.calls.append(("upsert", kwargs))
            return {"status": "ok"}

    client = FakeQdrantClient()
    chunks = (
        _chunk("child", text="child text", title="Child"),
        _chunk("parent", text="parent text", title="Parent"),
    )

    result = execute_knowledge_chunk_backfill(
        client=client,
        collection_name="knowledge_chunks",
        chunks=chunks,
        batch_size=1,
    )

    assert result.processed_count == 2
    assert result.updated_count == 2
    assert client.calls
