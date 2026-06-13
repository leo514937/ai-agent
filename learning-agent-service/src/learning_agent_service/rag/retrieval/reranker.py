from __future__ import annotations

from .shared import *# noqa: F401,F403,F405

from collections.abc import Mapping, Sequence
from collections import defaultdict
from dataclasses import replace
from typing import Any
import time

from .shared import (
    _LOGGER,
    _tokenize,
    _term_overlap,
    _point_to_chunk,
    httpx,
    RecallHit,
    RetrievalPlan,
    RRFConfig,
)
from ..protocols import Reranker
from ...domain.utils import coerce_float as _coerce_float

class HeuristicReranker:
    def rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> Sequence[RecallHit]:
        if not hits:
            return ()
        query_tokens = _tokenize(f"{plan.semantic_query} {plan.keyword_query}")
        preferred = set(plan.preferred_chunk_types)
        rescored: list[tuple[float, RecallHit, dict[str, float]]] = []
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
        reranked: list[RecallHit] = []
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
        rerank_fn: Any | None = None,
        fallback: Reranker | None = None,
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

    def _remote_rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
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
        rescored: list[RecallHit] = []
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

    def _serialize_hit(self, hit: RecallHit) -> dict[str, Any]:
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

    def _extract_remote_hits(self, payload: Any, original_hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
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
        normalized: list[RecallHit] = []
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
            ) or 0.0
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
                    route="hybrid",
                    rank=index,
                    route_scores={"hybrid": score},
                    matched_routes=("hybrid",),
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
    def __init__(self, config: RRFConfig | None = None) -> None:
        self._config = config or RRFConfig()

    def fuse(
        self,
        route_hits: Mapping[str, Sequence[RecallHit]],
        *,
        query_intent: str | None = None,
        query_slots: dict[str, Any] | None = None,
    ) -> tuple[RecallHit, ...]:
        effective_weights = self._compute_dynamic_weights(
            dict(route_hits),
            query_intent=query_intent,
            query_slots=query_slots or {},
        )

        fused_scores = defaultdict(float)
        base_hits: dict[str, RecallHit] = {}
        route_scores: dict[str, dict[str, float]] = defaultdict(dict)
        matched_routes: dict[str, list[str]] = defaultdict(list)

        for route_name, hits in route_hits.items():
            for rank, hit in enumerate(hits, start=1):
                chunk_id = hit.chunk.chunk_id
                route_weight = float(effective_weights.get(route_name, 1.0) or 1.0)
                fused_scores[chunk_id] += route_weight / float(self._config.k + rank)
                base_hits.setdefault(chunk_id, hit)
                route_scores[chunk_id][route_name] = hit.score
                if route_name not in matched_routes[chunk_id]:
                    matched_routes[chunk_id].append(route_name)

        if not fused_scores:
            return ()

        max_score = max(fused_scores.values())
        merged: list[RecallHit] = []
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
                    metadata={
                        **dict(base_hit.metadata),
                        "source_routes": tuple(sorted(matched_routes[chunk_id])),
                        "fusion_weights": dict(effective_weights),
                    },
                )
            )
        return tuple(merged)

    def _compute_dynamic_weights(
        self,
        route_hits: dict[str, Sequence[RecallHit]],
        *,
        query_intent: str | None = None,
        query_slots: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        base_weights = dict(self._config.route_weights)
        weights = dict(base_weights)

        intent = (query_intent or "").lower()
        slots = query_slots or {}

        if intent in ("compare", "recommend"):
            weights["dense"] = weights.get("dense", 1.0) * 1.2
            weights["metadata"] = weights.get("metadata", 0.6) * 0.8
        elif intent in ("follow_up", "detail"):
            has_shop = bool(slots.get("shop_name") or slots.get("shop_id"))
            if has_shop:
                weights["metadata"] = weights.get("metadata", 0.6) * 1.5
                weights["sparse"] = weights.get("sparse", 1.0) * 1.2
                weights["dense"] = weights.get("dense", 1.0) * 0.8
        elif intent == "explain":
            weights["dense"] = weights.get("dense", 1.0) * 1.1
        elif intent in ("booking", "coupon", "navigation"):
            weights["metadata"] = weights.get("metadata", 0.6) * 1.3
            weights["sparse"] = weights.get("sparse", 1.0) * 1.1

        if any(kw in str(slots.get("query", "")).lower() for kw in ("附近", "推荐", "好吃")):
            weights["dense"] = weights.get("dense", 1.0) * 1.15
            weights["metadata"] = weights.get("metadata", 0.6) * 1.1

        for route_name in list(weights.keys()):
            if route_name not in route_hits:
                continue
            hits = route_hits[route_name]
            if not hits:
                continue
            has_degraded = any(bool(h.degraded) for h in hits)
            if has_degraded:
                weights[route_name] = weights.get(route_name, 1.0) * 0.5

        total = sum(weights.values()) or 1.0
        return {k: v / total for k, v in weights.items()}

__all__ = [name for name in globals() if not name.startswith("__")]
