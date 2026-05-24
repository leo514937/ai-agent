from __future__ import annotations

import logging
import math
import re
import time
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

try:  # pragma: no cover - optional dependency path
    import httpx
except Exception:  # pragma: no cover - httpx may be unavailable in some runtime slices
    httpx = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency path
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - rank-bm25 may be unavailable in some runtime slices
    BM25Okapi = None  # type: ignore[assignment]

from .models import (
    HybridRecallResult,
    KnowledgeChunk,
    RecallHit,
    RetrievalFilters,
    RetrievalPlan,
    RetrievalTrace,
    RetrievalTraceItem,
)
from .qdrant_filters import QdrantFilterBuilder, _RUNTIME_FILTER_KEYS
from .protocols import DenseRetriever, MetadataRetriever, Reranker, SparseRetriever
from .rewrite import QueryRewriteService

_LOGGER = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")


def _collection_vectors(collection_info: Any) -> Any:
    config = getattr(collection_info, "config", None)
    params = getattr(config, "params", None) if config is not None else None
    if params is None:
        return None
    vectors = getattr(params, "vectors", None)
    if vectors is not None:
        return vectors
    return getattr(params, "sparse_vectors", None)


def _distance_value(distance: Any) -> str:
    val = distance.value if hasattr(distance, "value") else distance
    return str(val or "").strip().lower()


def _distance_matches(expected: Any, actual: Any) -> bool:
    return _distance_value(expected) == _distance_value(actual)


def validate_qdrant_collection_shape(
    client: Any,
    *,
    collection_name: str,
    vector_name: str,
    vector_size: Optional[int] = None,
    distance: Optional[Any] = None,
    action_hint: str = "run the dedicated seed or reindex command",
) -> None:
    get_collection = getattr(client, "get_collection", None)
    if not callable(get_collection):
        return
    try:
        collection_info = get_collection(collection_name)
    except Exception as exc:
        raise RuntimeError(
            "Qdrant collection missing:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"action={action_hint}"
        ) from exc

    vectors = _collection_vectors(collection_info)
    if vectors is None:
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            "actual_vector_size=unknown\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            "actual_distance=unknown\n"
            f"action={action_hint}"
        )
    if not isinstance(vectors, Mapping):
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            "actual_vector_size=unknown\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            "actual_distance=unknown\n"
            f"action={action_hint}"
        )
    vector_params = vectors.get(vector_name)
    if vector_params is None:
        sparse_vectors = getattr(collection_info.config.params, "sparse_vectors", None) if getattr(collection_info, "config", None) is not None else None
        if isinstance(sparse_vectors, Mapping):
            vector_params = sparse_vectors.get(vector_name)
    if vector_params is None:
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            "actual_vector_size=unknown\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            "actual_distance=unknown\n"
            f"action={action_hint}"
        )
    size = getattr(vector_params, "size", None)
    actual_distance = getattr(vector_params, "distance", None)
    if vector_size is not None and size is not None and int(size) != int(vector_size):
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size}\n"
            f"actual_vector_size={size}\n"
            f"expected_distance={_distance_value(distance) if distance is not None else 'unknown'}\n"
            f"actual_distance={_distance_value(actual_distance) if actual_distance is not None else 'unknown'}\n"
            f"action={action_hint}"
        )
    if distance is not None and actual_distance is not None and not _distance_matches(distance, actual_distance):
        raise RuntimeError(
            "Qdrant collection shape mismatch:\n"
            f"collection={collection_name}\n"
            f"vector_name={vector_name}\n"
            f"expected_vector_size={vector_size if vector_size is not None else 'unknown'}\n"
            f"actual_vector_size={size if size is not None else 'unknown'}\n"
            f"expected_distance={_distance_value(distance)}\n"
            f"actual_distance={_distance_value(actual_distance)}\n"
            f"action={action_hint}"
        )


