from __future__ import annotations

import types
from datetime import datetime
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    IntentType,
    LocalRouteType,
    NegativeScopeType,
    OutputStyle,
    PolarityType,
    RagStatus,
    TargetType,
    ToolExecutionStatus,
    TurnDecision,
)
from .errors import ErrorInfo, TerminalEvent, WorkflowErrorCode
from .memory import (
    MemoryCandidate,
    MemoryInjectionPlan,
    MemoryTrace,
    MemoryWritePlan,
    RetrievedMemoryPack,
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
    union_types = {Union}
    union_type = getattr(types, "UnionType", None)
    if union_type is not None:
        union_types.add(union_type)
    if origin in union_types:
        return type(None) in get_args(annotation)

    return False


class ChatTurnCommand(CoreModel):
    trace_id: str
    session_id: str
    turn_id: str
    user_id: str
    message: str
    page: str | None = None
    response_mode: str | None = None
    topic_hint: str | None = None
    history_summary: str | None = None
    # 这一层把外部上下文带进单轮对话，门店锚点、城市和来源都会从这里继续传下去。
    client_context: dict[str, Any] = Field(default_factory=dict)


class ClarificationOption(CoreModel):
    id: str
    label: str
    value: str | None
    description: str | None


class ClarificationCard(CoreModel):
    card_id: str
    question: str
    options: list[ClarificationOption] = Field(default_factory=list)
    ambiguity_type: str | None
    source_turn_id: str | None
    expires_at: datetime | None


class ReferenceResolutionResult(CoreModel):
    resolved: bool = False
    confidence: float = 0.0
    resolved_entity: str | None
    candidate_entities: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class RetrievalPlan(CoreModel):
    semantic_query: str = ""
    keyword_query: str = ""
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)
    preferred_chunk_types: list[str] = Field(default_factory=list)
    preferred_chunk_roles: list[str] = Field(default_factory=list)
    need_retry_rewrite: bool = False
    strategy: str = "dense+sparse+metadata->rrf->rerank->evidence"
    source: str = "classifier"
    reasoning_notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Citation(CoreModel):
    chunk_id: str
    document_id: str | None
    source_type: str | None
    version: str | None
    score: float | None
    title: str | None
    locator: str | None


