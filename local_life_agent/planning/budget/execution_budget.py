from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from .budget_context import BudgetContext, budget_context_from_state


class ExecutionBudget(BaseModel):
    """Minimal execution budget adapter for second-layer runtime limits."""

    model_config = ConfigDict(extra="forbid")

    max_tool_calls: int = 10
    max_llm_calls: int = 3
    max_review_rounds: int = 2
    max_rewrite_rounds: int = 1

    @field_validator("max_tool_calls", "max_llm_calls", "max_review_rounds", "max_rewrite_rounds", mode="before")
    @classmethod
    def _coerce_non_negative_int(cls, value: Any) -> int:
        try:
            return max(int(value), 0)
        except Exception:
            return 0

    @classmethod
    def from_budget_context(cls, budget_context: BudgetContext | dict[str, Any] | None = None) -> ExecutionBudget:
        if budget_context is None:
            return cls()
        if isinstance(budget_context, dict):
            try:
                budget_context = BudgetContext.model_validate(budget_context)
            except Exception:
                budget_context = BudgetContext()
        if not isinstance(budget_context, BudgetContext):
            return cls()
        return cls(
            max_tool_calls=max(int(budget_context.tool_round_budget or 0), 1),
            max_llm_calls=max(int(budget_context.retry_budget or 0) + 2, 1),
            max_review_rounds=max(int(budget_context.retry_budget or 0) + 1, 1),
            max_rewrite_rounds=max(int(budget_context.rewrite_budget or 0), 1),
        )

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> ExecutionBudget:
        state = state or {}
        value = state.get("execution_budget")
        if isinstance(value, ExecutionBudget):
            return value
        if isinstance(value, dict):
            try:
                return cls.model_validate(value)
            except Exception:
                pass
        return cls.from_budget_context(budget_context_from_state(state))

    def to_budget_context(self) -> BudgetContext:
        return BudgetContext(
            tool_round_budget=max(int(self.max_tool_calls or 0), 0),
            retry_budget=max(int(self.max_review_rounds or 0) - 1, 0),
            rewrite_budget=max(int(self.max_rewrite_rounds or 0), 0),
            expand_search_budget=max(int(self.max_review_rounds or 0) - 1, 0),
        )


def execution_budget_from_state(state: dict[str, Any] | None) -> ExecutionBudget:
    return ExecutionBudget.from_state(state)


def execution_budget_from_budget_context(
    budget_context: BudgetContext | dict[str, Any] | None = None,
) -> ExecutionBudget:
    return ExecutionBudget.from_budget_context(budget_context)
