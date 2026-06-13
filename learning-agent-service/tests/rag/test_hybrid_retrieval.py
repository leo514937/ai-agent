from __future__ import annotations

from dataclasses import replace
import threading
from types import SimpleNamespace

import pytest

from learning_agent_service.rag.evidence import EvidenceGovernanceConfig, EvidenceGovernanceService
from learning_agent_service.rag.hybrid import HybridRetrieverConfig
from learning_agent_service.rag.models import (
    EvidenceItem,
    KnowledgeChunk,
    RecallHit,
    RetrievalFilters,
    RetrievalPlan,
)
from learning_agent_service.rag.retrieval import (
    HeuristicDenseRetriever,
    HeuristicMetadataRetriever,
    HybridRetrieverService,
    ParentChildResolver,
    QdrantOnlineDenseRetriever,
    ReciprocalRankFusion,
)
from learning_agent_service.rag.rewrite import QueryRewriteConfig, QueryRewriteContext, QueryRewriteService
from learning_agent_service.rag.rewrite_guard import QueryRewriteGuard, QueryRewriteGuardConfig


class FixedRetriever:
    def __init__(self, hits):
        self._hits = tuple(hits)

    def retrieve(self, plan):
        return self._hits


class RecordingRetriever:
    def __init__(self, route_name: str, hits):
        self.route_name = route_name
        self._hits = tuple(hits)
        self.calls: list[tuple[str, str, object]] = []

    def retrieve(self, plan):
        self.calls.append((plan.semantic_query, plan.keyword_query, plan.extra.get("query_variant")))
        return self._hits


class ConditionalRetriever:
    def __init__(self, *, match_query: str, hits):
        self.match_query = match_query
        self._hits = tuple(hits)
        self.calls: list[tuple[str, str, object]] = []

    def retrieve(self, plan):
        self.calls.append((plan.semantic_query, plan.keyword_query, plan.extra.get("query_variant")))
        if plan.extra.get("query_variant") == self.match_query or plan.keyword_query == self.match_query:
            return self._hits
        return ()


def _chunk(
    chunk_id: str,
    *,
    text: str,
    document_id: str = "doc-1",
    title: str = "title",
    version: str = "v1",
    chunk_type: str = "concept",
    parent_id: str | None = None,
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
    )


def _hit(chunk: KnowledgeChunk, *, route: str, score: float, rank: int = 1) -> RecallHit:
    return RecallHit(
        chunk=chunk,
        score=score,
        route=route,
        rank=rank,
        route_scores={route: score},
        matched_routes=(route,),
    )


class _ShapeClient:
    def __init__(self, point, *, size: int = 4096, distance: str = "cosine") -> None:
        self.point = point
        self.calls: list[dict[str, object]] = []
        self._info = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={"embedding": SimpleNamespace(size=size, distance=distance)}
                )
            )
        )

    def get_collection(self, collection_name: str):  # noqa: ANN001
        self.calls.append({"get_collection": collection_name})
        return self._info

    def query_points(self, **kwargs):  # noqa: ANN001
        self.calls.append(dict(kwargs))
        return {"points": [self.point]}


def test_query_rewrite_llm_fallback_uses_structured_payload() -> None:
    calls: list[tuple[str, str]] = []

    def fake_llm(context: QueryRewriteContext, base_plan: RetrievalPlan, fallback_reason: str):
        calls.append((context.raw_query, fallback_reason))
        return {
            "semantic_query": "RAG 检索 原理",
            "keyword_query": "RAG 检索",
            "rewritten_queries": ["RAG 检索", "检索 原理"],
            "step_back_query": "什么是RAG",
            "retrieval_filters": {
                "category": ["rag"],
                "chunk_type": ["concept"],
            },
            "filter_confidence": 0.92,
        }

    service = QueryRewriteService(
        QueryRewriteConfig(llm_enabled=True, short_query_max_chars=4, low_confidence_threshold=0.5),
        llm_rewriter=fake_llm,
        rewrite_guard=QueryRewriteGuard(QueryRewriteGuardConfig(min_semantic_similarity=0.0)),
    )
    plan = service.rewrite_with_llm(
        QueryRewriteContext(raw_query="它", intent="explain", intent_confidence=0.12, resolved_topic="RAG"),
        fallback_reason="empty_recall",
    )

    assert calls == [("它", "empty_recall")]
    assert plan.semantic_query == "RAG 检索 原理"
    assert plan.keyword_query == "RAG 检索"
    assert plan.retrieval_filters.category == ("rag",)
    assert plan.preferred_chunk_types == ("concept", "qa", "roadmap")
    assert plan.extra["rewrite_source"] == "llm"
    assert plan.extra["metadata_filter_mode"] == "hard"


