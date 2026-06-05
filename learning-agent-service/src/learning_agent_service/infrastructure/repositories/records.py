"""Small persistence DTOs used by infrastructure repositories and async outbox writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class UserPreferenceProfileRecord:
    user_id: str
    answer_style: str | None = None
    explanation_depth: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserProfilePreferenceRecord:
    user_id: str
    preference_key: str
    current_value: str
    confidence: float = 0.0
    source_memory_id: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    status: str = "active"
    is_active: bool = True
    source_session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarificationRecordEntry:
    user_id: str
    session_id: str
    turn_id: str
    ambiguity_type: str
    question_text: str
    options_json: dict[str, Any] = field(default_factory=dict)
    selected_option_id: str | None = None
    selected_option_label: str | None = None
    resolution_status: str = "pending"
    resolved_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationLogEntry:
    session_id: str
    turn_id: str
    tool_name: str
    tool_call_id: str
    status: str
    duration_ms: int | None = None
    degraded_to: str | None = None
    error_code: str | None = None
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    document_id: str
    title: str
    source_type: str
    category: str
    checksum: str
    source_uri: str | None = None
    active_version: str | None = None
    status: str = "active"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDocumentVersionRecord:
    document_id: str
    version: str
    checksum: str
    chunk_count: int = 0
    status: str = "inactive"
    imported_at: datetime | None = None
    activated_at: datetime | None = None
    invalidated_at: datetime | None = None
    rollback_from_version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboxEventRecord:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    available_at: datetime | None = None
    trace_id: str | None = None
    attempts: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class MemoryOutboxRecord:
    aggregate_type: str
    aggregate_id: str
    memory_id: str
    user_id: str
    event_type: str
    dedupe_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    session_id: str | None = None
    turn_id: str | None = None
    available_at: datetime | None = None
    trace_id: str | None = None
    attempts: int = 0
    last_error: str | None = None
    vector_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
