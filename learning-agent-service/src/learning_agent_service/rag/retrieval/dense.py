from __future__ import annotations

from .shared import *# noqa: F401,F403,F405

from collections.abc import Iterable, Mapping, Sequence
from collections import defaultdict
from dataclasses import replace
from typing import Any
import time

from .shared import (
    _LOGGER,
    _tokenize,
    _jaccard,
    _normalize_points,
    _point_to_chunk,
    _point_score,
    validate_qdrant_collection_shape,
    KnowledgeChunk,
    RecallHit,
    RetrievalPlan,
)
from ..protocols import DenseRetriever
from ..qdrant_filters import QdrantFilterBuilder

class ParentChildResolver:
    def __init__(self, chunks: Iterable[KnowledgeChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._chunks_by_parent_id: dict[str, list[KnowledgeChunk]] = defaultdict(list)
        self._chunks_by_parent_chunk_id: dict[str, list[KnowledgeChunk]] = defaultdict(list)
        self._chunks_by_entity_id: dict[str, list[KnowledgeChunk]] = defaultdict(list)
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

    def expand_hit(self, hit: RecallHit) -> tuple[RecallHit, ...]:
        chunk = hit.chunk
        sibling_group = self._sibling_group_for(chunk)
        if len(sibling_group) <= 1:
            return (hit,)

        allowed_source_types, allowed_roles = self._sibling_filters_for(chunk)
        expanded: list[RecallHit] = [hit]
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

    def resolve_hits(self, hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
        seen: dict[str, RecallHit] = {}
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

    def _sibling_group_for(self, chunk: KnowledgeChunk) -> tuple[KnowledgeChunk, ...]:
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

    def _sibling_filters_for(self, chunk: KnowledgeChunk) -> tuple[tuple[str, ...], tuple[str, ...]]:
        source_types = self._coerce_string_tuple(chunk.metadata.get("sibling_source_types"))
        roles = self._coerce_string_tuple(chunk.metadata.get("sibling_roles"))
        return source_types, roles

    @staticmethod
    def _normalize_key(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _coerce_string_tuple(value: object) -> tuple[str, ...]:
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
    def _dedupe_group(group: Sequence[KnowledgeChunk]) -> tuple[KnowledgeChunk, ...]:
        seen: dict[str, KnowledgeChunk] = {}
        for chunk in group:
            seen.setdefault(chunk.chunk_id, chunk)
        return tuple(sorted(seen.values(), key=lambda item: (item.source_type or "", item.chunk_type or "", item.document_id, item.chunk_id)))

class HeuristicDenseRetriever:
    route_name = "dense"

    def __init__(
        self,
        chunks: Iterable[KnowledgeChunk],
        parent_child_resolver: ParentChildResolver | None = None,
        *,
        filter_builder: QdrantFilterBuilder | None = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._resolver = parent_child_resolver
        self._filter_builder = filter_builder or QdrantFilterBuilder()

    def retrieve(self, plan: RetrievalPlan) -> Sequence[RecallHit]:
        return self._retrieve(plan, plan.semantic_query, plan.dense_top_k)

    def _retrieve(self, plan: RetrievalPlan, query: str, limit: int) -> Sequence[RecallHit]:
        query_tokens = _tokenize(query)
        scored: list[tuple[float, KnowledgeChunk]] = []
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

        hits: list[RecallHit] = []
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

class QdrantOnlineDenseRetriever:
    route_name = "dense"

    def __init__(
        self,
        *,
        client: Any,
        collection_name: str,
        vector_name: str,
        embedding_adapter: Any | None = None,
        fallback: DenseRetriever | None = None,
        enabled: bool = False,
        filter_builder: QdrantFilterBuilder | None = None,
        vector_size: int | None = None,
        distance: Any | None = None,
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
                degraded=True,
                retrieval_mode="heuristic_fallback",
                metadata={
                    **dict(hit.metadata),
                    "degraded": True,
                    "fallback_reason": reason,
                    "retrieval_mode": "heuristic_fallback",
                    "confidence": 0.3,
                    "quality_hint": f"dense_degraded:{reason}",
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

__all__ = [name for name in globals() if not name.startswith("__")]
