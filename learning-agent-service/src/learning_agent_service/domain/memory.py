from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, runtime_checkable
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryCoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class MemoryType(str, Enum):
    SENSORY = "sensory"
    SHORT_TERM = "short_term"
    SESSION_SUMMARY = "session_summary"
    MASTERY = "mastery"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    ENTITY = "entity"
    PREFERENCE = "preference"


class MemoryPersistenceScope(str, Enum):
    TURN = "turn"
    SESSION = "session"
    LONG_TERM = "long_term"
    PROFILE = "profile"


class MemoryScope(str, Enum):
    TURN = "turn"
    SESSION = "session"
    USER = "user"
    PROJECT = "project"
    GLOBAL = "global"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"
    OBSERVED = "observed"
    EPHEMERAL = "ephemeral"
    ACTIVE_SESSION = "active_session"
    PENDING_CONFIRMATION = "pending_confirmation"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


_VECTOR_ID_NAMESPACE = UUID("7f9ef774-73c0-5f8f-9ef9-43a7d4c5e5e2")


def vector_id_for_memory_id(memory_id: str) -> str:
    memory_id_text = (memory_id or "").strip()
    if not memory_id_text:
        return ""
    return str(uuid5(_VECTOR_ID_NAMESPACE, f"learning-agent-service:qdrant:{memory_id_text}"))


def is_active_memory_status(status: MemoryStatus) -> bool:
    return status in {MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED}


class MemorySource(str, Enum):
    USER_EXPLICIT = "user_explicit"
    MODEL_INFERRED = "model_inferred"
    TOOL_RESULT = "tool_result"
    RAG_EVIDENCE = "rag_evidence"
    SYSTEM_EVENT = "system_event"
    HUMAN_REVIEW = "human_review"


class MemorySensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MemoryRetrievalMode(str, Enum):
    AUTO = "auto"
    PROMPT = "prompt"
    STATE = "state"
    TOOL = "tool"
    RAG = "rag"
    SUPPRESSED = "suppressed"


class MemoryEdgeType(str, Enum):
    SUPERSEDES = "supersedes"
    MERGED_INTO = "merged_into"
    RELATED_TO = "related_to"
    DERIVED_FROM = "derived_from"
    ACCESS_LOG = "access_log"


class MemoryDeletionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemoryTargetStore(str, Enum):
    TURN_STATE = "turn_state"
    REDIS = "redis"
    POSTGRES = "postgres"
    QDRANT = "qdrant"
    OUTBOX = "outbox"


class MemoryMetadata(MemoryCoreModel):
    memory_id: str = ""
    user_id: str = ""
    session_id: Optional[str] = None
    source_session_id: Optional[str] = None
    project_id: Optional[str] = None
    topic: Optional[str] = None
    normalized_key: Optional[str] = None
    normalized_value: Optional[str] = None
    type: MemoryType = MemoryType.SEMANTIC
    memory_type: Optional[MemoryType] = None
    scope: MemoryScope = MemoryScope.USER
    persistence_scope: MemoryPersistenceScope = MemoryPersistenceScope.LONG_TERM
    status: MemoryStatus = MemoryStatus.ACTIVE
    source: MemorySource = MemorySource.SYSTEM_EVENT
    source_turn_id: str = ""
    evidence_turn_id: Optional[str] = None
    source_message_ids: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    content: Any = Field(default_factory=dict)
    confidence: float = 0.0
    importance: float = 0.0
    stability: float = 0.5
    sensitivity: MemorySensitivity = MemorySensitivity.PUBLIC
    retrieval_mode: MemoryRetrievalMode = MemoryRetrievalMode.AUTO
    should_vectorize: bool = True
    ttl_seconds: Optional[int] = None
    valid_until: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_accessed_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    access_count: int = 0
    is_active: bool = True
    effective_from: datetime = Field(default_factory=_utcnow)
    effective_to: Optional[datetime] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    superseded_by_memory_id: Optional[str] = None
    embedding_id: Optional[str] = None
    vector_id: Optional[str] = None
    raw_evidence: Optional[Dict[str, Any]] = None
    schema_version: str = "1"

    @model_validator(mode="before")
    @classmethod
    def _compat_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "memory_type" not in payload and "type" in payload:
            payload["memory_type"] = payload["type"]
        if "evidence_turn_id" not in payload and "source_turn_id" in payload:
            payload["evidence_turn_id"] = payload["source_turn_id"]
        if "vector_id" not in payload and "embedding_id" in payload:
            payload["vector_id"] = payload["embedding_id"]
        if "valid_until" not in payload and "expires_at" in payload:
            payload["valid_until"] = payload["expires_at"]
        if "source_session_id" not in payload and "session_id" in payload:
            payload["source_session_id"] = payload["session_id"]
        return payload


