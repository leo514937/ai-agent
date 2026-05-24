from __future__ import annotations

import types
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal, get_args, get_origin, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import IntentType, OutputStyle, RagStatus, ToolExecutionStatus, TurnDecision
from .errors import ErrorInfo, TerminalEvent, WorkflowErrorCode

from .memory import (
    MemoryRecord,
    MemoryCandidate,
    MemoryTrace,
    MemoryWritePlan,
    MemoryRetrievalPlan,
    RetrievedMemoryPack,
    MemoryInjectionPlan,
    MemoryUpdateEvent,
    MemoryType,
    MemoryScope,
    MemoryStatus,
    MemorySource,
    MemorySensitivity,
    MemoryRetrievalMode,
    MemoryTargetStore,
    MemoryMetadata,
    _utcnow,
)


class CoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_missing_optional_fields(cls, data):
        if not isinstance(data, dict):
            return data

        next_data = dict(data)
        for name, field in cls.model_fields.items():
            if name in next_data:
                continue
            annotation = getattr(field, "annotation", None)
            if _is_optional_annotation(annotation):
                next_data[name] = None
        return next_data


def _is_optional_annotation(annotation: Any) -> bool:
    if annotation is None:
        return False

    origin = get_origin(annotation)
    if origin in {Union, types.UnionType}:
        return type(None) in get_args(annotation)

    return False


class ChatTurnCommand(CoreModel):
    trace_id: str
    session_id: str
    turn_id: str
    user_id: str
    message: str
    page: Optional[str] = None
    response_mode: Optional[str] = None
    topic_hint: Optional[str] = None
    history_summary: Optional[str] = None
    client_context: Dict[str, Any] = Field(default_factory=dict)


class ClarificationOption(CoreModel):
    id: str
    label: str
    value: Optional[str]
    description: Optional[str]


class ClarificationCard(CoreModel):
    card_id: str
    question: str
    options: List[ClarificationOption] = Field(default_factory=list)
    ambiguity_type: Optional[str]
    source_turn_id: Optional[str]
    expires_at: Optional[datetime]


class ReferenceResolutionResult(CoreModel):
    resolved: bool = False
    confidence: float = 0.0
    resolved_entity: Optional[str]
    candidate_entities: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class RetrievalPlan(CoreModel):
    semantic_query: str = ""
    keyword_query: str = ""
    retrieval_filters: Dict[str, Any] = Field(default_factory=dict)
    preferred_chunk_types: List[str] = Field(default_factory=list)
    preferred_chunk_roles: List[str] = Field(default_factory=list)
    need_retry_rewrite: bool = False
    strategy: str = "dense+sparse+metadata->rrf->rerank->evidence"
    source: str = "classifier"
    reasoning_notes: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class Citation(CoreModel):
    chunk_id: str
    document_id: Optional[str]
    source_type: Optional[str]
    version: Optional[str]
    score: Optional[float]
    title: Optional[str]
    locator: Optional[str]


