"""Global DTO schemas shared across all layers.

Pydantic BaseModel classes with built-in validation and JSON
serialization/deserialization.

Core DTOs:    TurnInput, SemanticFrame, PendingClarification, ToolResult
Complex DTOs: ExecutionPlan, EvidencePack, ResolveShopResult, AnswerPlan
              (deepened per todo/04 — 01.5 stage)
Context:      GlobalTurnContext (orchestration spine)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .enums import (
    TopIntent,
    TaskType,
    Facet,
    ToolResultStatus,
    ErrorCode,
)


# ===================================================================
# 0. Sub-enums for the deepened complex DTOs
# ===================================================================


class SourceType(str, Enum):
    """Valid source origins for evidence items."""
    TOOL = "tool"
    MOCK = "mock"
    HTTP = "http"
    DB = "db"


class MatchedBy(str, Enum):
    """How a shop was matched during resolution."""
    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    LOCATION_HINT = "location_hint"
    HISTORY = "history"


# ===================================================================
# 1. Core DTOs
# ===================================================================


class UserContext(BaseModel):
    """User's location and location metadata."""
    location_name: str = "北京邮电大学"
    lat: float | None = 39.9609
    lng: float | None = 116.3581
    location_status: str = "provided"
    location_source: str = "provided"
    requires_location: bool = False
    location_missing_reason: str = ""


class TurnInput(BaseModel):
    """Normalised input after receive + normalise."""
    input_type: str = "text"
    raw_text: str = ""
    user_context: UserContext | None = None


class SemanticFrame(BaseModel):
    """Structured interpretation of the user's request."""

    model_config = ConfigDict(extra="forbid")

    top_intent: TopIntent | None = None
    task_type: TaskType | None = None
    primary_task: str = ""
    facets: list["FacetSpec"] = Field(default_factory=list)
    merchant_mentions: list[str] = Field(default_factory=list)
    brand_mentions: list[str] = Field(default_factory=list)
    branch_mentions: list[str] = Field(default_factory=list)
    surface_hints: list[str] = Field(default_factory=list)
    alias_hints: list[str] = Field(default_factory=list)
    reference_mentions: list[str] = Field(default_factory=list)
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    ordinal_references: list[str] = Field(default_factory=list)
    deictic_references: list[str] = Field(default_factory=list)
    focused_facets: list[str] = Field(default_factory=list)
    comparison_focus: str = ""
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    ranking_signals: dict[str, Any] = Field(default_factory=dict)
    follow_up: dict[str, Any] | None = None
    confidence: float = 0.0
    need_context: bool = False
    semantic_source: str = ""
    fallback_reason: str = ""
    llm_called: bool = False
    llm_backend: str = ""

    # Candidate-resolution fields (populated by the Candidate layer)
    candidate_source: str | None = None
    candidate_category: str = ""
    candidate_limit: int | None = None
    candidate_sort_by: list[dict[str, Any]] = Field(default_factory=list)
    candidate_filters: dict[str, Any] = Field(default_factory=dict)
    candidate_source_origin: str | None = None

    @field_validator("facets", mode="before")
    @classmethod
    def _coerce_facets(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, FacetSpec):
                coerced.append(item)
                continue
            if isinstance(item, Facet):
                coerced.append({"name": item, "required": False})
                continue
            if isinstance(item, str):
                coerced.append({"name": item, "required": False})
                continue
            if isinstance(item, dict):
                payload = dict(item)
                if "name" not in payload and "facet" in payload:
                    payload["name"] = payload["facet"]
                coerced.append(payload)
                continue
            coerced.append(item)
        return coerced


class FacetSpec(BaseModel):
    """Facet request metadata with a required/optional boundary."""

    model_config = ConfigDict(extra="forbid")

    name: Facet
    required: bool = False

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FacetSpec):
            return self.name == other.name and self.required == other.required
        if isinstance(other, Facet):
            return self.name == other
        if isinstance(other, str):
            try:
                return self.name == Facet(other)
            except Exception:
                return False
        return False


SemanticFrame.model_rebuild()


