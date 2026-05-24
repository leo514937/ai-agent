"""Small persistence DTOs used by infrastructure repositories and async outbox writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class UserPreferenceProfileRecord:
    user_id: str
    answer_style: Optional[str] = None
    explanation_depth: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserProfilePreferenceRecord:
    user_id: str
    preference_key: str
    current_value: str
    confidence: float = 0.0
    source_memory_id: Optional[str] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    status: str = "active"
    is_active: bool = True
    source_session_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarificationRecordEntry:
    user_id: str
    session_id: str
    turn_id: str
    ambiguity_type: str
    question_text: str
    options_json: Dict[str, Any] = field(default_factory=dict)
    selected_option_id: Optional[str] = None
    selected_option_label: Optional[str] = None
    resolution_status: str = "pending"
    resolved_at: Optional[datetime] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationLogEntry:
    session_id: str
    turn_id: str
    tool_name: str
    tool_call_id: str
    status: str
    duration_ms: Optional[int] = None
    degraded_to: Optional[str] = None
    error_code: Optional[str] = None
    input_summary: Dict[str, Any] = field(default_factory=dict)
    output_summary: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    document_id: str
    title: str
    source_type: str
    category: str
    checksum: str
    source_uri: Optional[str] = None
    active_version: Optional[str] = None
    status: str = "active"
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDocumentVersionRecord:
    document_id: str
    version: str
    checksum: str
    chunk_count: int = 0
    status: str = "inactive"
    imported_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    rollback_from_version: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboxEventRecord:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    available_at: Optional[datetime] = None
    trace_id: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None


@dataclass(frozen=True)
class MemoryOutboxRecord:
    aggregate_type: str
    aggregate_id: str
    memory_id: str
    user_id: str
    event_type: str
    dedupe_key: str
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    available_at: Optional[datetime] = None
    trace_id: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None
    vector_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
