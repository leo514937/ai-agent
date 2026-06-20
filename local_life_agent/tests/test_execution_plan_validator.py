"""Focused contract tests for ExecutionPlanValidator.

These tests lock the validator behavior without touching any runtime
graph or business execution flow.
"""

from __future__ import annotations

from local_life_agent import config

from ..domain.schemas import ExecutionPlan, ToolCallSpec
from ..planning.plan_validator import ExecutionPlanValidator


def test_unregistered_tool_must_fail():
    validator = ExecutionPlanValidator(registered_tools={"get_shop_detail"})
    plan = ExecutionPlan(
        tool_calls=[
            ToolCallSpec(call_id="c1", tool_name="hallucinated_tool", args={}),
        ]
    )

    report = validator.validate(plan)

    assert not report.passed
    assert any("not registered" in error for error in report.errors)


def test_missing_required_args_must_fail():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        tool_calls=[
            ToolCallSpec(call_id="c1", tool_name="get_shop_detail", args={}),
        ]
    )

    report = validator.validate(plan)

    assert not report.passed
    assert any("SCHEMA_VALIDATION_FAILED" in error for error in report.errors)
    assert any("shop_id" in error for error in report.errors)


def test_argument_type_error_must_fail():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        tool_calls=[
            ToolCallSpec(
                call_id="c1",
                tool_name="get_shop_detail",
                args={"shop_id": 123},
            ),
        ]
    )

    report = validator.validate(plan)

    assert not report.passed
    assert any("INVALID_ARGUMENT" in error for error in report.errors)


def test_legal_args_must_pass():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        tool_calls=[
            ToolCallSpec(
                call_id="c1",
                tool_name="get_shop_detail",
                args={"shop_id": "shop_sc_01"},
            ),
        ]
    )

    report = validator.validate(plan, resolved_shop_ids={"shop_sc_01"})

    assert report.passed


def test_resolved_shop_id_mismatch_must_fail():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        task_type="coupon_query",
        tool_calls=[
            ToolCallSpec(
                call_id="c1",
                tool_name="get_coupon_list",
                args={"shop_id": "shop_b"},
                target_shop_id="shop_b",
            ),
        ],
    )

    report = validator.validate(plan, resolved_shop_ids={"shop_a"})

    assert not report.passed
    assert any("was not produced by legitimate resolve" in error for error in report.errors)


def test_legitimate_resolved_shop_id_passes():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        task_type="coupon_query",
        tool_calls=[
            ToolCallSpec(
                call_id="c1",
                tool_name="get_coupon_list",
                args={"shop_id": "shop_a"},
                target_shop_id="shop_a",
            ),
        ],
    )

    report = validator.validate(plan, resolved_shop_ids={"shop_a"})

    assert report.passed


def test_forbidden_tools_must_fail():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        task_type="coupon_query",
        tool_calls=[
            ToolCallSpec(
                call_id="c1",
                tool_name="search_shops",
                args={"query": "火锅"},
            ),
        ]
    )

    report = validator.validate(plan)

    assert not report.passed
    assert any("forbidden" in error for error in report.errors)


def test_max_tool_calls_exceeded_must_fail():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        tool_calls=[
            ToolCallSpec(
                call_id=f"c{i}",
                tool_name="get_shop_detail",
                args={"shop_id": f"shop_sc_{i:02d}"},
            )
            for i in range(config.MAX_TOOL_CALLS + 1)
        ]
    )

    report = validator.validate(plan)

    assert not report.passed
    assert any("exceeds max_tool_calls" in error for error in report.errors)