def test_hyde_generation_triggers_on_weak_query_and_returns_payload() -> None:
    calls: list[tuple[str, str]] = []

    def fake_hyde(context: QueryRewriteContext, base_plan: RetrievalPlan, trigger_reason: str):
        calls.append((context.raw_query, trigger_reason))
        return {
            "hyde_passage": "RAG retrieves evidence and grounds answers.",
            "hyde_title": "RAG retrieval",
            "hyde_keywords": ["RAG", "retrieval", "evidence"],
        }

    service = QueryRewriteService(
        QueryRewriteConfig(hyde_enabled=True, short_query_max_chars=4, low_confidence_threshold=0.5),
        hyde_rewriter=fake_hyde,
    )
    payload = service.build_hyde_payload(
        QueryRewriteContext(raw_query="它", intent="explain", intent_confidence=0.12, resolved_topic="RAG"),
    )

    assert payload is not None
    assert payload["hyde_passage"] == "RAG retrieves evidence and grounds answers."
    assert payload["hyde_source"] == "llm"
    assert payload["hyde_trigger_reason"]
    assert calls == [("它", payload["hyde_trigger_reason"])]


def test_hyde_generation_skips_when_disabled() -> None:
    calls: list[tuple[str, str]] = []

    def fake_hyde(context: QueryRewriteContext, base_plan: RetrievalPlan, trigger_reason: str):
        calls.append((context.raw_query, trigger_reason))
        return {"hyde_passage": "RAG retrieves evidence and grounds answers."}

    service = QueryRewriteService(
        QueryRewriteConfig(hyde_enabled=False, short_query_max_chars=4, low_confidence_threshold=0.5),
        hyde_rewriter=fake_hyde,
    )

    assert service.build_hyde_payload(
        QueryRewriteContext(raw_query="它", intent="explain", intent_confidence=0.12, resolved_topic="RAG"),
    ) is None
    assert calls == []


def test_hyde_generation_skips_normal_query() -> None:
    calls: list[tuple[str, str]] = []

    def fake_hyde(context: QueryRewriteContext, base_plan: RetrievalPlan, trigger_reason: str):
        calls.append((context.raw_query, trigger_reason))
        return {"hyde_passage": "RAG retrieves evidence and grounds answers."}

    service = QueryRewriteService(
        QueryRewriteConfig(hyde_enabled=True, short_query_max_chars=4, low_confidence_threshold=0.5),
        hyde_rewriter=fake_hyde,
    )

    assert service.build_hyde_payload(
        QueryRewriteContext(raw_query="RAG 检索原理是什么", intent="explain", intent_confidence=0.96, resolved_topic="RAG"),
    ) is None
    assert calls == []


def test_hybrid_service_appends_hyde_only_to_sparse_queries() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    hyde_passage = "RAG retrieves evidence and grounds answers."
    dense = RecordingRetriever("dense", (_hit(rag, route="dense", score=0.91, rank=1),))
    sparse = RecordingRetriever("sparse", (_hit(rag, route="sparse", score=0.82, rank=1),))
    metadata = RecordingRetriever("metadata", (_hit(rag, route="metadata", score=0.7, rank=1),))

    def fake_hyde(context: QueryRewriteContext, base_plan: RetrievalPlan, trigger_reason: str):
        return {"hyde_passage": hyde_passage, "hyde_title": "RAG retrieval"}

    rewrite_service = QueryRewriteService(
        QueryRewriteConfig(hyde_enabled=True, short_query_max_chars=4, low_confidence_threshold=0.5),
        hyde_rewriter=fake_hyde,
    )
    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
        rewrite_service=rewrite_service,
        hyde_enabled=True,
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={
                "raw_query": "它",
                "intent": "explain",
                "intent_confidence": 0.12,
                "resolved_topic": "RAG",
            },
        )
    )

    assert result.hits
    assert any(call[1] == hyde_passage for call in sparse.calls)
    assert not any(call[2] == hyde_passage for call in dense.calls)
    assert result.debug_trace is not None
    assert result.debug_trace.metrics["hyde_applied"] is True
    assert result.debug_trace.metrics["hyde_trigger_reason"]


