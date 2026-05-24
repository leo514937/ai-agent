from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class SessionPersistenceContext:
    session_id: str
    turn_id: str
    trace_id: str
    user_id: str
    request_ts: datetime


@dataclass(frozen=True)
class PreferenceProfileWrite:
    user_id: str
    answer_style: Optional[str] = None
    explanation_depth: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AsyncLogEvent:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    available_at: Optional[datetime] = None

    def as_mapping(self) -> Mapping[str, Any]:
        payload = {
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "dedupe_key": self.dedupe_key,
            "payload": dict(self.payload),
            "trace_id": self.trace_id,
        }
        if self.available_at is not None:
            payload["available_at"] = self.available_at
        return payload


@dataclass(frozen=True)
class UserPreferenceProfile:
    user_id: str
    preferred_output_style: Optional[str] = None
    answer_style_counter: Mapping[str, int] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicMasteryRecord:
    """兼容旧测试/旧导入的主题掌握记录结构。"""

    topic: str
    mastery_score: float = 0.0
    review_priority: int = 0
    updated_at: Optional[datetime] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistentSessionContext:
    current_topic: Optional[str] = None
    recent_entities: Tuple[str, ...] = ()
    clarification_result: Mapping[str, Any] = field(default_factory=dict)
    user_preferences: Mapping[str, Any] = field(default_factory=dict)
    last_retrieval_topic: Optional[str] = None
    history_summary: Optional[str] = None
    open_questions: Tuple[str, ...] = ()
    confirmed_facts: Tuple[str, ...] = ()
    next_steps: Tuple[str, ...] = ()
    summary_version: int = 0
    summary_updated_at: Optional[datetime] = None
    pending_clarification: Optional[Mapping[str, Any]] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticMemoryFact:
    fact_id: str
    topic: str
    content: str
    fact_type: str
    strength: float = 0.5
    created_at: Optional[datetime] = None
    last_referenced_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExplicitUserSignals:
    preferred_output_style: Optional[str] = None
    confirmed_output_style: bool = False
    wants_code_examples: bool = False
    confirmed_code_examples: bool = False
    focus_topics: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryRecallSignals:
    intent: Optional[str] = None
    raw_query: str = ""
    current_topic: Optional[str] = None
    history_summary: Optional[str] = None
    recent_entities: Tuple[str, ...] = ()
    active_plan_id: Optional[str] = None
    execution_mode: Optional[str] = None
    task_complexity: Optional[str] = None
    final_task_summary: Optional[Mapping[str, Any]] = None
    open_questions: Tuple[str, ...] = ()
    confirmed_facts: Tuple[str, ...] = ()
    next_steps: Tuple[str, ...] = ()
    summary_updated_at: Optional[datetime] = None
    response_mode: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None


@dataclass(frozen=True)
class MemoryRecallPlan:
    enabled: bool = False
    episodic_score: float = 0.0
    procedural_score: float = 0.0
    recall_episodic: bool = False
    recall_procedural: bool = False
    reason: str = ""
    top_k: int = 5
    token_budget: int = 1200
    same_session_boost: float = 0.0
    recency_window_seconds: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionUpdate:
    current_topic: Optional[str] = None
    recent_entities: Tuple[str, ...] = ()
    clarification_result: Mapping[str, Any] = field(default_factory=dict)
    last_retrieval_topic: Optional[str] = None
    history_summary: Optional[str] = None
    open_questions: Tuple[str, ...] = ()
    confirmed_facts: Tuple[str, ...] = ()
    next_steps: Tuple[str, ...] = ()
    summary_version: int = 0
    summary_updated_at: Optional[datetime] = None
    pending_clarification: Optional[Mapping[str, Any]] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryPromotionInput:
    session_id: str
    turn_id: str
    user_id: str
    query: str
    answer_text: str
    resolved_topic: Optional[str] = None
    intent: Optional[str] = None
    output_style: Optional[str] = None
    tool_name: Optional[str] = None
    explicit_signals: ExplicitUserSignals = field(default_factory=ExplicitUserSignals)
    current_session: PersistentSessionContext = field(default_factory=PersistentSessionContext)
    current_mastery: Optional[Any] = None
    current_preferences: Optional[UserPreferenceProfile] = None
    current_time: Optional[datetime] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DurableFactRequest:
    fact_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryPromotionResult:
    session_update: SessionUpdate
    preference_patch: Mapping[str, Any] = field(default_factory=dict)
    session_preference_patch: Mapping[str, Any] = field(default_factory=dict)
    profile_updates: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    semantic_facts: Tuple[SemanticMemoryFact, ...] = ()
    reasons: Tuple[str, ...] = ()
    durable_fact_requests: Tuple[DurableFactRequest, ...] = ()
    outbox_events: Tuple[Mapping[str, Any], ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistSessionPlan:
    updated_context: PersistentSessionContext
    preference_patch: Mapping[str, Any] = field(default_factory=dict)
    session_preference_patch: Mapping[str, Any] = field(default_factory=dict)
    profile_updates: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    semantic_facts: Tuple[SemanticMemoryFact, ...] = ()
    durable_fact_requests: Tuple[DurableFactRequest, ...] = ()
    outbox_events: Tuple[Mapping[str, Any], ...] = ()
    memory_updates: Mapping[str, Any] = field(default_factory=dict)


class MemoryCapabilityError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        stage: str,
        message: str,
        retryable: bool = True,
        degraded_to: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.retryable = retryable
        self.degraded_to = degraded_to

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "retryable": self.retryable,
            "degraded_to": self.degraded_to,
        }
