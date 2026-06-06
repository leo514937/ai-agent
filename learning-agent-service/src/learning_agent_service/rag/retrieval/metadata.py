from __future__ import annotations

from .shared import *# noqa: F401,F403,F405
from .dense import HeuristicDenseRetriever

from collections.abc import Sequence
from dataclasses import replace
from typing import Any
import time

from .shared import (
    _LOGGER,
    _tokenize,
    _normalize_points,
    _point_to_chunk,
    _point_score,
    validate_qdrant_collection_shape,
    _extract_hard_metadata_filters,
    _extract_soft_metadata_filters,
    _matches_hard_filters,
    _hard_metadata_score,
    _soft_metadata_score,
    _term_overlap,
    KnowledgeChunk,
    RecallHit,
    RetrievalPlan,
)
from ..protocols import MetadataRetriever
from ..qdrant_filters import QdrantFilterBuilder

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
        embedding_adapter: Any | None = None,
        fallback: MetadataRetriever | None = None,
        enabled: bool = False,
        filter_builder: QdrantFilterBuilder | None = None,
        scroll_fallback_enabled: bool = False,
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
            hits: list[RecallHit] = []
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
            hits: list[RecallHit] = []
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

__all__ = [name for name in globals() if not name.startswith("__")]