class EvidenceItem(CoreModel):
    chunk_id: str
    content: str
    score: float = 0.0
    document_id: Optional[str]
    chunk_type: Optional[str]
    tier: str = "strong"
    citation_chunk_id: Optional[str]
    source_chunk_id: Optional[str]
    parent_chunk_id: Optional[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidencePack(CoreModel):
    items: List[EvidenceItem] = Field(default_factory=list)
    discard_summary: Dict[str, Any] = Field(default_factory=dict)
    top_scores: List[float] = Field(default_factory=list)
    evidence_status: str = "EMPTY"
    strong_items: List[EvidenceItem] = Field(default_factory=list)
    weak_items: List[EvidenceItem] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class HybridRecallCandidate(CoreModel):
    chunk_id: str
    score: float = 0.0
    content: Optional[str]
    document_id: Optional[str]
    chunk_type: Optional[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    channels: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)


class HybridRecallResult(CoreModel):
    dense_hits: List[HybridRecallCandidate] = Field(default_factory=list)
    sparse_hits: List[HybridRecallCandidate] = Field(default_factory=list)
    metadata_hits: List[HybridRecallCandidate] = Field(default_factory=list)
    fused_hits: List[HybridRecallCandidate] = Field(default_factory=list)
    reranked_hits: List[HybridRecallCandidate] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class RagResult(CoreModel):
    status: RagStatus = RagStatus.EMPTY
    evidence_pack: Optional[EvidencePack]
    citations: List[Citation] = Field(default_factory=list)
    evidence_status: str = "EMPTY"
    retrieval_strategy: str = "dense+sparse+metadata->rrf->rerank->evidence"
    metrics: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class AnswerPlan(CoreModel):
    sections: List[str] = Field(default_factory=list)
    lead: Optional[str]
    ending_prompt: Optional[str]
    extra: Dict[str, Any] = Field(default_factory=dict)


class PlanStep(CoreModel):
    step_id: str = ""
    goal: str = ""
    expected_output: Optional[str]
    allowed_tools: List[str] = Field(default_factory=list)
    risk_level: Literal['low', 'medium', 'high'] = "low"
    requires_approval: bool = False


class StepResult(CoreModel):
    step_id: str = ""
    status: Literal['success', 'failed', 'skipped', 'need_approval'] = "skipped"
    tools_used: List[str] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    result: Dict[str, Any] | str | None
    error: Optional[str]
    next_action: Optional[str]


class PlanExecutionSummary(CoreModel):
    status: Literal['completed', 'partial', 'failed', 'need_approval'] = "partial"
    completed_steps: int = 0
    total_steps: int = 0
    key_findings: List[str] = Field(default_factory=list)
    final_decision: Optional[str]


class ToolSelection(CoreModel):
    tool_name: Optional[str]
    should_execute: bool = False
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str]
    approval_required: bool = False
    approval_status: Optional[str]
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(CoreModel):
    status: ToolExecutionStatus = ToolExecutionStatus.SKIPPED
    tool_name: Optional[str]
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    degraded_to: Optional[str]
    error: Optional[WorkflowErrorCode]
    approval_required: bool = False
    approval_status: Optional[str]
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class NormalizedToolResult(CoreModel):
    status: ToolExecutionStatus = ToolExecutionStatus.SKIPPED
    tool_name: Optional[str]
    normalized_output: Dict[str, Any] = Field(default_factory=dict)
    used_tools: List[str] = Field(default_factory=list)
    approval_required: bool = False
    approval_status: Optional[str]
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class TurnUnderstandingResult(CoreModel):
    decision: TurnDecision = TurnDecision.DIRECT_ANSWER
    intent: IntentType = IntentType.EXPLAIN
    intent_confidence: float = 0.0
    requested_output_style: Optional[OutputStyle] = None
    reference_resolution: Optional[ReferenceResolutionResult] = None
    retrieval_plan: Optional[RetrievalPlan] = None
    clarification_card: Optional[ClarificationCard] = None
    slots: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class FastDecision(CoreModel):
    intent: IntentType = IntentType.EXPLAIN
    needs_rag: bool = False
    needs_tool: bool = False
    needs_clarify: bool = False
    needs_query_rewrite: bool = False
    confidence: float = 0.0
    key_slots: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


class InputQualityDecision(CoreModel):
    kind: str = "valid_task"
    is_valid: bool = True
    reason: str = ""
    score: float = 1.0
    signals: List[str] = Field(default_factory=list)


class IntentRoutingDecision(CoreModel):
    name: str = "unknown"
    confidence: float = 0.0
    required_slots: List[str] = Field(default_factory=list)
    missing_slots: List[str] = Field(default_factory=list)
    allowed_routes: List[str] = Field(default_factory=list)
    forbidden_routes: List[str] = Field(default_factory=list)


class RewriteDecision(CoreModel):
    original_query: str = ""
    rewritten_query: str = ""
    added_terms: List[str] = Field(default_factory=list)
    removed_terms: List[str] = Field(default_factory=list)
    preserved_constraints: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    should_retrieve: bool = False
    reason: str = ""
    risky_rewrite: bool = False


