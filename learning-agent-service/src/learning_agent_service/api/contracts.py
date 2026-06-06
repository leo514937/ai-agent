from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from learning_agent_service.domain.contracts import (
    ClarificationCard,
    ErrorPayload,
    FinalPayload,
    PlanExecutionSummary,
    PlanStep,
    StepResult,
)


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any | None = None
    error: str | None = None

    @classmethod
    def success(cls, data: Any = None) -> ApiResponse:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str) -> ApiResponse:
        return cls(ok=False, error=error)


class EventType(str, Enum):
    ACK = "ack"
    HEARTBEAT = "heartbeat"
    LOAD_CONTEXT_STARTED = "load_context_started"
    LOAD_CONTEXT_DONE = "load_context_done"
    INTENT_ANALYSIS_STARTED = "intent_analysis_started"
    INTENT_ANALYSIS_DONE = "intent_analysis_done"
    QUERY_REWRITE_STARTED = "query_rewrite_started"
    QUERY_REWRITE_DONE = "query_rewrite_done"
    RETRIEVAL_STARTED = "retrieval_started"
    EMBEDDING_STARTED = "embedding_started"
    EMBEDDING_DONE = "embedding_done"
    QDRANT_SEARCH_STARTED = "qdrant_search_started"
    QDRANT_SEARCH_DONE = "qdrant_search_done"
    RRF_FUSION_STARTED = "rrf_fusion_started"
    RRF_FUSION_DONE = "rrf_fusion_done"
    RERANK_STARTED = "rerank_started"
    RERANK_DONE = "rerank_done"
    ANSWER_STREAM_STARTED = "answer_stream_started"
    DELTA = "delta"
    ANSWER_DELTA = "answer_delta"
    CLARIFICATION_CARD = "clarification_card"
    RETRIEVAL_RESULT = "retrieval_result"
    MEMORY_RETRIEVAL_STARTED = "memory_retrieval_started"
    MEMORY_RETRIEVAL_RESULT = "memory_retrieval_result"
    MEMORY_PROMOTION_RESULT = "memory_promotion_result"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PLAN_EXECUTION_STARTED = "plan_execution_started"
    PLAN_STEP_RESULT = "plan_step_result"
    APPROVAL_REQUIRED = "approval_required"
    PLAN_REPLANNED = "plan_replanned"
    PLAN_EXECUTION_SUMMARY = "plan_execution_summary"
    FINAL = "final"
    ERROR = "error"


class AckPayload(BaseModel):
    message: str
    accepted_at: datetime
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class AnswerDeltaPayload(BaseModel):
    delta: str
    answer_text: str
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class StageStatusPayload(BaseModel):
    stage: str
    status: str
    elapsed_ms: float | None = None
    degrade_to: str | None = None
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ClarificationOptionPayload(BaseModel):
    id: str
    label: str
    value: str | None = None
    description: str | None = None


class ClarificationCardPayload(BaseModel):
    card_id: str
    question: str
    options: list[ClarificationOptionPayload] = Field(default_factory=list)
    ambiguity_type: str | None = None

    @classmethod
    def from_domain(cls, card: ClarificationCard) -> ClarificationCardPayload:
        return cls.model_validate(card.model_dump(mode="json"))


class RetrievalStartedPayload(BaseModel):
    stage: str | None = None
    status: str | None = None
    elapsed_ms: float | None = None
    degrade_to: str | None = None
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    semantic_query: str | None = None
    keyword_query: str | None = None
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RetrievalResultPayload(BaseModel):
    retrieval_strategy: str
    retrieval_hit_count: int = Field(ge=0)
    evidence_used_count: int = Field(ge=0)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class MemoryRetrievalStartedPayload(BaseModel):
    trace_id: str
    session_id: str
    turn_id: str
    user_id: str
    query: str
    current_topic: str | None = None
    retrieval_budget: int = Field(default=0, ge=0)