def test_hybrid_service_retries_with_hyde_after_empty_recall() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    hyde_passage = "RAG retrieves evidence and grounds answers."
    dense = FixedRetriever(())
    metadata = FixedRetriever(())
    sparse = ConditionalRetriever(match_query=hyde_passage, hits=(_hit(rag, route="sparse", score=0.82, rank=1),))

    def fake_hyde(context: QueryRewriteContext, base_plan: RetrievalPlan, trigger_reason: str):
        return {"hyde_passage": hyde_passage, "hyde_title": "RAG retrieval"}

    rewrite_service = QueryRewriteService(
        QueryRewriteConfig(hyde_enabled=True, short_query_max_chars=4, low_confidence_threshold=0.5),
        hyde_rewriter=fake_hyde,
    )
    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
        rewrite_service=rewrite_service,
        hyde_enabled=True,
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval principle",
            keyword_query="RAG retrieval principle",
            extra={
                "raw_query": "RAG retrieval principle",
                "intent": "explain",
                "intent_confidence": 0.96,
            },
        )
    )

    assert result.hits
    assert result.debug_trace is not None
    assert result.debug_trace.metrics["hyde_applied"] is True
    assert result.debug_trace.metrics["retrieval_hit_count"] == len(result.hits)
    assert any(call[1] == hyde_passage for call in sparse.calls)


def test_hybrid_service_falls_back_when_hyde_payload_invalid() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    dense = RecordingRetriever("dense", (_hit(rag, route="dense", score=0.91, rank=1),))
    sparse = RecordingRetriever("sparse", (_hit(rag, route="sparse", score=0.82, rank=1),))
    metadata = RecordingRetriever("metadata", (_hit(rag, route="metadata", score=0.7, rank=1),))

    def fake_hyde(context: QueryRewriteContext, base_plan: RetrievalPlan, trigger_reason: str):
        return {}

    rewrite_service = QueryRewriteService(
        QueryRewriteConfig(hyde_enabled=True, short_query_max_chars=4, low_confidence_threshold=0.5),
        hyde_rewriter=fake_hyde,
    )
    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
        rewrite_service=rewrite_service,
        hyde_enabled=True,
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={
                "raw_query": "它",
                "intent": "explain",
                "intent_confidence": 0.12,
                "resolved_topic": "RAG",
            },
        )
    )

    assert result.hits
    assert result.debug_trace is not None
    assert result.debug_trace.metrics["hyde_applied"] is False
    assert not any(call[1] == "RAG retrieves evidence and grounds answers." for call in sparse.calls)


def test_hybrid_service_records_rrf_and_rerank_trace() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    aop = _chunk("spring-aop", text="Spring AOP uses proxies.", title="Spring AOP", document_id="spring-aop")

    dense = FixedRetriever((_hit(rag, route="dense", score=0.91, rank=1), _hit(aop, route="dense", score=0.25, rank=2)))
    sparse = FixedRetriever((_hit(rag, route="sparse", score=0.82, rank=1),))
    metadata = FixedRetriever((_hit(rag, route="metadata", score=0.7, rank=1),))

    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag, aop)),
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            preferred_chunk_types=("concept",),
            extra={"raw_query": "RAG"},
        )
    )

    assert result.hits
    assert result.hits[0].rrf_score > 0
    assert result.hits[0].rerank_score is not None
    assert result.fused_hits[0].matched_routes
    assert result.debug_trace is not None
    assert result.debug_trace.reranked_hits
    assert result.debug_trace.metrics["retrieval_hit_count"] == len(result.hits)
    assert result.debug_trace.metrics["policy_snapshot"]["rerank_top_k"] == 2
    assert result.debug_trace.extra["policy_snapshot"]["rerank_top_k"] == 2


def test_multi_query_variants_participate_in_retrieval() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    dense = RecordingRetriever("dense", (_hit(rag, route="dense", score=0.91, rank=1),))
    sparse = RecordingRetriever("sparse", (_hit(rag, route="sparse", score=0.82, rank=1),))
    metadata = RecordingRetriever("metadata", (_hit(rag, route="metadata", score=0.7, rank=1),))

    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        metadata_retriever=metadata,
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            step_back_query="什么是RAG",
            rewritten_queries=("RAG 检索", "检索 原理"),
            supplemental_queries=("RAG 检索",),
            extra={"raw_query": "RAG"},
        )
    )

    assert result.hits
    assert any(call[0] == "什么是RAG" for call in dense.calls)
    assert any(call[0] == "RAG 检索" for call in dense.calls)
    assert any(call[1] == "什么是RAG" for call in sparse.calls)
    assert any(call[1] == "检索 原理" for call in sparse.calls)