class EvidenceQualityDecision(CoreModel):
    evidence_count: int = 0
    top_score: float = 0.0
    score_gap: float = 0.0
    topic_consistency: float = 0.0
    entity_consistency: float = 0.0
    city_area_category_consistency: bool = False
    required_roles_covered: bool = False
    citation_available: bool = False
    stale_evidence: bool = False
    response_mode: str = "grounded"
    is_valid: bool = True
    reason: str = ""
    fallback_reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class RetrievalEligibility(CoreModel):
    allowed: bool = False
    blocked: bool = False
    reason: str = ""
    blocked_reason: Optional[str] = None
    failure_reasons: List[str] = Field(default_factory=list)
    required_action: Optional[str] = None
    intent_allowed: bool = False
    input_quality_ok: bool = False
    input_quality_score: float = 0.0
    normalized_query: Optional[str] = None
    rewritten_query: Optional[str] = None
    semantic_query: Optional[str] = None
    retrieval_plan_valid: bool = False
    route_candidate: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(CoreModel):
    raw_query: str = ""
    normalized_query: str = ""
    domain: str = "general"
    confidence: float = 0.0
    input_quality: InputQualityDecision = Field(default_factory=InputQualityDecision)
    intent: IntentRoutingDecision = Field(default_factory=IntentRoutingDecision)
    required_action: str = "no_op"
    blocked: bool = False
    blocked_reason: Optional[str] = None
    should_rewrite_query: bool = False
    should_retrieve: bool = False
    should_call_tool: bool = False
    should_use_memory: bool = True
    should_persist_memory: bool = True
    should_vectorize_memory: bool = True
    should_emit_retrieval_events: bool = False
    retrieval_skipped_reason: Optional[str] = None
    missing_slots: List[str] = Field(default_factory=list)
    resolved_references: List[str] = Field(default_factory=list)
    route_reason: str = ""
    safeguards_triggered: List[str] = Field(default_factory=list)
    fallback_reason: Optional[str] = None
    route_candidate: Optional[str] = None
    preferred_chunk_roles: List[str] = Field(default_factory=list)
    tool_candidates: List[str] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    rewrite_decision: Optional[RewriteDecision] = None
    evidence_quality: Optional[EvidenceQualityDecision] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class TurnUnderstandingRequest(CoreModel):
    command: ChatTurnCommand
    persistent: 'PersistentSessionContext'


class ReferenceResolutionRequest(CoreModel):
    raw_query: str
    current_topic: Optional[str] = None
    recent_entities: List[str] = Field(default_factory=list)
    clarification_result: Dict[str, Any] = Field(default_factory=dict)
    pending_clarification: Optional[ClarificationCard] = None
    history_summary: Optional[str] = None
    topic_hint: Optional[str] = None


class QueryRewriteRequest(CoreModel):
    raw_query: str
    intent: Optional[IntentType] = None
    requested_output_style: Optional[OutputStyle] = None
    reference_resolution: Optional[ReferenceResolutionResult] = None
    current_topic: Optional[str] = None
    topic_hint: Optional[str] = None
    intent_confidence: float = 0.0
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    base_filters: Dict[str, Any] = Field(default_factory=dict)


class HybridRetrieveRequest(CoreModel):
    plan: RetrievalPlan


class EvidenceEvaluationRequest(CoreModel):
    plan: RetrievalPlan
    hybrid_recall: HybridRecallResult
    intent: Optional[IntentType]
    requested_output_style: Optional[OutputStyle]


class CitationBuildRequest(CoreModel):
    evidence_pack: EvidencePack


class KnowledgeSearchRequest(CoreModel):
    topic: str
    limit: int = 5
    category: Optional[str] = None
    retrieval_filters: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResult(CoreModel):
    matches: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_pack: Optional[EvidencePack] = None
    citations: List[Citation] = Field(default_factory=list)
    retrieval_strategy: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class ToolPlanningRequest(CoreModel):
    raw_query: str
    decision: str = ""
    routing_decision: Optional['RoutingDecision'] = None
    intent: Optional[IntentType] = None
    slots: Dict[str, Any] = Field(default_factory=dict)
    current_topic: Optional[str] = None


class ToolExecutionCommand(CoreModel):
    selection: ToolSelection


class ToolNormalizationRequest(CoreModel):
    result: ToolExecutionResult


class PersistSessionCommand(CoreModel):
    trace_id: str = ""
    session_id: str
    turn_id: str
    user_id: str
    workflow_version: str = "learn-agent/v1"
    raw_query: str
    answer_text: str
    resolved_topic: Optional[str] = None
    intent: Optional[IntentType] = None
    requested_output_style: Optional[OutputStyle] = None
    tool_name: Optional[str] = None
    request_ts: datetime
    persistent: 'PersistentSessionContext'
    final_confidence: float = 0.0
    session_state_patch: Dict[str, Any] = Field(default_factory=dict)
    allow_memory_promotion: bool = True
    allow_semantic_memory_write: bool = True