class EvidenceItem(CoreModel):
    chunk_id: str
    content: str
    score: float = 0.0
    document_id: str | None
    chunk_type: str | None
    tier: str = "strong"
    citation_chunk_id: str | None
    source_chunk_id: str | None
    parent_chunk_id: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidencePack(CoreModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    discard_summary: dict[str, Any] = Field(default_factory=dict)
    top_scores: list[float] = Field(default_factory=list)
    evidence_status: str = "EMPTY"
    strong_items: list[EvidenceItem] = Field(default_factory=list)
    weak_items: list[EvidenceItem] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class HybridRecallCandidate(CoreModel):
    chunk_id: str
    score: float = 0.0
    content: str | None
    document_id: str | None
    chunk_type: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class HybridRecallResult(CoreModel):
    dense_hits: list[HybridRecallCandidate] = Field(default_factory=list)
    sparse_hits: list[HybridRecallCandidate] = Field(default_factory=list)
    metadata_hits: list[HybridRecallCandidate] = Field(default_factory=list)
    fused_hits: list[HybridRecallCandidate] = Field(default_factory=list)
    reranked_hits: list[HybridRecallCandidate] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class RagResult(CoreModel):
    status: RagStatus = RagStatus.EMPTY
    evidence_pack: EvidencePack | None
    citations: list[Citation] = Field(default_factory=list)
    evidence_status: str = "EMPTY"
    retrieval_strategy: str = "dense+sparse+metadata->rrf->rerank->evidence"
    metrics: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class AnswerPlan(CoreModel):
    sections: list[str] = Field(default_factory=list)
    lead: str | None
    ending_prompt: str | None
    extra: dict[str, Any] = Field(default_factory=dict)


class EntityJoinResult(CoreModel):
    candidate_entities: list[str] = Field(default_factory=list)
    evidence_bindings: dict[str, list[str]] = Field(default_factory=dict)
    tool_bindings: dict[str, list[str]] = Field(default_factory=dict)
    selected_entity: str | None = None
    cross_entity_detected: bool = False
    issues: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class SemanticParseResult(CoreModel):
    primary_intent: str | None = None
    top_level_intent: str | None = None
    sub_intents: list[str] = Field(default_factory=list)
    polarity: PolarityType = PolarityType.NEUTRAL
    negative_scope: NegativeScopeType = NegativeScopeType.ACTION
    target_type: TargetType = TargetType.AMBIGUOUS
    local_route: LocalRouteType = LocalRouteType.CLARIFY
    target_shops: list[str] = Field(default_factory=list)
    target_categories: list[str] = Field(default_factory=list)
    excluded_shops: list[str] = Field(default_factory=list)
    excluded_categories: list[str] = Field(default_factory=list)
    excluded_features: list[str] = Field(default_factory=list)
    required_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    forbidden_facets: list[str] = Field(default_factory=list)
    facets: list[str] = Field(default_factory=list)
    required_sources: list[str] = Field(default_factory=list)
    needs_context: bool = False
    constraints: dict[str, Any] = Field(default_factory=dict)
    target_reference: str | None = None
    confidence: float = 0.0
    missing_slots: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class SourceContract(CoreModel):
    required_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    forbidden_facets: list[str] = Field(default_factory=list)
    facet_source_map: dict[str, Any] = Field(default_factory=dict)
    target_shop_id: int | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)
    comparison_shop_ids: list[int] = Field(default_factory=list)
    scope_kind: str | None = None
    target_reference_source: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ClaimSourceRef(CoreModel):
    source_type: Literal[
        "tool_structured",
        "realtime_tool",
        "rag_evidence",
        "rerank_reason",
        "user_context",
        "template",
        "llm_generated",
    ] = "llm_generated"
    source_id: str = ""
    source_label: str | None = None
    confidence: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)


class ClaimBinding(CoreModel):
    claim_id: str = ""
    claim_type: str = "generic"
    facet: str = ""
    text: str = ""
    risk_level: Literal["high", "medium", "low"] = "low"
    entity_id: str | None = None
    shop_id: int | None = None
    entity_name: str | None = None
    primary_source_type: Literal[
        "tool_structured",
        "realtime_tool",
        "rag_evidence",
        "rerank_reason",
        "user_context",
        "template",
        "llm_generated",
    ] = "llm_generated"
    source_ids: list[str] = Field(default_factory=list)
    supporting_sources: list[ClaimSourceRef] = Field(default_factory=list)
    support_status: Literal["supported", "partial", "unsupported", "conflicted"] = "unsupported"
    extra: dict[str, Any] = Field(default_factory=dict)


class ReviewReport(CoreModel):
    decision: Literal["pass", "repair_answer", "retry_rag", "retry_tool", "retry_step", "replan", "degrade"] = "pass"
    reason: str = ""
    failed_facets: list[str] = Field(default_factory=list)
    repair_hint: str = ""
    retry_target: str | None = None
    retry_count: int = 0
    max_retry_count: int = 1
    target_step_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LoopCounter(CoreModel):
    retry_rag: int = 0
    retry_tool: int = 0
    retry_step: int = 0
    repair_answer: int = 0
    replan: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class AnswerContract(CoreModel):
    # 这些字段共同定义本轮回答边界：回答什么、依赖什么证据、能不能用工具。
    original_query: str = ""
    allowed_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    forbidden_facets: list[str] = Field(default_factory=list)
    required_facets: list[dict[str, Any]] = Field(default_factory=list)
    # 需要走实时工具的面，tool_planner 会靠这个字段决定是否下发工具调用。
    realtime_facets: list[str] = Field(default_factory=list)
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)
    tool_requirements: dict[str, Any] = Field(default_factory=dict)
    forbidden_without_evidence: list[str] = Field(default_factory=list)
    candidate_entities: list[str] = Field(default_factory=list)
    selected_entity: str | None = None
    missing_slots: list[str] = Field(default_factory=list)
    clarification_slot: str | None = None
    answer_style: str | None = None
    scope_kind: str | None = None
    facet_source_expectations: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class AnswerVerifierResult(CoreModel):
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    suggested_response_mode: str = "grounded"
    repair_hint: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class PlanStep(CoreModel):
    # 单个执行步，既给规划器读，也给后续执行节点直接消费。
    step_id: str = ""
    goal: str = ""
    expected_output: str | None
    allowed_tools: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal['low', 'medium', 'high'] = "low"
    requires_approval: bool = False