def test_metadata_soft_filter_does_not_mis_kill_related_chunk() -> None:
    chunk = _chunk("rag-concept", text="RAG retrieval uses evidence and grounding.", title="RAG")
    retriever = HeuristicMetadataRetriever((chunk,))

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            retrieval_filters=RetrievalFilters(category=("java",)),
            metadata_filter_mode="soft",
            extra={"raw_query": "RAG"},
        )
    )

    assert hits
    assert hits[0].chunk.chunk_id == "rag-concept"
    assert hits[0].score > 0


def test_qdrant_dense_fallback_when_adapter_missing() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    fallback = HeuristicDenseRetriever((rag,))
    retriever = QdrantOnlineDenseRetriever(
        client=object(),
        collection_name="knowledge_chunks",
        vector_name="embedding",
        embedding_adapter=None,
        fallback=fallback,
        enabled=True,
    )

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG"},
        )
    )

    assert hits
    assert hits[0].chunk.chunk_id == "rag-concept"


def test_qdrant_dense_retriever_records_provenance_and_validates_shape() -> None:
    point = SimpleNamespace(payload=_chunk("qdrant", text="RAG retrieves evidence and grounds answers.").to_payload(), score=0.88)
    client = _ShapeClient(point)
    retriever = QdrantOnlineDenseRetriever(
        client=client,
        collection_name="local_life_hybrid_chunks",
        vector_name="embedding",
        embedding_adapter=SimpleNamespace(embed=lambda text: [0.1, 0.2, 0.3]),
        fallback=HeuristicDenseRetriever((_chunk("fallback", text="fallback"),)),
        enabled=True,
        vector_size=4096,
        distance="cosine",
    )

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG"},
        )
    )

    assert client.calls
    assert hits
    assert hits[0].retrieval_kind == "dense_qdrant"
    assert hits[0].collection_name == "local_life_hybrid_chunks"
    assert hits[0].source_domain == "local_life_hybrid"


def test_qdrant_dense_retriever_rejects_shape_mismatch() -> None:
    point = SimpleNamespace(payload=_chunk("qdrant", text="RAG retrieves evidence and grounds answers.").to_payload(), score=0.88)
    client = _ShapeClient(point, size=64)

    with pytest.raises(RuntimeError, match="Qdrant collection shape mismatch"):
        QdrantOnlineDenseRetriever(
            client=client,
            collection_name="local_life_hybrid_chunks",
            vector_name="embedding",
            embedding_adapter=SimpleNamespace(embed=lambda text: [0.1, 0.2, 0.3]),
            fallback=HeuristicDenseRetriever((_chunk("fallback", text="fallback"),)),
            enabled=True,
            vector_size=4096,
            distance="cosine",
        )


def test_evidence_governance_records_rejected_reasons() -> None:
    good = _chunk("good", text="Stable answer about RAG.", title="Good")
    duplicate = _chunk("duplicate", text="Stable answer about RAG.", title="Dup")
    old = _chunk("old", text="Old answer about RAG.", title="Old", version="v0")
    low = _chunk("low", text="Low score answer.", title="Low")

    hits = (
        _hit(good, route="dense", score=0.92),
        _hit(duplicate, route="sparse", score=0.89),
        _hit(old, route="metadata", score=0.81),
        _hit(low, route="dense", score=0.01),
    )
    plan = RetrievalPlan(
        semantic_query="RAG",
        keyword_query="RAG",
        retrieval_filters=RetrievalFilters(version=("v1",)),
        preferred_chunk_types=("concept",),
    )
    pack = EvidenceGovernanceService(EvidenceGovernanceConfig(min_items=1, max_items=3)).evaluate(plan, hits)

    reasons = {item.rejected_reason for item in pack.rejected_items}
    assert {"duplicate", "old_version", "low_score"} <= reasons
    assert pack.debug_trace is not None
    assert pack.debug_trace.evidence_rejected


def test_parent_child_resolver_falls_back_when_parent_missing() -> None:
    parent = _chunk("parent", text="parent text", title="Parent")
    child = _chunk("child", text="child text", title="Child", parent_id="parent")
    orphan = _chunk("orphan", text="orphan text", title="Orphan", parent_id="missing-parent")

    resolver = ParentChildResolver((parent, child, orphan))
    assert resolver.resolve_chunk(child).chunk_id == "parent"
    assert resolver.resolve_chunk(orphan) is orphan