class MasteryUpdateCommand(CoreModel):
    trace_id: str = ""
    session_id: str
    turn_id: str
    user_id: str
    workflow_version: str = "learn-agent/v1"
    raw_query: str
    answer_text: str
    resolved_topic: Optional[str] = None
    intent: Optional[IntentType] = None
    requested_output_style: Optional[OutputStyle] = None
    tool_name: Optional[str] = None
    request_ts: datetime
    persistent: 'PersistentSessionContext'
    memory_updates: MemoryUpdateSummary = Field(default_factory=lambda: MemoryUpdateSummary())
    final_confidence: float = 0.0
    session_state_patch: Dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateSummary(CoreModel):
    current_topic: Optional[str] = None
    updated_preferences: Dict[str, Any] = Field(default_factory=dict)
    weak_topics: List[str] = Field(default_factory=list)
    semantic_memory: Dict[str, Any] = Field(default_factory=dict)
    open_questions: List[str] = Field(default_factory=list)
    confirmed_facts: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    summary_version: int = 0
    summary_updated_at: Optional[datetime] = None
    memory_trace_id: Optional[str] = None
    write_status: str = "success"
    write_targets: List[str] = Field(default_factory=list)
    decision_reasons: List[str] = Field(default_factory=list)
    degraded_parts: List[str] = Field(default_factory=list)
    retryable_failures: List[str] = Field(default_factory=list)
    permanent_failures: List[str] = Field(default_factory=list)
    memory_write: Optional['MemoryWriteResult'] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class MemoryWriteTargetResult(CoreModel):
    target: str
    status: Literal['success', 'degraded', 'retryable_failure', 'permanent_failure', 'skipped'] = "success"
    reason: Optional[str]
    retryable: bool = False
    error: Optional[str]
    details: Dict[str, Any] = Field(default_factory=dict)


class MemoryWriteResult(CoreModel):
    trace_id: str = ""
    idempotency_key: str = ""
    session_id: str = ""
    turn_id: str = ""
    user_id: str = ""
    operation: str = ""
    status: Literal['success', 'partial_success', 'degraded', 'pending_compensation', 'permanent_failure'] = "success"
    write_targets: List[str] = Field(default_factory=list)
    target_results: List[MemoryWriteTargetResult] = Field(default_factory=list)
    decision_reasons: List[str] = Field(default_factory=list)
    degraded_parts: List[str] = Field(default_factory=list)
    retryable_failures: List[str] = Field(default_factory=list)
    permanent_failures: List[str] = Field(default_factory=list)
    compensation_required: bool = False
    extra: Dict[str, Any] = Field(default_factory=dict)


class PersistSessionResult(CoreModel):
    updated_context: 'PersistentSessionContext'
    memory_updates: MemoryUpdateSummary = Field(default_factory=MemoryUpdateSummary)
    memory_write: Optional[MemoryWriteResult]


class MasteryUpdateResult(CoreModel):
    updated_context: Optional['PersistentSessionContext'] = None
    memory_updates: MemoryUpdateSummary = Field(default_factory=MemoryUpdateSummary)
    memory_write: Optional[MemoryWriteResult] = None


class RetrievalSummary(CoreModel):
    semantic_query: Optional[str]
    keyword_query: Optional[str]
    retrieval_filters: Dict[str, Any] = Field(default_factory=dict)
    retrieval_strategy: Optional[str]
    retrieval_hit_count: int = 0
    evidence_used_count: int = 0
    evidence_status: str = "EMPTY"
    evidence_strong_count: int = 0
    evidence_weak_count: int = 0
    route_decision: Optional[str]
    route_reason: Optional[str]
    current_stage: Optional[str]
    stage_status: Optional[str]
    stage_timeline: List[Dict[str, Any]] = Field(default_factory=list)


class MemoryUsedItemSummary(CoreModel):
    memory_id: str = ""
    memory_type: Optional[str]
    scope: Optional[str]
    summary: Optional[str]
    source: Optional[str]
    confidence: float = 0.0
    retrieval_kind: Optional[str] = None
    collection_name: Optional[str] = None
    source_domain: Optional[str] = None


class MemoryUsedSummary(CoreModel):
    used: bool = False
    total_memories: int = 0
    retrieval_reason: Optional[str]
    total_token_estimate: int = 0
    prompt_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)
    state_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)
    tool_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)
    semantic_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)
    episodic_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)
    procedural_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)
    rag_memories: List[MemoryUsedItemSummary] = Field(default_factory=list)


class AnswerComposeRequest(CoreModel):
    raw_query: str
    requested_output_style: Optional[OutputStyle]
    rag_result: Optional[RagResult]
    tool_result: Optional[NormalizedToolResult]
    plan_summary: Optional[PlanExecutionSummary]
    memory_injection_plan: Optional[MemoryInjectionPlan]
    routing_decision: Optional['RoutingDecision'] = None
    evidence_quality: Optional[EvidenceQualityDecision] = None
    final_response_mode: Optional[str] = None
    allow_direct_response: bool = False
    direct_response_kind: Optional[str]
    history_summary: Optional[str] = None
    stream_event_sink: Any = None
    stream_event_meta: Dict[str, Any] = Field(default_factory=dict)