class TaskPlan(CoreModel):
    # 复杂链路的显式执行计划，plan_execute 这条路会直接依赖它。
    enabled: bool = False
    trigger_reason: str = ""
    summary: str = ""
    route_candidate: str | None = None
    task_complexity: Literal['simple', 'complex'] = "complex"
    execution_mode: Literal['auto', 'simple', 'plan_execute'] = "plan_execute"
    can_fallback_to_legacy: bool = True
    required_facets: list[dict[str, Any]] = Field(default_factory=list)
    optional_facets: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    failure_reason: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class StepResult(CoreModel):
    step_id: str = ""
    status: Literal['success', 'failed', 'skipped', 'need_approval'] = "skipped"
    tools_used: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    result: dict[str, Any] | str | None
    error: str | None
    next_action: str | None


class PlanExecutionSummary(CoreModel):
    status: Literal['completed', 'partial', 'failed', 'need_approval'] = "partial"
    completed_steps: int = 0
    total_steps: int = 0
    key_findings: list[str] = Field(default_factory=list)
    final_decision: str | None


class ToolSelection(CoreModel):
    tool_name: str | None
    should_execute: bool = False
    input_payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None
    approval_required: bool = False
    approval_status: str | None
    approval_request: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(CoreModel):
    status: ToolExecutionStatus = ToolExecutionStatus.SKIPPED
    tool_name: str | None
    output_payload: dict[str, Any] = Field(default_factory=dict)
    degraded_to: str | None
    error: WorkflowErrorCode | None
    approval_required: bool = False
    approval_status: str | None
    approval_request: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedToolResult(CoreModel):
    status: ToolExecutionStatus = ToolExecutionStatus.SKIPPED
    tool_name: str | None
    normalized_output: dict[str, Any] = Field(default_factory=dict)
    used_tools: list[str] = Field(default_factory=list)
    approval_required: bool = False
    approval_status: str | None
    approval_request: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class TurnUnderstandingResult(CoreModel):
    decision: TurnDecision = TurnDecision.DIRECT_ANSWER
    intent: IntentType = IntentType.EXPLAIN
    intent_confidence: float = 0.0
    requested_output_style: OutputStyle | None = None
    reference_resolution: ReferenceResolutionResult | None = None
    retrieval_plan: RetrievalPlan | None = None
    clarification_card: ClarificationCard | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class FastDecision(CoreModel):
    intent: IntentType = IntentType.EXPLAIN
    needs_rag: bool = False
    needs_tool: bool = False
    needs_clarify: bool = False
    needs_query_rewrite: bool = False
    confidence: float = 0.0
    key_slots: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class InputQualityDecision(CoreModel):
    kind: str = "valid_task"
    is_valid: bool = True
    reason: str = ""
    score: float = 1.0
    signals: list[str] = Field(default_factory=list)


class IntentRoutingDecision(CoreModel):
    name: str = "unknown"
    confidence: float = 0.0
    required_slots: list[str] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    allowed_routes: list[str] = Field(default_factory=list)  # DEPRECATED: 由 facet_plan.source 替代
    forbidden_routes: list[str] = Field(default_factory=list)  # DEPRECATED: 由 facet_plan 替代