class MemoryRetrievalResultPayload(BaseModel):
    trace_id: str
    session_id: str
    turn_id: str
    retrieved: list[str] = Field(default_factory=list)
    injected: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    retrieval_reason: str | None = None
    total_token_estimate: int = Field(default=0, ge=0)
    trace_summary: dict[str, Any] = Field(default_factory=dict)


class MemoryPromotionResultPayload(BaseModel):
    trace_id: str
    session_id: str
    turn_id: str
    candidate_ids: list[str] = Field(default_factory=list)
    promoted_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    governed_actions: dict[str, str] = Field(default_factory=dict)
    conflict_ids: list[str] = Field(default_factory=list)
    deletion_job_ids: list[str] = Field(default_factory=list)
    governance_summary: dict[str, Any] = Field(default_factory=dict)
    memory_trace: dict[str, Any] = Field(default_factory=dict)


class ToolCallPayload(BaseModel):
    tool_name: str
    tool_call_id: str
    input_summary: dict[str, Any] = Field(default_factory=dict)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class ToolResultPayload(BaseModel):
    tool_name: str
    tool_call_id: str
    status: str
    degraded: bool = False
    retryable: bool = False
    error_code: str | None = None
    error_message: str | None = None
    degraded_to: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    approval_required: bool = False
    approval_status: str | None = None
    approval_request: dict[str, Any] = Field(default_factory=dict)


class PlanExecutionStartedPayload(BaseModel):
    plan: list[PlanStep] = Field(default_factory=list)
    total_steps: int = Field(default=0, ge=0)
    current_step_index: int = Field(default=0, ge=0)
    execution_mode: str | None = None
    risk_level: str | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class PlanStepResultPayload(BaseModel):
    step_result: StepResult
    current_step_index: int = Field(default=0, ge=0)
    total_steps: int = Field(default=0, ge=0)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class ApprovalRequiredPayload(BaseModel):
    step_id: str
    reason: str
    approval_request: dict[str, Any] = Field(default_factory=dict)
    risk_level: str | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class PlanReplannedPayload(BaseModel):
    reason: str
    previous_steps: int = Field(default=0, ge=0)
    total_steps: int = Field(default=0, ge=0)
    plan: list[PlanStep] = Field(default_factory=list)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class PlanExecutionSummaryPayload(BaseModel):
    summary: PlanExecutionSummary
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class ChatStreamRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    turn_id: str | None = None
    page: str | None = None
    response_mode: str | None = None
    topic_hint: str | None = None
    history_summary: str | None = None
    client_context: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("context", "client_context"))


class SessionStateResponse(BaseModel):
    session_id: str
    current_topic: str | None = None
    current_shop: str | None = None
    recent_entities: list[str] = Field(default_factory=list)
    clarification_result: dict[str, Any] | None = None
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    last_retrieval_topic: str | None = None
    history_summary: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    summary_version: int = 0
    summary_updated_at: datetime | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ApprovalSubmitRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    approval_id: str | None = None
    decision: str = Field(min_length=1)
    approval_request: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ApprovalSubmitResponse(BaseModel):
    session_id: str
    trace_id: str
    turn_id: str
    approval_state: str
    accepted: bool = True
    pending_approval: bool = False
    approval_request: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class FeedbackIssueType(str, Enum):
    HELPFUL = "helpful"
    UNHELPFUL = "unhelpful"
    CITATION_INCORRECT = "citation_incorrect"
    MISSED_RECALL = "missed_recall"
    OTHER = "other"


class FeedbackReportRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    thread_id: str | None = None
    trace_id: str | None = None
    issue_type: FeedbackIssueType = FeedbackIssueType.HELPFUL
    is_helpful: bool | None = None
    comment: str | None = None
    final_payload: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_summary: dict[str, Any] = Field(default_factory=dict)
    memory_used_summary: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackReportResponse(BaseModel):
    feedback_id: str
    status: str
    recorded_at: datetime
    dedupe_key: str
    payload: dict[str, Any] = Field(default_factory=dict)


