from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("qdrant-client is not installed") from exc

from learning_agent_service.rag.models import KnowledgeChunk, RetrievalFilters, RetrievalPlan
from learning_agent_service.rag.retrieval import (
    HeuristicMetadataRetriever,
    HeuristicSparseRetriever,
    LocalBM25SparseRetriever,
    QdrantMetadataRetriever,
    QdrantOnlineDenseRetriever,
)
from learning_agent_service.rag.qdrant_filters import QdrantFilterBuilder


def _chunk(
    chunk_id: str,
    *,
    text: str = "RAG retrieval relies on evidence.",
    tenant_id: str = "tenant-a",
    permission_tags: tuple[str, ...] = ("reader",),
    is_active: bool = True,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=text,
        title=chunk_id,
        category="rag",
        chunk_type="concept",
        tags=("rag",),
        metadata={
            "tenant_id": tenant_id,
            "permission_tags": list(permission_tags),
            "is_active": is_active,
        },
    )


def _plan(*, tenant_id: str = "tenant-a", permission_tags: tuple[str, ...] = ("reader",)) -> RetrievalPlan:
    return RetrievalPlan(
        semantic_query="RAG retrieval",
        keyword_query="RAG retrieval",
        retrieval_filters=RetrievalFilters(
            category=("rag",),
            chunk_type=("concept",),
            extra={
                "tenant_id": tenant_id,
                "permission_tags": list(permission_tags),
                "is_active": True,
            },
        ),
        extra={
            "raw_query": "RAG retrieval",
            "tenant_id": tenant_id,
            "permission_tags": list(permission_tags),
            "is_active": True,
            "filter_confidence": 1.0,
            "metadata_filter_confidence_threshold": 0.5,
        },
    )


def test_qdrant_filter_builder_merges_metadata_and_runtime_filters() -> None:
    builder = QdrantFilterBuilder()
    filters = RetrievalFilters(
        category=("rag",),
        chunk_type=("concept",),
        extra={
            "source_uri": "kb://rag",
            "tenant_id": "tenant-a",
            "permission_tags": ["reader"],
            "is_active": True,
        },
    )
    qfilter = builder.build(
        filters,
        tenant_id="tenant-a",
        permission_tags=("reader", "editor"),
        is_active=True,
    )

    assert isinstance(qfilter, Filter)
    assert qfilter.must
    keys = {condition.key for condition in qfilter.must if isinstance(condition, FieldCondition)}
    assert {"category", "chunk_type", "source_uri", "tenant_id", "permission_tags", "is_active"} <= keys

    permission_condition = next(condition for condition in qfilter.must if getattr(condition, "key", None) == "permission_tags")
    assert isinstance(permission_condition.match, MatchAny)
    assert set(permission_condition.match.any) == {"reader", "editor"}

    active_condition = next(condition for condition in qfilter.must if getattr(condition, "key", None) == "is_active")
    assert isinstance(active_condition.match, MatchValue)
    assert active_condition.match.value is True


def test_dense_retriever_passes_filter_to_qdrant() -> None:
    class FakePoint:
        def __init__(self, payload, score):
            self.payload = payload
            self.score = score

    class FakeEmbeddingAdapter:
        def embed(self, text: str):  # noqa: ANN001
            return [0.1, 0.2, 0.3]

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def query_points(self, **kwargs):  # noqa: ANN001
            self.calls.append(kwargs)
            return {"points": [FakePoint(payload=_chunk("visible").to_payload(), score=0.91)]}

    client = FakeClient()
    retriever = QdrantOnlineDenseRetriever(
        client=client,
        collection_name="knowledge_chunks_current",
        vector_name="dense",
        embedding_adapter=FakeEmbeddingAdapter(),
        fallback=None,
        enabled=True,
    )

    hits = retriever.retrieve(_plan())

    assert client.calls
    call = client.calls[0]
    assert call["collection_name"] == "knowledge_chunks_current"
    assert call["using"] == "dense"
    assert isinstance(call["query_filter"], Filter)
    assert hits and hits[0].chunk.chunk_id == "visible"


def test_local_bm25_sparse_retriever_filters_visibility_before_scoring() -> None:
    visible = _chunk("visible", tenant_id="tenant-a", permission_tags=("reader",), is_active=True)
    wrong_tenant = _chunk("wrong-tenant", tenant_id="tenant-b", permission_tags=("reader",), is_active=True)
    inactive = _chunk("inactive", tenant_id="tenant-a", permission_tags=("reader",), is_active=False)
    no_permission = _chunk("no-permission", tenant_id="tenant-a", permission_tags=("editor",), is_active=True)

    retriever = LocalBM25SparseRetriever((visible, wrong_tenant, inactive, no_permission), fallback=HeuristicSparseRetriever((visible, wrong_tenant, inactive, no_permission)), enabled=True)

    hits = retriever.retrieve(_plan())

    assert hits
    assert [hit.chunk.chunk_id for hit in hits] == ["visible"]