class RewriteDecision(CoreModel):
    original_query: str = ""
    rewritten_query: str = ""
    added_terms: list[str] = Field(default_factory=list)
    removed_terms: list[str] = Field(default_factory=list)
    preserved_constraints: list[str] = Field(default_factory=list)
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
    fallback_reason: str | None = None
    missing_slots: list[str] = Field(default_factory=list)
    clarification_slot: str | None = None
    covered_facets: list[str] = Field(default_factory=list)
    missing_facets: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class RetrievalEligibility(CoreModel):
    allowed: bool = False
    blocked: bool = False
    reason: str = ""
    blocked_reason: str | None = None
    failure_reasons: list[str] = Field(default_factory=list)
    required_action: str | None = None
    intent_allowed: bool = False
    input_quality_ok: bool = False
    input_quality_score: float = 0.0
    normalized_query: str | None = None
    rewritten_query: str | None = None
    semantic_query: str | None = None
    retrieval_plan_valid: bool = False
    route_candidate: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(CoreModel):
    # 路由器的综合输出，决定本轮是直答、检索、工具、澄清还是拒答。
    raw_query: str = ""
    normalized_query: str = ""
    domain: str = "general"
    confidence: float = 0.0
    input_quality: InputQualityDecision = Field(default_factory=InputQualityDecision)
    intent: IntentRoutingDecision = Field(default_factory=IntentRoutingDecision)

    # v4 能力线路
    capability_line: Literal["direct", "single_shop_tool", "recommendation_tool", "comparison_tool", "transaction_tool", "jailbreak", "clarify"] = "direct"

    required_action: str = "no_op"
    blocked: bool = False
    blocked_reason: str | None = None
    should_rewrite_query: bool = False
    should_retrieve: bool = False
    should_call_tool: bool = False
    resolved_shop_id: int | None = None
    should_use_memory: bool = True
    should_persist_memory: bool = True
    should_vectorize_memory: bool = True
    should_emit_retrieval_events: bool = False
    retrieval_skipped_reason: str | None = None
    missing_slots: list[str] = Field(default_factory=list)
    resolved_references: list[str] = Field(default_factory=list)
    route_reason: str = ""
    safeguards_triggered: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    route_candidate: str | None = None
    canonical_route: str | None = None
    required_sources: list[str] = Field(default_factory=list)
    semantic_parse_result: SemanticParseResult | None = None
    execution_mode: Literal["clarify", "simple", "standard", "complex"] = "simple"  # DEPRECATED: facet_planner 路径固定设为 "simple"，仅旧路径使用
    preferred_chunk_roles: list[str] = Field(default_factory=list)  # DEPRECATED: 由 facet_plan.preferred_roles 替代
    tool_candidates: list[str] = Field(default_factory=list)  # DEPRECATED: 由 facet_plan 替代
    clarification_question: str | None = None
    rewrite_decision: RewriteDecision | None = None
    evidence_quality: EvidenceQualityDecision | None = None
    facet_plan: list["FacetPlan"] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class FacetPlan(CoreModel):
    """一个信息面及其数据源。

    由 facet_planner 输出，指定需要获取什么信息、从哪里获取。
    """
    name: str = ""
    source: Literal["rag", "tool", "recommendation", "direct"] = "rag"
    tool_name: str | None = None
    preferred_roles: list[str] = Field(default_factory=list)
    required: bool = True
    parallel_group: int = 0

    # v4 路由扩展字段
    execution_mode: Literal["direct", "single_shop_tool", "recommendation_tool", "comparison_tool", "transaction_tool", "clarify", "jailbreak"] = "direct"
    required_target: Literal["single_shop", "multi_shop", "any", "none"] = "any"
    required_inputs: list[str] = Field(default_factory=list)
    allowed_claim_types: list[str] = Field(default_factory=list)
    ambiguity_policy: Literal["clarify", "candidate_list", "skip"] = "clarify"
    fallback_action: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class FacetPlannerOutput(CoreModel):
    """facet_planner 的输出，替代原有的多层路由结果。"""
    facets: list[FacetPlan] = Field(default_factory=list)
    simple_response: str | None = None
    clarification_needed: bool = False
    clarification_question: str | None = None
    reject: bool = False
    reject_reason: str | None = None
    target_shop_id: int | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)
    recommendation_mode: bool = False


