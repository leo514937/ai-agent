"""Session state definition for multi-turn conversation context.

Maintains user session data across turns: current shop, recommendation
lists, active constraints, pending clarifications, and comparison state.
Also defines the session write directive used by the routing engine.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StateUpdatePlan(BaseModel):
    """Canonical session write plan used for state persistence.

    This is the schema-owned form of a session write directive. The
    legacy ``SessionWriteDirective`` class remains as a backward-compatible
    subclass so the production path does not need a wholesale migration.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    set_fields: dict[str, Any] = Field(default_factory=dict)
    clear_fields: list[str] = Field(default_factory=list)
    source: str = ""
    evidence_ref: str = ""
    ttl: int | None = None
    location_context: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    blocked: bool = False
    blocked_reason: str = ""
    no_op: bool = False

    @field_validator("set_fields", "location_context", mode="before")
    @classmethod
    def _coerce_mapping(cls, value: Any) -> dict[str, Any]:
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

    @field_validator("clear_fields", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, (tuple, set)):
            return [str(item) for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @model_validator(mode="after")
    def _normalize(self) -> StateUpdatePlan:
        self.set_fields = dict(self.set_fields or {})
        self.location_context = dict(self.location_context or {})
        self.clear_fields = list(dict.fromkeys(str(item) for item in (self.clear_fields or []) if str(item).strip()))
        self.source = str(self.source or "").strip()
        self.evidence_ref = str(self.evidence_ref or "").strip()
        self.reason = str(self.reason or "").strip()
        self.blocked_reason = str(self.blocked_reason or "").strip()
        self.no_op = bool(self.no_op or (not self.set_fields and not self.clear_fields))
        if self.ttl is not None:
            try:
                self.ttl = max(int(self.ttl), 0)
            except Exception:
                self.ttl = None
        return self

    def clone(self) -> StateUpdatePlan:
        return self.model_copy(deep=True)


class SessionWriteDirective(StateUpdatePlan):
    """Backward-compatible alias for the canonical state update plan."""


class SessionValueMeta(BaseModel):
    """Traceable metadata attached to a session slot.

    P5 uses this as a minimal carrier for source / ttl / evidence / location
    context without changing the primary session value shape.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str = ""
    ttl: int | None = None
    evidence_ref: str = ""
    location_context: dict[str, Any] = Field(default_factory=dict)
    resume_strategy: str = ""


class SessionState(BaseModel):
    """Persistent session context across turns.
    
    P2 adds multi-turn tracking fields: last_candidate_spec, last_candidate_set,
    active_goal, review_results, last_decision_plan, replan_counters.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_shop: dict | None = None
    current_shop_meta: SessionValueMeta = Field(default_factory=SessionValueMeta)
    canonical_shop_entity: dict | None = None
    canonical_shop_entities: list[dict] = Field(default_factory=list)
    shop_resolution_trace: list[dict[str, Any]] = Field(default_factory=list)
    last_recommendation_list: list[dict] = Field(default_factory=list)
    last_recommendation_list_meta: SessionValueMeta = Field(default_factory=SessionValueMeta)
    active_constraints: dict[str, Any] = Field(default_factory=dict)
    pending_clarification: dict | None = None
    pending_clarification_meta: SessionValueMeta = Field(default_factory=SessionValueMeta)
    comparison_targets: list[dict] = Field(default_factory=list)
    comparison_targets_meta: SessionValueMeta = Field(default_factory=SessionValueMeta)
    comparison_result: Any = None
    suggested_shop: dict | None = None

    # === P2: Multi-turn tracking fields ===
    # Last candidate spec/set for "这两家" / "刚才那几家" reference
    last_candidate_spec: dict[str, Any] | None = Field(default=None)
    last_candidate_set: list[dict[str, Any]] = Field(default_factory=list)

    # Active goal for the current/recent turn
    active_goal: dict[str, Any] | None = Field(default=None)

    # Review results from previous turn (for trace replay)
    review_results: dict[str, Any] = Field(default_factory=dict)

    # Last DecisionPlan (for multi-turn consistency)
    last_decision_plan: dict[str, Any] | None = Field(default=None)

    # Replan counters to prevent infinite loops
    replan_counters: dict[str, int] = Field(default_factory=lambda: {
        "expand_search": 0,
        "replan_evidence": 0,
        "rewrite": 0,
    })


