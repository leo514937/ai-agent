"""Trace-only focus context DTO.

FocusContext is a lightweight observability layer for "this one / the
second one / the current shop / the comparison targets" style references.
It does not replace legacy session fields in P5.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FocusContext(BaseModel):
    """Trace-only view of the active conversational focus."""

    model_config = ConfigDict(extra="forbid")

    focus_type: str = ""
    focus_object: dict[str, Any] = Field(default_factory=dict)
    focus_index: int | None = None
    recommendation_item: dict[str, Any] = Field(default_factory=dict)
    comparison_targets: list[dict[str, Any]] = Field(default_factory=list)
    focus_source: str = ""
    resolution_status: str = ""
    clarification_needed: bool = False
    confidence: float = 0.0

    @classmethod
    def from_trace(
        cls,
        *,
        focus_type: str = "",
        focus_object: dict[str, Any] | None = None,
        focus_index: int | None = None,
        recommendation_item: dict[str, Any] | None = None,
        comparison_targets: list[dict[str, Any]] | None = None,
        focus_source: str = "",
        resolution_status: str = "",
        clarification_needed: bool = False,
        confidence: float = 0.0,
    ) -> FocusContext:
        return cls(
            focus_type=str(focus_type or ""),
            focus_object=dict(focus_object or {}),
            focus_index=focus_index if focus_index is None else int(focus_index),
            recommendation_item=dict(recommendation_item or {}),
            comparison_targets=[dict(item) for item in (comparison_targets or []) if isinstance(item, dict)],
            focus_source=str(focus_source or ""),
            resolution_status=str(resolution_status or ""),
            clarification_needed=bool(clarification_needed),
            confidence=max(float(confidence or 0.0), 0.0),
        )

    def trace_dict(self) -> dict[str, Any]:
        return self.model_dump()
