"""Session state definition for multi-turn conversation context.

Maintains user session data across turns: current shop, recommendation
lists, active constraints, pending clarifications, and comparison state.
Also defines the session write directive used by the routing engine.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class SessionState(BaseModel):
    """Persistent session context across turns.
    
    P2 adds multi-turn tracking fields: last_candidate_spec, last_candidate_set,
    active_goal, review_results, last_decision_plan, replan_counters.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_shop: dict | None = None
    last_recommendation_list: list[dict] = Field(default_factory=list)
    active_constraints: dict[str, Any] = Field(default_factory=dict)
    pending_clarification: dict | None = None
    comparison_targets: list[dict] = Field(default_factory=list)
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


class SessionWriteDirective:
    """Describes what to write to / clear from session state for a turn.

    Used by the routing engine and state_update_planner to ensure
    consistent session mutation regardless of which code path is taken.

    - set_fields:   {field_name: value_or_None} — fields to set.
                    None means "caller fills at runtime".
    - clear_fields: field names to reset to their default empty value.
    """
    def __init__(
        self,
        set_fields: dict[str, Any] | None = None,
        clear_fields: list[str] | None = None,
    ):
        self.set_fields = set_fields or {}
        self.clear_fields = clear_fields or []

    def clone(self) -> SessionWriteDirective:
        return deepcopy(self)