class FeedbackSampleItem(BaseModel):
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    status: str
    trace_id: str | None = None
    available_at: datetime | None = None
    published_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    last_error: str | None = None


class FeedbackSampleResponse(BaseModel):
    records: list[FeedbackSampleItem] = Field(default_factory=list)
    total: int = 0


class MemoryRecordSummary(BaseModel):
    memory_id: str
    user_id: str
    session_id: str | None = None
    project_id: str | None = None
    topic: str | None = None
    memory_type: str | None = None
    scope: str | None = None
    status: str | None = None
    source: str | None = None
    summary: str | None = None
    confidence: float = 0.0
    importance: float = 0.0
    stability: float = 0.0
    sensitivity: str | None = None
    retrieval_mode: str | None = None
    should_vectorize: bool = True
    ttl_seconds: int | None = None
    valid_until: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source_turn_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    last_accessed_at: datetime | None = None
    access_count: int = 0
    supersedes: str | None = None
    superseded_by: str | None = None
    embedding_id: str | None = None
    raw_evidence: dict[str, Any] = Field(default_factory=dict)
    schema_version: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MemoryCandidateSummary(BaseModel):
    candidate_id: str
    memory_id: str | None = None
    user_id: str
    session_id: str | None = None
    project_id: str | None = None
    topic: str | None = None
    memory_type: str | None = None
    scope: str | None = None
    status: str | None = None
    source: str | None = None
    summary: str | None = None
    confidence: float = 0.0
    importance: float = 0.0
    stability: float = 0.0
    governance_action: str | None = None
    require_confirmation: bool = False
    approval_notes: list[str] = Field(default_factory=list)
    decision_reason: str | None = None
    conflict_ids: list[str] = Field(default_factory=list)
    deletion_job_ids: list[str] = Field(default_factory=list)
    skip_reason: str | None = None
    record: MemoryRecordSummary | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MemoryTraceSummary(BaseModel):
    trace_id: str
    user_id: str
    session_id: str
    turn_id: str
    retrieved: list[str] = Field(default_factory=list)
    injected: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    promoted: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    decision_reasons: dict[str, str] = Field(default_factory=dict)
    conflict_ids: list[str] = Field(default_factory=list)
    deletion_job_ids: list[str] = Field(default_factory=list)
    skip_reasons: dict[str, str] = Field(default_factory=dict)
    conflict_resolutions: list[dict[str, Any]] = Field(default_factory=list)
    total_memory_tokens: int = 0
    qdrant_degraded: bool = False
    created_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MemoryAccessLogSummary(BaseModel):
    access_log_id: str
    memory_id: str
    user_id: str
    session_id: str | None = None
    turn_id: str | None = None
    action: str = "read"
    accessed_at: datetime
    trace_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MemoryDeletionJobSummary(BaseModel):
    deletion_job_id: str
    memory_id: str
    user_id: str
    session_id: str | None = None
    target_store: str | None = None
    status: str | None = None
    reason: str | None = None
    scheduled_at: datetime | None = None
    executed_at: datetime | None = None
    error_message: str | None = None
    vector_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MemoryListResponse(BaseModel):
    records: list[MemoryRecordSummary] = Field(default_factory=list)
    total: int = 0


class MemoryCandidateListResponse(BaseModel):
    records: list[MemoryCandidateSummary] = Field(default_factory=list)
    total: int = 0


class MemoryTraceListResponse(BaseModel):
    records: list[MemoryTraceSummary] = Field(default_factory=list)
    total: int = 0


class MemoryAccessLogListResponse(BaseModel):
    records: list[MemoryAccessLogSummary] = Field(default_factory=list)
    total: int = 0


class MemoryDeletionJobListResponse(BaseModel):
    records: list[MemoryDeletionJobSummary] = Field(default_factory=list)
    total: int = 0


