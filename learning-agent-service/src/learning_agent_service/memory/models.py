from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    answer_style: str | None = None
    explanation_depth: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AsyncLogEvent:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    available_at: datetime | None = None

    def as_mapping(self) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
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
    preferred_output_style: str | None = None
    answer_style_counter: Mapping[str, int] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicMasteryRecord:
    """兼容旧测试/旧导入的主题掌握记录结构。"""

    topic: str
    mastery_score: float = 0.0
    review_priority: int = 0
    updated_at: datetime | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistentSessionContext:
    current_topic: str | None = None
    current_shop: str | None = None
    current_shop_anchor: Mapping[str, Any] = field(default_factory=dict)
    recent_entities: tuple[str, ...] = ()
    pending_user_need: Mapping[str, Any] = field(default_factory=dict)
    clarification_result: Mapping[str, Any] = field(default_factory=dict)
    user_preferences: Mapping[str, Any] = field(default_factory=dict)
    last_retrieval_topic: str | None = None
    history_summary: str | None = None
    open_questions: tuple[str, ...] = ()
    confirmed_facts: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    summary_version: int = 0
    summary_updated_at: datetime | None = None
    pending_clarification: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticMemoryFact:
    fact_id: str
    topic: str
    content: str
    fact_type: str
    strength: float = 0.5
    created_at: datetime | None = None
    last_referenced_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExplicitUserSignals:
    preferred_output_style: str | None = None
    confirmed_output_style: bool = False
    wants_code_examples: bool = False
    confirmed_code_examples: bool = False
    focus_topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryRecallSignals:
    intent: str | None = None
    raw_query: str = ""
    current_topic: str | None = None
    current_shop: str | None = None
    history_summary: str | None = None
    recent_entities: tuple[str, ...] = ()
    active_plan_id: str | None = None
    execution_mode: str | None = None
    task_complexity: str | None = None
    final_task_summary: Mapping[str, Any] | None = None
    open_questions: tuple[str, ...] = ()
    confirmed_facts: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    summary_updated_at: datetime | None = None
    response_mode: str | None = None
    session_id: str | None = None
    turn_id: str | None = None


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
    current_topic: str | None = None
    current_shop: str | None = None
    recent_entities: tuple[str, ...] = ()
    clarification_result: Mapping[str, Any] = field(default_factory=dict)
    last_retrieval_topic: str | None = None
    history_summary: str | None = None
    open_questions: tuple[str, ...] = ()
    confirmed_facts: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    summary_version: int = 0
    summary_updated_at: datetime | None = None
    pending_clarification: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryPromotionInput:
    session_id: str
    turn_id: str
    user_id: str
    query: str
    answer_text: str
    resolved_topic: str | None = None
    intent: str | None = None
    output_style: str | None = None
    tool_name: str | None = None
    explicit_signals: ExplicitUserSignals = field(default_factory=ExplicitUserSignals)
    current_session: PersistentSessionContext = field(default_factory=PersistentSessionContext)
    current_mastery: Any | None = None
    current_preferences: UserPreferenceProfile | None = None
    current_time: datetime | None = None
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
    profile_updates: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    semantic_facts: tuple[SemanticMemoryFact, ...] = ()
    weak_topics: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    durable_fact_requests: tuple[DurableFactRequest, ...] = ()
    outbox_events: tuple[Mapping[str, Any], ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistSessionPlan:
    updated_context: PersistentSessionContext
    preference_patch: Mapping[str, Any] = field(default_factory=dict)
    session_preference_patch: Mapping[str, Any] = field(default_factory=dict)
    profile_updates: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    semantic_facts: tuple[SemanticMemoryFact, ...] = ()
    durable_fact_requests: tuple[DurableFactRequest, ...] = ()
    outbox_events: tuple[Mapping[str, Any], ...] = ()
    memory_updates: Mapping[str, Any] = field(default_factory=dict)


class MemoryCapabilityError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        stage: str,
        message: str,
        retryable: bool = True,
        degraded_to: str | None = None,
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