class MemoryRecord(MemoryCoreModel):
    memory_id: str = ""
    user_id: str = ""
    session_id: Optional[str] = None
    source_session_id: Optional[str] = None
    project_id: Optional[str] = None
    topic: Optional[str] = None
    normalized_key: Optional[str] = None
    normalized_value: Optional[str] = None
    type: MemoryType = MemoryType.SEMANTIC
    scope: MemoryScope = MemoryScope.USER
    persistence_scope: MemoryPersistenceScope = MemoryPersistenceScope.LONG_TERM
    status: MemoryStatus = MemoryStatus.ACTIVE
    source: MemorySource = MemorySource.SYSTEM_EVENT
    content: Any = Field(default_factory=dict)
    summary: Optional[str] = None
    stability: float = 0.5
    sensitivity: MemorySensitivity = MemorySensitivity.PUBLIC
    retrieval_mode: MemoryRetrievalMode = MemoryRetrievalMode.AUTO
    should_vectorize: bool = True
    ttl_seconds: Optional[int] = None
    valid_until: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    source_turn_id: Optional[str] = None
    source_message_ids: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    importance: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_accessed_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    access_count: int = 0
    is_active: bool = True
    effective_from: datetime = Field(default_factory=_utcnow)
    effective_to: Optional[datetime] = None
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    superseded_by_memory_id: Optional[str] = None
    embedding_id: Optional[str] = None
    raw_evidence: Optional[Dict[str, Any]] = None
    schema_version: str = "2"
    metadata: Optional[MemoryMetadata] = None
    extra: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _compat_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "type" not in payload and "memory_type" in payload:
            payload["type"] = payload["memory_type"]
        payload.pop("memory_type", None)
        if "source_turn_id" not in payload and "evidence_turn_id" in payload:
            payload["source_turn_id"] = payload["evidence_turn_id"]
        payload.pop("evidence_turn_id", None)
        if "embedding_id" not in payload and "vector_id" in payload:
            payload["embedding_id"] = payload["vector_id"]
        payload.pop("vector_id", None)
        if "valid_until" not in payload and "expires_at" in payload:
            payload["valid_until"] = payload["expires_at"]
        payload.pop("expires_at", None)
        if "source_session_id" not in payload and "session_id" in payload:
            payload["source_session_id"] = payload["session_id"]
        if "topic" not in payload:
            entities = payload.get("entities")
            if isinstance(entities, list) and entities:
                payload["topic"] = entities[0]
        return payload

    @model_validator(mode="after")
    def _sync_metadata(self) -> "MemoryRecord":
        canonical_vector_id = self.embedding_id or vector_id_for_memory_id(self.memory_id)
        self.embedding_id = canonical_vector_id or None
        if self.metadata is None:
            self.metadata = MemoryMetadata(
                memory_id=self.memory_id,
                user_id=self.user_id,
                session_id=self.session_id,
                source_session_id=self.source_session_id,
                project_id=self.project_id,
                topic=self.topic,
                normalized_key=self.normalized_key,
                normalized_value=self.normalized_value,
                type=self.type,
                memory_type=self.type,
                scope=self.scope,
                persistence_scope=self.persistence_scope,
                status=self.status,
                source=self.source,
                source_turn_id=self.source_turn_id,
                evidence_turn_id=self.source_turn_id,
                source_message_ids=list(self.source_message_ids),
                summary=self.summary,
                content=self.content,
                confidence=self.confidence,
                importance=self.importance,
                stability=self.stability,
                sensitivity=self.sensitivity,
                retrieval_mode=self.retrieval_mode,
                should_vectorize=self.should_vectorize,
                ttl_seconds=self.ttl_seconds,
                valid_until=self.valid_until,
                tags=list(self.tags),
                entities=list(self.entities),
                created_at=self.created_at,
                updated_at=self.updated_at,
                last_accessed_at=self.last_accessed_at,
                last_seen_at=self.last_seen_at,
                access_count=self.access_count,
                is_active=self.is_active,
                effective_from=self.effective_from,
                effective_to=self.effective_to,
                supersedes=self.supersedes,
                superseded_by=self.superseded_by,
                superseded_by_memory_id=self.superseded_by_memory_id,
                embedding_id=None,
                vector_id=None,
                raw_evidence=dict(self.raw_evidence or {}),
                schema_version=self.schema_version,
            )
        else:
            self.metadata = self.metadata.model_copy(
                update={
                    "memory_id": self.memory_id,
                    "user_id": self.user_id,
                    "session_id": self.session_id,
                    "source_session_id": self.source_session_id,
                    "project_id": self.project_id,
                    "topic": self.topic,
                    "normalized_key": self.normalized_key,
                    "normalized_value": self.normalized_value,
                    "type": self.type,
                    "memory_type": self.type,
                    "scope": self.scope,
                    "persistence_scope": self.persistence_scope,
                    "status": self.status,
                    "source": self.source,
                    "source_turn_id": self.source_turn_id,
                    "evidence_turn_id": self.source_turn_id,
                    "source_message_ids": list(self.source_message_ids),
                    "summary": self.summary,
                    "content": self.content,
                    "confidence": self.confidence,
                    "importance": self.importance,
                    "stability": self.stability,
                    "sensitivity": self.sensitivity,
                    "retrieval_mode": self.retrieval_mode,
                    "should_vectorize": self.should_vectorize,
                    "ttl_seconds": self.ttl_seconds,
                    "valid_until": self.valid_until,
                    "tags": list(self.tags),
                    "entities": list(self.entities),
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                    "last_accessed_at": self.last_accessed_at,
                    "last_seen_at": self.last_seen_at,
                    "access_count": self.access_count,
                    "is_active": self.is_active,
                    "effective_from": self.effective_from,
                    "effective_to": self.effective_to,
                    "supersedes": self.supersedes,
                    "superseded_by": self.superseded_by,
                    "superseded_by_memory_id": self.superseded_by_memory_id,
                    "embedding_id": None,
                    "vector_id": None,
                    "raw_evidence": dict(self.raw_evidence or {}),
                    "schema_version": self.schema_version,
                }
            )
        return self

    @property
    def memory_type(self) -> MemoryType:
        return self.type

    @property
    def evidence_turn_id(self) -> Optional[str]:
        return self.source_turn_id

    @evidence_turn_id.setter
    def evidence_turn_id(self, value: Optional[str]) -> None:
        self.source_turn_id = value

    @property
    def vector_id(self) -> Optional[str]:
        return self.embedding_id or vector_id_for_memory_id(self.memory_id)

    @vector_id.setter
    def vector_id(self, value: Optional[str]) -> None:
        self.embedding_id = value

    @property
    def expires_at(self) -> Optional[datetime]:
        return self.valid_until

    @property
    def normalized_key_name(self) -> Optional[str]:
        return self.normalized_key


class SensoryMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.SENSORY
    scope: MemoryScope = MemoryScope.TURN


class ShortTermMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.SHORT_TERM
    scope: MemoryScope = MemoryScope.SESSION


class SessionSummaryMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.SESSION_SUMMARY
    scope: MemoryScope = MemoryScope.SESSION


class EpisodicMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.EPISODIC


class SemanticMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.SEMANTIC


class ProceduralMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.PROCEDURAL


class EntityMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.ENTITY


class UserPreferenceMemoryRecord(MemoryRecord):
    type: MemoryType = MemoryType.PREFERENCE


class MemoryCandidate(MemoryCoreModel):
    candidate_id: str = ""
    should_promote: bool = False
    memory_type: MemoryType = MemoryType.SEMANTIC
    target_store: MemoryTargetStore = MemoryTargetStore.POSTGRES
    persistence_scope: MemoryPersistenceScope = MemoryPersistenceScope.LONG_TERM
    confidence: float = 0.0
    importance: float = 0.0
    stability: float = 0.5
    reason: str = ""
    ttl_seconds: Optional[int] = None
    source_turn_id: str = ""
    normalized_key: Optional[str] = None
    normalized_value: Optional[str] = None
    dedupe_key: Optional[str] = None
    conflict_check_key: Optional[str] = None
    governance_action: str = "pending"
    require_confirmation: bool = False
    approval_notes: List[str] = Field(default_factory=list)
    record: MemoryRecord = Field(default_factory=MemoryRecord)
    decision_reason: str = ""
    conflict_ids: List[str] = Field(default_factory=list)
    deletion_job_ids: List[str] = Field(default_factory=list)
    skip_reason: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class MemoryEdge(MemoryCoreModel):
    edge_id: str = ""
    source_memory_id: str = ""
    target_memory_id: str = ""
    edge_type: MemoryEdgeType = MemoryEdgeType.RELATED_TO
    reason: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    extra: Dict[str, Any] = Field(default_factory=dict)