class AnswerComposeResult(CoreModel):
    answer_text: str
    confidence: float = 0.0


class PersistentSessionContext(CoreModel):
    current_topic: Optional[str] = None
    recent_entities: List[str] = Field(default_factory=list)
    clarification_result: Dict[str, Any] = Field(default_factory=dict)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    last_retrieval_topic: Optional[str] = None
    history_summary: Optional[str] = None
    open_questions: List[str] = Field(default_factory=list)
    confirmed_facts: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    summary_version: int = 0
    summary_updated_at: Optional[datetime] = None
    pending_clarification: Optional[ClarificationCard] = None
    current_city: Optional[str] = None
    current_location: Dict[str, Any] = Field(default_factory=dict)
    current_constraints: Dict[str, Any] = Field(default_factory=dict)
    last_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    selected_shop_id: Optional[int] = None
    selected_shop_name: Optional[str] = None
    local_life_preferences: List[str] = Field(default_factory=list)
    local_life_avoid: List[str] = Field(default_factory=list)
    current_scene: Optional[str] = None
    current_action: Optional[str] = None
    page: Optional[str] = None
    route_decision: Optional[str] = None
    route_reason: Optional[str] = None
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    stage_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class TurnRuntimeState(CoreModel):
    raw_query: str
    decision: str = "direct_answer"
    intent: Optional[IntentType] = None
    intent_confidence: float = 0.0
    requested_output_style: Optional[OutputStyle] = None
    task_complexity: Literal['simple', 'complex'] = "simple"
    execution_mode: Literal['auto', 'simple', 'plan_execute'] = "auto"
    risk_level: Literal['low', 'medium', 'high'] = "low"
    route_decision: Optional[str] = None
    route_reason: Optional[str] = None
    routing_decision: Optional[RoutingDecision] = None
    rewrite_decision: Optional[RewriteDecision] = None
    evidence_quality: Optional[EvidenceQualityDecision] = None
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    stage_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    slots: Dict[str, Any] = Field(default_factory=dict)
    reference_resolution: Optional[ReferenceResolutionResult] = None
    clarification_card: Optional[ClarificationCard] = None
    retrieval_plan: Optional[RetrievalPlan] = None
    hybrid_recall: Optional[HybridRecallResult] = None
    evidence_pack: Optional[EvidencePack] = None
    citations: List[Citation] = Field(default_factory=list)
    answer_plan: Optional[AnswerPlan] = None
    tool_plan: Optional[ToolSelection] = None
    raw_tool_result: Optional[ToolExecutionResult] = None
    tool_result: Optional[NormalizedToolResult] = None
    plan: List[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0
    current_step: Optional[PlanStep] = None
    step_results: List[StepResult] = Field(default_factory=list)
    need_replan: bool = False
    replan_reason: Optional[str] = None
    need_human_approval: bool = False
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    final_task_summary: Optional[PlanExecutionSummary] = None
    sensory_memory: Dict[str, Any] = Field(default_factory=dict)
    short_term_window: List[Dict[str, Any]] = Field(default_factory=list)
    retrieved_memory_pack: Optional[RetrievedMemoryPack] = None
    memory_candidates: List[MemoryCandidate] = Field(default_factory=list)
    memory_write_plan: Optional[MemoryWritePlan] = None
    memory_injection_plan: Optional[MemoryInjectionPlan] = None
    final_answer: Optional[str] = None
    rag_result: Optional[RagResult] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class GraphRuntimeMeta(CoreModel):
    trace_id: str
    session_id: str
    turn_id: str
    workflow_version: str
    request_ts: datetime
    user_id: str
    page: Optional[str] = None
    response_mode: Optional[str] = None
    topic_hint: Optional[str] = None
    history_summary: Optional[str] = None
    client_context: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    errors: List[ErrorInfo] = Field(default_factory=list)
    degrade_to: Optional[str] = None
    terminal_event: Optional[TerminalEvent] = None
    emitted_events: List[SseEnvelope] = Field(default_factory=list)
    memory_updates: MemoryUpdateSummary = Field(default_factory=MemoryUpdateSummary)
    memory_trace: Optional[MemoryTrace] = None
    session_persisted: bool = False
    extra: Dict[str, Any] = Field(default_factory=dict)


class FinalPayload(CoreModel):
    answer_text: str
    citations: List[Citation] = Field(default_factory=list)
    used_tools: List[str] = Field(default_factory=list)
    resolved_topic: Optional[str] = None
    current_topic: Optional[str] = None
    mode: str = "recommend"
    source: str = "local-life-agent"
    page: Optional[str] = None
    selected_shop_id: Optional[int] = None
    route_decision: Optional[str] = None
    route_reason: Optional[str] = None
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    stage_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    cards: List[Dict[str, Any]] = Field(default_factory=list)
    shops: List[Dict[str, Any]] = Field(default_factory=list)
    vouchers: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_replies: List[Dict[str, Any]] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    task_chain: List[Dict[str, Any]] = Field(default_factory=list)
    ranked_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    fallback: bool = False
    retrieval_strategy: Optional[str] = None
    grounding_status: Literal['grounded', 'weakly_grounded', 'not_grounded'] = "not_grounded"
    retrieval_summary: Optional[RetrievalSummary] = None
    memory_used_summary: Optional[MemoryUsedSummary] = None
    memory_updates: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    approval_required: bool = False
    approval_request: Dict[str, Any] = Field(default_factory=dict)
    transaction_draft: Dict[str, Any] = Field(default_factory=dict)
    safety_result: Dict[str, Any] = Field(default_factory=dict)
    intent: Optional[IntentType] = None
    requested_output_style: Optional[OutputStyle] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(CoreModel):
    code: str
    message: str
    retryable: bool = False
    stage: str
    degraded_to: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    current_stage: Optional[str] = None
    stage_status: Optional[str] = None
    route_decision: Optional[str] = None
    route_reason: Optional[str] = None


class SseEnvelope(CoreModel):
    event_type: str
    trace_id: str
    session_id: str
    turn_id: str
    timestamp: datetime
    workflow_version: str
    payload: Dict[str, Any] = Field(default_factory=dict)


# Rebuild models at the end
ChatTurnCommand.model_rebuild()
ClarificationOption.model_rebuild()
ClarificationCard.model_rebuild()
ReferenceResolutionResult.model_rebuild()
RetrievalPlan.model_rebuild()
Citation.model_rebuild()
EvidenceItem.model_rebuild()
EvidencePack.model_rebuild()
HybridRecallCandidate.model_rebuild()
HybridRecallResult.model_rebuild()
RagResult.model_rebuild()
AnswerPlan.model_rebuild()
PlanStep.model_rebuild()
StepResult.model_rebuild()
PlanExecutionSummary.model_rebuild()
ToolSelection.model_rebuild()
ToolExecutionResult.model_rebuild()
NormalizedToolResult.model_rebuild()
TurnUnderstandingResult.model_rebuild()
FastDecision.model_rebuild()
InputQualityDecision.model_rebuild()
IntentRoutingDecision.model_rebuild()
RewriteDecision.model_rebuild()
EvidenceQualityDecision.model_rebuild()
RoutingDecision.model_rebuild()
TurnUnderstandingRequest.model_rebuild()
ReferenceResolutionRequest.model_rebuild()
QueryRewriteRequest.model_rebuild()
HybridRetrieveRequest.model_rebuild()
EvidenceEvaluationRequest.model_rebuild()
CitationBuildRequest.model_rebuild()
KnowledgeSearchRequest.model_rebuild()
KnowledgeSearchResult.model_rebuild()
ToolPlanningRequest.model_rebuild()
ToolExecutionCommand.model_rebuild()
ToolNormalizationRequest.model_rebuild()
PersistSessionCommand.model_rebuild()
MasteryUpdateCommand.model_rebuild()
MemoryUpdateSummary.model_rebuild()
MemoryWriteTargetResult.model_rebuild()
MemoryWriteResult.model_rebuild()
PersistSessionResult.model_rebuild()
MasteryUpdateResult.model_rebuild()
RetrievalSummary.model_rebuild()
MemoryUsedItemSummary.model_rebuild()
MemoryUsedSummary.model_rebuild()
AnswerComposeRequest.model_rebuild()
AnswerComposeResult.model_rebuild()
PersistentSessionContext.model_rebuild()
TurnRuntimeState.model_rebuild()
GraphRuntimeMeta.model_rebuild()
FinalPayload.model_rebuild()
ErrorPayload.model_rebuild()
SseEnvelope.model_rebuild()