class RoutingContract(CoreModel):
    # 把路由判断收敛成执行契约，下游节点主要看这里来决定怎么做。
    required_action: str = "no_op"
    canonical_route: str | None = None
    required_sources: list[str] = Field(default_factory=list)
    required_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    forbidden_facets: list[str] = Field(default_factory=list)
    facet_source_map: dict[str, Any] = Field(default_factory=dict)
    facet_plan: list[FacetPlan] = Field(default_factory=list)

    target_shop_id: int | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)
    comparison_shop_ids: list[int] = Field(default_factory=list)
    single_shop_mode: bool = False
    recommendation_mode: bool = False
    scope_kind: str | None = None
    target_reference_source: str | None = None

    rag_allowed: bool = True
    tool_allowed: bool = True
    compose_allowed_facets: list[str] = Field(default_factory=list)

    input_invalid: bool = False
    need_clarify: bool = False
    clarify_reason: str | None = None


class TurnUnderstandingRequest(CoreModel):
    command: ChatTurnCommand
    persistent: PersistentSessionContext


class ReferenceResolutionRequest(CoreModel):
    raw_query: str
    current_topic: str | None = None
    recent_entities: list[str] = Field(default_factory=list)
    clarification_result: dict[str, Any] = Field(default_factory=dict)
    pending_clarification: ClarificationCard | None = None
    history_summary: str | None = None
    topic_hint: str | None = None


class QueryRewriteRequest(CoreModel):
    raw_query: str
    intent: IntentType | None = None
    requested_output_style: OutputStyle | None = None
    reference_resolution: ReferenceResolutionResult | None = None
    current_topic: str | None = None
    topic_hint: str | None = None
    intent_confidence: float = 0.0
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    base_filters: dict[str, Any] = Field(default_factory=dict)


class HybridRetrieveRequest(CoreModel):
    plan: RetrievalPlan


class EvidenceEvaluationRequest(CoreModel):
    plan: RetrievalPlan
    hybrid_recall: HybridRecallResult
    intent: IntentType | None
    requested_output_style: OutputStyle | None


class CitationBuildRequest(CoreModel):
    evidence_pack: EvidencePack


class KnowledgeSearchRequest(CoreModel):
    topic: str
    limit: int = 5
    category: str | None = None
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResult(CoreModel):
    matches: list[dict[str, Any]] = Field(default_factory=list)
    evidence_pack: EvidencePack | None = None
    citations: list[Citation] = Field(default_factory=list)
    retrieval_strategy: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolPlanningRequest(CoreModel):
    raw_query: str
    decision: str = ""
    routing_decision: RoutingDecision | None = None
    intent: IntentType | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    current_topic: str | None = None


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
    resolved_topic: str | None = None
    intent: IntentType | None = None
    requested_output_style: OutputStyle | None = None
    tool_name: str | None = None
    request_ts: datetime
    persistent: PersistentSessionContext
    final_confidence: float = 0.0
    session_state_patch: dict[str, Any] = Field(default_factory=dict)
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
    resolved_topic: str | None = None
    intent: IntentType | None = None
    requested_output_style: OutputStyle | None = None
    tool_name: str | None = None
    request_ts: datetime
    persistent: PersistentSessionContext
    memory_updates: MemoryUpdateSummary = Field(default_factory=lambda: MemoryUpdateSummary())
    final_confidence: float = 0.0
    session_state_patch: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateSummary(CoreModel):
    current_topic: str | None = None
    updated_preferences: dict[str, Any] = Field(default_factory=dict)
    weak_topics: list[str] = Field(default_factory=list)
    semantic_memory: dict[str, Any] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    summary_version: int = 0
    summary_updated_at: datetime | None = None
    memory_trace_id: str | None = None
    write_status: str = "success"
    write_targets: list[str] = Field(default_factory=list)
    decision_reasons: list[str] = Field(default_factory=list)
    degraded_parts: list[str] = Field(default_factory=list)
    retryable_failures: list[str] = Field(default_factory=list)
    permanent_failures: list[str] = Field(default_factory=list)
    memory_write: MemoryWriteResult | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MemoryWriteTargetResult(CoreModel):
    target: str
    status: Literal['success', 'degraded', 'retryable_failure', 'permanent_failure', 'skipped'] = "success"
    reason: str | None
    retryable: bool = False
    error: str | None
    details: dict[str, Any] = Field(default_factory=dict)