def test_parent_child_citation_traces_child() -> None:
    parent = _chunk("parent", text="parent text about RAG", title="Parent")
    child = _chunk("child", text="child text about RAG grounding", title="Child", parent_id="parent")

    dense = FixedRetriever((_hit(child, route="dense", score=0.95),))
    service = HybridRetrieverService(
        dense_retriever=dense,
        sparse_retriever=FixedRetriever(()),
        metadata_retriever=FixedRetriever(()),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=1),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((parent, child)),
    )
    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG grounding",
            keyword_query="RAG grounding",
            extra={"raw_query": "RAG grounding"},
        )
    )

    pack = EvidenceGovernanceService(EvidenceGovernanceConfig(min_items=1, max_items=1)).evaluate(
        RetrievalPlan(
            semantic_query="RAG grounding",
            keyword_query="RAG grounding",
            extra={"raw_query": "RAG grounding"},
        ),
        result.reranked_hits,
    )

    assert pack.items
    assert pack.items[0].chunk.chunk_id == "parent"
    assert pack.items[0].citation_chunk_id == "child"


def test_hybrid_service_exposes_route_states_and_pre_evidence_stage() -> None:
    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")

    dense_hit = replace(
        _hit(rag, route="dense", score=0.91, rank=1),
        metadata={
            "degraded": True,
            "fallback_reason": "dense_query_failed",
            "retrieval_mode": "fallback",
        },
    )
    sparse_hit = _hit(rag, route="sparse", score=0.82, rank=1)
    metadata_hit = replace(
        _hit(rag, route="metadata", score=0.7, rank=1),
        metadata={
            "degraded": True,
            "fallback_reason": "metadata_query_failed",
            "retrieval_mode": "fallback",
        },
    )

    service = HybridRetrieverService(
        dense_retriever=FixedRetriever((dense_hit,)),
        sparse_retriever=FixedRetriever((sparse_hit,)),
        metadata_retriever=FixedRetriever((metadata_hit,)),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG"},
        )
    )

    assert result.debug_trace is not None
    assert result.debug_trace.extra["evidence_stage"] == "pre_evidence_governance"
    assert set(result.debug_trace.extra["working_routes"]) == {"dense", "sparse", "metadata"}
    assert result.debug_trace.extra["failed_routes"] == []
    assert result.debug_trace.extra["empty_routes"] == []
    assert result.debug_trace.extra["route_stats"]["dense"]["state"] == "degraded"
    assert result.debug_trace.extra["route_stats"]["sparse"]["state"] == "working"
    assert result.debug_trace.extra["route_stats"]["metadata"]["state"] == "degraded"
    assert result.debug_trace.metrics["working_route_count"] == 3
    assert result.debug_trace.metrics["failed_route_count"] == 0
    assert result.debug_trace.metrics["empty_route_count"] == 0


def test_hybrid_retriever_collects_routes_in_parallel() -> None:
    barrier = threading.Barrier(3, timeout=2.0)
    started: list[str] = []
    completed: list[str] = []

    class BarrierRetriever:
        def __init__(self, route_name: str, hit: RecallHit):
            self.route_name = route_name
            self._hit = hit

        def retrieve(self, plan):
            started.append(self.route_name)
            barrier.wait()
            completed.append(self.route_name)
            return (self._hit,)

    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    service = HybridRetrieverService(
        dense_retriever=BarrierRetriever("dense", _hit(rag, route="dense", score=0.91, rank=1)),
        sparse_retriever=BarrierRetriever("sparse", _hit(rag, route="sparse", score=0.82, rank=1)),
        metadata_retriever=BarrierRetriever("metadata", _hit(rag, route="metadata", score=0.7, rank=1)),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG"},
        )
    )

    assert result.hits
    assert sorted(started) == ["dense", "metadata", "sparse"]
    assert sorted(completed) == ["dense", "metadata", "sparse"]
    assert result.debug_trace is not None
    assert set(result.debug_trace.extra["working_routes"]) == {"dense", "sparse", "metadata"}


