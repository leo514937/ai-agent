from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


class ChunkType(str, Enum):
    CONCEPT = "concept"
    COMPARISON = "comparison"
    QA = "qa"
    CODE_EXAMPLE = "code_example"
    ROADMAP = "roadmap"
    PITFALL = "pitfall"


class DifficultyLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class SourceType(str, Enum):
    DOCUMENT = "document"
    FAQ = "faq"
    NOTE = "note"


class GovernanceAction(str, Enum):
    ACTIVATE_VERSION = "activate_version"
    ROLLBACK_VERSION = "rollback_version"
    REBUILD_DOCUMENT = "rebuild_document"
    CLEAN_DUPLICATES = "clean_duplicates"
    NOOP = "noop"


class EvidenceStatus(str, Enum):
    OK = "OK"
    WEAK = "WEAK"
    EMPTY = "EMPTY"


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    text: str
    title: str = ""
    summary: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    difficulty: Optional[str] = None
    source_type: Optional[str] = None
    chunk_type: Optional[str] = None
    version: Optional[str] = None
    chunk_level: Optional[str] = None
    parent_id: Optional[str] = None
    parent_title: Optional[str] = None
    parent_chunk_id: Optional[str] = None
    child_chunk_ids: Tuple[str, ...] = ()
    child_roles: Tuple[str, ...] = ()
    chunk_role: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    is_latest: bool = True
    is_active: bool = True
    hash: Optional[str] = None
    tags: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def searchable_text(self) -> str:
        """保持与旧实现兼容的检索文本。"""
        parts = [
            self.title,
            self.summary or "",
            self.text,
            self.category or "",
            self.subcategory or "",
            " ".join(self.tags),
        ]
        return " ".join(part for part in parts if part).strip()

    def searchable_dense_text(self) -> str:
        """供向量 embedding 使用的主文本。"""
        parts = [
            self.title,
            self.summary or "",
            self.text,
        ]
        return " ".join(part for part in parts if part).strip()

    def searchable_sparse_text(self) -> str:
        """供 sparse / keyword 召回使用的扩展文本。"""
        metadata = dict(self.metadata)
        parts = [
            self.title,
            self.summary or "",
            self.text,
            self.category or "",
            self.subcategory or "",
            self.chunk_role or self._normalize_optional(metadata.get("chunk_role")) or "",
            self.source_type or self._normalize_optional(metadata.get("source_type")) or "",
            self.entity_type or self._normalize_optional(metadata.get("entity_type")) or "",
            self.parent_title or self._normalize_optional(metadata.get("parent_title")) or "",
            self._normalize_optional(metadata.get("shop_name")) or "",
            self._normalize_optional(metadata.get("city")) or "",
            self._normalize_optional(metadata.get("area")) or "",
            " ".join(self.tags),
            " ".join(self._coerce_tags(metadata.get("search_keywords"))),
            self._normalize_optional(metadata.get("chunk_role_label")) or "",
            self._normalize_optional(metadata.get("source_type_label")) or "",
        ]
        return " ".join(part for part in parts if part).strip()

    @property
    def doc_id(self) -> str:
        return self.document_id

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "doc_id": self.document_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "chunk_level": self.chunk_level,
            "parent_id": self.parent_id,
            "parent_title": self.parent_title,
            "parent_chunk_id": self.parent_chunk_id or self.parent_id,
            "child_chunk_ids": list(self.child_chunk_ids),
            "child_roles": list(self.child_roles),
            "title": self.title,
            "text": self.text,
            "summary": self.summary,
            "category": self.category,
            "subcategory": self.subcategory,
            "chunk_type": self.chunk_type,
            "chunk_role": self.chunk_role,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "difficulty": self.difficulty,
            "source_type": self.source_type,
            "version": self.version,
            "is_latest": self.is_latest,
            "is_active": self.is_active,
            "tags": list(self.tags),
            "hash": self.hash,
        }
        payload.update(dict(self.metadata))
        return {key: value for key, value in payload.items() if value is not None}

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        fallback_chunk_id: Optional[str] = None,
        fallback_document_id: Optional[str] = None,
    ) -> Optional["KnowledgeChunk"]:
        chunk_id = payload.get("chunk_id") or fallback_chunk_id
        document_id = payload.get("document_id") or payload.get("doc_id") or payload.get("source_id") or fallback_document_id
        text = payload.get("text") or payload.get("content")
        if not chunk_id or not document_id or not text:
            return None

        summary = payload.get("summary") or payload.get("excerpt")
        hash_value = payload.get("hash")
        if not hash_value:
            hash_value = hashlib.sha1(f"{document_id}:{chunk_id}:{text}".encode("utf-8")).hexdigest()

        ignored = {
            "doc_id",
            "document_id",
            "source_id",
            "chunk_id",
            "text",
            "content",
            "title",
            "summary",
            "excerpt",
            "category",
            "subcategory",
            "difficulty",
            "source_type",
            "chunk_type",
            "version",
            "chunk_level",
            "parent_id",
            "parent_chunk_id",
            "parent_title",
            "child_chunk_ids",
            "child_roles",
            "chunk_role",
            "entity_type",
            "entity_id",
            "is_latest",
            "is_active",
            "tags",
            "hash",
        }
        parent_chunk_id = cls._normalize_optional(payload.get("parent_chunk_id") or payload.get("parent_id"))
        chunk_level = cls._normalize_optional(payload.get("chunk_level"))
        if chunk_level is None and parent_chunk_id is not None:
            if parent_chunk_id == str(chunk_id):
                chunk_level = "parent"
            else:
                chunk_level = "child"
        return cls(
            chunk_id=str(chunk_id),
            document_id=str(document_id),
            text=str(text),
            title=str(payload.get("title") or chunk_id),
            summary=str(summary) if summary is not None else None,
            category=cls._normalize_optional(payload.get("category")),
            subcategory=cls._normalize_optional(payload.get("subcategory")),
            difficulty=cls._normalize_optional(payload.get("difficulty")),
            source_type=cls._normalize_optional(payload.get("source_type")),
            chunk_type=cls._normalize_optional(payload.get("chunk_type")),
            version=cls._normalize_optional(payload.get("version")),
            chunk_level=chunk_level,
            parent_id=cls._normalize_optional(payload.get("parent_id") or payload.get("parent_chunk_id")),
            parent_title=cls._normalize_optional(payload.get("parent_title")),
            parent_chunk_id=parent_chunk_id,
            child_chunk_ids=cls._coerce_tags(payload.get("child_chunk_ids")),
            child_roles=cls._coerce_tags(payload.get("child_roles")),
            chunk_role=cls._normalize_optional(payload.get("chunk_role")),
            entity_type=cls._normalize_optional(payload.get("entity_type")),
            entity_id=cls._normalize_optional(payload.get("entity_id")),
            is_latest=bool(payload.get("is_latest", True)),
            is_active=bool(payload.get("is_active", True)),
            hash=str(hash_value) if hash_value is not None else None,
            tags=cls._coerce_tags(payload.get("tags")),
            metadata={key: value for key, value in payload.items() if key not in ignored},
        )

    @staticmethod
    def _normalize_optional(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        return str(value)

    @staticmethod
    def _coerce_tags(value: Any) -> Tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Iterable):
            return tuple(str(tag) for tag in value if tag)
        return (str(value),)