def _with_hit_provenance(
    hit: RecallHit,
    *,
    retrieval_kind: str,
    collection_name: str = "",
    source_domain: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> RecallHit:
    return replace(
        hit,
        retrieval_kind=retrieval_kind,
        collection_name=collection_name,
        source_domain=source_domain,
        metadata={**dict(hit.metadata), **dict(metadata or {})},
    )


class RetrieverRoute(Protocol):
    route_name: str

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        ...


@dataclass(frozen=True)
class HybridRerankConfig:
    top_k: int = 15


@dataclass(frozen=True)
class RRFConfig:
    k: int = 60
    route_weights: Mapping[str, float] = field(
        default_factory=lambda: {"dense": 1.0, "sparse": 1.0, "metadata": 0.6}
    )


class ParentChildResolver:
    def __init__(self, chunks: Iterable[KnowledgeChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._chunks_by_parent_id: Dict[str, List[KnowledgeChunk]] = defaultdict(list)
        self._chunks_by_parent_chunk_id: Dict[str, List[KnowledgeChunk]] = defaultdict(list)
        self._chunks_by_entity_id: Dict[str, List[KnowledgeChunk]] = defaultdict(list)
        for chunk in self._chunks.values():
            parent_id = self._normalize_key(chunk.parent_id)
            if parent_id:
                self._chunks_by_parent_id[parent_id].append(chunk)
            parent_chunk_id = self._normalize_key(chunk.parent_chunk_id or chunk.metadata.get("parent_chunk_id"))
            if parent_chunk_id:
                self._chunks_by_parent_chunk_id[parent_chunk_id].append(chunk)
            entity_id = self._normalize_key(chunk.metadata.get("entity_id"))
            if entity_id:
                self._chunks_by_entity_id[entity_id].append(chunk)

    def resolve_chunk(self, chunk: KnowledgeChunk) -> KnowledgeChunk:
        parent_chunk_id = self._normalize_key(chunk.parent_chunk_id or chunk.metadata.get("parent_chunk_id"))
        if parent_chunk_id and parent_chunk_id in self._chunks:
            return self._chunks[parent_chunk_id]
        if chunk.parent_id and chunk.parent_id in self._chunks:
            parent = self._chunks[chunk.parent_id]
            return parent
        return chunk

    def resolve_hit(self, hit: RecallHit) -> RecallHit:
        resolved_chunk = self.resolve_chunk(hit.chunk)
        if resolved_chunk is hit.chunk:
            return replace(
                hit,
                source_chunk_id=hit.source_chunk_id or hit.chunk.chunk_id,
                citation_chunk_id=hit.citation_chunk_id or hit.chunk.chunk_id,
            )
        source_chunk_id = hit.source_chunk_id or hit.chunk.chunk_id
        citation_chunk_id = hit.citation_chunk_id or hit.chunk.chunk_id
        metadata = dict(hit.metadata)
        metadata.update(
            {
                "source_chunk_id": source_chunk_id,
                "citation_chunk_id": citation_chunk_id,
                "parent_chunk_id": resolved_chunk.chunk_id,
                "expanded_from_parent": True,
            }
        )
        return replace(
            hit,
            chunk=resolved_chunk,
            source_chunk_id=source_chunk_id,
            citation_chunk_id=citation_chunk_id,
            metadata=metadata,
        )

    def expand_hit(self, hit: RecallHit) -> Tuple[RecallHit, ...]:
        chunk = hit.chunk
        sibling_group = self._sibling_group_for(chunk)
        if len(sibling_group) <= 1:
            return (hit,)

        allowed_source_types, allowed_roles = self._sibling_filters_for(chunk)
        expanded: List[RecallHit] = [hit]
        sibling_rank = int(hit.rank)
        for sibling in sibling_group:
            if sibling.chunk_id == chunk.chunk_id:
                continue
            sibling_source_type = str(sibling.source_type or "")
            sibling_role = str(sibling.metadata.get("chunk_role") or sibling.chunk_type or sibling_source_type)
            if allowed_source_types and sibling_source_type not in allowed_source_types:
                continue
            if allowed_roles and sibling_role not in allowed_roles:
                continue
            sibling_rank += 1
            expanded.append(
                replace(
                    hit,
                    chunk=sibling,
                    score=hit.score,
                    rank=sibling_rank,
                    route_scores=dict(hit.route_scores),
                    matched_routes=tuple(hit.matched_routes),
                    fused_score=hit.fused_score,
                    rrf_score=hit.rrf_score,
                    rerank_score=hit.rerank_score,
                    rerank_rank=hit.rerank_rank,
                    rerank_model=hit.rerank_model,
                    source_chunk_id=hit.source_chunk_id or chunk.chunk_id,
                    citation_chunk_id=hit.citation_chunk_id or hit.source_chunk_id or chunk.chunk_id,
                    score_breakdown=dict(hit.score_breakdown),
                    metadata={
                        **dict(hit.metadata),
                        "expanded_from_parent": True,
                        "expanded_from_chunk_id": chunk.chunk_id,
                        "expanded_from_entity_id": str(chunk.metadata.get("entity_id") or chunk.parent_id or ""),
                        "expanded_sibling_chunk_id": sibling.chunk_id,
                        "expanded_sibling_role": sibling_role,
                        "expanded_sibling_source_type": sibling_source_type,
                    },
                )
            )
        return tuple(expanded)

    def resolve_hits(self, hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        seen: Dict[str, RecallHit] = {}
        for hit in hits:
            for expanded_hit in self.expand_hit(hit):
                seen.setdefault(expanded_hit.chunk.chunk_id, expanded_hit)
        return tuple(
            sorted(
                seen.values(),
                key=lambda item: (
                    0 if not item.chunk.parent_id else 1,
                    -float(item.score),
                    int(item.rank),
                    item.chunk.chunk_id,
                ),
            )
        )

    def _sibling_group_for(self, chunk: KnowledgeChunk) -> Tuple[KnowledgeChunk, ...]:
        parent_id = self._normalize_key(chunk.parent_id)
        if parent_id:
            group = list(self._chunks_by_parent_id.get(parent_id, ()))
            parent = self._chunks.get(parent_id)
            if parent is not None and all(item.chunk_id != parent.chunk_id for item in group):
                group.insert(0, parent)
            if group:
                return self._dedupe_group(group)
        parent_chunk_id = self._normalize_key(chunk.parent_chunk_id or chunk.metadata.get("parent_chunk_id"))
        if parent_chunk_id:
            group = list(self._chunks_by_parent_chunk_id.get(parent_chunk_id, ()))
            parent = self._chunks.get(parent_chunk_id)
            if parent is not None and all(item.chunk_id != parent.chunk_id for item in group):
                group.insert(0, parent)
            if group:
                return self._dedupe_group(group)
        entity_id = self._normalize_key(chunk.metadata.get("entity_id"))
        if entity_id:
            group = self._chunks_by_entity_id.get(entity_id, ())
            if group:
                return self._dedupe_group(group)
        return (chunk,)

    def _sibling_filters_for(self, chunk: KnowledgeChunk) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        source_types = self._coerce_string_tuple(chunk.metadata.get("sibling_source_types"))
        roles = self._coerce_string_tuple(chunk.metadata.get("sibling_roles"))
        return source_types, roles

    @staticmethod
    def _normalize_key(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _coerce_string_tuple(value: object) -> Tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Mapping):
            return tuple(str(item) for item in value.values() if item)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(str(item) for item in value if item)
        return (str(value),)

    @staticmethod
    def _dedupe_group(group: Sequence[KnowledgeChunk]) -> Tuple[KnowledgeChunk, ...]:
        seen: Dict[str, KnowledgeChunk] = {}
        for chunk in group:
            seen.setdefault(chunk.chunk_id, chunk)
        return tuple(sorted(seen.values(), key=lambda item: (item.source_type or "", item.chunk_type or "", item.document_id, item.chunk_id)))


class HeuristicDenseRetriever:
    route_name = "dense"

    def __init__(
        self,
        chunks: Iterable[KnowledgeChunk],
        parent_child_resolver: Optional[ParentChildResolver] = None,
        *,
        filter_builder: Optional[QdrantFilterBuilder] = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._resolver = parent_child_resolver
        self._filter_builder = filter_builder or QdrantFilterBuilder()

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        return self._retrieve(plan, plan.semantic_query, plan.dense_top_k)

    def _retrieve(self, plan: RetrievalPlan, query: str, limit: int) -> Sequence[RecallHit]:
        query_tokens = _tokenize(query)
        scored: List[Tuple[float, KnowledgeChunk]] = []
        for chunk in self._chunks:
            if not self._filter_builder.matches_visibility(
                chunk,
                plan.retrieval_filters,
                runtime_context=self._filter_builder._plan_runtime_context(plan),
            ):
                continue
            score = self._dense_score(plan, query_tokens, chunk)
            if score <= 0:
                continue
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)

        hits: List[RecallHit] = []
        for index, (score, chunk) in enumerate(scored[:limit], start=1):
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
                score_breakdown={"dense": score},
                metadata={
                    "source": "heuristic",
                    "retrieval_type": f"{self.route_name}_heuristic",
                    "retrieval_mode": "heuristic",
                },
                retrieval_kind=f"{self.route_name}_heuristic",
                collection_name="",
                source_domain="in_memory",
            )
            hits.append(self._resolver.resolve_hit(hit) if self._resolver else hit)
        return tuple(hits)

    def _dense_score(self, plan: RetrievalPlan, query_tokens: Sequence[str], chunk: KnowledgeChunk) -> float:
        chunk_tokens = _tokenize(chunk.searchable_text())
        score = _jaccard(query_tokens, chunk_tokens)
        if chunk.chunk_type in plan.preferred_chunk_types:
            score += 0.1
        return min(score, 1.0)


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
        parent_child_resolver: Optional[ParentChildResolver] = None,
        *,
        fallback: Optional[SparseRetriever] = None,
        enabled: bool = True,
        k1: float = 1.5,
        b: float = 0.75,
        filter_builder: Optional[QdrantFilterBuilder] = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._resolver = parent_child_resolver
        self._fallback = fallback or HeuristicSparseRetriever(self._chunks, parent_child_resolver)
        self._enabled = enabled
        self._k1 = float(k1)
        self._b = float(b)
        self._filter_builder = filter_builder or QdrantFilterBuilder()
        self._index_error: Optional[str] = None
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

        scored: List[Tuple[float, KnowledgeChunk]] = []
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
        hits: List[RecallHit] = []
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

    def _build_doc_freq(self, doc_tokens: Sequence[Sequence[str]]) -> Dict[str, int]:
        frequencies: Dict[str, int] = defaultdict(int)
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
        token_counts: Dict[str, int] = defaultdict(int)
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
        sparse_query_adapter: Optional[Any] = None,
        fallback: Optional[SparseRetriever] = None,
        enabled: bool = False,
        filter_builder: Optional[QdrantFilterBuilder] = None,
        vector_size: Optional[int] = None,
        distance: Optional[Any] = None,
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
            hits: List[RecallHit] = []
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

    def warmup_embedding(self, query: str) -> Dict[str, Any]:
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


class HeuristicMetadataRetriever(HeuristicDenseRetriever):
    route_name = "metadata"

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        return self._retrieve(plan, plan.semantic_query, plan.metadata_top_k)

    def _dense_score(self, plan: RetrievalPlan, query_tokens: Sequence[str], chunk: KnowledgeChunk) -> float:
        filter_confidence = float(plan.extra.get("filter_confidence", 1.0) or 0.0)
        metadata_filter_confidence_threshold = float(
            plan.extra.get("metadata_filter_confidence_threshold", 1.0) or 1.0
        )
        hard_filters = _extract_hard_metadata_filters(plan)
        soft_filters = _extract_soft_metadata_filters(plan)
        if hard_filters and filter_confidence >= metadata_filter_confidence_threshold and not _matches_hard_filters(chunk, hard_filters):
            return 0.0

        soft_score = _soft_metadata_score(chunk, soft_filters)
        hard_score = _hard_metadata_score(chunk, hard_filters)
        score = max(soft_score, hard_score)
        if query_tokens:
            score += 0.22 * _term_overlap(query_tokens, _tokenize(chunk.searchable_text()))
        if chunk.chunk_type in plan.preferred_chunk_types:
            score += 0.1
        return min(score, 1.0)


class QdrantMetadataRetriever(HeuristicMetadataRetriever):
    route_name = "metadata"

    def __init__(
        self,
        *,
        client: Any,
        collection_name: str,
        vector_name: str,
        embedding_adapter: Optional[Any] = None,
        fallback: Optional[MetadataRetriever] = None,
        enabled: bool = False,
        filter_builder: Optional[QdrantFilterBuilder] = None,
        scroll_fallback_enabled: bool = False,
        vector_size: Optional[int] = None,
        distance: Optional[Any] = None,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._vector_name = vector_name
        self._embedding_adapter = embedding_adapter
        self._fallback = fallback
        self._enabled = enabled
        self._filter_builder = filter_builder or QdrantFilterBuilder()
        self._scroll_fallback_enabled = scroll_fallback_enabled
        self._vector_size = vector_size
        self._distance = distance
        self._validate_collection_shape()

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        if not self._enabled or self._client is None or self._embedding_adapter is None or not self._collection_name or not self._vector_name:
            return self._fallback_retrieve(plan, degraded=True, reason="metadata_qdrant_unavailable")

        try:
            embed_started_at = time.perf_counter()
            try:
                vector = self._embedding_adapter.embed(plan.semantic_query or plan.keyword_query)
            except Exception as exc:
                _LOGGER.exception("qdrant_metadata_embedding_failed")
                normalized_reason = str(exc).strip().replace(" ", "_") or "metadata_embedding_failed"
                return self._fallback_retrieve(plan, degraded=True, reason=normalized_reason)
            embed_latency_ms = (time.perf_counter() - embed_started_at) * 1000.0
            if not vector:
                return self._fallback_retrieve(plan, degraded=True, reason="metadata_embedding_empty")

            search_fn = getattr(self._client, "query_points", None)
            if not callable(search_fn):
                return self._fallback_retrieve(plan, degraded=True, reason="metadata_query_fn_missing")

            query_filter = self._filter_builder.build_for_plan(plan)
            search_started_at = time.perf_counter()
            response = search_fn(
                collection_name=self._collection_name,
                query=vector,
                using=self._vector_name,
                query_filter=query_filter,
                limit=plan.metadata_top_k,
                with_payload=True,
            )
            search_latency_ms = (time.perf_counter() - search_started_at) * 1000.0
            points = _normalize_points(response)
            hits: List[RecallHit] = []
            query_tokens = _tokenize(plan.semantic_query or plan.keyword_query)
            for index, point in enumerate(points, start=1):
                chunk = _point_to_chunk(point)
                if chunk is None:
                    continue
                if not self._filter_builder.matches_plan(chunk, plan):
                    continue
                score = max(_point_score(point), self._dense_score(plan, query_tokens, chunk))
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
                        score_breakdown={"metadata": score, "online_metadata": _point_score(point)},
                        metadata={
                            "source": "qdrant_metadata_query",
                            "retrieval_type": "metadata_qdrant",
                            "retrieval_mode": "qdrant_query_points",
                        },
                        retrieval_kind="metadata_qdrant",
                        collection_name=self._collection_name,
                        source_domain="local_life_hybrid",
                    )
                )
            _LOGGER.info(
                "qdrant_metadata_timing embed_ms=%.1f search_ms=%.1f total_ms=%.1f hits=%s collection=%s",
                embed_latency_ms,
                search_latency_ms,
                embed_latency_ms + search_latency_ms,
                len(hits),
                self._collection_name,
            )
            if hits:
                return tuple(hits)
            if self._scroll_fallback_enabled:
                scrolled = self._scroll_fallback(plan, query_filter)
                if scrolled:
                    return scrolled
            return self._fallback_retrieve(plan, degraded=True, reason="metadata_query_empty")
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("qdrant_metadata_retriever_failed")
            if self._scroll_fallback_enabled:
                scrolled = self._scroll_fallback(plan, self._filter_builder.build_for_plan(plan))
                if scrolled:
                    return scrolled
            return self._fallback_retrieve(plan, degraded=True, reason="metadata_query_failed")

    def _fallback_retrieve(self, plan: RetrievalPlan, *, degraded: bool, reason: str) -> Sequence[RecallHit]:
        if self._fallback is None:
            return ()
        hits = tuple(self._fallback.retrieve(plan))
        if not degraded:
            return hits
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

    def _scroll_fallback(self, plan: RetrievalPlan, query_filter: Any) -> Sequence[RecallHit]:
        scroll = getattr(self._client, "scroll", None)
        if not callable(scroll):
            return ()
        try:
            response = scroll(
                collection_name=self._collection_name,
                scroll_filter=query_filter,
                limit=plan.metadata_top_k,
                with_payload=True,
                with_vectors=False,
            )
            points = _normalize_points(response)
            hits: List[RecallHit] = []
            query_tokens = _tokenize(plan.semantic_query or plan.keyword_query)
            for index, point in enumerate(points, start=1):
                chunk = _point_to_chunk(point)
                if chunk is None or not self._filter_builder.matches_plan(chunk, plan):
                    continue
                score = max(_point_score(point), self._dense_score(plan, query_tokens, chunk))
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
                        score_breakdown={"metadata": score, "scroll_fallback": _point_score(point)},
                        metadata={
                            "source": "qdrant_metadata_scroll",
                            "retrieval_type": "metadata_scroll_fallback",
                            "retrieval_mode": "scroll_fallback",
                            "degraded": True,
                            "fallback_reason": "metadata_scroll_fallback",
                        },
                        retrieval_kind="metadata_scroll_fallback",
                        collection_name=self._collection_name,
                        source_domain="local_life_hybrid",
                    )
                )
            return tuple(hits)
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("qdrant_metadata_scroll_fallback_failed")
            return ()

    def _validate_collection_shape(self) -> None:
        validate_qdrant_collection_shape(
            self._client,
            collection_name=self._collection_name,
            vector_name=self._vector_name,
            vector_size=self._vector_size,
            distance=self._distance,
            action_hint="use the dedicated hybrid seed or reindex command",
        )