class PendingClarification(BaseModel):
    """An outstanding clarification waiting for user reply."""
    pending_id: str = ""
    original_task_type: str = ""
    candidate_targets: list[dict[str, Any]] = Field(default_factory=list)
    expected_reply_type: str = ""
    created_at: datetime | None = None
    expires_at: datetime | None = None
    original_text: str = ""
    original_semantic_frame: dict[str, Any] | None = None
    reason: str = ""
    source_node: str = ""
    already_resolved_targets: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_target_slot: str = ""


class ActiveTurnResult(BaseModel):
    """Canonical result of pending clarification turn resolution."""

    route: str = ""
    source: str = ""
    reason: str = ""
    confidence: float = 0.0
    selected_index: int | None = None
    selected_candidate: dict[str, Any] | None = None
    new_query: str = ""


class ToolResult(BaseModel):
    """Normalised result from a single tool call.

    The `result_status` field follows strict verbalisation rules
    defined in the AnswerPolicy (see todo/03 §4).
    """
    call_id: str
    shop_id: str = ""
    tool_name: str
    success: bool = False
    result_status: ToolResultStatus
    data: Any = None
    error_code: ErrorCode | None = None
    error_message: str = ""
    source: str = ""
    degraded: bool = False
    retriable: bool = True
    backend_source: str = ""
    http_status: int | None = None
    endpoint: str | None = None
    fallback_from: str | None = None

    @model_validator(mode="after")
    def _validate_shop_scope(self) -> ToolResult:
        """Enforce shop_id only for shop-scoped tools."""
        shop_scoped_tools = {
            "get_shop_detail",
            "get_coupon_list",
            "check_open_status",
            "get_distance_eta",
            "get_deal_list",
        }
        if self.tool_name in shop_scoped_tools and not self.shop_id.strip():
            raise ValueError(f"Tool '{self.tool_name}' requires shop_id")
        return self


