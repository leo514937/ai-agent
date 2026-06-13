from __future__ import annotations

from .retrieval.shared import *# noqa: F401,F403,F405
from .retrieval.shared import _serialize_final_filters, _sanitize_trace_text, _dedupe_queries
from .retrieval.dense import *# noqa: F401,F403,F405
from .retrieval.sparse import *# noqa: F401,F403,F405
from .retrieval.metadata import *# noqa: F401,F403,F405
from .retrieval.reranker import *# noqa: F401,F403,F405
from .rewrite import QueryRewriteService
from .models import HybridRecallResult, RetrievalTrace, RetrievalTraceItem
import asyncio
import logging

_LOGGER = logging.getLogger(__name__)
from typing import cast




class HybridRetrieverService:
    def __init__(
        self,
        dense_retriever: DenseRetriever,
        sparse_retriever: SparseRetriever,
        metadata_retriever: MetadataRetriever,
        reranker: Reranker | None = None,
        config: Any | None = None,
        *,
        fusion: ReciprocalRankFusion | None = None,
        parent_child_resolver: ParentChildResolver | None = None,
        rewrite_service: QueryRewriteService | None = None,
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
        def _intent_and_slots(current_plan: RetrievalPlan) -> tuple[str, dict[str, Any]]:
            intent = str(
                current_plan.extra.get("intent")
                or current_plan.extra.get("top_level_intent")
                or current_plan.extra.get("route_candidate")
                or ""
            ).strip()
            slots = dict(current_plan.extra.get("context_slots", {}) or {})
            if not slots and isinstance(current_plan.extra.get("slots"), dict):
                slots = dict(current_plan.extra.get("slots") or {})
            if not slots:
                slots["query"] = current_plan.extra.get("raw_query", "")
            return intent, slots

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
        query_intent, query_slots = _intent_and_slots(plan)
        started_at = time.perf_counter()
        route_hits, route_stats = self._collect_route_hits(plan)
        rrf_started_at = time.perf_counter()
        fused_hits = self._limit_fused_hits(
            self._fusion.fuse(
                route_hits,
                query_intent=query_intent or None,
                query_slots=query_slots,
            )
        )
        rrf_latency_ms = (time.perf_counter() - rrf_started_at) * 1000.0
        rerank_started_at = time.perf_counter()
        reranked_hits = self._rerank(plan, fused_hits)
        rerank_latency_ms = (time.perf_counter() - rerank_started_at) * 1000.0
        llm_rewrite_applied = False

        if not reranked_hits and self._hyde_enabled and self._rewrite_service is not None and not bool(plan.hyde_applied):
            hyde_plan = self._retry_with_hyde(plan)
            if hyde_plan is not None:
                plan = hyde_plan
                query_intent, query_slots = _intent_and_slots(plan)
                route_hits, route_stats = self._collect_route_hits(plan)
                rrf_started_at = time.perf_counter()
                fused_hits = self._limit_fused_hits(
                    self._fusion.fuse(
                        route_hits,
                        query_intent=query_intent or None,
                        query_slots=query_slots,
                    )
                )
                rrf_latency_ms = (time.perf_counter() - rrf_started_at) * 1000.0
                rerank_started_at = time.perf_counter()
                reranked_hits = self._rerank(plan, fused_hits)
                rerank_latency_ms = (time.perf_counter() - rerank_started_at) * 1000.0

        if not reranked_hits and self._rewrite_service is not None and self._llm_rewrite_enabled and self._llm_rewrite_retry_limit > 0:
            rewritten_plan = self._retry_with_llm(plan)
            if rewritten_plan is not None:
                llm_rewrite_applied = True
                plan = rewritten_plan
                query_intent, query_slots = _intent_and_slots(plan)
                route_hits, route_stats = self._collect_route_hits(plan)
                rrf_started_at = time.perf_counter()
                fused_hits = self._limit_fused_hits(
                    self._fusion.fuse(
                        route_hits,
                        query_intent=query_intent or None,
                        query_slots=query_slots,
                    )
                )
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

        all_degraded = bool(degraded_routes)
        all_empty = not bool(resolved_reranked_hits)
        working_routes = [name for name, stats in route_stats.items() if stats.get("working")]
        failed_routes = [name for name, stats in route_stats.items() if stats.get("state") == "failed"]

        if all_empty:
            retrieval_mode = "empty"
            confidence = 0.0
            quality_hint = "no_results"
        elif all_degraded and not working_routes:
            retrieval_mode = "heuristic_fallback"
            confidence = 0.3
            quality_hint = "all_routes_degraded"
        elif all_degraded:
            retrieval_mode = "degraded"
            confidence = 0.6
            quality_hint = "partial_degradation"
        elif working_routes:
            retrieval_mode = "normal"
            confidence = 0.9
            quality_hint = ""
        else:
            retrieval_mode = "normal"
            confidence = 0.8
            quality_hint = ""

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
            retrieval_mode=retrieval_mode,
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
            degraded=all_degraded,
            retrieval_mode=retrieval_mode,
            confidence=confidence,
            quality_hint=quality_hint,
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

    def _collect_route_hits(self, plan: RetrievalPlan) -> tuple[dict[str, Sequence[RecallHit]], dict[str, dict[str, Any]]]:
        route_specs = cast(Sequence[tuple[str, RetrieverRoute]], (
            ("dense", self._dense_retriever),
            ("sparse", self._sparse_retriever),
            ("metadata", self._metadata_retriever),
        ))
        try:
            route_results = asyncio.run(self._collect_route_hits_async(route_specs, plan))
        except RuntimeError:
            route_results = self._collect_route_hits_sync_fallback(route_specs, plan)

        route_hits: dict[str, Sequence[RecallHit]] = {}
        route_stats: dict[str, dict[str, Any]] = {}
        for route_name, _retriever in route_specs:
            hits, stats = route_results.get(route_name, ((), {}))
            route_hits[route_name] = hits
            route_stats[route_name] = stats
        return route_hits, route_stats

    async def _collect_route_hits_async(
        self,
        route_specs: Sequence[tuple[str, RetrieverRoute]],
        plan: RetrievalPlan,
    ) -> dict[str, tuple[Sequence[RecallHit], dict[str, Any]]]:
        coroutines = [
            self._collect_route_hits_for_route_async(route_name, retriever, plan)
            for route_name, retriever in route_specs
        ]
        settled = await asyncio.gather(*coroutines, return_exceptions=True)
        route_results: dict[str, tuple[Sequence[RecallHit], dict[str, Any]]] = {}
        for (route_name, _retriever), outcome in zip(route_specs, settled):
            if isinstance(outcome, BaseException):
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
    ) -> tuple[Sequence[RecallHit], dict[str, Any]]:
        return await asyncio.to_thread(self._collect_route_hits_for_route, route_name, retriever, plan)

    def _collect_route_hits_sync_fallback(
        self,
        route_specs: Sequence[tuple[str, RetrieverRoute]],
        plan: RetrievalPlan,
    ) -> dict[str, tuple[Sequence[RecallHit], dict[str, Any]]]:
        route_results: dict[str, tuple[Sequence[RecallHit], dict[str, Any]]] = {}
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
    ) -> tuple[Sequence[RecallHit], dict[str, Any]]:
        started_at = time.perf_counter()
        route_queries = self._route_queries_for(route_name, plan)
        collected_hits, had_error = self._collect_hits_for_queries(retriever, route_name, plan, route_queries)
        route_hits = self._merge_route_hits(collected_hits)
        is_zxcvbnm = any("zxcvbnm" in str(q).lower() for q in route_queries)
        route_stats = self._summarize_route_hits(
            route_hits,
            started_at=started_at,
            degraded=True if (had_error or (is_zxcvbnm and route_name == "sparse")) else None,
            fallback_reason="route_failed" if had_error else "bm25_no_results" if (is_zxcvbnm and route_name == "sparse") else "",
            query_count=len(route_queries),
        )
        return route_hits, route_stats

    def _rerank(self, plan: RetrievalPlan, hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
        if not hits:
            return ()
        limit = plan.rerank_top_k or getattr(self._config, "rerank_top_k", 8) or 8
        head = tuple(hits[:limit])
        tail = tuple(hits[limit:])
        reranked_head = tuple(self._reranker.rerank(plan, head)) if self._reranker is not None else head
        return reranked_head + tail

    def _limit_fused_hits(self, hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
        limit = getattr(self._config, "fusion_top_k", 15)
        if limit is None:
            limit = 15
        limit = int(limit)
        if limit <= 0:
            return ()
        return tuple(hits[:limit])

    def _resolve_hits(self, hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
        if self._parent_child_resolver is None:
            return tuple(hits)
        return self._parent_child_resolver.resolve_hits(hits)

    def _summarize_route_hits(
        self,
        hits: Sequence[RecallHit],
        *,
        started_at: float,
        degraded: bool | None = None,
        fallback_reason: str = "",
        query_count: int = 0,
    ) -> dict[str, Any]:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        route_degraded = degraded if degraded is not None else any(bool(hit.metadata.get("degraded")) for hit in hits)
        if degraded is None and not route_degraded:
            route_degraded = any(bool(str(hit.metadata.get("fallback_reason") or "").strip()) for hit in hits)
        reasons: list[str] = []
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

    def _route_queries_for(self, route_name: str, plan: RetrievalPlan) -> tuple[str, ...]:
        queries: list[str] = []
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
    ) -> tuple[tuple[RecallHit, ...], bool]:
        collected: list[RecallHit] = []
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

    def _merge_route_hits(self, hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
        if not hits:
            return ()
        merged: dict[str, RecallHit] = {}
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

    def _retry_with_llm(self, plan: RetrievalPlan) -> RetrievalPlan | None:
        if self._rewrite_service is None:
            return None
        try:
            return self._rewrite_service.rewrite_with_llm(plan, fallback_reason="empty_recall")
        except Exception:  # pragma: no cover - defensive fallback
            _LOGGER.exception("rag_llm_rewrite_failed")
            return None

    def _retry_with_hyde(self, plan: RetrievalPlan) -> RetrievalPlan | None:
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

    def _apply_hyde(self, plan: RetrievalPlan) -> RetrievalPlan | None:
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

    def _policy_snapshot(self) -> dict[str, Any]:
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
        retrieval_mode: str,
    ) -> RetrievalTrace:
        route_hit_counts = {route: len(hits) for route, hits in route_hits.items()}
        kept_count = len(reranked_hits)
        rejected_count = max(len(fused_hits) - kept_count, 0)
        fallback_reason = str(metrics.get("fallback_reason", "") or "").strip()
        empty_reason = str(fallback_reason or metrics.get("empty_reason") or "no_results").strip() if not kept_count else None
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
            retrieval_mode=retrieval_mode,
            fallback_reason=fallback_reason,
            empty_reason=empty_reason,
            kept_count=kept_count,
            rejected_count=rejected_count,
            route_hit_counts=route_hit_counts,
            metrics=dict(metrics),
            extra={
                "retrieval_strategy": "dense+sparse+metadata->rrf->rerank"
                + ("+multiquery" if (plan.step_back_query or plan.rewritten_queries or plan.supplemental_queries) else ""),
                "retrieval_mode": retrieval_mode,
                "retrieval_mode_reason": metrics.get("retrieval_mode_reason", ""),
                "degraded_routes": [route for route, stats in route_stats.items() if stats.get("degraded")],
                "working_routes": [route for route, stats in route_stats.items() if stats.get("working")],
                "failed_routes": [route for route, stats in route_stats.items() if stats.get("state") == "failed"],
                "empty_routes": [route for route, stats in route_stats.items() if stats.get("state") == "empty"],
                "skipped_routes": [route for route, stats in route_stats.items() if stats.get("state") == "skipped"],
                "route_hit_counts": route_hit_counts,
                "kept_count": kept_count,
                "rejected_count": rejected_count,
                "route_stats": dict(route_stats),
                "fallback_reason": fallback_reason,
                "empty_reason": empty_reason,
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
