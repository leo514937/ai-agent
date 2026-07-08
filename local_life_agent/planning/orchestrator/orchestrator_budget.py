from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..budget.execution_budget import ExecutionBudget, execution_budget_from_state


@dataclass(frozen=True)
class OrchestratorBudget:
    """Orchestrator-level budget derived from the execution budget."""

    max_subtask_count: int = 8
    max_parallelism: int = 4
    subtask_timeout_ms: int = 1500
    max_failed_subtasks: int = 2

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> "OrchestratorBudget":
        state = state or {}
        execution_budget = execution_budget_from_state(state)
        if not isinstance(execution_budget, ExecutionBudget):
            execution_budget = ExecutionBudget()

        override = state.get("orchestrator_budget")
        if isinstance(override, dict):
            return cls(
                max_subtask_count=max(int(override.get("max_subtask_count", execution_budget.max_tool_calls) or 0), 1),
                max_parallelism=max(int(override.get("max_parallelism", min(execution_budget.max_tool_calls, execution_budget.max_review_rounds + 1)) or 0), 1),
                subtask_timeout_ms=max(int(override.get("subtask_timeout_ms", 1500) or 0), 1),
                max_failed_subtasks=max(int(override.get("max_failed_subtasks", execution_budget.max_review_rounds) or 0), 0),
            )

        timeout_value = state.get("orchestrator_subtask_timeout_ms")
        if timeout_value is None:
            timeout_value = state.get("subtask_timeout_ms")

        return cls(
            max_subtask_count=max(int(execution_budget.max_tool_calls or 0), 1),
            max_parallelism=max(1, min(int(execution_budget.max_tool_calls or 1), int(execution_budget.max_review_rounds or 0) + 1)),
            subtask_timeout_ms=max(int(timeout_value or 1500), 1),
            max_failed_subtasks=max(int(execution_budget.max_review_rounds or 0), 0),
        )