class InMemoryTokenRetriever:
    def __init__(self, chunks: Iterable[KnowledgeChunk], route_name: str, parent_child_resolver: Optional[ParentChildResolver] = None) -> None:
        if route_name == "dense":
            self._delegate: RetrieverRoute = HeuristicDenseRetriever(chunks, parent_child_resolver)
        elif route_name == "sparse":
            self._delegate = HeuristicSparseRetriever(chunks, parent_child_resolver)
        else:
            self._delegate = HeuristicMetadataRetriever(chunks, parent_child_resolver)
        self.route_name = route_name

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        return self._delegate.retrieve(plan)


class QdrantOnlineDenseRetriever:
    route_name = "dense"

    def __init__(
        self,
        *,
        client: Any,
        collection_name: str,
        vector_name: str,
        embedding_adapter: Optional[Any] = None,
        fallback: Optional[DenseRetriever] = None,
        enabled: bool = False,
        filter_builder: Optional[QdrantFilterBuilder] = None,
        vector_size: Optional[int] = None,
        distance: Optional[Any] = None,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._vector_name = vector_name
        self._embedding_adapter = embedding_adapter
        self._fallback = fallback
        self._enabled = enabled
        self._filter_builder = filter_builder or QdrantFilterBuilder()
        self._vector_size = vector_size
        self._distance = distance
        self._validate_collection_shape()

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        if not self._enabled or self._client is None or self._embedding_adapter is None or not self._collection_name or not self._vector_name:
            return self._fallback_retrieve(plan, reason="dense_qdrant_unavailable")

        try:
            embed_started_at = time.perf_counter()
            cache_hit = False
            if hasattr(self._embedding_adapter, "embed_with_stats"):
                vector, cache_hit = self._embedding_adapter.embed_with_stats(plan.semantic_query)
            else:
                vector = self._embedding_adapter.embed(plan.semantic_query)
            embed_latency_ms = (time.perf_counter() - embed_started_at) * 1000.0
            if not vector:
                return self._fallback_retrieve(plan, reason="dense_embedding_empty")

            search_fn = getattr(self._client, "query_points", None) or getattr(self._client, "search", None)
            if not callable(search_fn):
                return self._fallback_retrieve(plan, reason="dense_query_fn_missing")

            search_started_at = time.perf_counter()
            response = search_fn(
                collection_name=self._collection_name,
                query=vector,
                using=self._vector_name,
                query_filter=self._filter_builder.build_for_plan(plan),
                limit=plan.dense_top_k,
                with_payload=True,
            )
            search_latency_ms = (time.perf_counter() - search_started_at) * 1000.0
            points = _normalize_points(response)
            hits: List[RecallHit] = []
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
                        score_breakdown={"dense": score, "online_dense": score},
                        metadata={
                            "source": "qdrant_dense_query",
                            "retrieval_type": "dense_qdrant",
                            "retrieval_mode": "qdrant_query_points",
                            "embedding_cache_hit": bool(cache_hit),
                            "embedding_latency_ms": embed_latency_ms,
                            "qdrant_search_latency_ms": search_latency_ms,
                        },
                        retrieval_kind="dense_qdrant",
                        collection_name=self._collection_name,
                        source_domain="local_life_hybrid",
                    )
                )
            _LOGGER.info(
                "qdrant_dense_timing embed_ms=%.1f search_ms=%.1f total_ms=%.1f hits=%s collection=%s",
                embed_latency_ms,
                search_latency_ms,
                embed_latency_ms + search_latency_ms,
                len(hits),
                self._collection_name,
            )
            return tuple(hits) if hits else self._fallback_retrieve(plan, reason="dense_query_empty")
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("qdrant_online_dense_retriever_failed")
            return self._fallback_retrieve(plan, reason="dense_query_failed")

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

    def _validate_collection_shape(self) -> None:
        validate_qdrant_collection_shape(
            self._client,
            collection_name=self._collection_name,
            vector_name=self._vector_name,
            vector_size=self._vector_size,
            distance=self._distance,
            action_hint="use the dedicated hybrid seed or reindex command",
        )


