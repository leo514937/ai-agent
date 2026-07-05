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
    ComparisonStructure,
    FilterType,
    GroundingStatus,
    MissingSlotType,
    MultiTurnSignalType,
    PreferenceType,
    ReferenceType,
    SemanticParseSource,
)
from .facets import (
    ConflictingFacet,
    FacetSet,
    QueryFacet,
    RankingPolicy,
    TargetResolutionResult,
    build_target_resolution_result,
    normalize_query_facets,
)


def _coerce_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _coerce_location_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    try:
        return dict(value)
    except Exception:
        return {}


def _coerce_enum(value: Any, enum_cls: type[Enum], default: Enum) -> Enum:
    if value is None or value == "":
        return default
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except Exception:
        return default


def _first_non_empty(items: list[Any]) -> Any:
    for item in items:
        if isinstance(item, str) and item.strip():
            return item
        if isinstance(item, dict) and item:
            return item
        if item not in (None, "", [], {}):
            return item
    return None


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


class SemanticPreference(BaseModel):
    """Typed semantic preference signal."""

    model_config = ConfigDict(extra="forbid")

    preference_type: PreferenceType = PreferenceType.value_for_money
    value: str = ""
    operator: str = ""
    text: str = ""
    source: str = ""


class SemanticFilter(BaseModel):
    """Typed semantic filter signal."""

    model_config = ConfigDict(extra="forbid")

    filter_type: FilterType = FilterType.coupon_filter
    value: Any = None
    required: bool = False
    text: str = ""
    source: str = ""


class SemanticReference(BaseModel):
    """Typed discourse reference signal."""

    model_config = ConfigDict(extra="forbid")

    reference_type: ReferenceType = ReferenceType.location_reference
    text: str = ""
    value: Any = None
    shop_id: str = ""
    shop_name: str = ""
    location_name: str = ""
    resolved: bool = False


class MultiTurnSemanticSignal(BaseModel):
    """Typed multi-turn semantic signal."""

    model_config = ConfigDict(extra="forbid")

    signal_type: MultiTurnSignalType = MultiTurnSignalType.constraint_update
    text: str = ""
    from_state: bool = False
    notes: str = ""


