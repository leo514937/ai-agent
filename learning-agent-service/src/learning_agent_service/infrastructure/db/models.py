"""SQLAlchemy durable models for the standalone learning agent service.

The model module is import-tolerant when SQLAlchemy is not installed so that
other workstreams can still import repository and bootstrap modules during early
integration. Methods that require actual SQLAlchemy behavior should still guard
against missing dependencies before use.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

try:
    from sqlalchemy import (
        JSON,
        Boolean,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        String,
        Text,
        UniqueConstraint,
        func,
        text,
    )
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only before dependencies are installed.
    SQLALCHEMY_AVAILABLE = False

    class _PlaceholderType:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class _MappedAlias:
        def __class_getitem__(cls, item: Any) -> _MappedAlias:
            return cls

    def mapped_column(*args: Any, **kwargs: Any) -> None:
        return None

    class _FallbackMetadata:
        def create_all(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("sqlalchemy is not installed")

    class DeclarativeBase:
        metadata = _FallbackMetadata()

    Boolean = DateTime = Float = ForeignKey = Index = Integer = JSON = String = Text = UniqueConstraint = _PlaceholderType
    Mapped = _MappedAlias
    text = _PlaceholderType

    class _Func:
        @staticmethod
        def now() -> None:
            return None

    func = _Func()


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base for durable tables."""