class HeuristicReranker:
    def rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> Sequence[RecallHit]:
        if not hits:
            return ()
        query_tokens = _tokenize(f"{plan.semantic_query} {plan.keyword_query}")
        preferred = set(plan.preferred_chunk_types)
        rescored: List[Tuple[float, RecallHit, Dict[str, float]]] = []
        for hit in hits:
            chunk_tokens = _tokenize(hit.chunk.searchable_text())
            overlap = _term_overlap(query_tokens, chunk_tokens)
            preferred_bonus = 0.08 if hit.chunk.chunk_type in preferred else 0.0
            route_bonus = 0.03 * len(hit.matched_routes or hit.route_scores or {hit.route: hit.score})
            rerank_score = hit.score + overlap + preferred_bonus + route_bonus
            breakdown = {
                "base": float(hit.score),
                "overlap": overlap,
                "preferred_chunk_type": preferred_bonus,
                "route_bonus": route_bonus,
            }
            rescored.append((rerank_score, hit, breakdown))

        rescored.sort(key=lambda item: item[0], reverse=True)
        top_score = rescored[0][0] if rescored else 1.0
        reranked: List[RecallHit] = []
        for index, (score, hit, breakdown) in enumerate(rescored, start=1):
            reranked.append(
                replace(
                    hit,
                    score=score / top_score if top_score else 0.0,
                    rank=index,
                    rerank_score=score,
                    fused_score=hit.fused_score or hit.rrf_score or hit.score,
                    rerank_rank=index,
                    rerank_model="heuristic",
                    score_breakdown=breakdown,
                )
            )
        return tuple(reranked)


