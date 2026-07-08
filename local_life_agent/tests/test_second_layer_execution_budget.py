from __future__ import annotations

import json

from local_life_agent.planning.budget.budget_context import BudgetContext
from local_life_agent.planning.budget.execution_budget import (
    ExecutionBudget,
    execution_budget_from_state,
)
from local_life_agent.planning.orchestrator.orchestrator_budget import OrchestratorBudget


def test_execution_budget_defaults_are_stable() -> None:
    budget = ExecutionBudget()
    assert budget.max_tool_calls == 10
    assert budget.max_llm_calls == 3
    assert budget.max_review_rounds == 2
    assert budget.max_rewrite_rounds == 1
    assert ExecutionBudget.model_validate(budget.model_dump()) == budget
    assert json.loads(json.dumps(budget.model_dump()))["max_tool_calls"] == 10


def test_execution_budget_reads_budget_context_and_state() -> None:
    budget_context = BudgetContext(tool_round_budget=5, retry_budget=3, rewrite_budget=2)
    budget = ExecutionBudget.from_budget_context(budget_context)
    assert budget.max_tool_calls == 5
    assert budget.max_llm_calls == 5
    assert budget.max_review_rounds == 4
    assert budget.max_rewrite_rounds == 2

    state_budget = execution_budget_from_state({"budget_context": budget_context.model_dump()})
    assert state_budget == budget
    assert state_budget.to_budget_context().tool_round_budget == 5
    assert state_budget.to_budget_context().retry_budget == 3
    assert state_budget.to_budget_context().rewrite_budget == 2


def test_execution_budget_explicit_state_value_wins() -> None:
    state = {
        "execution_budget": {
            "max_tool_calls": 7,
            "max_llm_calls": 4,
            "max_review_rounds": 3,
            "max_rewrite_rounds": 2,
        },
        "budget_context": BudgetContext(tool_round_budget=2, retry_budget=1, rewrite_budget=1).model_dump(),
    }
    budget = execution_budget_from_state(state)
    assert budget.max_tool_calls == 7
    assert budget.max_llm_calls == 4
    assert budget.max_review_rounds == 3
    assert budget.max_rewrite_rounds == 2


def test_orchestrator_budget_derives_parallelism_and_timeout_from_state() -> None:
    budget = OrchestratorBudget.from_state(
        {
            "execution_budget": {
                "max_tool_calls": 6,
                "max_llm_calls": 4,
                "max_review_rounds": 2,
                "max_rewrite_rounds": 1,
            },
            "orchestrator_subtask_timeout_ms": 321,
        }
    )

    assert budget.max_subtask_count == 6
    assert budget.max_parallelism == 3
    assert budget.subtask_timeout_ms == 321
    assert budget.max_failed_subtasks == 2
