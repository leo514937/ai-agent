from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Tuple

from learning_agent_service.domain import (
    Citation,
    CitationBuildRequest,
    EvidenceEvaluationRequest,
    EvidenceItem,
    EvidencePack,
    HybridRecallCandidate,
    HybridRecallResult as DomainHybridRecallResult,
    HybridRetrieveRequest,
    KnowledgeSearchRequest as DomainKnowledgeSearchRequest,
    KnowledgeSearchResult as DomainKnowledgeSearchResult,
    QueryRewriteRequest,
    ReferenceResolutionRequest as DomainReferenceResolutionRequest,
    ReferenceResolutionResult,
    RetrievalPlan,
)
from learning_agent_service.domain.enums import IntentType, OutputStyle

from .models import (
    Citation as InternalCitation,
    EvidenceItem as InternalEvidenceItem,
    EvidencePack as InternalEvidencePack,
    HybridRecallResult,
    KnowledgeChunk,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RecallHit,
    ReferenceResolutionRequest,
    RetrievalTrace,
    RetrievalTraceItem,
    RetrievalFilters,
    RetrievalPlan as InternalRetrievalPlan,
)
from .rewrite import QueryRewriteContext

_CN_COMPARE = "\u533a\u522b"
_CN_EXPLAIN = "\u7406\u89e3"
_CN_EXPLAIN_ALT = "\u89e3\u91ca"
_CN_HOW = "\u600e\u4e48"
_CN_THIS = "\u8fd9\u4e2a"
_CN_THAT = "\u90a3\u4e2a"
_CN_PREVIOUS = "\u4e0a\u4e00\u4e2a"
_CN_IT = "\u5b83"
_EN_FOLLOW_UP_TOKENS = ("explain", "how", "compare")