class RemoteReranker:
    def __init__(
        self,
        *,
        endpoint: str = "",
        api_key: str = "",
        timeout_seconds: float = 10.0,
        model: str = "",
        rerank_fn: Optional[Any] = None,
        fallback: Optional[Reranker] = None,
        enabled: bool = False,
    ) -> None:
        self._endpoint = endpoint.strip()
        self._api_key = api_key.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._model = model.strip()
        self._rerank_fn = rerank_fn
        self._fallback = fallback or HeuristicReranker()
        self._enabled = enabled

    def rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> Sequence[RecallHit]:
        if not hits:
            return ()
        if self._enabled and self._endpoint:
            try:
                remote_hits = self._remote_rerank(plan, hits)
            except Exception:  # pragma: no cover - defensive fallback
                _LOGGER.exception("remote_reranker_failed")
                remote_hits = ()
            if remote_hits:
                return remote_hits
        try:
            if self._enabled and self._rerank_fn is not None:
                return self._rerank_fn(plan, hits)
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("remote_reranker_custom_fn_failed")
        return self._fallback.rerank(plan, hits)

    def _remote_rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        if httpx is None:
            return ()
        payload = {
            "model": self._model or None,
            "semantic_query": plan.semantic_query,
            "keyword_query": plan.keyword_query,
            "raw_query": plan.extra.get("raw_query"),
            "hits": [self._serialize_hit(hit) for hit in hits],
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        started_at = time.perf_counter()
        response = httpx.post(
            self._endpoint,
            json=payload,
            headers=headers,
            timeout=self._timeout_seconds,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _LOGGER.info(
            "remote_reranker_timing elapsed_ms=%.1f endpoint=%s hits=%s model=%s",
            elapsed_ms,
            self._endpoint,
            len(hits),
            self._model or "remote",
        )
        response.raise_for_status()
        normalized = self._extract_remote_hits(response.json(), hits)
        if not normalized:
            return ()
        top_score = max((hit.rerank_score or hit.score or 0.0) for hit in normalized) or 1.0
        rescored: List[RecallHit] = []
        for index, hit in enumerate(normalized, start=1):
            raw_score = float(hit.rerank_score if hit.rerank_score is not None else hit.score)
            rescored.append(
                replace(
                    hit,
                    score=raw_score / top_score if top_score else 0.0,
                    rank=index,
                    rerank_score=raw_score,
                    rerank_rank=index,
                    rerank_model=self._model or "remote",
                    fused_score=hit.fused_score or hit.rrf_score or hit.score,
                )
            )
        return tuple(rescored)

    def _serialize_hit(self, hit: RecallHit) -> Dict[str, Any]:
        return {
            "chunk_id": hit.chunk.chunk_id,
            "document_id": hit.chunk.document_id,
            "title": hit.chunk.title,
            "summary": hit.chunk.summary,
            "text": hit.chunk.text,
            "route": hit.route,
            "rank": hit.rank,
            "score": hit.score,
            "fused_score": hit.fused_score,
            "rrf_score": hit.rrf_score,
            "matched_routes": list(hit.matched_routes),
            "route_scores": dict(hit.route_scores),
            "score_breakdown": dict(hit.score_breakdown),
            "source_chunk_id": hit.source_chunk_id or hit.chunk.chunk_id,
            "citation_chunk_id": hit.citation_chunk_id or hit.chunk.chunk_id,
            "metadata": dict(hit.metadata),
        }

    def _extract_remote_hits(self, payload: Any, original_hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        if isinstance(payload, Mapping):
            candidates = payload.get("hits") or payload.get("results") or payload.get("data") or payload.get("items")
            if candidates is None:
                if all(isinstance(value, (int, float)) for value in payload.values()):
                    candidates = [
                        {"chunk_id": key, "score": value}
                        for key, value in payload.items()
                    ]
                else:
                    candidates = []
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            candidates = payload
        else:
            candidates = []

        original_by_chunk = {hit.chunk.chunk_id: hit for hit in original_hits}
        normalized: List[RecallHit] = []
        for index, item in enumerate(candidates, start=1):
            if not isinstance(item, Mapping):
                continue
            chunk_id = str(item.get("chunk_id") or item.get("id") or "").strip()
            if not chunk_id:
                continue
            base_hit = original_by_chunk.get(chunk_id)
            score = _coerce_float(
                item.get("score")
                if item.get("score") is not None
                else item.get("rerank_score")
                if item.get("rerank_score") is not None
                else item.get("value")
            )
            breakdown = item.get("score_breakdown")
            if not isinstance(breakdown, Mapping):
                breakdown = {}
            if base_hit is None:
                chunk = _point_to_chunk({"payload": item, "id": chunk_id})
                if chunk is None:
                    continue
                base_hit = RecallHit(
                    chunk=chunk,
                    score=score,
                    route=self.route_name,
                    rank=index,
                    route_scores={self.route_name: score},
                    matched_routes=(self.route_name,),
                    source_chunk_id=chunk.chunk_id,
                    citation_chunk_id=chunk.chunk_id,
                    retrieval_kind="hybrid_rerank",
                    collection_name="",
                    source_domain="local_life_hybrid",
                )
            normalized.append(
                replace(
                    base_hit,
                    route="hybrid",
                    rank=index,
                    rerank_score=score,
                    rerank_rank=index,
                    rerank_model=str(item.get("model") or item.get("rerank_model") or self._model or "remote"),
                    fused_score=base_hit.fused_score or base_hit.rrf_score or base_hit.score,
                    source_chunk_id=str(item.get("source_chunk_id") or base_hit.source_chunk_id or base_hit.chunk.chunk_id),
                    citation_chunk_id=str(item.get("citation_chunk_id") or base_hit.citation_chunk_id or base_hit.chunk.chunk_id),
                    score_breakdown=dict(breakdown) if breakdown else {"remote": score},
                )
            )
        normalized.sort(key=lambda hit: hit.rerank_score if hit.rerank_score is not None else hit.score, reverse=True)
        return tuple(normalized)


class RemoteCrossEncoderReranker(RemoteReranker):
    pass


CrossEncoderReranker = RemoteCrossEncoderReranker


class ReciprocalRankFusion:
    def __init__(self, config: Optional[RRFConfig] = None) -> None:
        self._config = config or RRFConfig()

    def fuse(self, route_hits: Mapping[str, Sequence[RecallHit]]) -> Tuple[RecallHit, ...]:
        fused_scores = defaultdict(float)
        base_hits: Dict[str, RecallHit] = {}
        route_scores: Dict[str, Dict[str, float]] = defaultdict(dict)
        matched_routes: Dict[str, List[str]] = defaultdict(list)

        for route_name, hits in route_hits.items():
            for rank, hit in enumerate(hits, start=1):
                chunk_id = hit.chunk.chunk_id
                route_weight = float(dict(self._config.route_weights).get(route_name, 1.0) or 1.0)
                fused_scores[chunk_id] += route_weight / float(self._config.k + rank)
                base_hits.setdefault(chunk_id, hit)
                route_scores[chunk_id][route_name] = hit.score
                if route_name not in matched_routes[chunk_id]:
                    matched_routes[chunk_id].append(route_name)

        if not fused_scores:
            return ()

        max_score = max(fused_scores.values())
        merged: List[RecallHit] = []
        for index, (chunk_id, fused_score) in enumerate(
            sorted(fused_scores.items(), key=lambda item: item[1], reverse=True),
            start=1,
        ):
            base_hit = base_hits[chunk_id]
            merged.append(
                replace(
                    base_hit,
                    score=fused_score / max_score if max_score else 0.0,
                    route="hybrid",
                    rank=index,
                    route_scores=route_scores[chunk_id],
                    matched_routes=tuple(sorted(matched_routes[chunk_id])),
                    fused_score=fused_score,
                    rrf_score=fused_score,
                    score_breakdown={"rrf": fused_score},
                    metadata={**dict(base_hit.metadata), "source_routes": tuple(sorted(matched_routes[chunk_id]))},
                )
            )
        return tuple(merged)


class HybridRetrieverService:
    def __init__(
        self,
        dense_retriever: DenseRetriever,
        sparse_retriever: SparseRetriever,
        metadata_retriever: MetadataRetriever,
        reranker: Optional[Reranker] = None,
        config: Optional[Any] = None,
        *,
        fusion: Optional[ReciprocalRankFusion] = None,
        parent_child_resolver: Optional[ParentChildResolver] = None,
        rewrite_service: Optional[QueryRewriteService] = None,
        llm_rewrite_enabled: bool = False,
        llm_rewrite_retry_limit: int = 1,
        hyde_enabled: bool = False,
    ) -> None:
        self._dense_retriever = dense_retriever
        self._sparse_retriever = sparse_retriever
        self._metadata_retriever = metadata_retriever
        self._reranker = reranker or HeuristicReranker()
        self._config = config
        self._fusion = fusion or ReciprocalRankFusion()
        self._parent_child_resolver = parent_child_resolver
        self._rewrite_service = rewrite_service
        self._llm_rewrite_enabled = llm_rewrite_enabled
        self._llm_rewrite_retry_limit = max(0, llm_rewrite_retry_limit)
        self._hyde_enabled = hyde_enabled

    def retrieve(self, plan: RetrievalPlan) -> HybridRecallResult:
        plan = replace(
            plan,
            extra={
                **dict(plan.extra),
                "metadata_filter_confidence_threshold": getattr(
                    self._config,
                    "metadata_filter_confidence_threshold",
                    0.5,
                ),
            },
        )
        plan = self._apply_hyde(plan) or plan
        started_at = time.perf_counter()
        route_hits, route_stats = self._collect_route_hits(plan)
        rrf_started_at = time.perf_counter()
        fused_hits = self._limit_fused_hits(self._fusion.fuse(route_hits))
        rrf_latency_ms = (time.perf_counter() - rrf_started_at) * 1000.0
        rerank_started_at = time.perf_counter()
        reranked_hits = self._rerank(plan, fused_hits)
        rerank_latency_ms = (time.perf_counter() - rerank_started_at) * 1000.0
        llm_rewrite_applied = False

        if not reranked_hits and self._hyde_enabled and self._rewrite_service is not None and not bool(plan.hyde_applied):
            hyde_plan = self._retry_with_hyde(plan)
            if hyde_plan is not None:
                plan = hyde_plan
                route_hits, route_stats = self._collect_route_hits(plan)
                rrf_started_at = time.perf_counter()
                fused_hits = self._limit_fused_hits(self._fusion.fuse(route_hits))
                rrf_latency_ms = (time.perf_counter() - rrf_started_at) * 1000.0
                rerank_started_at = time.perf_counter()
                reranked_hits = self._rerank(plan, fused_hits)
                rerank_latency_ms = (time.perf_counter() - rerank_started_at) * 1000.0

        if not reranked_hits and self._rewrite_service is not None and self._llm_rewrite_enabled and self._llm_rewrite_retry_limit > 0:
            rewritten_plan = self._retry_with_llm(plan)
            if rewritten_plan is not None:
                llm_rewrite_applied = True
                plan = rewritten_plan
                route_hits, route_stats = self._collect_route_hits(plan)
                rrf_started_at = time.perf_counter()
                fused_hits = self._limit_fused_hits(self._fusion.fuse(route_hits))
                rrf_latency_ms = (time.perf_counter() - rrf_started_at) * 1000.0
                rerank_started_at = time.perf_counter()
                reranked_hits = self._rerank(plan, fused_hits)
                rerank_latency_ms = (time.perf_counter() - rerank_started_at) * 1000.0

        resolved_route_hits = {name: self._resolve_hits(hits) for name, hits in route_hits.items()}
        resolved_fused_hits = self._resolve_hits(fused_hits)
        resolved_reranked_hits = self._resolve_hits(reranked_hits)
        degraded_routes = tuple(name for name, stats in route_stats.items() if stats.get("degraded"))
        fallback_reason_by_route = {
            name: str(stats.get("fallback_reason") or "")
            for name, stats in route_stats.items()
            if stats.get("fallback_reason")
        }
        total_latency_ms = (time.perf_counter() - started_at) * 1000.0

        metrics = {
            "dense_hit_count": len(resolved_route_hits.get("dense", ())),
            "sparse_hit_count": len(resolved_route_hits.get("sparse", ())),
            "metadata_hit_count": len(resolved_route_hits.get("metadata", ())),
            "retrieval_hit_count": len(resolved_reranked_hits),
            "retrieval_top_score": resolved_reranked_hits[0].score if resolved_reranked_hits else 0.0,
            "dense_latency_ms": float(route_stats.get("dense", {}).get("latency_ms", 0.0)),
            "sparse_latency_ms": float(route_stats.get("sparse", {}).get("latency_ms", 0.0)),
            "metadata_latency_ms": float(route_stats.get("metadata", {}).get("latency_ms", 0.0)),
            "embedding_latency_ms": float(route_stats.get("dense", {}).get("embedding_latency_ms", 0.0)),
            "qdrant_search_latency_ms": float(route_stats.get("dense", {}).get("qdrant_search_latency_ms", 0.0)),
            "embedding_cache_hit": bool(route_stats.get("dense", {}).get("embedding_cache_hit", False)),
            "rrf_latency_ms": float(rrf_latency_ms),
            "rerank_latency_ms": float(rerank_latency_ms),
            "total_latency_ms": float(total_latency_ms),
            "fallback_reason": ";".join(
                reason for reason in dict.fromkeys(reason for reason in fallback_reason_by_route.values() if reason)
            ),
            "fallback_reason_by_route": fallback_reason_by_route,
            "degraded_rate": (len(degraded_routes) / float(len(route_stats) or 1)),
            "working_route_count": sum(1 for stats in route_stats.values() if bool(stats.get("working"))),
            "failed_route_count": sum(1 for stats in route_stats.values() if stats.get("state") == "failed"),
            "empty_route_count": sum(1 for stats in route_stats.values() if stats.get("state") == "empty"),
            "hyde_enabled": self._hyde_enabled,
            "hyde_applied": bool(plan.hyde_applied),
            "hyde_trigger_reason": plan.hyde_trigger_reason or "",
            "hyde_passage_length": len(plan.hyde_passage or ""),
            "llm_rewrite_enabled": self._llm_rewrite_enabled,
            "llm_rewrite_retry_limit": self._llm_rewrite_retry_limit,
            "llm_rewrite_applied": llm_rewrite_applied,
            "route_weights": dict(getattr(self._fusion._config, "route_weights", {})),
            "policy_snapshot": self._policy_snapshot(),
        }
        debug_trace = self._build_trace(
            plan=plan,
            route_hits=resolved_route_hits,
            route_stats=route_stats,
            fused_hits=resolved_fused_hits,
            reranked_hits=resolved_reranked_hits,
            metrics=metrics,
            final_retrieval_filters=_serialize_final_filters(plan),
        )
        retrieval_strategy = "dense+sparse+metadata->rrf->rerank"
        if plan.hyde_applied:
            retrieval_strategy += "+hyde"
        if plan.step_back_query or plan.rewritten_queries or plan.supplemental_queries:
            retrieval_strategy += "+multiquery"
        _LOGGER.info(
            "rag_retrieval_trace",
            extra={"retrieval_debug": debug_trace.to_dict()},
        )
        return HybridRecallResult(
            hits=tuple(resolved_reranked_hits),
            retrieval_strategy=retrieval_strategy,
            retrieval_kind="hybrid",
            collection_name=self._infer_collection_name(),
            source_domain=self._infer_source_domain(),
            dense_hits=resolved_route_hits.get("dense", ()),
            sparse_hits=resolved_route_hits.get("sparse", ()),
            metadata_hits=resolved_route_hits.get("metadata", ()),
            fused_hits=resolved_fused_hits,
            reranked_hits=tuple(resolved_reranked_hits),
            degraded_routes=degraded_routes,
            metrics=metrics,
            query_plan=plan,
            debug_trace=debug_trace,
        )

    def _infer_collection_name(self) -> str:
        for retriever in (self._dense_retriever, self._sparse_retriever, self._metadata_retriever):
            for attr in ("collection_name", "_collection_name"):
                value = getattr(retriever, attr, "")
                if value:
                    return str(value)
        return ""

    def _infer_source_domain(self) -> str:
        for retriever in (self._dense_retriever, self._sparse_retriever, self._metadata_retriever):
            for attr in ("source_domain", "_source_domain"):
                value = getattr(retriever, attr, "")
                if value:
                    return str(value)
        return "local_life_hybrid"

    def _collect_route_hits(self, plan: RetrievalPlan) -> Tuple[Dict[str, Sequence[RecallHit]], Dict[str, Dict[str, Any]]]:
        route_specs = (
            ("dense", self._dense_retriever),
            ("sparse", self._sparse_retriever),
            ("metadata", self._metadata_retriever),
        )
        try:
            route_results = asyncio.run(self._collect_route_hits_async(route_specs, plan))
        except RuntimeError:
            route_results = self._collect_route_hits_sync_fallback(route_specs, plan)

        route_hits: Dict[str, Sequence[RecallHit]] = {}
        route_stats: Dict[str, Dict[str, Any]] = {}
        for route_name, _retriever in route_specs:
            hits, stats = route_results.get(route_name, ((), {}))
            route_hits[route_name] = hits
            route_stats[route_name] = stats
        return route_hits, route_stats

    async def _collect_route_hits_async(
        self,
        route_specs: Sequence[Tuple[str, RetrieverRoute]],
        plan: RetrievalPlan,
    ) -> Dict[str, Tuple[Sequence[RecallHit], Dict[str, Any]]]:
        coroutines = [
            self._collect_route_hits_for_route_async(route_name, retriever, plan)
            for route_name, retriever in route_specs
        ]
        settled = await asyncio.gather(*coroutines, return_exceptions=True)
        route_results: Dict[str, Tuple[Sequence[RecallHit], Dict[str, Any]]] = {}
        for (route_name, _retriever), outcome in zip(route_specs, settled):
            if isinstance(outcome, Exception):
                _LOGGER.exception("rag_route_failed", extra={"route": route_name})
                started_at = time.perf_counter()
                route_results[route_name] = (
                    (),
                    self._summarize_route_hits(
                        (),
                        started_at=started_at,
                        degraded=True,
                        fallback_reason="route_failed",
                        query_count=len(self._route_queries_for(route_name, plan)),
                    ),
                )
                continue
            route_results[route_name] = outcome
        return route_results

    async def _collect_route_hits_for_route_async(
        self,
        route_name: str,
        retriever: RetrieverRoute,
        plan: RetrievalPlan,
    ) -> Tuple[Sequence[RecallHit], Dict[str, Any]]:
        return await asyncio.to_thread(self._collect_route_hits_for_route, route_name, retriever, plan)

    def _collect_route_hits_sync_fallback(
        self,
        route_specs: Sequence[Tuple[str, RetrieverRoute]],
        plan: RetrievalPlan,
    ) -> Dict[str, Tuple[Sequence[RecallHit], Dict[str, Any]]]:
        route_results: Dict[str, Tuple[Sequence[RecallHit], Dict[str, Any]]] = {}
        for route_name, retriever in route_specs:
            try:
                route_results[route_name] = self._collect_route_hits_for_route(route_name, retriever, plan)
            except Exception:  # pragma: no cover - defensive fallback
                _LOGGER.exception("rag_route_failed", extra={"route": route_name})
                started_at = time.perf_counter()
                route_results[route_name] = (
                    (),
                    self._summarize_route_hits(
                        (),
                        started_at=started_at,
                        degraded=True,
                        fallback_reason="route_failed",
                        query_count=len(self._route_queries_for(route_name, plan)),
                    ),
                )
        return route_results

    def _collect_route_hits_for_route(
        self,
        route_name: str,
        retriever: RetrieverRoute,
        plan: RetrievalPlan,
    ) -> Tuple[Sequence[RecallHit], Dict[str, Any]]:
        started_at = time.perf_counter()
        route_queries = self._route_queries_for(route_name, plan)
        collected_hits, had_error = self._collect_hits_for_queries(retriever, route_name, plan, route_queries)
        route_hits = self._merge_route_hits(collected_hits)
        route_stats = self._summarize_route_hits(
            route_hits,
            started_at=started_at,
            degraded=True if had_error else None,
            fallback_reason="route_failed" if had_error else "",
            query_count=len(route_queries),
        )
        return route_hits, route_stats

    def _rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        if not hits:
            return ()
        limit = plan.rerank_top_k or getattr(self._config, "rerank_top_k", 8) or 8
        head = tuple(hits[:limit])
        tail = tuple(hits[limit:])
        reranked_head = tuple(self._reranker.rerank(plan, head)) if self._reranker is not None else head
        return reranked_head + tail

    def _limit_fused_hits(self, hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        limit = getattr(self._config, "fusion_top_k", 15)
        if limit is None:
            limit = 15
        limit = int(limit)
        if limit <= 0:
            return ()
        return tuple(hits[:limit])

    def _resolve_hits(self, hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        if self._parent_child_resolver is None:
            return tuple(hits)
        return self._parent_child_resolver.resolve_hits(hits)

    def _summarize_route_hits(
        self,
        hits: Sequence[RecallHit],
        *,
        started_at: float,
        degraded: Optional[bool] = None,
        fallback_reason: str = "",
        query_count: int = 0,
    ) -> Dict[str, Any]:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        route_degraded = degraded if degraded is not None else any(bool(hit.metadata.get("degraded")) for hit in hits)
        if degraded is None and not route_degraded:
            route_degraded = any(bool(str(hit.metadata.get("fallback_reason") or "").strip()) for hit in hits)
        reasons: List[str] = []
        if fallback_reason:
            reasons.append(fallback_reason)
        for hit in hits:
            reason = str(hit.metadata.get("fallback_reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        if query_count <= 0:
            state = "skipped"
        elif hits and route_degraded:
            state = "degraded"
        elif hits:
            state = "working"
        elif route_degraded:
            state = "failed"
        else:
            state = "empty"
        if not hits and not reasons:
            reasons.append("no_hits")
        embedding_cache_hit = any(bool(hit.metadata.get("embedding_cache_hit")) for hit in hits)
        embedding_latency_ms = max(float(hit.metadata.get("embedding_latency_ms", 0.0) or 0.0) for hit in hits) if hits else 0.0
        qdrant_search_latency_ms = max(float(hit.metadata.get("qdrant_search_latency_ms", 0.0) or 0.0) for hit in hits) if hits else 0.0
        return {
            "latency_ms": elapsed_ms,
            "hit_count": len(hits),
            "query_count": query_count,
            "degraded": route_degraded,
            "working": bool(hits),
            "state": state,
            "fallback_reason": ";".join(reasons),
            "embedding_cache_hit": embedding_cache_hit,
            "embedding_latency_ms": embedding_latency_ms,
            "qdrant_search_latency_ms": qdrant_search_latency_ms,
        }

    def _route_queries_for(self, route_name: str, plan: RetrievalPlan) -> Tuple[str, ...]:
        queries: List[str] = []
        if route_name == "dense":
            queries.extend([plan.semantic_query, plan.step_back_query or ""])
            queries.extend(plan.rewritten_queries)
            queries.extend(plan.supplemental_queries)
        elif route_name == "sparse":
            queries.extend([plan.keyword_query, plan.step_back_query or ""])
            if plan.hyde_passage:
                queries.append(plan.hyde_passage)
            queries.extend(plan.rewritten_queries)
            queries.extend(plan.supplemental_queries)
        else:
            queries.extend([plan.semantic_query, plan.keyword_query, plan.step_back_query or ""])
            queries.extend(plan.rewritten_queries)
            queries.extend(plan.supplemental_queries)
        return tuple(_dedupe_queries(queries))

    def _collect_hits_for_queries(
        self,
        retriever: RetrieverRoute,
        route_name: str,
        plan: RetrievalPlan,
        queries: Sequence[str],
    ) -> Tuple[Tuple[RecallHit, ...], bool]:
        collected: List[RecallHit] = []
        had_error = False
        for index, query in enumerate(queries, start=1):
            variant_plan = replace(
                plan,
                semantic_query=query if route_name in {"dense", "metadata"} else plan.semantic_query,
                keyword_query=query if route_name == "sparse" else plan.keyword_query,
                extra={
                    **dict(plan.extra),
                    "query_variant": query,
                    "query_variant_rank": index,
                },
            )
            try:
                hits = tuple(retriever.retrieve(variant_plan))
            except Exception:  # pragma: no cover - defensive fallback
                _LOGGER.exception("rag_route_variant_failed", extra={"route": route_name, "query": query})
                hits = ()
                had_error = True
            for hit in hits:
                collected.append(
                    replace(
                        hit,
                        metadata={
                            **dict(hit.metadata),
                            "query_variant": query,
                            "query_variant_rank": index,
                        },
                    )
                )
        return tuple(collected), had_error

    def _merge_route_hits(self, hits: Sequence[RecallHit]) -> Tuple[RecallHit, ...]:
        if not hits:
            return ()
        merged: Dict[str, RecallHit] = {}
        for hit in hits:
            chunk_id = hit.chunk.chunk_id
            current = merged.get(chunk_id)
            if current is None:
                merged[chunk_id] = hit
                continue
            best = hit if (hit.score, hit.rerank_score or 0.0) >= (current.score, current.rerank_score or 0.0) else current
            other = current if best is hit else hit
            merged_metadata = {**dict(other.metadata), **dict(best.metadata)}
            merged_route_scores = dict(current.route_scores)
            for route_name, route_score in hit.route_scores.items():
                merged_route_scores[route_name] = max(float(merged_route_scores.get(route_name, 0.0) or 0.0), float(route_score or 0.0))
            merged[chunk_id] = replace(
                best,
                route_scores=merged_route_scores,
                matched_routes=tuple(sorted(set(current.matched_routes) | set(hit.matched_routes))),
                fused_score=max(current.fused_score, hit.fused_score),
                rrf_score=max(current.rrf_score, hit.rrf_score),
                rerank_score=max(
                    current.rerank_score or 0.0,
                    hit.rerank_score or 0.0,
                )
                or None,
                metadata=merged_metadata,
            )
        return tuple(sorted(merged.values(), key=lambda item: item.score, reverse=True))

    def _retry_with_llm(self, plan: RetrievalPlan) -> Optional[RetrievalPlan]:
        if self._rewrite_service is None:
            return None
        try:
            return self._rewrite_service.rewrite_with_llm(plan, fallback_reason="empty_recall")
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("rag_llm_rewrite_failed")
            return None

    def _retry_with_hyde(self, plan: RetrievalPlan) -> Optional[RetrievalPlan]:
        if self._rewrite_service is None or not self._hyde_enabled:
            return None
        try:
            hyde_payload = self._rewrite_service.build_hyde_payload(plan, fallback_reason="empty_recall")
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("rag_hyde_rewrite_failed")
            return None
        if not hyde_payload:
            return None
        hyde_passage = str(hyde_payload.get("hyde_passage") or "").strip()
        if not hyde_passage:
            return None
        extra = dict(plan.extra)
        extra.update(hyde_payload)
        extra.update(
            {
                "hyde_passage": hyde_passage,
                "hyde_applied": True,
                "hyde_source": hyde_payload.get("hyde_source", "llm"),
            }
        )
        return replace(
            plan,
            hyde_passage=hyde_passage,
            hyde_trigger_reason=str(hyde_payload.get("hyde_trigger_reason") or "empty_recall"),
            hyde_applied=True,
            extra=extra,
        )

    def _apply_hyde(self, plan: RetrievalPlan) -> Optional[RetrievalPlan]:
        if self._rewrite_service is None or not self._hyde_enabled or plan.hyde_applied:
            return None
        try:
            hyde_payload = self._rewrite_service.build_hyde_payload(plan)
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("rag_hyde_generation_failed")
            return None
        if not hyde_payload:
            return None
        hyde_passage = str(hyde_payload.get("hyde_passage") or "").strip()
        if not hyde_passage:
            return None
        extra = dict(plan.extra)
        extra.update(hyde_payload)
        extra.update(
            {
                "hyde_passage": hyde_passage,
                "hyde_applied": True,
                "hyde_source": hyde_payload.get("hyde_source", "llm"),
            }
        )
        return replace(
            plan,
            hyde_passage=hyde_passage,
            hyde_trigger_reason=str(hyde_payload.get("hyde_trigger_reason") or ""),
            hyde_applied=True,
            extra=extra,
        )

    def _policy_snapshot(self) -> Dict[str, Any]:
        fusion_config = getattr(self._fusion, "_config", None)
        return {
            "dense_top_k": getattr(self._config, "dense_top_k", 10),
            "sparse_top_k": getattr(self._config, "sparse_top_k", 8),
            "metadata_top_k": getattr(self._config, "metadata_top_k", 8),
            "fusion_top_k": getattr(self._config, "fusion_top_k", 15),
            "rerank_top_k": getattr(self._config, "rerank_top_k", 8),
            "llm_rewrite_enabled": self._llm_rewrite_enabled,
            "llm_rewrite_retry_limit": self._llm_rewrite_retry_limit,
            "hyde_enabled": self._hyde_enabled,
            "rrf_k": getattr(fusion_config, "k", 60),
            "route_weights": dict(getattr(fusion_config, "route_weights", {})),
            "metadata_filter_confidence_threshold": getattr(self._config, "metadata_filter_confidence_threshold", 1.0),
        }

    def _build_trace(
        self,
        *,
        plan: RetrievalPlan,
        route_hits: Mapping[str, Sequence[RecallHit]],
        route_stats: Mapping[str, Mapping[str, Any]],
        fused_hits: Sequence[RecallHit],
        reranked_hits: Sequence[RecallHit],
        metrics: Mapping[str, Any],
        final_retrieval_filters: Mapping[str, Any],
    ) -> RetrievalTrace:
        return RetrievalTrace(
            raw_query=_sanitize_trace_text(plan.extra.get("raw_query") or ""),
            semantic_query=_sanitize_trace_text(plan.semantic_query),
            keyword_query=_sanitize_trace_text(plan.keyword_query),
            retrieval_filters=plan.retrieval_filters,
            final_retrieval_filters=dict(final_retrieval_filters),
            preferred_chunk_types=plan.preferred_chunk_types,
            dense_hits=tuple(RetrievalTraceItem.from_hit(hit) for hit in route_hits.get("dense", ())),
            sparse_hits=tuple(RetrievalTraceItem.from_hit(hit) for hit in route_hits.get("sparse", ())),
            metadata_hits=tuple(RetrievalTraceItem.from_hit(hit) for hit in route_hits.get("metadata", ())),
            fused_hits=tuple(RetrievalTraceItem.from_hit(hit) for hit in fused_hits),
            reranked_hits=tuple(RetrievalTraceItem.from_hit(hit) for hit in reranked_hits),
            evidence_kept=(),
            evidence_rejected=(),
            degraded=any(bool(stats.get("degraded")) for stats in route_stats.values()),
            empty=not bool(reranked_hits),
            metrics=dict(metrics),
            extra={
                "retrieval_strategy": "dense+sparse+metadata->rrf->rerank"
                + ("+multiquery" if (plan.step_back_query or plan.rewritten_queries or plan.supplemental_queries) else ""),
                "degraded_routes": [route for route, stats in route_stats.items() if stats.get("degraded")],
                "working_routes": [route for route, stats in route_stats.items() if stats.get("working")],
                "failed_routes": [route for route, stats in route_stats.items() if stats.get("state") == "failed"],
                "empty_routes": [route for route, stats in route_stats.items() if stats.get("state") == "empty"],
                "skipped_routes": [route for route, stats in route_stats.items() if stats.get("state") == "skipped"],
                "route_stats": dict(route_stats),
                "fallback_reason": metrics.get("fallback_reason", ""),
                "fallback_reason_by_route": dict(metrics.get("fallback_reason_by_route", {})),
                "query_plan": plan.extra,
                "step_back_query": plan.step_back_query,
                "rewritten_queries": list(plan.rewritten_queries),
                "supplemental_queries": list(plan.supplemental_queries),
                "hyde_passage": plan.hyde_passage,
                "hyde_trigger_reason": plan.hyde_trigger_reason,
                "hyde_applied": plan.hyde_applied,
                "evidence_stage": "pre_evidence_governance",
                "evidence_kept_note": "evidence_kept_is_populated_after_evidence_governance",
                "policy_snapshot": metrics.get("policy_snapshot", {}),
            },
        )


def _tokenize(text: str) -> Tuple[str, ...]:
    if not text:
        return ()
    return tuple(token.lower() for token in _TOKEN_PATTERN.findall(text))


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    return intersection / float(union or 1)


def _term_overlap(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        return 0.0
    right_set = set(right)
    matched = sum(1 for token in left if token in right_set)
    return matched / float(max(len(left), 1))


_HARD_METADATA_KEYS = {
    "tenant",
    "tenant_id",
    "workspace_id",
    "org_id",
    "organization_id",
    "owner_id",
    "user_id",
    "permission",
    "permissions",
    "access_scope",
    "acl",
    "visibility",
    "version",
}

_SOFT_METADATA_WEIGHTS = {
    "category": 0.22,
    "subcategory": 0.18,
    "difficulty": 0.1,
    "source_type": 0.12,
    "chunk_type": 0.18,
    "tags": 0.2,
}


def _dedupe_queries(queries: Sequence[str]) -> Tuple[str, ...]:
    seen = set()
    ordered: List[str] = []
    for query in queries:
        normalized = (query or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return tuple(ordered)


def _serialize_final_filters(plan: RetrievalPlan) -> Dict[str, Any]:
    extra = dict(plan.retrieval_filters.extra)
    for key in _RUNTIME_FILTER_KEYS:
        if key in plan.extra and key not in extra:
            extra[key] = plan.extra[key]
    return {
        "category": list(plan.retrieval_filters.category),
        "subcategory": list(plan.retrieval_filters.subcategory),
        "difficulty": list(plan.retrieval_filters.difficulty),
        "source_type": list(plan.retrieval_filters.source_type),
        "chunk_type": list(plan.retrieval_filters.chunk_type),
        "version": list(plan.retrieval_filters.version),
        "tags": list(plan.retrieval_filters.tags),
        "extra": extra,
    }


def _sanitize_trace_text(value: Any, *, limit: int = 256) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _is_hard_metadata_key(key: str) -> bool:
    normalized = _normalize_value(key)
    return normalized in _HARD_METADATA_KEYS or normalized.startswith("tenant_") or normalized.startswith("permission_")


def _coerce_filter_values(value: Any) -> Tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(str(item) for item in value.values() if item)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if item)
    return (str(value),)


def _extract_soft_metadata_filters(plan: RetrievalPlan) -> Dict[str, Tuple[str, ...]]:
    if plan.metadata_filter_mode == "hard":
        return {}
    return {key: values for key, values in plan.retrieval_filters.soft_fields().items() if values}


def _extract_hard_metadata_filters(plan: RetrievalPlan) -> Dict[str, Tuple[str, ...]]:
    hard: Dict[str, Tuple[str, ...]] = {}
    for key, values in plan.retrieval_filters.hard_fields().items():
        if values:
            hard[key] = values
    for key, value in plan.retrieval_filters.extra.items():
        if _is_hard_metadata_key(str(key)):
            normalized = _coerce_filter_values(value)
            if normalized:
                hard[str(key)] = normalized
    if plan.metadata_filter_mode == "hard":
        for key, values in plan.retrieval_filters.soft_fields().items():
            if values:
                hard[key] = values
    return hard


def _metadata_value_for_key(chunk: KnowledgeChunk, key: str) -> Any:
    if key == "category":
        return chunk.category
    if key == "subcategory":
        return chunk.subcategory
    if key == "difficulty":
        return chunk.difficulty
    if key == "source_type":
        return chunk.source_type
    if key == "chunk_type":
        return chunk.chunk_type
    if key == "version":
        return chunk.version
    if key == "tags":
        return chunk.tags
    return chunk.metadata.get(key)


def _value_matches(actual: Any, expected: Sequence[str]) -> bool:
    actual_values = _coerce_filter_values(actual)
    expected_values = {value.lower() for value in expected if value}
    if not expected_values:
        return True
    if not actual_values:
        return False
    return any(value.lower() in expected_values for value in actual_values)


def _matches_hard_filters(chunk: KnowledgeChunk, filters: Mapping[str, Tuple[str, ...]]) -> bool:
    for key, expected in filters.items():
        if not _value_matches(_metadata_value_for_key(chunk, key), expected):
            return False
    return True


def _hard_metadata_score(chunk: KnowledgeChunk, filters: Mapping[str, Tuple[str, ...]]) -> float:
    if not filters:
        return 0.0
    matched = 0
    total = 0
    for key, expected in filters.items():
        total += 1
        if _value_matches(_metadata_value_for_key(chunk, key), expected):
            matched += 1
    return matched / float(total or 1)


def _soft_metadata_score(chunk: KnowledgeChunk, filters: Mapping[str, Tuple[str, ...]]) -> float:
    if not filters:
        return 0.0
    total_weight = 0.0
    matched_weight = 0.0
    for key, expected in filters.items():
        weight = _SOFT_METADATA_WEIGHTS.get(key, 0.08)
        total_weight += weight
        if _value_matches(_metadata_value_for_key(chunk, key), expected):
            matched_weight += weight
    return matched_weight / float(total_weight or 1.0)


def _matches_filters(chunk: KnowledgeChunk, filters: RetrievalFilters) -> bool:
    checks = (
        (filters.category, chunk.category),
        (filters.subcategory, chunk.subcategory),
        (filters.difficulty, chunk.difficulty),
        (filters.source_type, chunk.source_type),
        (filters.chunk_type, chunk.chunk_type),
        (filters.version, chunk.version),
    )
    for expected, actual in checks:
        normalized_expected = {_normalize_value(value) for value in expected if value}
        normalized_actual = _normalize_value(actual)
        if normalized_expected and normalized_actual not in normalized_expected:
            return False
    if filters.tags and not {_normalize_value(tag) for tag in filters.tags}.issubset(
        {_normalize_value(tag) for tag in chunk.tags}
    ):
        return False
    for key, expected in filters.extra.items():
        actual = chunk.metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            normalized_expected = {_normalize_value(value) for value in expected if value}
            if _normalize_value(actual) not in normalized_expected:
                return False
        elif _normalize_value(actual) != _normalize_value(expected):
            return False
    return True


def _count_filter_constraints(filters: RetrievalFilters) -> int:
    total = 0
    for values in filters.as_dict().values():
        if values:
            total += 1
    total += len(filters.extra)
    return total


def _count_filter_matches(chunk: KnowledgeChunk, filters: RetrievalFilters) -> int:
    matches = 0
    checks = (
        (filters.category, chunk.category),
        (filters.subcategory, chunk.subcategory),
        (filters.difficulty, chunk.difficulty),
        (filters.source_type, chunk.source_type),
        (filters.chunk_type, chunk.chunk_type),
        (filters.version, chunk.version),
    )
    for expected, actual in checks:
        normalized_expected = {_normalize_value(value) for value in expected if value}
        if normalized_expected and _normalize_value(actual) in normalized_expected:
            matches += 1
    if filters.tags and {_normalize_value(tag) for tag in filters.tags}.issubset(
        {_normalize_value(tag) for tag in chunk.tags}
    ):
        matches += 1
    for key, expected in filters.extra.items():
        actual = chunk.metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            normalized_expected = {_normalize_value(value) for value in expected if value}
            if _normalize_value(actual) in normalized_expected:
                matches += 1
        elif _normalize_value(actual) == _normalize_value(expected):
            matches += 1
    return matches


def _normalize_value(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_points(response: Any) -> Sequence[Any]:
    if response is None:
        return ()
    if isinstance(response, tuple) and len(response) == 2:
        return response[0] or ()
    points = getattr(response, "points", None)
    if points is not None:
        return points or ()
    if isinstance(response, Mapping):
        return response.get("points", ()) or ()
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes, bytearray)):
        return response
    return ()


def _point_to_chunk(point: Any) -> Optional[KnowledgeChunk]:
    payload = getattr(point, "payload", None)
    if payload is None and isinstance(point, Mapping):
        payload = point.get("payload")
    if not isinstance(payload, Mapping):
        return None
    return KnowledgeChunk.from_payload(payload, fallback_chunk_id=str(getattr(point, "id", "") or ""))  # type: ignore[arg-type]


def _point_score(point: Any) -> float:
    score = getattr(point, "score", None)
    if score is None and isinstance(point, Mapping):
        score = point.get("score")
    try:
        return float(score or 0.0)
    except Exception:
        return 0.0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0