class MemoryWriteResult(CoreModel):
    trace_id: str = ""
    idempotency_key: str = ""
    session_id: str = ""
    turn_id: str = ""
    user_id: str = ""
    operation: str = ""
    status: Literal['success', 'partial_success', 'degraded', 'pending_compensation', 'permanent_failure'] = "success"
    write_targets: list[str] = Field(default_factory=list)
    target_results: list[MemoryWriteTargetResult] = Field(default_factory=list)
    decision_reasons: list[str] = Field(default_factory=list)
    degraded_parts: list[str] = Field(default_factory=list)
    retryable_failures: list[str] = Field(default_factory=list)
    permanent_failures: list[str] = Field(default_factory=list)
    compensation_required: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class PersistSessionResult(CoreModel):
    updated_context: PersistentSessionContext
    memory_updates: MemoryUpdateSummary = Field(default_factory=MemoryUpdateSummary)
    memory_write: MemoryWriteResult | None


class MasteryUpdateResult(CoreModel):
    updated_context: PersistentSessionContext | None = None
    memory_updates: MemoryUpdateSummary = Field(default_factory=MemoryUpdateSummary)
    memory_write: MemoryWriteResult | None = None


class RetrievalSummary(CoreModel):
    semantic_query: str | None
    keyword_query: str | None
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)
    retrieval_strategy: str | None
    retrieval_hit_count: int = 0
    evidence_used_count: int = 0
    evidence_status: str = "EMPTY"
    evidence_strong_count: int = 0
    evidence_weak_count: int = 0
    route_decision: str | None
    route_reason: str | None
    current_stage: str | None
    stage_status: str | None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    source_mode: str | None = None
    degraded_reason: str | None = None
    knowledge_freshness: dict[str, Any] = Field(default_factory=dict)
    model_hint_used: bool = False


class MemoryUsedItemSummary(CoreModel):
    memory_id: str = ""
    memory_type: str | None
    scope: str | None
    summary: str | None
    source: str | None
    confidence: float = 0.0
    retrieval_kind: str | None = None
    collection_name: str | None = None
    source_domain: str | None = None


class MemoryUsedSummary(CoreModel):
    used: bool = False
    total_memories: int = 0
    retrieval_reason: str | None
    total_token_estimate: int = 0
    prompt_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)
    state_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)
    tool_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)
    semantic_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)
    episodic_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)
    procedural_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)
    rag_memories: list[MemoryUsedItemSummary] = Field(default_factory=list)


class AnswerComposeRequest(CoreModel):
    raw_query: str
    requested_output_style: OutputStyle | None
    rag_result: RagResult | None
    tool_result: NormalizedToolResult | None
    plan_summary: PlanExecutionSummary | None
    memory_injection_plan: MemoryInjectionPlan | None
    entity_join_result: EntityJoinResult | None = None
    answer_contract: AnswerContract | None = None
    answer_depth_policy: dict[str, Any] | None = None
    ranked_candidates: list[dict[str, Any]] = Field(default_factory=list)
    facet_result_bundle: dict[str, Any] | None = None
    answer_context: dict[str, Any] | None = None
    routing_decision: RoutingDecision | None = None
    evidence_quality: EvidenceQualityDecision | None = None
    final_response_mode: str | None = None
    missing_slots: list[str] = Field(default_factory=list)
    clarification_slot: str | None = None
    allow_direct_response: bool = False
    direct_response_kind: str | None
    history_summary: str | None = None
    stream_event_sink: Any = None
    stream_event_meta: dict[str, Any] = Field(default_factory=dict)


class AnswerComposeResult(CoreModel):
    answer_text: str
    confidence: float = 0.0


