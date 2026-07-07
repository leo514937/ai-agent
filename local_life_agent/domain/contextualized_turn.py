"""Trace-only contextualized turn DTO.

P5 先把上下文改写的痕迹显式化，但不接管语义解析和路由决策。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContextualizedTurn(BaseModel):
    """Trace-only record of how a turn was contextualized."""

    model_config = ConfigDict(extra="forbid")

    original_text: str = ""
    normalized_text: str = ""
    contextualized_query: str = ""
    rewrite_type: str = ""
    mixed_intent: bool = False
    terminal_policy: str = "inherit"
    context_used: list[str] = Field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_trace(
        cls,
        *,
        original_text: str = "",
        normalized_text: str = "",
        contextualized_query: str = "",
        rewrite_type: str = "",
        mixed_intent: bool = False,
        terminal_policy: str = "inherit",
        context_used: list[str] | None = None,
        confidence: float = 0.0,
    ) -> ContextualizedTurn:
        return cls(
            original_text=str(original_text or ""),
            normalized_text=str(normalized_text or ""),
            contextualized_query=str(contextualized_query or ""),
            rewrite_type=str(rewrite_type or ""),
            mixed_intent=bool(mixed_intent),
            terminal_policy=str(terminal_policy or "inherit"),
            context_used=[str(item).strip() for item in (context_used or []) if str(item).strip()],
            confidence=max(float(confidence or 0.0), 0.0),
        )

    def trace_dict(self) -> dict[str, Any]:
        return self.model_dump()