class DomainRagAdapter:
    def build_query_rewrite_context(self, request: QueryRewriteRequest) -> QueryRewriteContext:
        return QueryRewriteContext(
            raw_query=request.raw_query,
            intent=self._intent_value(request.intent),
            resolved_topic=request.reference_resolution.resolved_entity if request.reference_resolution else None,
            session_topic=request.current_topic or request.topic_hint,
            requested_output_style=self._style_value(request.requested_output_style),
            filters=self.to_internal_filters(request.base_filters),
            user_preferences=request.user_preferences,
            extra={"raw_query": request.raw_query, "intent_confidence": request.intent_confidence},
            intent_confidence=request.intent_confidence,
        )

    def build_reference_request(self, request: DomainReferenceResolutionRequest) -> ReferenceResolutionRequest:
        values = []
        if request.pending_clarification is not None:
            for option in request.pending_clarification.options:
                if option.value:
                    values.append(option.value)
                elif option.label:
                    values.append(option.label)
        message = request.raw_query.strip()
        lowered_message = message.lower()
        return ReferenceResolutionRequest(
            message=message,
            lowered_message=lowered_message,
            current_topic=request.current_topic,
            last_retrieval_topic=request.clarification_result.get("last_retrieval_topic"),
            recent_entities=tuple(request.recent_entities),
            pending_clarification_values=tuple(values),
            clarification_result=dict(request.clarification_result),
            follow_up_intent=self._looks_like_follow_up_query(request, message, lowered_message),
        )

    def to_domain_reference(self, resolution) -> ReferenceResolutionResult:
        return ReferenceResolutionResult(
            resolved=resolution.resolved,
            confidence=resolution.confidence,
            resolved_entity=resolution.resolved_entity,
            candidate_entities=list(resolution.candidate_entities),
            extra=dict(resolution.metadata),
        )

    def to_domain_plan(self, plan: InternalRetrievalPlan) -> RetrievalPlan:
        filters = plan.retrieval_filters
        extra = dict(plan.extra)
        extra.setdefault("step_back_query", plan.step_back_query)
        extra.setdefault("rewritten_queries", list(plan.rewritten_queries))
        extra.setdefault("supplemental_queries", list(plan.supplemental_queries))
        extra.setdefault("hyde_passage", plan.hyde_passage)
        extra.setdefault("hyde_trigger_reason", plan.hyde_trigger_reason)
        extra.setdefault("hyde_applied", plan.hyde_applied)
        extra.setdefault("metadata_filter_mode", plan.metadata_filter_mode)
        return RetrievalPlan(
            semantic_query=plan.semantic_query,
            keyword_query=plan.keyword_query,
            retrieval_filters={
                "category": list(filters.category),
                "subcategory": list(filters.subcategory),
                "difficulty": list(filters.difficulty),
                "source_type": list(filters.source_type),
                "chunk_type": list(filters.chunk_type),
                "version": list(filters.version),
                "tags": list(filters.tags),
                "extra": dict(filters.extra),
            },
            preferred_chunk_types=list(plan.preferred_chunk_types),
            reasoning_notes=["rewrite_query_for_retrieval"],
            extra=extra,
        )

    def to_internal_plan(
        self,
        request: RetrievalPlan | HybridRetrieveRequest | EvidenceEvaluationRequest,
        *,
        dense_top_k: int,
        sparse_top_k: int,
        metadata_top_k: int,
        rerank_top_k: int,
        max_evidence: int,
    ) -> InternalRetrievalPlan:
        plan = request.plan if hasattr(request, "plan") else request
        return InternalRetrievalPlan(
            semantic_query=plan.semantic_query,
            keyword_query=plan.keyword_query,
            retrieval_filters=self.to_internal_filters(plan.retrieval_filters),
            preferred_chunk_types=tuple(plan.preferred_chunk_types),
            step_back_query=self._optional_str(plan.extra.get("step_back_query")),
            rewritten_queries=self._coerce_query_list(plan.extra.get("rewritten_queries")),
            supplemental_queries=self._coerce_query_list(plan.extra.get("supplemental_queries")),
            hyde_passage=self._optional_str(plan.extra.get("hyde_passage")),
            hyde_trigger_reason=self._optional_str(plan.extra.get("hyde_trigger_reason")),
            hyde_applied=bool(plan.extra.get("hyde_applied", False)),
            metadata_filter_mode=self._optional_str(plan.extra.get("metadata_filter_mode")) or "soft",
            dense_top_k=dense_top_k,
            sparse_top_k=sparse_top_k,
            metadata_top_k=metadata_top_k,
            rerank_top_k=rerank_top_k,
            max_evidence=max_evidence,
            extra=dict(plan.extra),
        )

    def to_domain_hybrid(self, recall: HybridRecallResult) -> DomainHybridRecallResult:
        source_hits = tuple(recall.hits)
        dense_hits = tuple(recall.dense_hits or tuple(hit for hit in source_hits if "dense" in hit.route_scores))
        sparse_hits = tuple(recall.sparse_hits or tuple(hit for hit in source_hits if "sparse" in hit.route_scores))
        metadata_hits = tuple(recall.metadata_hits or tuple(hit for hit in source_hits if "metadata" in hit.route_scores))
        fused_hits = tuple(recall.fused_hits or source_hits)
        reranked_hits = tuple(recall.reranked_hits or source_hits)
        return DomainHybridRecallResult(
            dense_hits=self._to_domain_candidates(dense_hits),
            sparse_hits=self._to_domain_candidates(sparse_hits),
            metadata_hits=self._to_domain_candidates(metadata_hits),
            fused_hits=self._to_domain_candidates(fused_hits),
            reranked_hits=self._to_domain_candidates(reranked_hits),
            metrics=dict(recall.metrics),
            extra={
                "retrieval_strategy": recall.retrieval_strategy,
                "degraded_routes": list(recall.degraded_routes),
                "query_plan": self.to_domain_plan(recall.query_plan).model_dump(mode="json")
                if recall.query_plan is not None
                else None,
                "retrieval_debug": recall.debug_trace.to_dict() if recall.debug_trace is not None else None,
            },
        )

    def to_internal_hits(self, candidates: Iterable[HybridRecallCandidate]) -> Tuple[RecallHit, ...]:
        hits = []
        for index, candidate in enumerate(candidates, start=1):
            metadata = dict(self._candidate_mapping(candidate, "metadata", {}))
            raw = dict(self._candidate_mapping(candidate, "raw", {}))
            chunk_id = str(self._candidate_value(candidate, "chunk_id"))
            document_id = str(self._candidate_value(candidate, "document_id"))
            score = float(self._candidate_value(candidate, "score", 0.0) or 0.0)
            route = str(raw.get("route") or self._candidate_value(candidate, "route") or "hybrid")
            rank = int(raw.get("rank") or self._candidate_value(candidate, "rank") or index)
            payload = {
                **raw,
                **metadata,
                "chunk_id": chunk_id,
                "doc_id": document_id,
                "document_id": document_id,
                "text": str(self._candidate_value(candidate, "content", "") or ""),
                "title": metadata.get("title") or chunk_id,
                "chunk_type": metadata.get("chunk_type") or self._candidate_value(candidate, "chunk_type"),
            }
            chunk = KnowledgeChunk.from_payload(payload, fallback_chunk_id=chunk_id, fallback_document_id=document_id)
            if chunk is None:
                continue
            hits.append(
                RecallHit(
                    chunk=chunk,
                    score=score,
                    route=route,
                    rank=rank,
                    route_scores=dict(raw.get("route_scores", {})),
                    metadata={**dict(raw.get("metadata", {})), **metadata},
                    matched_routes=tuple(raw.get("matched_routes", ()) or self._candidate_value(candidate, "channels", ()) or ()),
                    fused_score=float(raw.get("fused_score") or raw.get("rrf_score") or 0.0),
                    rrf_score=float(raw.get("rrf_score") or 0.0),
                    rerank_score=raw.get("rerank_score"),
                    rerank_rank=int(raw.get("rerank_rank") or 0) or None,
                    rerank_model=self._optional_str(raw.get("rerank_model")),
                    source_chunk_id=self._optional_str(raw.get("source_chunk_id") or metadata.get("source_chunk_id") or chunk.chunk_id),
                    citation_chunk_id=self._optional_str(raw.get("citation_chunk_id") or metadata.get("citation_chunk_id") or chunk.chunk_id),
                    score_breakdown=dict(raw.get("score_breakdown", {})),
                    rejected_reason=raw.get("rejected_reason"),
                )
            )
        return tuple(hits)

    def to_domain_evidence_pack(self, evidence: InternalEvidencePack, plan: RetrievalPlan) -> EvidencePack:
        evidence_status = getattr(evidence.evidence_status, "value", evidence.evidence_status)
        return EvidencePack(
            items=[
                EvidenceItem(
                    chunk_id=item.chunk.chunk_id,
                    content=item.chunk.text,
                    score=item.score,
                    document_id=item.chunk.document_id,
                    chunk_type=item.chunk.chunk_type,
                    tier=item.tier,
                    citation_chunk_id=item.citation_chunk_id,
                    source_chunk_id=item.source_chunk_id,
                    parent_chunk_id=item.parent_chunk_id,
                    metadata={
                        "title": item.chunk.title,
                        "summary": item.chunk.summary,
                        "category": item.chunk.category,
                        "subcategory": item.chunk.subcategory,
                        "difficulty": item.chunk.difficulty,
                        "source_type": item.chunk.source_type,
                        "version": item.chunk.version,
                        "parent_id": item.chunk.parent_id,
                        "is_latest": item.chunk.is_latest,
                        "hash": item.chunk.hash,
                        "tags": list(item.chunk.tags),
                        "routes": list(item.routes),
                        "reasons": list(item.reasons),
                        "tier": item.tier,
                        "citation_chunk_id": item.citation_chunk_id,
                        "source_chunk_id": item.source_chunk_id,
                        "parent_chunk_id": item.parent_chunk_id,
                        **dict(item.metadata),
                    },
                )
                for item in evidence.items
            ],
            discard_summary={
                "status": evidence.status,
                "filtered_out": evidence.filtered_out,
                "rationale": list(evidence.rationale),
            },
            top_scores=[item.score for item in evidence.items],
            evidence_status=evidence_status if isinstance(evidence_status, str) else str(evidence_status),
            strong_items=[
                EvidenceItem(
                    chunk_id=item.chunk.chunk_id,
                    content=item.chunk.text,
                    score=item.score,
                    document_id=item.chunk.document_id,
                    chunk_type=item.chunk.chunk_type,
                    tier=item.tier,
                    citation_chunk_id=item.citation_chunk_id,
                    source_chunk_id=item.source_chunk_id,
                    parent_chunk_id=item.parent_chunk_id,
                    metadata={
                        "title": item.chunk.title,
                        "summary": item.chunk.summary,
                        "tier": item.tier,
                        "citation_chunk_id": item.citation_chunk_id,
                        "source_chunk_id": item.source_chunk_id,
                        "parent_chunk_id": item.parent_chunk_id,
                    },
                )
                for item in evidence.strong_items
            ],
            weak_items=[
                EvidenceItem(
                    chunk_id=item.chunk.chunk_id,
                    content=item.chunk.text,
                    score=item.score,
                    document_id=item.chunk.document_id,
                    chunk_type=item.chunk.chunk_type,
                    tier=item.tier,
                    citation_chunk_id=item.citation_chunk_id,
                    source_chunk_id=item.source_chunk_id,
                    parent_chunk_id=item.parent_chunk_id,
                    metadata={
                        "title": item.chunk.title,
                        "summary": item.chunk.summary,
                        "tier": item.tier,
                        "citation_chunk_id": item.citation_chunk_id,
                        "source_chunk_id": item.source_chunk_id,
                        "parent_chunk_id": item.parent_chunk_id,
                    },
                )
                for item in evidence.weak_items
            ],
            extra={
                "metrics": dict(evidence.metrics),
                "query_plan": plan.model_dump(mode="json"),
                "retrieval_debug": evidence.debug_trace.to_dict() if evidence.debug_trace is not None else None,
                "rejected_items": [item.to_dict() for item in evidence.rejected_items],
            },
        )

    def to_internal_evidence_pack(self, request: CitationBuildRequest | EvidencePack) -> InternalEvidencePack:
        evidence = request.evidence_pack if hasattr(request, "evidence_pack") else request
        rejected_items = tuple(
            self._rejected_item_to_trace_item(item)
            for item in evidence.extra.get("rejected_items", [])
            if isinstance(item, dict) or hasattr(item, "chunk_id")
        )
        debug_trace = None
        if isinstance(evidence.extra.get("retrieval_debug"), dict):
            debug = dict(evidence.extra.get("retrieval_debug", {}))
            debug_trace = RetrievalTrace(
                raw_query=str(debug.get("raw_query") or ""),
                semantic_query=str(debug.get("semantic_query") or ""),
                keyword_query=str(debug.get("keyword_query") or ""),
                retrieval_filters=self.to_internal_filters(debug.get("retrieval_filters", {})),
                final_retrieval_filters=dict(debug.get("final_retrieval_filters", {})),
                preferred_chunk_types=tuple(debug.get("preferred_chunk_types", [])),
                metrics=dict(debug.get("metrics", {})),
                extra=dict(debug.get("extra", {})),
            )
        def _build_internal_item(item: EvidenceItem, default_tier: str) -> InternalEvidenceItem:
            chunk = KnowledgeChunk.from_payload(
                {
                    "chunk_id": item.chunk_id,
                    "doc_id": item.document_id,
                    "document_id": item.document_id,
                    "text": item.content,
                    "title": item.metadata.get("title") or item.chunk_id,
                    "summary": item.metadata.get("summary"),
                    "category": item.metadata.get("category"),
                    "subcategory": item.metadata.get("subcategory"),
                    "chunk_type": item.chunk_type,
                    "source_type": item.metadata.get("source_type"),
                    "version": item.metadata.get("version"),
                    "tags": item.metadata.get("tags", []),
                },
                fallback_chunk_id=item.chunk_id,
                fallback_document_id=item.document_id,
            ) or KnowledgeChunk(
                chunk_id=item.chunk_id,
                document_id=item.document_id or "unknown-document",
                text=item.content,
                title=str(item.metadata.get("title") or item.chunk_id),
            )
            return InternalEvidenceItem(
                chunk=chunk,
                score=item.score,
                routes=tuple(str(route) for route in item.metadata.get("routes", []) if route),
                reasons=tuple(str(reason) for reason in item.metadata.get("reasons", []) if reason),
                tier=str(item.metadata.get("tier") or item.tier or default_tier),
                citation_chunk_id=self._optional_str(item.metadata.get("citation_chunk_id") or item.citation_chunk_id or item.chunk_id),
                source_chunk_id=self._optional_str(item.metadata.get("source_chunk_id") or item.source_chunk_id or item.chunk_id),
                parent_chunk_id=self._optional_str(item.metadata.get("parent_chunk_id") or item.parent_chunk_id or item.metadata.get("parent_id")),
                metadata={
                    "rejected_reason": item.metadata.get("rejected_reason"),
                    "summary": item.metadata.get("summary"),
                    "parent_id": item.metadata.get("parent_id"),
                    "is_latest": item.metadata.get("is_latest"),
                    "hash": item.metadata.get("hash"),
                },
            )

        items = tuple(_build_internal_item(item, "weak") for item in evidence.items)
        strong_items = tuple(_build_internal_item(item, "strong") for item in getattr(evidence, "strong_items", []))
        weak_items = tuple(_build_internal_item(item, "weak") for item in getattr(evidence, "weak_items", []))
        return InternalEvidencePack(
            items=items,
            status=str(evidence.discard_summary.get("status", "empty")),
            evidence_status=str(getattr(evidence, "evidence_status", "EMPTY") or evidence.discard_summary.get("status", "EMPTY")),
            strong_items=strong_items,
            weak_items=weak_items,
            filtered_out=int(evidence.discard_summary.get("filtered_out", 0)),
            rationale=tuple(str(reason) for reason in evidence.discard_summary.get("rationale", [])),
            metrics=dict(evidence.extra.get("metrics", {})),
            rejected_items=rejected_items,
            debug_trace=debug_trace,
        )

    def to_domain_citation(self, citation: InternalCitation) -> Citation:
        return Citation(
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            source_type=citation.source_type,
            version=citation.version,
            score=citation.score,
            title=citation.title,
            locator=str(citation.metadata.get("chunk_type") or ""),
        )

    def to_internal_search_request(self, request: DomainKnowledgeSearchRequest) -> KnowledgeSearchRequest:
        category = request.category
        if category is None:
            category_filters = request.retrieval_filters.get("category") if request.retrieval_filters else None
            if isinstance(category_filters, str):
                category = category_filters
            elif category_filters:
                category = str(list(category_filters)[0])
        return KnowledgeSearchRequest(
            query=request.topic,
            limit=request.limit,
            category=category,
            query_context={"retrieval_filters": dict(request.retrieval_filters)},
        )

    def to_domain_search_result(self, result: KnowledgeSearchResult) -> DomainKnowledgeSearchResult:
        matches = []
        citations = []
        for match in result.matches:
            citation = self.to_domain_citation(match.citation) if match.citation is not None else None
            if citation is not None:
                citations.append(citation)
            matches.append(
                {
                    "chunk_id": match.chunk.chunk_id,
                    "document_id": match.chunk.document_id,
                    "title": match.chunk.title,
                    "score": match.score,
                    "content": match.chunk.text,
                    "chunk_type": match.chunk.chunk_type,
                    "category": match.chunk.category,
                    "subcategory": match.chunk.subcategory,
                    "source_type": match.chunk.source_type,
                    "version": match.chunk.version,
                    "citation": citation.model_dump(mode="json") if citation is not None else None,
                }
            )
        domain_plan = self.to_domain_plan(result.plan)
        return DomainKnowledgeSearchResult(
            matches=matches,
            evidence_pack=self.to_domain_evidence_pack(result.evidence, domain_plan),
            citations=citations,
            retrieval_strategy=self.retrieval_strategy(result.retrieval_strategy),
            extra={
                "runtime_mode": result.runtime_mode,
                "metrics": dict(result.metrics),
                "retrieval_plan": domain_plan.model_dump(mode="json"),
                "retrieval_debug": result.extra.get("retrieval_debug"),
            },
        )

    @staticmethod
    def to_internal_filters(raw_filters: Mapping[str, Any]) -> RetrievalFilters:
        def coerce(value: Any) -> Tuple[str, ...]:
            if not value:
                return ()
            if isinstance(value, str):
                return (value,)
            return tuple(str(item) for item in value if item)

        raw = dict(raw_filters or {})
        extra = dict(raw.get("extra", {}))
        for key, value in raw.items():
            if key in {"category", "subcategory", "difficulty", "source_type", "chunk_type", "version", "tags", "extra"}:
                continue
            if value in (None, ""):
                continue
            extra[key] = value

        return RetrievalFilters(
            category=coerce(raw.get("category")),
            subcategory=coerce(raw.get("subcategory")),
            difficulty=coerce(raw.get("difficulty")),
            source_type=coerce(raw.get("source_type")),
            chunk_type=coerce(raw.get("chunk_type")),
            version=coerce(raw.get("version")),
            tags=coerce(raw.get("tags")),
            extra=extra,
        )

    @staticmethod
    def retrieval_strategy(strategy: Optional[str]) -> str:
        if isinstance(strategy, str) and strategy:
            return strategy if strategy.endswith("->evidence") else strategy + "->evidence"
        return "dense+sparse+metadata->rrf->rerank->evidence"

    @staticmethod
    def _to_domain_candidates(hits: Iterable[RecallHit]) -> list[HybridRecallCandidate]:
        return [
            HybridRecallCandidate(
                chunk_id=hit.chunk.chunk_id,
                score=hit.score,
                content=hit.chunk.text,
                document_id=hit.chunk.document_id,
                chunk_type=hit.chunk.chunk_type,
                metadata={
                    "title": hit.chunk.title,
                    "summary": hit.chunk.summary,
                    "category": hit.chunk.category,
                    "subcategory": hit.chunk.subcategory,
                    "difficulty": hit.chunk.difficulty,
                    "source_type": hit.chunk.source_type,
                    "version": hit.chunk.version,
                    "parent_id": hit.chunk.parent_id,
                    "is_latest": hit.chunk.is_latest,
                    "hash": hit.chunk.hash,
                    "tags": list(hit.chunk.tags),
                },
                channels=list(sorted(hit.route_scores)) or [hit.route],
                raw={
                    "route": hit.route,
                    "rank": hit.rank,
                    "route_scores": dict(hit.route_scores),
                    "matched_routes": list(hit.matched_routes),
                    "rrf_score": hit.rrf_score,
                    "rerank_score": hit.rerank_score,
                    "score_breakdown": dict(hit.score_breakdown),
                    "rejected_reason": hit.rejected_reason,
                    "metadata": dict(hit.metadata),
                },
            )
            for hit in hits
        ]

    @staticmethod
    def _intent_value(intent: Optional[IntentType]) -> Optional[str]:
        return intent.value if intent is not None else None

    @staticmethod
    def _style_value(style: Optional[OutputStyle]) -> Optional[str]:
        return style.value if style is not None else None

    @staticmethod
    def _optional_str(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        return str(value)

    @staticmethod
    def _coerce_query_list(value: Any) -> Tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(str(item) for item in value if item)
        return (str(value),)

    @staticmethod
    def _candidate_value(candidate: Any, key: str, default: Any = None) -> Any:
        if isinstance(candidate, Mapping):
            return candidate.get(key, default)
        return getattr(candidate, key, default)

    @staticmethod
    def _candidate_mapping(candidate: Any, key: str, default: Any = None) -> Mapping[str, Any]:
        value = DomainRagAdapter._candidate_value(candidate, key, default or {})
        if isinstance(value, Mapping):
            return value
        return {}

    def _rejected_item_to_trace_item(self, item: Any) -> RetrievalTraceItem:
        chunk_id = str(self._candidate_value(item, "chunk_id", ""))
        document_id = str(self._candidate_value(item, "document_id", "") or self._candidate_value(item, "doc_id", ""))
        content = str(self._candidate_value(item, "content", ""))
        metadata = dict(self._candidate_value(item, "metadata", {}) or {})
        payload = {
            "chunk_id": chunk_id,
            "doc_id": document_id,
            "document_id": document_id,
            "text": content,
            "title": metadata.get("title") or chunk_id,
            "summary": metadata.get("summary"),
            "category": metadata.get("category"),
            "subcategory": metadata.get("subcategory"),
            "chunk_type": self._candidate_value(item, "chunk_type", metadata.get("chunk_type")),
            "source_type": metadata.get("source_type"),
            "version": metadata.get("version"),
            "tags": metadata.get("tags", []),
        }
        chunk = KnowledgeChunk.from_payload(
            payload,
            fallback_chunk_id=chunk_id or None,
            fallback_document_id=document_id or None,
        ) or KnowledgeChunk(
            chunk_id=chunk_id or "unknown-chunk",
            document_id=document_id or "unknown-document",
            text=content,
            title=str(metadata.get("title") or chunk_id or "unknown-chunk"),
        )
        return RetrievalTraceItem.from_chunk(
            chunk,
            rejected_reason=str(self._candidate_value(item, "rejected_reason", metadata.get("rejected_reason")) or ""),
        )

    @staticmethod
    def _looks_like_follow_up_query(
        request: DomainReferenceResolutionRequest,
        message: str,
        lowered_message: str,
    ) -> bool:
        if DomainRagAdapter._contains_reference_token(message, lowered_message):
            return True
        has_context = bool(
            request.current_topic
            or request.recent_entities
            or request.clarification_result.get("last_retrieval_topic")
            or request.topic_hint
            or request.history_summary
        )
        if not has_context:
            return False
        short_cn_follow_up = len(message) <= 14 and any(
            token in message for token in (_CN_EXPLAIN, _CN_EXPLAIN_ALT, _CN_HOW, _CN_COMPARE)
        )
        short_en_follow_up = len(lowered_message.split()) <= 4 and any(
            token in lowered_message for token in _EN_FOLLOW_UP_TOKENS
        )
        return short_cn_follow_up or short_en_follow_up

    @staticmethod
    def _contains_reference_token(message: str, lowered_message: str) -> bool:
        return any(token in lowered_message for token in ("this", "that", "previous", "it")) or any(
            token in message for token in (_CN_THIS, _CN_THAT, _CN_PREVIOUS, _CN_IT)
        )
