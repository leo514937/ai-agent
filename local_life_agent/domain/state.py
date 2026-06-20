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
    """Persistent session context across turns."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_shop: dict | None = None
    last_recommendation_list: list[dict] = Field(default_factory=list)
    active_constraints: dict[str, Any] = Field(default_factory=dict)
    pending_clarification: dict | None = None
    comparison_targets: list[dict] = Field(default_factory=list)
    comparison_result: Any = None
    suggested_shop: dict | None = None


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