@dataclass(frozen=True)
class RetrievalFilters:
    category: Tuple[str, ...] = ()
    subcategory: Tuple[str, ...] = ()
    difficulty: Tuple[str, ...] = ()
    source_type: Tuple[str, ...] = ()
    chunk_type: Tuple[str, ...] = ()
    version: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Tuple[str, ...]]:
        return {
            "category": self.category,
            "subcategory": self.subcategory,
            "difficulty": self.difficulty,
            "source_type": self.source_type,
            "chunk_type": self.chunk_type,
            "version": self.version,
            "tags": self.tags,
        }

    def has_constraints(self) -> bool:
        return any(self.as_dict().values()) or bool(self.extra)

    def soft_fields(self) -> Dict[str, Tuple[str, ...]]:
        return {
            "category": self.category,
            "subcategory": self.subcategory,
            "difficulty": self.difficulty,
            "source_type": self.source_type,
            "chunk_type": self.chunk_type,
            "tags": self.tags,
        }

    def hard_fields(self) -> Dict[str, Tuple[str, ...]]:
        return {
            "version": self.version,
        }


@dataclass(frozen=True)
class RetrievalPlan:
    semantic_query: str
    keyword_query: str
    retrieval_filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    preferred_chunk_types: Tuple[str, ...] = ()
    step_back_query: Optional[str] = None
    rewritten_queries: Tuple[str, ...] = ()
    supplemental_queries: Tuple[str, ...] = ()
    hyde_passage: Optional[str] = None
    hyde_trigger_reason: Optional[str] = None
    hyde_applied: bool = False
    metadata_filter_mode: str = "soft"
    dense_top_k: int = 10
    sparse_top_k: int = 8
    metadata_top_k: int = 8
    rerank_top_k: int = 8
    max_evidence: int = 5
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallHit:
    chunk: KnowledgeChunk
    score: float
    route: str
    rank: int
    route_scores: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    matched_routes: Tuple[str, ...] = ()
    fused_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    rerank_rank: Optional[int] = None
    rerank_model: Optional[str] = None
    source_chunk_id: Optional[str] = None
    citation_chunk_id: Optional[str] = None
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    rejected_reason: Optional[str] = None
    retrieval_kind: str = ""
    collection_name: str = ""
    source_domain: str = ""