class PersistentSessionContext(CoreModel):
    # 当前会话锚点：用于把上一轮选中的店、城市和比较对象延续到下一轮追问。
    current_topic: str | None = None
    current_shop: str | None = None
    current_shop_anchor: dict[str, Any] = Field(default_factory=dict)
    recent_entities: list[str] = Field(default_factory=list)
    pending_user_need: dict[str, Any] = Field(default_factory=dict)
    clarification_result: dict[str, Any] = Field(default_factory=dict)
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    last_retrieval_topic: str | None = None
    history_summary: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    summary_version: int = 0
    summary_updated_at: datetime | None = None
    pending_clarification: ClarificationCard | None = None
    current_city: str | None = None
    current_location: dict[str, Any] = Field(default_factory=dict)
    current_constraints: dict[str, Any] = Field(default_factory=dict)
    last_candidates: list[dict[str, Any]] = Field(default_factory=list)
    # 这些字段表示当前轮已经锚定到哪家店，后续“有券吗”“营业吗”都会沿用这里的门店。
    selected_shop_id: int | None = None
    selected_shop_name: str | None = None
    local_life_preferences: list[str] = Field(default_factory=list)
    local_life_avoid: list[str] = Field(default_factory=list)
    current_scene: str | None = None
    current_action: str | None = None
    page: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None
    # current_stage 和 stage_status 记录单轮流程处于哪个节点，便于调试和回放。
    current_stage: str | None = None
    stage_status: str | None = None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    # 下面这些字段是对话状态机的显式状态，负责承接“有券吗”“离我多远”这类追问。
    dialog_state: str | None = None  # DialogState value
    dialog_task: str | None = None  # current_task
    dialog_intent: str | None = None  # active_intent
    dialog_comparison_targets: list[str] = Field(default_factory=list)
    dialog_pending_slots: list[str] = Field(default_factory=list)
    dialog_transition_count: int = 0


