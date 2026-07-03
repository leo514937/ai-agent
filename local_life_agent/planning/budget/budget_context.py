from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BudgetContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_round_budget: int = 2
    retry_budget: int = 1
    expand_search_budget: int = 1
    rewrite_budget: int = 1
    facet_enrich_budget: int = 6
    deadline_remaining_ms: int | None = None

    consumed_tool_rounds: int = 0
    consumed_retries: int = 0
    consumed_expand_searches: int = 0
    consumed_rewrites: int = 0
    consumed_facet_enrich: int = 0

    budget_exhausted_reasons: list[str] = Field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def remaining(self, field: str) -> int:
        total = int(getattr(self, field, 0) or 0)
        consumed_field_map = {
            "tool_round_budget": "consumed_tool_rounds",
            "retry_budget": "consumed_retries",
            "expand_search_budget": "consumed_expand_searches",
            "rewrite_budget": "consumed_rewrites",
            "facet_enrich_budget": "consumed_facet_enrich",
        }
        consumed_field = consumed_field_map.get(field, f"consumed_{field}")
        consumed = int(getattr(self, consumed_field, 0) or 0)
        return max(total - consumed, 0)

    def record_exhaustion(self, reason: str) -> None:
        reason = str(reason or "").strip()
        if reason and reason not in self.budget_exhausted_reasons:
            self.budget_exhausted_reasons.append(reason)


def default_budget_context(_: Any | None = None) -> BudgetContext:
    return BudgetContext()


def budget_context_from_state(state: dict[str, Any] | None) -> BudgetContext:
    state = state or {}
    value = state.get("budget_context")
    if isinstance(value, BudgetContext):
        return value
    if isinstance(value, dict):
        try:
            return BudgetContext.model_validate(value)
        except Exception:
            return BudgetContext()
    return BudgetContext()
