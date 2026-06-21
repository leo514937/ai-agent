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
    """User's location and mock preferences (static mock for MVP)."""
    location_name: str = "北京邮电大学"
    lat: float = 39.9609
    lng: float = 116.3581


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

    @model_validator(mode="after")
    def _validate_shop_scope(self) -> ToolResult:
        """Enforce shop_id only for shop-scoped tools."""
        shop_scoped_tools = {
            "get_shop_detail",
            "get_coupon_list",
            "check_open_status",
            "get_distance_eta",
        }
        if self.tool_name in shop_scoped_tools and not self.shop_id.strip():
            raise ValueError(f"Tool '{self.tool_name}' requires shop_id")
        return self


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
