from __future__ import annotations

import json

from local_life_agent.planning.budget.budget_context import BudgetContext
from local_life_agent.planning.policies.review_policy import ReviewPolicy, review_policy_from_state


def test_review_policy_defaults_are_stable() -> None:
    policy = ReviewPolicy()
    assert policy.max_review_rounds == 2
    assert policy.max_rewrite_rounds == 1
    assert policy.allow_fallback is True
    assert policy.allow_clarify is True
    assert ReviewPolicy.model_validate(policy.model_dump()) == policy
    assert json.loads(json.dumps(policy.model_dump()))["max_review_rounds"] == 2


def test_review_policy_reads_explicit_state_value() -> None:
    state = {
        "review_policy": {
            "max_review_rounds": 4,
            "max_rewrite_rounds": 2,
            "allow_fallback": False,
            "allow_clarify": True,
        }
    }
    policy = review_policy_from_state(state)
    assert policy.max_review_rounds == 4
    assert policy.max_rewrite_rounds == 2
    assert policy.allow_fallback is False
    assert policy.allow_clarify is True


def test_review_policy_can_fall_back_to_budget_context() -> None:
    budget_context = BudgetContext(tool_round_budget=5, retry_budget=3, rewrite_budget=2)
    policy = review_policy_from_state({"budget_context": budget_context.model_dump()})
    assert policy.max_review_rounds == 4
    assert policy.max_rewrite_rounds == 2
    assert json.loads(json.dumps(policy.model_dump()))["max_rewrite_rounds"] == 2