@dataclass(frozen=True)
class RetrievalTraceItem:
    chunk_id: str
    document_id: str
    title: str
    score: float = 0.0
    route: str = ""
    rank: int = 0
    parent_id: Optional[str] = None
    summary: Optional[str] = None
    chunk_type: Optional[str] = None
    source_type: Optional[str] = None
    version: Optional[str] = None
    matched_routes: Tuple[str, ...] = ()
    fused_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    rerank_rank: Optional[int] = None
    rerank_model: Optional[str] = None
    source_chunk_id: Optional[str] = None
    citation_chunk_id: Optional[str] = None
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    rejected_reason: Optional[str] = None
    retrieval_kind: str = ""
    collection_name: str = ""
    source_domain: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: KnowledgeChunk, **kwargs: Any) -> "RetrievalTraceItem":
        return cls(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            title=chunk.title,
            parent_id=chunk.parent_id,
            summary=chunk.summary,
            chunk_type=chunk.chunk_type,
            source_type=chunk.source_type,
            version=chunk.version,
            metadata=dict(chunk.metadata),
            **kwargs,
        )

    @classmethod
    def from_hit(cls, hit: RecallHit, **kwargs: Any) -> "RetrievalTraceItem":
        rejected_reason = kwargs.pop("rejected_reason", hit.rejected_reason)
        return cls.from_chunk(
            hit.chunk,
            score=hit.score,
            route=hit.route,
            rank=hit.rank,
            matched_routes=hit.matched_routes,
            fused_score=hit.fused_score,
            rrf_score=hit.rrf_score,
            rerank_score=hit.rerank_score,
            rerank_rank=hit.rerank_rank,
            rerank_model=hit.rerank_model,
            source_chunk_id=hit.source_chunk_id,
            citation_chunk_id=hit.citation_chunk_id,
            score_breakdown=dict(hit.score_breakdown),
            rejected_reason=rejected_reason,
            retrieval_kind=hit.retrieval_kind,
            collection_name=hit.collection_name,
            source_domain=hit.source_domain,
            **kwargs,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class RetrievalTrace:
    raw_query: str = ""
    semantic_query: str = ""
    keyword_query: str = ""
    retrieval_filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    final_retrieval_filters: Mapping[str, Any] = field(default_factory=dict)
    preferred_chunk_types: Tuple[str, ...] = ()
    dense_hits: Tuple[RetrievalTraceItem, ...] = ()
    sparse_hits: Tuple[RetrievalTraceItem, ...] = ()
    metadata_hits: Tuple[RetrievalTraceItem, ...] = ()
    fused_hits: Tuple[RetrievalTraceItem, ...] = ()
    reranked_hits: Tuple[RetrievalTraceItem, ...] = ()
    evidence_kept: Tuple[RetrievalTraceItem, ...] = ()
    evidence_rejected: Tuple[RetrievalTraceItem, ...] = ()
    degraded: bool = False
    empty: bool = False
    metrics: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "semantic_query": self.semantic_query,
            "keyword_query": self.keyword_query,
            "retrieval_filters": self.retrieval_filters.as_dict() | {"extra": dict(self.retrieval_filters.extra)},
            "final_retrieval_filters": dict(self.final_retrieval_filters),
            "preferred_chunk_types": list(self.preferred_chunk_types),
            "dense_hits": [item.to_dict() for item in self.dense_hits],
            "sparse_hits": [item.to_dict() for item in self.sparse_hits],
            "metadata_hits": [item.to_dict() for item in self.metadata_hits],
            "fused_hits": [item.to_dict() for item in self.fused_hits],
            "reranked_hits": [item.to_dict() for item in self.reranked_hits],
            "evidence_kept": [item.to_dict() for item in self.evidence_kept],
            "evidence_rejected": [item.to_dict() for item in self.evidence_rejected],
            "degraded": self.degraded,
            "empty": self.empty,
            "metrics": dict(self.metrics),
            "extra": dict(self.extra),
        }