def test_hybrid_retriever_keeps_result_when_one_route_fails() -> None:
    class FailingRetriever:
        route_name = "dense"

        def retrieve(self, plan):  # noqa: ANN001
            raise RuntimeError("dense failed")

    rag = _chunk("rag-concept", text="RAG retrieves evidence and grounds answers.", title="RAG")
    service = HybridRetrieverService(
        dense_retriever=FailingRetriever(),
        sparse_retriever=FixedRetriever((_hit(rag, route="sparse", score=0.82, rank=1),)),
        metadata_retriever=FixedRetriever((_hit(rag, route="metadata", score=0.7, rank=1),)),
        reranker=None,
        config=SimpleNamespace(rerank_top_k=2),
        fusion=ReciprocalRankFusion(),
        parent_child_resolver=ParentChildResolver((rag,)),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="RAG retrieval",
            extra={"raw_query": "RAG"},
        )
    )

    assert result.hits
    assert result.debug_trace is not None
    assert "dense" in result.debug_trace.extra["failed_routes"] or "dense" in result.degraded_routes


def test_evidence_governance_retention_summary_explains_empty_evidence() -> None:
    chunk = _chunk("low", text="Low score answer.", title="Low")
    hits = (_hit(chunk, route="dense", score=0.01, rank=1),)
    plan = RetrievalPlan(
        semantic_query="RAG",
        keyword_query="RAG",
        extra={"raw_query": "RAG"},
    )

    pack = EvidenceGovernanceService(EvidenceGovernanceConfig(min_items=1, max_items=3)).evaluate(plan, hits)

    assert pack.items == ()
    assert pack.evidence_status.value == "EMPTY"
    assert pack.debug_trace is not None
    assert pack.debug_trace.evidence_kept == ()
    assert pack.debug_trace.extra["evidence_stage"] == "post_evidence_governance"
    summary = pack.debug_trace.extra["retention_summary"]
    assert summary["input_hit_count"] == 1
    assert summary["kept_hit_count"] == 0
    assert summary["retention_reason"].startswith("low_score:")
    assert pack.debug_trace.metrics["evidence_rejected_reasons"]["low_score"] == 1


def test_default_evidence_governance_filters_marginal_similarity_hits() -> None:
    chunk = _chunk("marginal", text="Borderline similar evidence.", title="Marginal")
    hits = (_hit(chunk, route="dense", score=0.25, rank=1),)
    plan = RetrievalPlan(
        semantic_query="RAG",
        keyword_query="RAG",
        extra={"raw_query": "RAG"},
    )

    pack = EvidenceGovernanceService().evaluate(plan, hits)

    assert pack.items == ()
    assert pack.evidence_status.value == "EMPTY"
    assert pack.debug_trace is not None
    assert pack.debug_trace.metrics["evidence_rejected_reasons"]["low_score"] == 1


def test_default_hybrid_retriever_config_matches_new_recall_budget() -> None:
    config = HybridRetrieverConfig()

    assert config.dense_top_k == 10
    assert config.sparse_top_k == 8
    assert config.metadata_top_k == 8
    assert config.fusion_top_k == 15
    assert config.rerank_top_k == 8


def test_hybrid_retriever_caps_fused_hits_before_rerank() -> None:
    chunks = tuple(_chunk(f"chunk-{index}", text=f"chunk {index}") for index in range(25))
    fused_hits = tuple(_hit(chunk, route="dense", score=1.0 - index * 0.01, rank=index + 1) for index, chunk in enumerate(chunks))

    class _Fusion:
        def __init__(self) -> None:
            self._config = SimpleNamespace(k=60, route_weights={"dense": 1.0, "sparse": 1.0, "metadata": 0.6})

        def fuse(self, route_hits, *, query_intent=None, query_slots=None):  # noqa: ANN001
            return fused_hits

    class _Reranker:
        def rerank(self, plan, hits):  # noqa: ANN001
            return hits

    service = HybridRetrieverService(
        dense_retriever=FixedRetriever(()),
        sparse_retriever=FixedRetriever(()),
        metadata_retriever=FixedRetriever(()),
        reranker=_Reranker(),
        config=SimpleNamespace(rerank_top_k=8, fusion_top_k=20),
        fusion=_Fusion(),
    )

    result = service.retrieve(
        RetrievalPlan(
            semantic_query="测试融合截断",
            keyword_query="测试融合截断",
            rerank_top_k=8,
        )
    )

    assert len(result.fused_hits) == 20
    assert len(result.hits) == 20
    assert result.debug_trace is not None
    assert result.debug_trace.metrics["policy_snapshot"]["fusion_top_k"] == 20