class MemoryAccessLog(MemoryCoreModel):
    access_log_id: str = ""
    memory_id: str = ""
    user_id: str = ""
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    action: str = "read"
    accessed_at: datetime = Field(default_factory=_utcnow)
    trace_id: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class MemoryDeletionJob(MemoryCoreModel):
    deletion_job_id: str = ""
    memory_id: str = ""
    user_id: str = ""
    session_id: Optional[str] = None
    target_store: MemoryTargetStore = MemoryTargetStore.POSTGRES
    status: MemoryDeletionStatus = MemoryDeletionStatus.PENDING
    reason: str = ""
    scheduled_at: datetime = Field(default_factory=_utcnow)
    executed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    vector_id: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class MemoryTrace(MemoryCoreModel):
    trace_id: str = ""
    user_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    retrieved: List[str] = Field(default_factory=list)
    injected: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    candidates: List[str] = Field(default_factory=list)
    promoted: List[str] = Field(default_factory=list)
    rejected: List[str] = Field(default_factory=list)
    decision_reasons: Dict[str, str] = Field(default_factory=dict)
    conflict_ids: List[str] = Field(default_factory=list)
    deletion_job_ids: List[str] = Field(default_factory=list)
    skip_reasons: Dict[str, str] = Field(default_factory=dict)
    conflict_resolutions: List[Any] = Field(default_factory=list)
    total_memory_tokens: int = 0
    qdrant_degraded: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    extra: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _compat_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        alias_map = {
            "retrieved_memory_ids": "retrieved",
            "injected_memory_ids": "injected",
            "skipped_memories": "skipped",
            "candidate_ids": "candidates",
            "promoted_memory_ids": "promoted",
            "rejected_candidates": "rejected",
        }
        for source, target in alias_map.items():
            if target not in payload and source in payload:
                payload[target] = payload[source]
            payload.pop(source, None)
        return payload

    @property
    def retrieved_memory_ids(self) -> List[str]:
        return self.retrieved

    @retrieved_memory_ids.setter
    def retrieved_memory_ids(self, value: List[str]) -> None:
        self.retrieved = value

    @property
    def injected_memory_ids(self) -> List[str]:
        return self.injected

    @injected_memory_ids.setter
    def injected_memory_ids(self, value: List[str]) -> None:
        self.injected = value

    @property
    def skipped_memories(self) -> List[str]:
        return self.skipped

    @skipped_memories.setter
    def skipped_memories(self, value: List[str]) -> None:
        self.skipped = value

    @property
    def candidate_ids(self) -> List[str]:
        return self.candidates

    @candidate_ids.setter
    def candidate_ids(self, value: List[str]) -> None:
        self.candidates = value

    @property
    def promoted_memory_ids(self) -> List[str]:
        return self.promoted

    @promoted_memory_ids.setter
    def promoted_memory_ids(self, value: List[str]) -> None:
        self.promoted = value

    @property
    def rejected_candidates(self) -> List[str]:
        return self.rejected

    @rejected_candidates.setter
    def rejected_candidates(self, value: List[str]) -> None:
        self.rejected = value