def test_local_bm25_sparse_retriever_empty_keyword_query_marks_degraded_fallback() -> None:
    visible = _chunk("visible", tenant_id="tenant-a", permission_tags=("reader",), is_active=True)
    retriever = LocalBM25SparseRetriever((visible,), fallback=HeuristicSparseRetriever((visible,)), enabled=True)

    hits = retriever.retrieve(
        RetrievalPlan(
            semantic_query="RAG retrieval",
            keyword_query="",
            retrieval_filters=RetrievalFilters(
                category=("rag",),
                chunk_type=("concept",),
                extra={
                    "tenant_id": "tenant-a",
                    "permission_tags": ["reader"],
                    "is_active": True,
                },
            ),
            extra={
                "raw_query": "RAG retrieval",
                "tenant_id": "tenant-a",
                "permission_tags": ["reader"],
                "is_active": True,
            },
        )
    )

    assert hits
    assert hits[0].chunk.chunk_id == "visible"
    assert hits[0].metadata.get("degraded") is True
    assert hits[0].metadata.get("fallback_reason") == "empty_keyword_query"


def test_metadata_retriever_uses_qdrant_query_points_without_scroll() -> None:
    class FakePoint:
        def __init__(self, payload, score):
            self.payload = payload
            self.score = score

    class FakeEmbeddingAdapter:
        def embed(self, text: str):  # noqa: ANN001
            return [0.1, 0.2, 0.3]

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def query_points(self, **kwargs):  # noqa: ANN001
            self.calls.append(kwargs)
            return {"points": [FakePoint(payload=_chunk("meta").to_payload(), score=0.77)]}

        def scroll(self, **kwargs):  # noqa: ANN001
            raise AssertionError("metadata retrieval should not use scroll on the main path")

    client = FakeClient()
    retriever = QdrantMetadataRetriever(
        client=client,
        collection_name="knowledge_chunks_current",
        vector_name="dense",
        embedding_adapter=FakeEmbeddingAdapter(),
        fallback=HeuristicSparseRetriever((_chunk("fallback"),)),
        enabled=True,
    )

    hits = retriever.retrieve(_plan())

    assert client.calls
    assert isinstance(client.calls[0]["query_filter"], Filter)
    assert hits and hits[0].chunk.chunk_id == "meta"
    assert not hits[0].metadata.get("degraded")


def test_metadata_retriever_fallback_marks_degraded() -> None:
    class FailingEmbeddingAdapter:
        def embed(self, text: str):  # noqa: ANN001
            raise RuntimeError("embedding unavailable")

    fallback_chunk = _chunk("fallback")
    retriever = QdrantMetadataRetriever(
        client=SimpleNamespace(),
        collection_name="knowledge_chunks_current",
        vector_name="dense",
        embedding_adapter=FailingEmbeddingAdapter(),
        fallback=LocalBM25SparseRetriever((fallback_chunk,), enabled=True),
        enabled=True,
    )

    hits = retriever.retrieve(_plan())

    assert hits
    assert hits[0].chunk.chunk_id == "fallback"
    assert hits[0].metadata.get("degraded") is True
    assert hits[0].metadata.get("fallback_reason") == "embedding_unavailable"


def test_heuristic_metadata_retriever_uses_configured_threshold() -> None:
    chunk = _chunk("visible", tenant_id="tenant-a", permission_tags=("reader",), is_active=True)
    retriever = HeuristicMetadataRetriever((chunk,), parent_child_resolver=None)

    base_plan = _plan(tenant_id="tenant-a", permission_tags=("reader",))
    base_filters = dict(base_plan.retrieval_filters.extra)
    base_filters["tenant_owner_id"] = "owner-1"
    plan = RetrievalPlan(
        semantic_query=base_plan.semantic_query,
        keyword_query=base_plan.keyword_query,
        retrieval_filters=RetrievalFilters(
            category=base_plan.retrieval_filters.category,
            chunk_type=base_plan.retrieval_filters.chunk_type,
            extra=base_filters,
        ),
        extra={
            **dict(base_plan.extra),
            "filter_confidence": 0.7,
            "metadata_filter_confidence_threshold": 0.9,
            "tenant_owner_id": "owner-1",
        },
    )
    relaxed_hits = retriever.retrieve(plan)
    assert relaxed_hits
    assert relaxed_hits[0].chunk.chunk_id == "visible"

    strict_plan = RetrievalPlan(
        semantic_query=plan.semantic_query,
        keyword_query=plan.keyword_query,
        retrieval_filters=plan.retrieval_filters,
        extra={**dict(plan.extra), "filter_confidence": 0.95, "metadata_filter_confidence_threshold": 0.5},
    )
    strict_hits = retriever.retrieve(strict_plan)
    assert not strict_hits