class ToolTrace(BaseModel):
    """Debug trace embedded in the new query tool payloads."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = ""
    backend_source: str = "unknown"
    duration_ms: int | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    status: str = ""
    item_count: int | None = None
    missing_shop_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


class ShopCardInput(BaseModel):
    """Input contract for get_shop_cards."""

    model_config = ConfigDict(extra="forbid")

    shop_ids: list[str] = Field(default_factory=list)
    user_location: dict[str, Any] | None = None
    need_coupon_brief: bool = True
    need_open_status: bool = True
    need_distance_eta: bool = True
    max_items: int | None = None


class ShopCardItem(BaseModel):
    """A lightweight shop card used in recommendation and comparison."""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = ""
    name: str = ""
    alias: list[str] = Field(default_factory=list)
    category: str | None = None
    address: str | None = None
    rating: float | None = None
    avg_price: float | None = None
    price_level: str | None = None
    distance_m: int | None = None
    eta_minutes: int | None = None
    is_open: bool | None = None
    open_status_text: str | None = None
    coupon_count: int | None = None
    has_coupon: bool | None = None
    top_coupon_title: str | None = None
    top_tags: list[str] = Field(default_factory=list)
    scene_tags: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)


class ShopCardsResult(BaseModel):
    """Output contract for get_shop_cards."""

    model_config = ConfigDict(extra="forbid")

    status: str = "empty"
    items: list[ShopCardItem] = Field(default_factory=list)
    missing_shop_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace: ToolTrace = Field(default_factory=ToolTrace)


class ShopReviewSummaryInput(BaseModel):
    """Input contract for get_shop_review_summary."""

    model_config = ConfigDict(extra="forbid")

    shop_ids: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)
    scene: str | None = None
    max_reviews: int | None = None


class ReviewSceneFit(BaseModel):
    """Scene fit summary for a specific use case."""

    model_config = ConfigDict(extra="forbid")

    scene: str | None = None
    score: float | None = None
    label: str | None = None
    reasons: list[str] = Field(default_factory=list)


class ShopReviewSummaryItem(BaseModel):
    """Structured review summary for a single shop."""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = ""
    name: str = ""
    rating: float | None = None
    review_count: int | None = None
    taste_score: float | None = None
    environment_score: float | None = None
    service_score: float | None = None
    price_score: float | None = None
    positive_tags: list[str] = Field(default_factory=list)
    negative_tags: list[str] = Field(default_factory=list)
    scene_tags: list[str] = Field(default_factory=list)
    scene_fit: ReviewSceneFit = Field(default_factory=ReviewSceneFit)
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    summary: str | None = None
    source_fields: list[str] = Field(default_factory=list)


class ShopReviewSummaryResult(BaseModel):
    """Output contract for get_shop_review_summary."""

    model_config = ConfigDict(extra="forbid")

    status: str = "empty"
    items: list[ShopReviewSummaryItem] = Field(default_factory=list)
    missing_shop_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace: ToolTrace = Field(default_factory=ToolTrace)


class DealListInput(BaseModel):
    """Input contract for get_deal_list."""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = ""
    people_count: int | None = None
    budget_per_person: float | None = None
    deal_type: str | None = None
    only_available: bool = True


class DealItem(BaseModel):
    """Structured deal / group-buy fact."""

    model_config = ConfigDict(extra="forbid")

    deal_id: str = ""
    title: str = ""
    deal_type: str | None = None
    price: float | None = None
    original_price: float | None = None
    discount_rate: float | None = None
    people_count_min: int | None = None
    people_count_max: int | None = None
    avg_price_per_person: float | None = None
    available: bool | None = None
    valid_time_text: str | None = None
    use_time_rules: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    included_items: list[str] = Field(default_factory=list)
    recommend_tags: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)


class DealListResult(BaseModel):
    """Output contract for get_deal_list."""

    model_config = ConfigDict(extra="forbid")

    status: str = "empty"
    shop_id: str = ""
    shop_name: str | None = None
    items: list[DealItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace: ToolTrace = Field(default_factory=ToolTrace)


# ===================================================================
# 2. ExecutionPlan & ToolCallSpec (deepened per todo/04 §2)
# ===================================================================


class ExecutionStage(BaseModel):
    """A named stage within an execution plan, grouping related tool calls.

    Mirrors the recommendation flow from todo/04 §2:
      stage_1 → search_shops
      stage_2 → batch get_shop_detail (top_k)
      stage_3 → batch check_open_status / get_coupon_list
      stage_4 → ranking_policy
    """
    stage_id: str = ""          # e.g. "stage_1"
    description: str = ""       # e.g. "Search shops by query"
    tool_names: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    max_parallelism: int = 4


class ToolCallSpec(BaseModel):
    """Specification for a single tool call within an execution plan.

    Deepened per todo/04 §2 with retry/fallback policy and parallelism.
    """
    call_id: str = ""
    tool_name: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    target_shop_id: str = ""
    required: bool = True
    facet: str = ""
    depends_on: list[str] = Field(default_factory=list)
    timeout_ms: int = 2000
    retry_policy: dict[str, Any] = Field(default_factory=lambda: {"max_attempts": 3, "backoff_ms": 200})
    fallback_policy: dict[str, Any] = Field(default_factory=lambda: {"fallback_tool": "", "fallback_args": {}})
    group_id: str = ""
    max_parallelism: int = 1


class ExecutionPlan(BaseModel):
    """Ordered / staged plan of tool calls for one turn.

    Deepened per todo/04 §2 — now carries explicit execution stages
    alongside the flat tool_calls list.
    """
    plan_id: str = ""
    task_type: str = ""
    tool_calls: list[ToolCallSpec] = Field(default_factory=list)
    stages: list[ExecutionStage] = Field(default_factory=list)
    target_shop_ids: list[str] = Field(default_factory=list)
    query_terms: list[str] = Field(default_factory=list)
    scene_terms: list[str] = Field(default_factory=list)
    open_now_preferred: bool = False
    coupon_preferred: bool = False
    nearby_preferred: bool = False
    plan_source: str = ""
    planning_notes: list[str] = Field(default_factory=list)
    assumptions_used: list[str] = Field(default_factory=list)


class ToolIntentSpec(BaseModel):
    """LLM-only intermediate tool intent before hard validation."""
    tool_name: str = ""
    purpose: str = ""
    required: bool = True
    facet: str | None = None
    priority: int = 1
    depends_on: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ToolIntentPlan(BaseModel):
    """LLM-only high-level plan that can be compiled into an ExecutionPlan."""

    model_config = ConfigDict(extra="forbid")

    task_type: str = ""
    primary_task: str = ""
    purpose: str = ""
    confidence: float = 0.0
    tool_intents: list[ToolIntentSpec] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ===================================================================
# 3. EvidencePack (deepened per todo/04 §1)
# ===================================================================


class EvidenceItem(BaseModel):
    """A single piece of evidence backing a claim."""
    evidence_id: str = ""
    shop_id: str = ""
    shop_name: str = ""
    facet: str = ""
    tool_name: str = ""
    call_id: str = ""
    result_status: ToolResultStatus = ToolResultStatus.unknown
    field_path: str = ""
    value: Any = None
    confidence: float = 1.0
    timestamp: str = ""
    source_type: SourceType = SourceType.TOOL
    backend_source: str = ""


class EvidencePack(BaseModel):
    """Verified evidence from tool results — the only source of truth.

    Deepened per todo/04 §1 with ranking_snapshot and comparison_matrix.
    """
    target_shop_ids: list[str] = Field(default_factory=list)
    requested_facets: list[str] = Field(default_factory=list)
    facet_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    unknown_items: list[EvidenceItem] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    ranking_snapshot: dict[str, Any] | None = None
    comparison_matrix: dict[str, Any] | None = None
    tool_results: dict[str, Any] = Field(default_factory=dict)


# ===================================================================
# 4. ResolveShopResult (deepened per todo/04 §4 + conditional validation)
# ===================================================================


class ShopRef(BaseModel):
    """Minimal shop reference."""
    shop_id: str = ""
    shop_name: str = ""


class ShopCandidate(BaseModel):
    """Candidate shop for ambiguous resolution."""
    shop: ShopRef = Field(default_factory=ShopRef)
    match_score: float = 0.0
    matched_by: MatchedBy = MatchedBy.FUZZY


class ResolveShopResult(BaseModel):
    """Outcome of the shop-resolution step.

    Validates status/candidates consistency:
      - AMBIGUOUS  → candidates must be non-empty
      - NOT_FOUND  → candidates must be empty
      - RESOLVED   → resolved_shop must be set
    """
    status: str = ""  # RESOLVED | AMBIGUOUS | LOW_CONFIDENCE | NOT_FOUND
    resolved_shop: ShopRef | None = None
    candidates: list[ShopCandidate] = Field(default_factory=list)
    confidence: float = 0.0
    matched_by: MatchedBy = MatchedBy.FUZZY
    reason: str = ""

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> ResolveShopResult:
        if self.status == "AMBIGUOUS" and not self.candidates:
            raise ValueError(
                "ResolveShopResult status=AMBIGUOUS requires at least one candidate"
            )
        if self.status == "NOT_FOUND" and self.candidates:
            raise ValueError(
                "ResolveShopResult status=NOT_FOUND requires candidates to be empty"
            )
        if self.status == "RESOLVED" and self.resolved_shop is None:
            raise ValueError(
                "ResolveShopResult status=RESOLVED requires resolved_shop to be set"
            )
        return self


# ===================================================================
# 5. AnswerPlan (deepened per todo/04 §3)
# ===================================================================


class AllowedClaim(BaseModel):
    """A claim that the answer is allowed to make."""
    claim_id: str = ""
    shop_id: str = ""
    facet: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    claim_type: str = ""
    value: Any = None
    verbalization_hint: str = ""


class AnswerClaim(BaseModel):
    """A factual claim extracted from the agent's natural response."""
    model_config = ConfigDict(extra="forbid")

    claim_id: str = ""
    claim_type: str = ""  # shop_existence | coupon | open_status | distance | price | rating | ranking | comparison_winner | scene_match | tool_success | all_targets_covered
    shop_id: str | None = None
    shop_name: str | None = None
    value: Any = None
    polarity: str = "positive"  # positive | negative | unknown | comparative
    text_span: str = ""
    evidence_refs: list[str] = Field(default_factory=list)