class MemoryWritePlan(MemoryCoreModel):
    candidates: List[MemoryCandidate] = Field(default_factory=list)
    write_targets: List[MemoryTargetStore] = Field(default_factory=list)
    outbox_required: bool = False


class MemoryRetrievalPlan(MemoryCoreModel):
    user_id: str = ""
    session_id: str = ""
    project_id: Optional[str] = None
    raw_query: str = ""
    intent: Optional[str] = None
    current_topic: Optional[str] = None
    recent_entities: List[str] = Field(default_factory=list)
    history_summary: Optional[str] = None
    retrieval_budget: int = 8
    response_mode: Optional[str] = None


class RetrievedMemoryPack(MemoryCoreModel):
    prompt_memories: List[MemoryRecord] = Field(default_factory=list)
    state_memories: List[MemoryRecord] = Field(default_factory=list)
    tool_memories: List[MemoryRecord] = Field(default_factory=list)
    semantic_memories: List[MemoryRecord] = Field(default_factory=list)
    episodic_memories: List[MemoryRecord] = Field(default_factory=list)
    procedural_memories: List[MemoryRecord] = Field(default_factory=list)
    rag_memories: List[MemoryRecord] = Field(default_factory=list)
    excluded_memories: List[MemoryRecord] = Field(default_factory=list)
    retrieval_reason: str = ""
    total_token_estimate: int = 0
    source_memory_ids: List[str] = Field(default_factory=list)
    retrieval_kind: str = "long_term_memory"
    collection_name: str = ""
    source_domain: str = "memory"

    @model_validator(mode="after")
    def _sync_compat_buckets(self) -> "RetrievedMemoryPack":
        if not self.semantic_memories and self.rag_memories:
            self.semantic_memories = list(self.rag_memories)
        if not self.rag_memories and self.semantic_memories:
            self.rag_memories = list(self.semantic_memories)
        if not self.procedural_memories and self.tool_memories:
            self.procedural_memories = list(self.tool_memories)
        if not self.tool_memories and self.procedural_memories:
            self.tool_memories = list(self.procedural_memories)
        return self


class MemoryInjectionPlan(MemoryCoreModel):
    prompt_memories: List[MemoryRecord] = Field(default_factory=list)
    state_memories: List[MemoryRecord] = Field(default_factory=list)
    tool_memories: List[MemoryRecord] = Field(default_factory=list)
    semantic_memories: List[MemoryRecord] = Field(default_factory=list)
    episodic_memories: List[MemoryRecord] = Field(default_factory=list)
    procedural_memories: List[MemoryRecord] = Field(default_factory=list)
    rag_memories: List[MemoryRecord] = Field(default_factory=list)
    hidden_trace_memories: List[MemoryRecord] = Field(default_factory=list)
    token_budget: int = 1200

    @model_validator(mode="after")
    def _sync_compat_buckets(self) -> "MemoryInjectionPlan":
        if not self.semantic_memories and self.rag_memories:
            self.semantic_memories = list(self.rag_memories)
        if not self.rag_memories and self.semantic_memories:
            self.rag_memories = list(self.semantic_memories)
        if not self.procedural_memories and self.tool_memories:
            self.procedural_memories = list(self.tool_memories)
        if not self.tool_memories and self.procedural_memories:
            self.tool_memories = list(self.procedural_memories)
        return self