class MemoryActionRequest(BaseModel):
    reason: str | None = None
    superseded_by: str | None = None
    target_memory_id: str | None = None


class MemoryActionResponse(BaseModel):
    status: str
    action: str
    message: str | None = None
    record: MemoryRecordSummary | None = None
    candidate: MemoryCandidateSummary | None = None
    trace: MemoryTraceSummary | None = None


class SseEnvelope(BaseModel):
    event_type: str
    trace_id: str
    session_id: str
    turn_id: str
    timestamp: datetime
    workflow_version: str
    payload: dict[str, Any] = Field(default_factory=dict)


EVENT_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.ACK: AckPayload,
    EventType.HEARTBEAT: StageStatusPayload,
    EventType.LOAD_CONTEXT_STARTED: StageStatusPayload,
    EventType.LOAD_CONTEXT_DONE: StageStatusPayload,
    EventType.INTENT_ANALYSIS_STARTED: StageStatusPayload,
    EventType.INTENT_ANALYSIS_DONE: StageStatusPayload,
    EventType.QUERY_REWRITE_STARTED: StageStatusPayload,
    EventType.QUERY_REWRITE_DONE: StageStatusPayload,
    EventType.RETRIEVAL_STARTED: RetrievalStartedPayload,
    EventType.EMBEDDING_STARTED: StageStatusPayload,
    EventType.EMBEDDING_DONE: StageStatusPayload,
    EventType.QDRANT_SEARCH_STARTED: StageStatusPayload,
    EventType.QDRANT_SEARCH_DONE: StageStatusPayload,
    EventType.RRF_FUSION_STARTED: StageStatusPayload,
    EventType.RRF_FUSION_DONE: StageStatusPayload,
    EventType.RERANK_STARTED: StageStatusPayload,
    EventType.RERANK_DONE: StageStatusPayload,
    EventType.ANSWER_STREAM_STARTED: StageStatusPayload,
    EventType.DELTA: AnswerDeltaPayload,
    EventType.ANSWER_DELTA: AnswerDeltaPayload,
    EventType.CLARIFICATION_CARD: ClarificationCardPayload,
    EventType.RETRIEVAL_RESULT: RetrievalResultPayload,
    EventType.MEMORY_RETRIEVAL_STARTED: MemoryRetrievalStartedPayload,
    EventType.MEMORY_RETRIEVAL_RESULT: MemoryRetrievalResultPayload,
    EventType.MEMORY_PROMOTION_RESULT: MemoryPromotionResultPayload,
    EventType.TOOL_CALL: ToolCallPayload,
    EventType.TOOL_RESULT: ToolResultPayload,
    EventType.PLAN_EXECUTION_STARTED: PlanExecutionStartedPayload,
    EventType.PLAN_STEP_RESULT: PlanStepResultPayload,
    EventType.APPROVAL_REQUIRED: ApprovalRequiredPayload,
    EventType.PLAN_REPLANNED: PlanReplannedPayload,
    EventType.PLAN_EXECUTION_SUMMARY: PlanExecutionSummaryPayload,
    EventType.FINAL: FinalPayload,
    EventType.ERROR: ErrorPayload,
}


class StateSnapshotResponse(BaseModel):
    checkpoint_id: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    next_nodes: list[str] = Field(default_factory=list)
    created_at: str | None = None
    parent_checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionHistoryResponse(BaseModel):
    session_id: str
    history: list[StateSnapshotResponse] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    checkpoint_id: str


class ForkRequest(BaseModel):
    checkpoint_id: str
    target_session_id: str | None = None
    state_patch: dict[str, Any] | None = None



def validate_event_payload(event_type: EventType | str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_event = event_type if isinstance(event_type, EventType) else EventType(event_type)
    model = EVENT_PAYLOAD_MODELS[normalized_event]
    return model.model_validate(payload).model_dump(mode="json")