class AnswerPlan(BaseModel):
    """Structured plan for generating the final answer.

    Deepened per todo/04 §3 with ranking/comparison references.
    """
    answer_type: str = ""  # single_shop | recommendation | comparison | clarification | error
    target_shop_ids: list[str] = Field(default_factory=list)
    response_sections: list[dict[str, Any]] = Field(default_factory=list)
    allowed_claims: list[AllowedClaim] = Field(default_factory=list)
    required_claims: list[AllowedClaim] = Field(default_factory=list)
    must_mention_unknowns: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    ranking_snapshot_id: str = ""
    comparison_matrix_id: str = ""
    tone: str = "neutral"
    fallback_template_type: str = ""


class ComparisonTargetResolution(BaseModel):
    """Resolution details for multi-target comparison references."""
    model_config = ConfigDict(extra="forbid")

    status: str = ""
    targets: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_targets: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_target: dict[str, Any] | None = None
    reason: str = ""
    prompt: str | None = None


class ComparisonTurnArtifact(BaseModel):
    """Comparison turn handoff payload for the thin core wrapper."""
    model_config = ConfigDict(extra="forbid")

    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    comparison_target_resolution: dict[str, Any] = Field(default_factory=dict)
    pending_clarification: dict[str, Any] | None = None
    comparison_result: dict[str, Any] | None = None
    displayed_items: list[dict[str, Any]] = Field(default_factory=list)
    source: str = ""
    provenance: str = ""