class TimestampMixin:
    """Standard created/updated timestamps for durable rows."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserPreferenceProfileModel(TimestampMixin, Base):
    """Durable user preference snapshot used by answer planning and routing."""

    __tablename__ = "user_preference_profile"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_preference_profile_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    answer_style: Mapped[str] = mapped_column(String(64), nullable=True)
    explanation_depth: Mapped[str] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class UserProfilePreferenceModel(TimestampMixin, Base):
    """Current user profile projection keyed by normalized preference name."""

    __tablename__ = "user_profile_preference"
    __table_args__ = (
        Index(
            "uq_user_profile_preference_user_key_active",
            "user_id",
            "preference_key",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
        Index("ix_user_profile_preference_user_key_status", "user_id", "preference_key", "status"),
        Index("ix_user_profile_preference_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    preference_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_value: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_memory_id: Mapped[str] = mapped_column(String(128), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ClarificationRecordModel(TimestampMixin, Base):
    """Durable record of clarification prompts and user selections."""

    __tablename__ = "clarification_record"
    __table_args__ = (Index("ix_clarification_record_session_turn", "session_id", "turn_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ambiguity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    selected_option_id: Mapped[str] = mapped_column(String(128), nullable=True)
    selected_option_label: Mapped[str] = mapped_column(String(255), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ToolInvocationLogModel(TimestampMixin, Base):
    """Durable tool invocation facts, written asynchronously through the outbox."""

    __tablename__ = "tool_invocation_log"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_tool_invocation_log_tool_call_id"),
        Index("ix_tool_invocation_log_session_turn", "session_id", "turn_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    degraded_to: Mapped[str] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str] = mapped_column(String(32), nullable=True)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class KnowledgeDocumentModel(TimestampMixin, Base):
    """Governance metadata for logical knowledge documents."""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_knowledge_document_document_id"),
        Index("ix_knowledge_document_source_type_category", "source_type", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    active_version: Mapped[str] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class KnowledgeDocumentVersionModel(TimestampMixin, Base):
    """Version-level governance metadata used for rollout, invalidation, and rollback."""

    __tablename__ = "knowledge_document_version"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_document_version_doc_version"),
        Index("ix_knowledge_document_version_document_status", "document_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("knowledge_document.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="inactive")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_from_version: Mapped[str] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MemoryRecordModel(TimestampMixin, Base):
    """Durable long-term memory metadata persisted in Postgres."""

    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint("memory_id", name="uq_memory_records_memory_id"),
        Index(
            "uq_memory_records_user_normalized_key_active",
            "user_id",
            "normalized_key",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
        Index("ix_memory_records_user_type_scope_status", "user_id", "memory_type", "scope", "status"),
        Index("ix_memory_records_user_topic", "user_id", "topic"),
        Index("ix_memory_records_user_summary", "user_id", "summary"),
        Index("ix_memory_records_user_normalized_key_status", "user_id", "normalized_key", "status"),
        Index("ix_memory_records_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    memory_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    source_session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=True)
    topic: Mapped[str] = mapped_column(String(255), nullable=True)
    normalized_key: Mapped[str] = mapped_column(String(128), nullable=True)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    persistence_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="long_term")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="system_event")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default="public")
    retrieval_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    should_vectorize: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    entities: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    evidence_turn_id: Mapped[str] = mapped_column(String(128), nullable=True)
    source_message_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes: Mapped[str] = mapped_column(String(128), nullable=True)
    superseded_by: Mapped[str] = mapped_column(String(128), nullable=True)
    superseded_by_memory_id: Mapped[str] = mapped_column(String(128), nullable=True)
    vector_id: Mapped[str] = mapped_column(String(128), nullable=True)
    raw_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="2")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    @property
    def source_turn_id(self) -> str | None:
        return self.evidence_turn_id

    @source_turn_id.setter
    def source_turn_id(self, value: str | None) -> None:
        self.evidence_turn_id = value

    @property
    def expires_at(self) -> datetime | None:
        return self.valid_until

    @expires_at.setter
    def expires_at(self, value: datetime | None) -> None:
        self.valid_until = value

    @property
    def embedding_id(self) -> str | None:
        return self.vector_id

    @embedding_id.setter
    def embedding_id(self, value: str | None) -> None:
        self.vector_id = value

    @property
    def type(self) -> str:
        return self.memory_type

    @type.setter
    def type(self, value: str) -> None:
        self.memory_type = value


class MemoryCandidateModel(TimestampMixin, Base):
    """Candidate memory rows staged before governance approval."""

    __tablename__ = "memory_candidates"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_memory_candidates_candidate_id"),
        Index("ix_memory_candidates_user_status", "user_id", "status"),
        Index("ix_memory_candidates_user_topic", "user_id", "topic"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    project_id: Mapped[str] = mapped_column(String(128), nullable=True)
    topic: Mapped[str] = mapped_column(String(255), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="model_inferred")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default="public")
    retrieval_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    should_vectorize: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_turn_id: Mapped[str] = mapped_column(String(128), nullable=True)
    source_message_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supersedes: Mapped[str] = mapped_column(String(128), nullable=True)
    superseded_by: Mapped[str] = mapped_column(String(128), nullable=True)
    vector_id: Mapped[str] = mapped_column(String(128), nullable=True)
    raw_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    governance_action: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    require_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_notes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MemoryEdgeModel(TimestampMixin, Base):
    __tablename__ = "memory_edges"
    __table_args__ = (
        UniqueConstraint("edge_id", name="uq_memory_edges_edge_id"),
        Index("ix_memory_edges_source_target", "source_memory_id", "target_memory_id"),
        Index("ix_memory_edges_type", "edge_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    edge_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_memory_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("memory_records.memory_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_memory_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("memory_records.memory_id", ondelete="CASCADE"),
        nullable=False,
    )
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False, default="related_to")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MemoryAccessLogModel(TimestampMixin, Base):
    __tablename__ = "memory_access_logs"
    __table_args__ = (
        UniqueConstraint("access_log_id", name="uq_memory_access_logs_access_log_id"),
        Index("ix_memory_access_logs_memory_user", "memory_id", "user_id"),
        Index("ix_memory_access_logs_accessed_at", "accessed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    access_log_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("memory_records.memory_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="read")
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    trace_id: Mapped[str] = mapped_column(String(128), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MemoryDeletionJobModel(TimestampMixin, Base):
    __tablename__ = "memory_deletion_jobs"
    __table_args__ = (
        UniqueConstraint("deletion_job_id", name="uq_memory_deletion_jobs_deletion_job_id"),
        Index("ix_memory_deletion_jobs_status_scheduled", "status", "scheduled_at"),
        Index("ix_memory_deletion_jobs_memory_id", "memory_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    deletion_job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("memory_records.memory_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    target_store: Mapped[str] = mapped_column(String(32), nullable=False, default="postgres")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    vector_id: Mapped[str] = mapped_column(String(128), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MemoryOutboxModel(TimestampMixin, Base):
    """Durable outbox for memory and vector synchronization events."""

    __tablename__ = "memory_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_memory_outbox_dedupe_key"),
        Index("ix_memory_outbox_status_available_at", "status", "available_at"),
        Index("ix_memory_outbox_memory_id", "memory_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=True)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=True)
    vector_id: Mapped[str] = mapped_column(String(128), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MemoryTraceModel(Base):
    __tablename__ = "memory_traces"
    __table_args__ = (
        UniqueConstraint("trace_id", name="uq_memory_traces_trace_id"),
        Index("ix_memory_traces_user_created_at", "user_id", "created_at"),
        Index("ix_memory_traces_session_turn", "session_id", "turn_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=False)
    retrieved_memory_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    injected_memory_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    skipped_memories: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    candidate_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    promoted_memory_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    rejected_candidates: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    conflict_resolutions: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    total_memory_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qdrant_degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


LongTermMemoryModel = MemoryRecordModel


class OutboxEventModel(TimestampMixin, Base):
    """Generic outbox table used for async log writes and deferred side effects."""

    __tablename__ = "outbox_event"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_event_dedupe_key"),
        Index("ix_outbox_event_status_available_at", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=True)