RetrievalDebugInfo = RetrievalTrace


@dataclass(frozen=True)
class HybridRecallResult:
    hits: Tuple[RecallHit, ...]
    retrieval_strategy: str
    retrieval_kind: str = "hybrid"
    collection_name: str = ""
    source_domain: str = ""
    dense_hits: Tuple[RecallHit, ...] = ()
    sparse_hits: Tuple[RecallHit, ...] = ()
    metadata_hits: Tuple[RecallHit, ...] = ()
    fused_hits: Tuple[RecallHit, ...] = ()
    reranked_hits: Tuple[RecallHit, ...] = ()
    degraded_routes: Tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    query_plan: Optional[RetrievalPlan] = None
    debug_trace: Optional[RetrievalTrace] = None


@dataclass(frozen=True)
class EvidenceItem:
    chunk: KnowledgeChunk
    score: float
    routes: Tuple[str, ...]
    reasons: Tuple[str, ...]
    tier: str = "strong"
    citation_chunk_id: Optional[str] = None
    source_chunk_id: Optional[str] = None
    parent_chunk_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidencePack:
    items: Tuple[EvidenceItem, ...]
    status: str
    evidence_status: EvidenceStatus = EvidenceStatus.EMPTY
    strong_items: Tuple[EvidenceItem, ...] = ()
    weak_items: Tuple[EvidenceItem, ...] = ()
    filtered_out: int = 0
    rationale: Tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    rejected_items: Tuple[RetrievalTraceItem, ...] = ()
    debug_trace: Optional[RetrievalTrace] = None


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    document_id: str
    title: str
    source_type: Optional[str]
    version: Optional[str]
    score: float
    excerpt: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeGovernanceDecision:
    action: GovernanceAction
    document_id: str
    reason: str
    target_version: Optional[str] = None
    affected_chunk_ids: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReferenceResolutionRequest:
    message: str
    lowered_message: str
    current_topic: Optional[str] = None
    last_retrieval_topic: Optional[str] = None
    recent_entities: Tuple[str, ...] = ()
    pending_clarification_values: Tuple[str, ...] = ()
    clarification_result: Mapping[str, Any] = field(default_factory=dict)
    follow_up_intent: bool = False


@dataclass(frozen=True)
class ReferenceResolution:
    resolved: bool
    confidence: float
    resolved_entity: Optional[str] = None
    candidate_entities: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchRequest:
    query: str
    limit: int = 5
    category: Optional[str] = None
    query_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchMatch:
    chunk: KnowledgeChunk
    score: float
    citation: Optional[Citation] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    query: str
    retrieval_strategy: str
    runtime_mode: str
    plan: RetrievalPlan
    recall: HybridRecallResult
    evidence: EvidencePack
    citations: Tuple[Citation, ...]
    matches: Tuple[KnowledgeSearchMatch, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)


def coerce_tuple(values: Optional[Iterable[str]]) -> Tuple[str, ...]:
    if not values:
        return ()
    return tuple(value for value in values if value)


def latest_version(chunks: Sequence[KnowledgeChunk]) -> Optional[str]:
    versions = sorted({chunk.version for chunk in chunks if chunk.version})
    return versions[-1] if versions else None