ComparisonTargetResolution.model_rebuild()


class ComparisonCell(BaseModel):
    shop_id: str = ""
    shop_name: str = ""
    facet: str = ""
    dimension: str = ""
    status: str = ""
    result_status: str = ""
    value: Any = None
    evidence_ref: str = ""
    eligible_for_comparison: bool = True


class ComparisonMatrix(BaseModel):
    matrix_id: str = ""
    status: str = ""
    rows: list[dict] = Field(default_factory=list)
    cells: list[ComparisonCell] = Field(default_factory=list)
    unknown_cells: list[ComparisonCell] = Field(default_factory=list)
    failed_cells: list[ComparisonCell] = Field(default_factory=list)
    dimension_winners: dict[str, list[dict]] = Field(default_factory=dict)
    uncertainty_notes: list[str] = Field(default_factory=list)
    overall_ranked: list[dict] = Field(default_factory=list)
    overall_ranking: list[dict] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


ComparisonCell.model_rebuild()
ComparisonMatrix.model_rebuild()

_ORCHESTRATION_PATTERNS = {
    "direct_response",
    "deterministic_tool",
    "discovery_decision",
    "exploration_planning",
    "clarification_fallback",
}
_ORCHESTRATION_COMPLEXITY = {"low", "medium", "high"}
_ORCHESTRATION_RESPONSE_MODES = {
    "direct_response",
    "tool_answer",
    "search_list",
    "recommendation",
    "comparison",
    "refinement",
    "clarify",
    "fallback",
    "exploration_plan",
}
_ORCHESTRATION_NEXT_ACTIONS = {"run_workflow", "clarify", "fallback"}