class TurnRuntimeState(CoreModel):
    # 单轮执行上下文，路由、检索、规划和最终回答都会写在这里。
    raw_query: str
    decision: str = "direct_answer"
    intent: IntentType | None = None
    intent_confidence: float = 0.0
    requested_output_style: OutputStyle | None = None
    task_complexity: Literal['simple', 'complex'] = "simple"
    execution_mode: Literal['auto', 'simple', 'plan_execute'] = "auto"
    risk_level: Literal['low', 'medium', 'high'] = "low"
    route_decision: str | None = None
    route_reason: str | None = None
    routing_decision: RoutingDecision | None = None
    routing_contract: RoutingContract | None = None
    rewrite_decision: RewriteDecision | None = None
    evidence_quality: EvidenceQualityDecision | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    reference_resolution: ReferenceResolutionResult | None = None
    clarification_card: ClarificationCard | None = None
    retrieval_plan: RetrievalPlan | None = None
    hybrid_recall: HybridRecallResult | None = None
    evidence_pack: EvidencePack | None = None
    citations: list[Citation] = Field(default_factory=list)
    answer_plan: AnswerPlan | None = None
    entity_join_result: EntityJoinResult | None = None
    semantic_parse_result: SemanticParseResult | None = None
    source_contract: SourceContract | None = None
    review_report: ReviewReport | None = None
    loop_counter: LoopCounter | None = None
    answer_contract: AnswerContract | None = None
    answer_verifier_result: AnswerVerifierResult | None = None
    tool_plan: ToolSelection | None = None
    # task_plan / plan / final_task_summary 只在复杂链路里真正起作用。
    task_plan: TaskPlan | None = None
    raw_tool_result: ToolExecutionResult | None = None
    tool_result: NormalizedToolResult | None = None
    plan: list[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0
    current_step: PlanStep | None = None
    step_results: list[StepResult] = Field(default_factory=list)
    need_replan: bool = False
    replan_reason: str | None = None
    need_human_approval: bool = False
    approval_request: dict[str, Any] = Field(default_factory=dict)
    final_task_summary: PlanExecutionSummary | None = None
    sensory_memory: dict[str, Any] = Field(default_factory=dict)
    short_term_window: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_memory_pack: RetrievedMemoryPack | None = None
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    memory_write_plan: MemoryWritePlan | None = None
    memory_injection_plan: MemoryInjectionPlan | None = None
    # final_answer 和 rag_result 是最终输出前最关键的两类结果。
    final_answer: str | None = None
    rag_result: RagResult | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class GraphRuntimeMeta(CoreModel):
    # client_context 贯穿整条链路，决定路由、记忆和调试指标的上下文输入。
    trace_id: str
    session_id: str
    turn_id: str
    workflow_version: str
    request_ts: datetime
    user_id: str
    page: str | None = None
    response_mode: str | None = None
    topic_hint: str | None = None
    history_summary: str | None = None
    client_context: dict[str, Any] = Field(default_factory=dict)
    # metrics、emitted_events 和 memory_updates 主要服务于可观测性和端到端断言。
    metrics: dict[str, Any] = Field(default_factory=dict)
    errors: list[ErrorInfo] = Field(default_factory=list)
    degrade_to: str | None = None
    terminal_event: TerminalEvent | None = None
    emitted_events: list[SseEnvelope] = Field(default_factory=list)
    memory_updates: MemoryUpdateSummary = Field(default_factory=MemoryUpdateSummary)
    memory_trace: MemoryTrace | None = None
    session_persisted: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class FinalPayload(CoreModel):
    # 最终 SSE/HTTP 输出需要的摘要、来源和会话轨迹都集中在这里。
    answer_text: str
    citations: list[Citation] = Field(default_factory=list)
    claim_bindings: list[ClaimBinding] = Field(default_factory=list)
    source_mode: str | None = None
    degraded_reason: str | None = None
    knowledge_freshness: dict[str, Any] = Field(default_factory=dict)
    used_tools: list[str] = Field(default_factory=list)
    resolved_topic: str | None = None
    current_topic: str | None = None
    mode: str = "recommend"
    source: str = "local-life-agent"
    page: str | None = None
    selected_shop_id: int | None = None
    # 这些字段把本轮最终走到了哪条路、卡在哪个节点一起带回给前端和调试工具。
    route_decision: str | None = None
    route_reason: str | None = None
    current_stage: str | None = None
    stage_status: str | None = None
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    shops: list[dict[str, Any]] = Field(default_factory=list)
    vouchers: list[dict[str, Any]] = Field(default_factory=list)
    suggested_replies: list[dict[str, Any]] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    task_chain: list[dict[str, Any]] = Field(default_factory=list)
    ranked_candidates: list[dict[str, Any]] = Field(default_factory=list)
    last_candidates: list[dict[str, Any]] = Field(default_factory=list)
    fallback: bool = False
    retrieval_strategy: str | None = None
    grounding_status: Literal['grounded', 'weakly_grounded', 'not_grounded'] = "not_grounded"
    retrieval_summary: RetrievalSummary | None = None
    memory_used_summary: MemoryUsedSummary | None = None
    memory_updates: dict[str, Any] = Field(default_factory=dict)
    answer_style: str | None = None
    final_response_mode: str | None = None
    route_gate: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    approval_required: bool = False
    approval_request: dict[str, Any] = Field(default_factory=dict)
    transaction_draft: dict[str, Any] = Field(default_factory=dict)
    safety_result: dict[str, Any] = Field(default_factory=dict)
    intent: IntentType | None = None
    requested_output_style: OutputStyle | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(CoreModel):
    code: str
    message: str
    retryable: bool = False
    stage: str
    degraded_to: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    current_stage: str | None = None
    stage_status: str | None = None
    route_decision: str | None = None
    route_reason: str | None = None


class SseEnvelope(CoreModel):
    event_type: str
    trace_id: str
    session_id: str
    turn_id: str
    timestamp: datetime
    workflow_version: str
    payload: dict[str, Any] = Field(default_factory=dict)


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
SemanticParseResult.model_rebuild()
SourceContract.model_rebuild()
ClaimSourceRef.model_rebuild()
ClaimBinding.model_rebuild()
ReviewReport.model_rebuild()
LoopCounter.model_rebuild()
EntityJoinResult.model_rebuild()
AnswerContract.model_rebuild()
AnswerVerifierResult.model_rebuild()
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
RoutingContract.model_rebuild()
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