class ExplorationStageSpec(BaseModel):
    """Structured exploration stage used to represent scene/time/constraints."""

    model_config = ConfigDict(extra="forbid")

    stage_id: str = ""
    stage_type: str = ""
    category: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    order: int = 0
    required: bool = True
    candidate_query: str = ""
    scene: str = ""
    time: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    evidence_requirements: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""
    status: str = "unknown"
    query: str = ""
    notes: str = ""

    @field_validator("evidence_requirements", mode="before")
    @classmethod
    def _coerce_evidence_requirements(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

    @field_validator("location", mode="before")
    @classmethod
    def _coerce_location(cls, value: Any) -> dict[str, Any]:
        return _coerce_location_value(value)

    @model_validator(mode="after")
    def _normalize_exploration_stage(self) -> ExplorationStageSpec:
        self.stage_id = str(self.stage_id or "").strip()
        self.stage_type = str(self.stage_type or "").strip()
        self.category = str(self.category or "").strip()
        self.candidate_query = str(self.candidate_query or self.query or self.stage_type or self.category or "").strip()
        self.query = str(self.query or self.candidate_query or "").strip()
        self.scene = str(self.scene or "").strip()
        self.time = str(self.time or "").strip()
        self.fallback_strategy = str(self.fallback_strategy or "").strip()
        self.status = str(self.status or "unknown").strip() or "unknown"
        self.notes = str(self.notes or "").strip()
        if not isinstance(self.location, dict):
            self.location = {}
        else:
            self.location = dict(self.location)
        if not isinstance(self.constraints, dict):
            self.constraints = {}
        else:
            self.constraints = dict(self.constraints)
        try:
            self.order = int(self.order or 0)
        except Exception:
            self.order = 0
        self.required = bool(self.required)
        if not self.stage_id:
            self.stage_id = f"stage_{self.order or 1}"
        if not self.stage_type:
            self.stage_type = self.category or "custom"
        return self


class SemanticFrame(BaseModel):
    """Structured interpretation of the user's request."""

    model_config = ConfigDict(extra="forbid")

    intent: TopIntent | None = None
    top_intent: TopIntent | None = None
    task_type: TaskType | None = None
    primary_task: str = ""
    workflow_hint: str = ""
    comparison_intent: bool = False
    comparison_structure: ComparisonStructure = ComparisonStructure.unknown
    comparison_facets: list[str] = Field(default_factory=list)
    exploration_stages: list[ExplorationStageSpec] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)
    preference_signals: list[SemanticPreference] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    category: str = ""
    shop_target: dict[str, Any] | None = None
    reference: dict[str, Any] = Field(default_factory=dict)
    location_reference: SemanticReference | None = None
    shop_reference: SemanticReference | None = None
    ordinal_reference: SemanticReference | None = None
    deictic_reference: SemanticReference | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    filter_signals: list[SemanticFilter] = Field(default_factory=list)
    facets: list["QueryFacet"] = Field(default_factory=list)
    facet_set: FacetSet | None = None
    target_resolution: TargetResolutionResult | None = None
    conflicting_facets: list[ConflictingFacet] = Field(default_factory=list)
    ranking_policy: RankingPolicy | None = None
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
    parse_source: SemanticParseSource = SemanticParseSource.unknown
    semantic_parse_source: SemanticParseSource = SemanticParseSource.unknown
    grounding_status: GroundingStatus = GroundingStatus.unknown
    discourse_marker: str = ""
    constraint_update: bool = False
    new_task_override: bool = False
    cancel_intent: bool = False
    missing_slot_type: MissingSlotType = MissingSlotType.other
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
            if isinstance(item, QueryFacet):
                coerced.append(item)
                continue
            if isinstance(item, Facet):
                coerced.append({"name": item.value, "group": "", "required": False})
                continue
            if isinstance(item, str):
                coerced.append({"name": item, "group": "", "required": False})
                continue
            if isinstance(item, dict):
                payload = dict(item)
                if "name" not in payload and "facet" in payload:
                    payload["name"] = payload["facet"]
                if "group" not in payload:
                    payload["group"] = ""
                coerced.append(payload)
                continue
                coerced.append(item)
        return coerced

    @field_validator("location", mode="before")
    @classmethod
    def _coerce_location(cls, value: Any) -> dict[str, Any]:
        return _coerce_location_value(value)

    @field_validator("exploration_stages", mode="before")
    @classmethod
    def _coerce_exploration_stages(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        items = _coerce_list_value(value)
        coerced: list[Any] = []
        for item in items:
            if isinstance(item, ExplorationStageSpec):
                coerced.append(item)
                continue
            if isinstance(item, str):
                coerced.append({"stage_type": item})
                continue
            if isinstance(item, dict):
                payload = dict(item)
                if "stage_type" not in payload:
                    payload["stage_type"] = str(payload.get("kind", payload.get("name", "")) or "")
                if "candidate_query" not in payload and "query" in payload:
                    payload["candidate_query"] = payload.get("query", "")
                if "order" not in payload and "sequence_order" in payload:
                    payload["order"] = payload.get("sequence_order", 0)
                coerced.append(payload)
                continue
            coerced.append(item)
        return coerced

    @field_validator("preference_signals", mode="before")
    @classmethod
    def _coerce_preference_signals(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        items = _coerce_list_value(value)
        coerced: list[Any] = []
        for item in items:
            if isinstance(item, SemanticPreference):
                coerced.append(item)
                continue
            if isinstance(item, str):
                coerced.append({"preference_type": PreferenceType.value_for_money, "text": item, "value": item})
                continue
            if isinstance(item, dict):
                payload = dict(item)
                if "preference_type" not in payload:
                    payload["preference_type"] = payload.get("type", PreferenceType.value_for_money.value)
                coerced.append(payload)
                continue
            coerced.append(item)
        return coerced

    @field_validator("filter_signals", mode="before")
    @classmethod
    def _coerce_filter_signals(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        items = _coerce_list_value(value)
        coerced: list[Any] = []
        for item in items:
            if isinstance(item, SemanticFilter):
                coerced.append(item)
                continue
            if isinstance(item, str):
                coerced.append({"filter_type": FilterType.coupon_filter, "text": item, "value": item})
                continue
            if isinstance(item, dict):
                payload = dict(item)
                if "filter_type" not in payload:
                    payload["filter_type"] = payload.get("type", FilterType.coupon_filter.value)
                coerced.append(payload)
                continue
            coerced.append(item)
        return coerced

    @field_validator(
        "location_reference",
        "shop_reference",
        "ordinal_reference",
        "deictic_reference",
        mode="before",
    )
    @classmethod
    def _coerce_reference_signal(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, SemanticReference):
            return value
        if isinstance(value, str):
            return {"text": value, "value": value}
        if isinstance(value, dict):
            payload = dict(value)
            if "reference_type" not in payload:
                payload["reference_type"] = payload.get("type", ReferenceType.location_reference.value)
            return payload
        return value

    @field_validator(
        "intent",
        "top_intent",
        mode="before",
    )
    @classmethod
    def _coerce_top_intent(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, TopIntent):
            return value
        try:
            return TopIntent(str(value).strip())
        except Exception:
            return value

    @field_validator("parse_source", "semantic_parse_source", mode="before")
    @classmethod
    def _coerce_parse_source(cls, value: Any) -> Any:
        return _coerce_enum(value, SemanticParseSource, SemanticParseSource.unknown)

    @field_validator("grounding_status", mode="before")
    @classmethod
    def _coerce_grounding_status(cls, value: Any) -> Any:
        return _coerce_enum(value, GroundingStatus, GroundingStatus.unknown)

    @field_validator("comparison_structure", mode="before")
    @classmethod
    def _coerce_comparison_structure(cls, value: Any) -> Any:
        return _coerce_enum(value, ComparisonStructure, ComparisonStructure.unknown)

    @field_validator("missing_slot_type", mode="before")
    @classmethod
    def _coerce_missing_slot_type(cls, value: Any) -> Any:
        if value is None or value == "":
            return MissingSlotType.other
        if isinstance(value, MissingSlotType):
            return value
        text = str(value).strip()
        alias_map = {
            "missing_shop_target": MissingSlotType.missing_shop_target,
            "missing_shop": MissingSlotType.missing_shop,
            "missing_location": MissingSlotType.missing_location,
            "missing_comparison_targets": MissingSlotType.missing_comparison_targets,
            "missing_exploration_location": MissingSlotType.missing_exploration_location,
            "missing_category": MissingSlotType.missing_category,
            "ambiguous_shop": MissingSlotType.ambiguous_shop,
            "ambiguous_comparison_targets": MissingSlotType.ambiguous_comparison_targets,
            "unresolved_deictic_reference": MissingSlotType.unresolved_deictic_reference,
            "unresolved_ordinal_reference": MissingSlotType.unresolved_ordinal_reference,
            "low_confidence_semantic_parse": MissingSlotType.low_confidence_semantic_parse,
            "cancel": MissingSlotType.cancel,
            "new_task_override": MissingSlotType.new_task_override,
            "constraint_update": MissingSlotType.constraint_update,
            "unresolved_reference": MissingSlotType.unresolved_reference,
        }
        if text in alias_map:
            return alias_map[text]
        try:
            return MissingSlotType(text)
        except Exception:
            return MissingSlotType.other

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            confidence = float(value)
        except Exception:
            confidence = 0.0
        if confidence < 0.0:
            return 0.0
        if confidence > 1.0:
            return 1.0
        return confidence

    @field_validator("discourse_marker")
    @classmethod
    def _strip_discourse_marker(cls, value: Any) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _normalize_semantic_frame(self) -> SemanticFrame:
        if self.intent is None and self.top_intent is not None:
            self.intent = self.top_intent
        elif self.top_intent is None and self.intent is not None:
            self.top_intent = self.intent
        elif self.intent is not None and self.top_intent is not None and self.intent != self.top_intent:
            raise ValueError("intent and top_intent must match when both are provided")

        if self.semantic_parse_source == SemanticParseSource.unknown and self.parse_source != SemanticParseSource.unknown:
            self.semantic_parse_source = self.parse_source
        elif self.parse_source == SemanticParseSource.unknown and self.semantic_parse_source != SemanticParseSource.unknown:
            self.parse_source = self.semantic_parse_source

        if self.semantic_source and self.semantic_parse_source == SemanticParseSource.unknown:
            try:
                self.semantic_parse_source = SemanticParseSource(self.semantic_source)
            except Exception:
                if self.semantic_source in {item.value for item in SemanticParseSource}:
                    self.semantic_parse_source = SemanticParseSource(self.semantic_source)
        if self.parse_source == SemanticParseSource.unknown and self.semantic_parse_source != SemanticParseSource.unknown:
            self.parse_source = self.semantic_parse_source
        if not self.semantic_source and self.semantic_parse_source != SemanticParseSource.unknown:
            self.semantic_source = self.semantic_parse_source.value

        if self.location_reference is None and self.location:
            self.location_reference = SemanticReference(
                reference_type=ReferenceType.location_reference,
                text=str(self.location.get("text", "") or ""),
                value=dict(self.location),
                location_name=str(self.location.get("location_name", self.location.get("name", "")) or ""),
                resolved=bool(self.location),
            )
        if self.shop_reference is None and self.shop_target:
            self.shop_reference = SemanticReference(
                reference_type=ReferenceType.shop_reference,
                text=str(self.shop_target.get("text", "") or ""),
                value=dict(self.shop_target),
                shop_id=str(self.shop_target.get("shop_id", "") or ""),
                shop_name=str(self.shop_target.get("shop_name", self.shop_target.get("name", "")) or ""),
                resolved=bool(self.shop_target),
            )
        if self.ordinal_reference is None and self.ordinal_references:
            first_ordinal = _first_non_empty(list(self.ordinal_references))
            if first_ordinal is not None:
                self.ordinal_reference = SemanticReference(
                    reference_type=ReferenceType.ordinal_reference,
                    text=str(first_ordinal),
                    value=list(self.ordinal_references),
                    resolved=True,
                )
        if self.deictic_reference is None and self.deictic_references:
            first_deictic = _first_non_empty(list(self.deictic_references))
            if first_deictic is not None:
                self.deictic_reference = SemanticReference(
                    reference_type=ReferenceType.deictic_reference,
                    text=str(first_deictic),
                    value=list(self.deictic_references),
                    resolved=True,
                )

        self.scene = str(self.scene or "").strip()
        self.time = str(self.time or "").strip()
        if self.exploration_stages:
            first_stage = _first_non_empty(list(self.exploration_stages))
            if isinstance(first_stage, ExplorationStageSpec):
                if not self.scene and first_stage.scene:
                    self.scene = first_stage.scene
                if not self.time and first_stage.time:
                    self.time = first_stage.time
            elif isinstance(first_stage, dict):
                if not self.scene:
                    self.scene = str(first_stage.get("scene", "") or "").strip()
                if not self.time:
                    self.time = str(first_stage.get("time", "") or "").strip()
            if self.workflow_hint != "exploration_planning":
                self.workflow_hint = "exploration_planning"
            if not self.primary_task:
                self.primary_task = "exploration"
            if not self.missing_slot_type and not self.location:
                self.missing_slot_type = MissingSlotType.missing_exploration_location
            if self.missing_slot_type == MissingSlotType.missing_exploration_location and not self.missing_slots:
                self.missing_slots = [self.missing_slot_type.value]

        if self.comparison_intent and not (self.comparison_targets or self.comparison_structure != ComparisonStructure.unknown or self.comparison_facets):
            raise ValueError("comparison_intent requires comparison_targets, comparison_structure, or comparison_facets")
        if self.comparison_intent:
            if self.comparison_structure == ComparisonStructure.unknown:
                if len(self.comparison_targets) >= 2:
                    self.comparison_structure = ComparisonStructure.multi_target
                elif self.ordinal_references:
                    self.comparison_structure = ComparisonStructure.ordinal
                elif self.deictic_references:
                    self.comparison_structure = ComparisonStructure.deictic
                elif self.merchant_mentions:
                    self.comparison_structure = ComparisonStructure.explicit
        if self.cancel_intent and self.new_task_override:
            raise ValueError("cancel_intent cannot coexist with new_task_override")

        # Keep missing_slots and missing_slot_type aligned without duplicating semantics.
        normalized_missing_slots = [str(item).strip() for item in (self.missing_slots or []) if str(item).strip()]
        if self.missing_slot_type != MissingSlotType.other and not normalized_missing_slots:
            normalized_missing_slots = [self.missing_slot_type.value]
        elif normalized_missing_slots and self.missing_slot_type == MissingSlotType.other:
            slot_alias = normalized_missing_slots[0]
            alias_map = {
                "location": MissingSlotType.missing_location,
                "missing_location": MissingSlotType.missing_location,
                "shop": MissingSlotType.missing_shop,
                "missing_shop": MissingSlotType.missing_shop,
                "shop_target": MissingSlotType.missing_shop_target,
                "missing_shop_target": MissingSlotType.missing_shop_target,
                "comparison_targets": MissingSlotType.missing_comparison_targets,
                "missing_comparison_targets": MissingSlotType.missing_comparison_targets,
                "exploration_location": MissingSlotType.missing_exploration_location,
                "missing_exploration_location": MissingSlotType.missing_exploration_location,
                "category": MissingSlotType.missing_category,
                "missing_category": MissingSlotType.missing_category,
                "ambiguous_shop": MissingSlotType.ambiguous_shop,
                "ambiguous_comparison_targets": MissingSlotType.ambiguous_comparison_targets,
                "unresolved_deictic_reference": MissingSlotType.unresolved_deictic_reference,
                "unresolved_ordinal_reference": MissingSlotType.unresolved_ordinal_reference,
                "low_confidence_semantic_parse": MissingSlotType.low_confidence_semantic_parse,
                "cancel": MissingSlotType.cancel,
                "new_task_override": MissingSlotType.new_task_override,
                "constraint_update": MissingSlotType.constraint_update,
            }
            self.missing_slot_type = alias_map.get(slot_alias, MissingSlotType.other)
        elif normalized_missing_slots and self.missing_slot_type != MissingSlotType.other:
            canonical_missing = {
                self.missing_slot_type.value,
                self.missing_slot_type.name,
            }
            if not any(item in canonical_missing for item in normalized_missing_slots):
                raise ValueError("missing_slots and missing_slot_type describe different missing semantic slots")
        self.missing_slots = normalized_missing_slots

        if self.location_reference is not None and self.location and not self.location_reference.value:
            self.location_reference.value = dict(self.location)
        if self.shop_reference is not None and self.shop_target and not self.shop_reference.value:
            self.shop_reference.value = dict(self.shop_target)

        return self


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
    missing_slot_type: str = ""
    expected_reply_type: str = ""
    created_at: datetime | None = None
    expires_at: datetime | None = None
    original_text: str = ""
    original_semantic_frame: dict[str, Any] | None = None
    reason: str = ""
    source_node: str = ""
    already_resolved_targets: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_target_slot: str = ""
    resume_strategy: str = ""


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
    facets: list[QueryFacet] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    target_resolution: TargetResolutionResult | None = None
    conflicting_facets: list[ConflictingFacet] = Field(default_factory=list)
    ranking_policy: RankingPolicy | None = None
    dependencies: list[str] = Field(default_factory=list)
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
    facet_candidates: list[dict[str, Any]] = Field(default_factory=list)
    facet_validation_result: dict[str, Any] | None = None
    facet_budget_plan: dict[str, Any] | None = None
    blocked_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    planning_warnings: list[str] = Field(default_factory=list)
    evidence_enrichment_top_k: int = 0
    evidence_planner_result: dict[str, Any] | None = None
    budget_context_snapshot: dict[str, Any] | None = None
    timeout_policy: dict[str, Any] = Field(default_factory=dict)
    degradation_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "facets",
        "optional_facets",
        "conflicting_facets",
        "dependencies",
        "tool_calls",
        "stages",
        "target_shop_ids",
        "query_terms",
        "scene_terms",
        "planning_notes",
        "assumptions_used",
        "facet_candidates",
        "blocked_tool_calls",
        "unsupported_facets",
        "missing_inputs",
        "planning_warnings",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)


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
    subgoal_id: str = ""
    route_step: str = ""
    tool_name: str = ""
    call_id: str = ""
    result_status: ToolResultStatus = ToolResultStatus.unknown
    status: str = ""
    field_path: str = ""
    value: Any = None
    confidence: float = 1.0
    timestamp: str = ""
    observed_at_ms: int | None = None
    ttl_seconds: int | None = None
    freshness_class: str | None = None
    is_stale: bool = False
    cache_hit: bool = False
    location_fingerprint: str | None = None
    budget_context_snapshot: dict[str, Any] | None = None
    source_type: SourceType = SourceType.TOOL
    backend_source: str = ""


class EvidencePack(BaseModel):
    """Verified evidence from tool results — the only source of truth.

    Deepened per todo/04 §1 with ranking_snapshot and comparison_matrix.
    """
    owner: str = ""
    facets: list[QueryFacet] = Field(default_factory=list)
    target_resolution: TargetResolutionResult | None = None
    conflicting_facets: list[ConflictingFacet] = Field(default_factory=list)
    ranking_policy: RankingPolicy | None = None
    answerable_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_facets: list[str] = Field(default_factory=list)
    target_shop_ids: list[str] = Field(default_factory=list)
    requested_facets: list[str] = Field(default_factory=list)
    facet_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    unknown_items: list[EvidenceItem] = Field(default_factory=list)
    route_steps: list[dict[str, Any]] = Field(default_factory=list)
    last_recommendation_list: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    ranking_snapshot: dict[str, Any] | None = None
    comparison_matrix: dict[str, Any] | None = None
    tool_results: dict[str, Any] = Field(default_factory=dict)
    semantic_frame: dict[str, Any] = Field(default_factory=dict)
    semantic_parse_source: str = ""
    grounding_status: str = ""
    missing_slot_type: str = ""
    router_policy_decision: dict[str, Any] = Field(default_factory=dict)
    router_policy_conflicts: list[str] = Field(default_factory=list)
    conversation_continuity: dict[str, Any] = Field(default_factory=dict)
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    facet_statuses: dict[str, str] = Field(default_factory=dict)
    grounded_facts: dict[str, Any] = Field(default_factory=dict)
    facet_reasons: dict[str, str] = Field(default_factory=dict)
    evidence_status: str = ""
    comparison_support_status: str = ""
    ranking_preserved: bool = True
    unsupported_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    partial_fields: list[str] = Field(default_factory=list)
    evidence_review_result: dict[str, Any] = Field(default_factory=dict)
    answer_verify_result: dict[str, Any] = Field(default_factory=dict)
    evidence_cache_key: str = ""
    evidence_cache_scope: str = ""
    evidence_cache_hit: bool = False
    evidence_enrichment_top_k: int = 0
    observed_at_ms: int | None = None
    ttl_seconds: int | None = None
    freshness_class: str | None = None
    is_stale: bool = False
    cache_hit: bool = False
    location_fingerprint: str | None = None
    budget_context_snapshot: dict[str, Any] | None = None

    @field_validator(
        "facets",
        "conflicting_facets",
        "answerable_facets",
        "unknown_facets",
        "failed_facets",
        "target_shop_ids",
        "requested_facets",
        "facet_results",
        "evidence_items",
        "unknown_items",
        "route_steps",
        "last_recommendation_list",
        "forbidden_claims",
        "stage_queries",
        "stage_statuses",
        "unsupported_reasons",
        "unknown_fields",
        "failed_tools",
        "partial_fields",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

    @field_validator("location", "facet_statuses", "grounded_facts", "facet_reasons", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, value: Any) -> dict[str, Any]:
        return _coerce_location_value(value)

    @field_validator("tool_results", mode="before")
    @classmethod
    def _coerce_tool_results(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        try:
            return dict(value)
        except Exception:
            return {}


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

    @field_validator("candidates", mode="before")
    @classmethod
    def _coerce_candidates(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

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
    facets: list[QueryFacet] = Field(default_factory=list)
    target_resolution: TargetResolutionResult | None = None
    conflicting_facets: list[ConflictingFacet] = Field(default_factory=list)
    ranking_policy: RankingPolicy | None = None
    answerable_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_facets: list[str] = Field(default_factory=list)
    required_disclaimers: list[str] = Field(default_factory=list)
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
    semantic_frame: dict[str, Any] = Field(default_factory=dict)
    semantic_parse_source: str = ""
    grounding_status: str = ""
    missing_slot_type: str = ""
    router_policy_decision: dict[str, Any] = Field(default_factory=dict)
    router_policy_conflicts: list[str] = Field(default_factory=list)
    conversation_continuity: dict[str, Any] = Field(default_factory=dict)
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    facet_statuses: dict[str, str] = Field(default_factory=dict)
    grounded_facts: dict[str, Any] = Field(default_factory=dict)
    facet_reasons: dict[str, str] = Field(default_factory=dict)
    evidence_status: str = ""
    comparison_support_status: str = ""
    ranking_preserved: bool = True
    unsupported_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    partial_fields: list[str] = Field(default_factory=list)
    evidence_review_result: dict[str, Any] = Field(default_factory=dict)
    answer_verify_result: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "facets",
        "conflicting_facets",
        "answerable_facets",
        "unknown_facets",
        "failed_facets",
        "required_disclaimers",
        "target_shop_ids",
        "response_sections",
        "allowed_claims",
        "required_claims",
        "must_mention_unknowns",
        "forbidden_claims",
        "stage_queries",
        "stage_statuses",
        "unsupported_reasons",
        "unknown_fields",
        "failed_tools",
        "partial_fields",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)


class ComparisonTargetResolution(BaseModel):
    """Resolution details for multi-target comparison references."""
    model_config = ConfigDict(extra="forbid")

    status: str = ""
    targets: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_targets: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_target: dict[str, Any] | None = None
    reason: str = ""
    prompt: str | None = None

    @field_validator("targets", "unresolved_targets", mode="before")
    @classmethod
    def _coerce_targets(cls, value: Any) -> list[dict[str, Any]]:
        return [item for item in _coerce_list_value(value) if item is not None]


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

    @field_validator("missing_fields", mode="before")
    @classmethod
    def _coerce_missing_fields(cls, value: Any) -> list[str]:
        return [str(item) for item in _coerce_list_value(value) if str(item).strip()]

    @field_validator("workflow_name", mode="before")
    @classmethod
    def _reject_multi_value_workflow_name(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple, set)):
            raise ValueError("workflow_name must be a single value")
        return value

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
    answerable_facets: list[str] = Field(default_factory=list)
    unknown_facets: list[str] = Field(default_factory=list)
    failed_facets: list[str] = Field(default_factory=list)
    required_disclaimers: list[str] = Field(default_factory=list)
    conversation_continuity: dict[str, Any] = Field(default_factory=dict)
    semantic_frame: dict[str, Any] = Field(default_factory=dict)
    semantic_parse_source: str = ""
    grounding_status: str = ""
    missing_slot_type: str = ""
    router_policy_decision: dict[str, Any] = Field(default_factory=dict)
    router_policy_conflicts: list[str] = Field(default_factory=list)
    exploration_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
    scene: str = ""
    time: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    facet_statuses: dict[str, str] = Field(default_factory=dict)
    grounded_facts: dict[str, Any] = Field(default_factory=dict)
    facet_reasons: dict[str, str] = Field(default_factory=dict)
    evidence_status: str = ""
    comparison_support_status: str = ""
    ranking_preserved: bool = True
    unsupported_reasons: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    partial_fields: list[str] = Field(default_factory=list)
    evidence_review_result: dict[str, Any] = Field(default_factory=dict)
    answer_verify_result: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "selected_targets",
        "omitted_targets",
        "overall_ranking",
        "factual_points",
        "uncertainty_notes",
        "forbidden_claims",
        "style_hints",
        "candidate_summaries",
        "must_mention_unknowns",
        "answerable_facets",
        "unknown_facets",
        "failed_facets",
        "required_disclaimers",
        "stage_queries",
        "stage_statuses",
        "unsupported_reasons",
        "unknown_fields",
        "failed_tools",
        "partial_fields",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

    @field_validator("location", "facet_statuses", "grounded_facts", "facet_reasons", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, value: Any) -> dict[str, Any]:
        return _coerce_location_value(value)


class ExplorationSubgoal(BaseModel):
    """A single step in an exploration itinerary."""

    model_config = ConfigDict(extra="forbid")

    stage_id: str = ""
    stage_type: str = ""
    category: str = ""
    location: dict[str, Any] = Field(default_factory=dict)
    time: str = ""
    scene: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    order: int = 0
    required: bool = True
    candidate_query: str = ""
    evidence_requirements: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""
    status: str = "planned"
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

    @field_validator("evidence_requirements", mode="before")
    @classmethod
    def _coerce_evidence_requirements(cls, value: Any) -> list[Any]:
        return _coerce_list_value(value)

    @field_validator("location", mode="before")
    @classmethod
    def _coerce_location(cls, value: Any) -> dict[str, Any]:
        return _coerce_location_value(value)

    @model_validator(mode="after")
    def _normalize_exploration_subgoal(self) -> ExplorationSubgoal:
        self.stage_id = str(self.stage_id or self.subgoal_id or "").strip()
        self.stage_type = str(self.stage_type or self.kind or "").strip()
        self.category = str(self.category or self.stage_type or self.kind or "").strip()
        self.candidate_query = str(self.candidate_query or self.query or self.kind or self.stage_type or "").strip()
        self.query = str(self.query or self.candidate_query or "").strip()
        self.time = str(self.time or "").strip()
        self.scene = str(self.scene or "").strip()
        self.fallback_strategy = str(self.fallback_strategy or "").strip()
        self.status = str(self.status or "planned").strip() or "planned"
        self.note = str(self.note or "").strip()
        if not isinstance(self.location, dict):
            self.location = {}
        else:
            self.location = dict(self.location)
        if not isinstance(self.constraints, dict):
            self.constraints = {}
        else:
            self.constraints = dict(self.constraints)
        try:
            self.order = int(self.order or self.sequence_order or 0)
        except Exception:
            self.order = int(self.sequence_order or 0)
        try:
            self.sequence_order = int(self.sequence_order or self.order or 0)
        except Exception:
            self.sequence_order = int(self.order or 0)
        self.required = bool(self.required)
        if not self.subgoal_id:
            self.subgoal_id = self.stage_id or f"subgoal_{self.sequence_order or self.order or 1}"
        if not self.stage_id:
            self.stage_id = self.subgoal_id
        if not self.kind:
            self.kind = self.stage_type or self.category or self.query
        return self


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
    stage_queries: list[str] = Field(default_factory=list)
    stage_evidence_requirements: list[list[str]] = Field(default_factory=list)
    stage_statuses: list[str] = Field(default_factory=list)
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