class OrchestrationDecision(BaseModel):
    """Shadow-mode secondary routing decision for Phase 4.

    This object records which workflow pattern the orchestration router
    would prefer, without changing the active execution path.
    """

    model_config = ConfigDict(extra="forbid")

    orchestration_pattern: str = "direct_response"
    workflow_name: str = "direct_response"
    workflow_reason: str = ""
    task_complexity: str = "low"
    requires_tool: bool = False
    requires_clarification: bool = False
    response_mode: str = "direct_response"
    confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)
    next_action: str = "run_workflow"

    @field_validator("orchestration_pattern", "workflow_name")
    @classmethod
    def _validate_pattern(cls, value: str) -> str:
        value = str(value or "").strip() or "direct_response"
        if value not in _ORCHESTRATION_PATTERNS:
            raise ValueError(f"unsupported orchestration pattern: {value}")
        return value

    @field_validator("task_complexity")
    @classmethod
    def _validate_complexity(cls, value: str) -> str:
        value = str(value or "").strip() or "low"
        if value not in _ORCHESTRATION_COMPLEXITY:
            raise ValueError(f"unsupported task complexity: {value}")
        return value

    @field_validator("response_mode")
    @classmethod
    def _validate_response_mode(cls, value: str) -> str:
        value = str(value or "").strip() or "direct_response"
        if value not in _ORCHESTRATION_RESPONSE_MODES:
            raise ValueError(f"unsupported response mode: {value}")
        return value

    @field_validator("next_action")
    @classmethod
    def _validate_next_action(cls, value: str) -> str:
        value = str(value or "").strip() or "run_workflow"
        if value not in _ORCHESTRATION_NEXT_ACTIONS:
            raise ValueError(f"unsupported next action: {value}")
        return value

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        confidence = float(value or 0.0)
        if confidence < 0.0:
            return 0.0
        if confidence > 1.0:
            return 1.0
        return confidence


class DecisionPlan(BaseModel):
    """Factual plan used by the LLMVerbalizer to generate a natural response."""
    model_config = ConfigDict(extra="forbid")

    answer_type: str = ""  # recommendation | comparison | single_shop | coupon | open_status | distance | general
    selected_targets: list[dict[str, Any]] = Field(default_factory=list)
    omitted_targets: list[dict[str, Any]] = Field(default_factory=list)
    main_recommendation: dict[str, Any] | None = None
    overall_ranking: list[dict[str, Any]] = Field(default_factory=list)
    best_for: dict[str, dict[str, Any]] = Field(default_factory=dict)
    factual_points: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    style_hints: list[str] = Field(default_factory=list)
    decision_context: dict[str, Any] = Field(default_factory=dict)
    candidate_summaries: list[dict[str, Any]] = Field(default_factory=list)
    must_mention_unknowns: list[str] = Field(default_factory=list)
    conversation_continuity: dict[str, Any] = Field(default_factory=dict)


class ExplorationSubgoal(BaseModel):
    """A single step in an exploration itinerary."""

    model_config = ConfigDict(extra="forbid")

    subgoal_id: str = ""
    kind: str = ""
    query: str = ""
    sequence_order: int = 0
    temporal_relation: str = ""
    require_location: bool = False
    max_candidates: int = 3
    tool_rounds: list[dict[str, Any]] = Field(default_factory=list)
    selected_candidate: dict[str, Any] | None = None
    candidate_shops: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""


class ExplorationPlan(BaseModel):
    """Structured plan for multi-subgoal local-life exploration."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = ""
    task_type: str = ""
    goal_type: str = ""
    has_temporal_sequence: bool = False
    expected_output: str = ""
    subgoal_limit: int = 3
    expansion_round_limit: int = 2
    subgoals: list[ExplorationSubgoal] = Field(default_factory=list)
    tool_rounds_used: int = 0
    location_required: bool = False
    location_available: bool = False
    tool_names_used: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    fallback_reason: str = ""


DecisionPlan.model_rebuild()
ExplorationPlan.model_rebuild()
OrchestrationDecision.model_rebuild()


# ===================================================================
# 6. Orchestration context
# ===================================================================


class GlobalTurnContext(BaseModel):
    """Context object threaded through all processing layers.

    Each layer appends fields without overwriting upstream data.
    """
    trace_id: str = ""
    turn_id: str = ""
    session_id: str = ""
    user_id: str = ""
    raw_text: str = ""
    normalized_text: str = ""
    user_context: UserContext | None = None
    session_state_before: dict[str, Any] | None = None

    # Intermediate artifacts (populated as the turn progresses)
    semantic_frame: SemanticFrame | None = None
    resolved_target: ResolveShopResult | None = None
    execution_plan: ExecutionPlan | None = None
    tool_result_set: dict[str, ToolResult] | None = None
    evidence_pack: EvidencePack | None = None
    answer_plan: AnswerPlan | None = None
    final_response: str | None = None
    state_update: dict[str, Any] | None = None
