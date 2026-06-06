from __future__ import annotations

from .shared import *# noqa: F401,F403,F405

from collections.abc import Iterable, Sequence
from collections import defaultdict
from dataclasses import replace
from typing import Any
import math
import time

from .shared import (
    _LOGGER,
    _tokenize,
    _term_overlap,
    _normalize_points,
    _point_to_chunk,
    _point_score,
    validate_qdrant_collection_shape,
    KnowledgeChunk,
    RecallHit,
    RetrievalPlan,
    BM25Okapi,
)
from ..protocols import SparseRetriever
from ..qdrant_filters import QdrantFilterBuilder
from .dense import HeuristicDenseRetriever, ParentChildResolver

class HeuristicSparseRetriever(HeuristicDenseRetriever):
    route_name = "sparse"

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        return self._retrieve(plan, plan.keyword_query or plan.semantic_query, plan.sparse_top_k)

    def _dense_score(self, plan: RetrievalPlan, query_tokens: Sequence[str], chunk: KnowledgeChunk) -> float:
        chunk_tokens = _tokenize(chunk.searchable_text())
        score = _term_overlap(query_tokens, chunk_tokens)
        if chunk.chunk_type in plan.preferred_chunk_types:
            score += 0.08
        return min(score, 1.0)

class LocalBM25SparseRetriever:
    route_name = "sparse"

    def __init__(
        self,
        chunks: Iterable[KnowledgeChunk],
        parent_child_resolver: ParentChildResolver | None = None,
        *,
        fallback: SparseRetriever | None = None,
        enabled: bool = True,
        k1: float = 1.5,
        b: float = 0.75,
        filter_builder: QdrantFilterBuilder | None = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._resolver = parent_child_resolver
        self._fallback = fallback or HeuristicSparseRetriever(self._chunks, parent_child_resolver)
        self._enabled = enabled
        self._k1 = float(k1)
        self._b = float(b)
        self._filter_builder = filter_builder or QdrantFilterBuilder()
        self._index_error: str | None = None
        self._bm25 = None
        try:
            self._doc_tokens = tuple(_tokenize(chunk.searchable_text()) for chunk in self._chunks)
            self._doc_freq = self._build_doc_freq(self._doc_tokens)
            self._avg_doc_len = (
                sum(len(tokens) for tokens in self._doc_tokens) / float(len(self._doc_tokens))
                if self._doc_tokens
                else 0.0
            )
            if BM25Okapi is not None and self._doc_tokens:
                self._bm25 = BM25Okapi(list(self._doc_tokens))
        except Exception as exc:  # pragma: no cover - defensive fallback
            _LOGGER.exception("bm25_index_build_failed")
            self._index_error = str(exc)
            self._doc_tokens = ()
            self._doc_freq = {}
            self._avg_doc_len = 0.0
            self._bm25 = None

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        if not self._enabled:
            return self._fallback_retrieve(plan, reason="bm25_disabled")
        if not self._chunks:
            return self._fallback_retrieve(plan, reason="bm25_index_empty")
        if self._index_error is not None:
            return self._fallback_retrieve(plan, reason="bm25_build_failed")

        query = (plan.keyword_query or "").strip()
        query_tokens = _tokenize(query)
        if not query_tokens:
            return self._fallback_retrieve(plan, reason="empty_keyword_query")

        scored: list[tuple[float, KnowledgeChunk]] = []
        if self._bm25 is not None:
            raw_scores = self._bm25.get_scores(query_tokens)
            for chunk, score in zip(self._chunks, raw_scores):
                if not self._filter_builder.matches_visibility(
                    chunk,
                    plan.retrieval_filters,
                    runtime_context=self._filter_builder._plan_runtime_context(plan),
                ):
                    continue
                score_value = float(score)
                if score_value <= 0:
                    continue
                if chunk.chunk_type in plan.preferred_chunk_types:
                    score_value += 0.05
                scored.append((score_value, chunk))
        else:
            for chunk, doc_tokens in zip(self._chunks, self._doc_tokens):
                if not self._filter_builder.matches_visibility(
                    chunk,
                    plan.retrieval_filters,
                    runtime_context=self._filter_builder._plan_runtime_context(plan),
                ):
                    continue
                score = self._bm25_score(query_tokens, doc_tokens)
                if score <= 0:
                    continue
                if chunk.chunk_type in plan.preferred_chunk_types:
                    score += 0.05
                scored.append((score, chunk))

        if not scored:
            return self._fallback_retrieve(plan, reason="bm25_no_results")

        scored.sort(key=lambda item: item[0], reverse=True)
        hits: list[RecallHit] = []
        for index, (score, chunk) in enumerate(scored[: plan.sparse_top_k], start=1):
            hit = RecallHit(
                chunk=chunk,
                score=score,
                route=self.route_name,
                rank=index,
                route_scores={self.route_name: score},
                matched_routes=(self.route_name,),
                source_chunk_id=chunk.chunk_id,
                citation_chunk_id=chunk.chunk_id,
                rrf_score=score,
                fused_score=score,
                score_breakdown={"bm25": score},
                metadata={
                    "source": "local_bm25",
                    "retrieval_type": "sparse_bm25",
                    "retrieval_mode": "bm25",
                    "bm25_enabled": True,
                },
                retrieval_kind="sparse_bm25",
                collection_name="",
                source_domain="in_memory",
            )
            hits.append(self._resolver.resolve_hit(hit) if self._resolver else hit)
        return tuple(hits)

    def _fallback_retrieve(self, plan: RetrievalPlan, *, reason: str) -> Sequence[RecallHit]:
        if self._fallback is None:
            return ()
        hits = tuple(self._fallback.retrieve(plan))
        if not hits:
            return ()
        return tuple(
            replace(
                hit,
                metadata={
                    **dict(hit.metadata),
                    "source": "heuristic_fallback",
                    "degraded": True,
                    "fallback_reason": reason,
                    "retrieval_mode": "fallback",
                    "retrieval_type": "sparse_heuristic_fallback",
                },
            )
            for hit in hits
        )

    def _build_doc_freq(self, doc_tokens: Sequence[Sequence[str]]) -> dict[str, int]:
        frequencies: dict[str, int] = defaultdict(int)
        for tokens in doc_tokens:
            for token in set(tokens):
                frequencies[token] += 1
        return frequencies

    def _bm25_score(self, query_tokens: Sequence[str], doc_tokens: Sequence[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        doc_length = len(doc_tokens)
        if doc_length <= 0:
            return 0.0
        token_counts: dict[str, int] = defaultdict(int)
        for token in doc_tokens:
            token_counts[token] += 1

        score = 0.0
        doc_count = max(len(self._chunks), 1)
        norm = self._k1 * (1.0 - self._b + self._b * (doc_length / float(self._avg_doc_len or 1.0)))
        for token in query_tokens:
            tf = token_counts.get(token, 0)
            if not tf:
                continue
            df = self._doc_freq.get(token, 0)
            if not df:
                continue
            idf = math.log(1.0 + ((doc_count - df + 0.5) / (df + 0.5)))
            score += idf * ((tf * (self._k1 + 1.0)) / (tf + norm))
        return score

class QdrantOnlineSparseRetriever:
    route_name = "sparse"

    def __init__(
        self,
        *,
        client: Any,
        collection_name: str,
        sparse_vector_name: str,
        sparse_query_adapter: Any | None = None,
        fallback: SparseRetriever | None = None,
        enabled: bool = False,
        filter_builder: QdrantFilterBuilder | None = None,
        vector_size: int | None = None,
        distance: Any | None = None,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._sparse_vector_name = sparse_vector_name
        self._sparse_query_adapter = sparse_query_adapter
        self._fallback = fallback
        self._enabled = enabled
        self._filter_builder = filter_builder or QdrantFilterBuilder()
        self._vector_size = vector_size
        self._distance = distance
        self._validate_collection_shape()

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        if (
            not self._enabled
            or self._client is None
            or not self._collection_name
            or not self._sparse_vector_name
            or self._sparse_query_adapter is None
        ):
            return self._fallback_retrieve(plan, reason="sparse_qdrant_unavailable")

        try:
            sparse_query = self._adapt_query(plan.keyword_query or plan.semantic_query)
            if not sparse_query:
                return self._fallback_retrieve(plan, reason="sparse_query_empty")

            search_fn = getattr(self._client, "query_points", None) or getattr(self._client, "search", None)
            if not callable(search_fn):
                return self._fallback_retrieve(plan, reason="sparse_query_fn_missing")

            response = search_fn(
                collection_name=self._collection_name,
                query=sparse_query,
                using=self._sparse_vector_name,
                query_filter=self._filter_builder.build_for_plan(plan),
                limit=plan.sparse_top_k,
                with_payload=True,
            )
            points = _normalize_points(response)
            hits: list[RecallHit] = []
            for index, point in enumerate(points, start=1):
                chunk = _point_to_chunk(point)
                if chunk is None:
                    continue
                if not self._filter_builder.matches_plan(chunk, plan):
                    continue
                score = _point_score(point)
                hits.append(
                    RecallHit(
                        chunk=chunk,
                        score=score,
                        route=self.route_name,
                        rank=index,
                        route_scores={self.route_name: score},
                        matched_routes=(self.route_name,),
                        source_chunk_id=chunk.chunk_id,
                        citation_chunk_id=chunk.chunk_id,
                        rrf_score=score,
                        fused_score=score,
                        score_breakdown={"sparse": score, "online_sparse": score},
                        metadata={
                            "source": "qdrant_sparse_vector",
                            "retrieval_type": "sparse_qdrant",
                            "retrieval_mode": "qdrant_query_points",
                        },
                        retrieval_kind="sparse_qdrant",
                        collection_name=self._collection_name,
                        source_domain="local_life_hybrid",
                    )
                )
            return tuple(hits) if hits else self._fallback_retrieve(plan, reason="sparse_qdrant_no_results")
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("qdrant_online_sparse_retriever_failed")
            return self._fallback_retrieve(plan, reason="sparse_qdrant_failed")

    def _adapt_query(self, query: str) -> Any:
        adapter = self._sparse_query_adapter
        if hasattr(adapter, "encode"):
            return adapter.encode(query)
        if callable(adapter):
            return adapter(query)
        return None

    def _fallback_retrieve(self, plan: RetrievalPlan, *, reason: str) -> Sequence[RecallHit]:
        if self._fallback is None:
            return ()
        hits = tuple(self._fallback.retrieve(plan))
        if not hits:
            return ()
        return tuple(
            replace(
                hit,
                metadata={
                    **dict(hit.metadata),
                    "degraded": True,
                    "fallback_reason": reason,
                    "retrieval_mode": "fallback",
                },
            )
            for hit in hits
        )

    def warmup_embedding(self, query: str) -> dict[str, Any]:
        if not self._enabled or self._embedding_adapter is None:
            return {"cache_hit": False, "latency_ms": 0.0, "skipped": True}
        started_at = time.perf_counter()
        cache_hit = False
        try:
            if hasattr(self._embedding_adapter, "embed_with_stats"):
                _vector, cache_hit = self._embedding_adapter.embed_with_stats(query)
            else:
                _vector = self._embedding_adapter.embed(query)
        except Exception:  # pragma: no cover - warmup must be best-effort
            _LOGGER.exception("qdrant_dense_embedding_warmup_failed")
            return {"cache_hit": False, "latency_ms": (time.perf_counter() - started_at) * 1000.0, "failed": True}
        return {
            "cache_hit": bool(cache_hit),
            "latency_ms": (time.perf_counter() - started_at) * 1000.0,
            "skipped": False,
        }

    def _validate_collection_shape(self) -> None:
        validate_qdrant_collection_shape(
            self._client,
            collection_name=self._collection_name,
            vector_name=self._sparse_vector_name,
            vector_size=self._vector_size,
            distance=self._distance,
            action_hint="use the dedicated hybrid seed or reindex command",
        )

class InMemoryTokenRetriever:
    def __init__(self, chunks: Iterable[KnowledgeChunk], route_name: str, parent_child_resolver: ParentChildResolver | None = None) -> None:
        if route_name == "dense":
            self._delegate: RetrieverRoute = HeuristicDenseRetriever(chunks, parent_child_resolver)
        elif route_name == "sparse":
            self._delegate = HeuristicSparseRetriever(chunks, parent_child_resolver)
        else:
            self._delegate = HeuristicMetadataRetriever(chunks, parent_child_resolver)
        self.route_name = route_name

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        return self._delegate.retrieve(plan)

__all__ = [name for name in globals() if not name.startswith("__")]