class MemoryConsolidationPlan(MemoryCoreModel):
    source_memory_ids: List[str] = Field(default_factory=list)
    target_memory_id: Optional[str] = None
    action: Literal["merge", "supersede", "expire", "split"] = "merge"
    reason: str = ""


class MemoryConflict(MemoryCoreModel):
    conflict_id: str = ""
    winner_memory_id: str = ""
    loser_memory_ids: List[str] = Field(default_factory=list)
    conflict_type: str = ""
    reason: str = ""
    resolved_by: MemorySource = MemorySource.SYSTEM_EVENT
    resolved_at: datetime = Field(default_factory=_utcnow)


class MemoryUpdateEvent(MemoryCoreModel):
    event_id: str = ""
    memory_id: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    action: str = ""
    status_before: Optional[MemoryStatus] = None
    status_after: Optional[MemoryStatus] = None
    source_turn_id: str = ""
    timestamp: datetime = Field(default_factory=_utcnow)
    trace_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SensoryMemoryBuffer(Protocol):
    def ingest(self, turn_id: str, payload: Mapping[str, Any]) -> None:
        ...

    def snapshot(self, turn_id: str) -> Mapping[str, Any]:
        ...

    def clear(self, turn_id: str) -> None:
        ...


@runtime_checkable
class ShortTermMemoryStore(Protocol):
    def append_messages(self, session_id: str, messages: Sequence[Mapping[str, Any]]) -> None:
        ...

    def get_window(self, session_id: str, limit: int = 20) -> Sequence[Mapping[str, Any]]:
        ...

    def save_task_context(self, session_id: str, context: Mapping[str, Any]) -> None:
        ...

    def get_task_context(self, session_id: str) -> Mapping[str, Any]:
        ...

    def prune(self, session_id: str, limit: int = 20) -> None:
        ...


@runtime_checkable
class SessionMemoryStore(Protocol):
    def load(self, session_id: str, user_id: str) -> Any:
        ...

    def save(self, context: Any, runtime: Any) -> None:
        ...

    def update_summary(self, session_id: str, summary: Mapping[str, Any]) -> None:
        ...

    def load_any(self, session_id: str) -> Any:
        ...


@runtime_checkable
class LongTermMemoryStore(Protocol):
    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        ...

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        ...

    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 10,
        memory_types: Optional[Sequence[MemoryType]] = None,
    ) -> Sequence[MemoryRecord]:
        ...

    def list_by_scope(self, user_id: str, scope: MemoryScope) -> Sequence[MemoryRecord]:
        ...

    def supersede(
        self,
        memory_id: str,
        superseded_by: str,
        reason: str,
        edge_type: MemoryEdgeType = MemoryEdgeType.SUPERSEDES,
    ) -> None:
        ...

    def soft_delete(self, memory_id: str, reason: str) -> None:
        ...


@runtime_checkable
class EntityMemoryStore(Protocol):
    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        ...

    def get(self, entity_id: str, user_id: str) -> Optional[MemoryRecord]:
        ...

    def list_by_user(self, user_id: str, entity_type: Optional[str] = None) -> Sequence[MemoryRecord]:
        ...

    def search(self, user_id: str, query: str, limit: int = 10) -> Sequence[MemoryRecord]:
        ...

    def merge(self, target_entity_id: str, source_entity_ids: List[str], reason: str) -> MemoryRecord:
        ...


