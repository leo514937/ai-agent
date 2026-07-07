"""Phase 2 routing authority boundary tests.

These tests freeze the current division of responsibilities:
canonical router decides business routing, _routes maps edges, shadow
router wraps canonical output, and workflow registry only validates names.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from local_life_agent.engine._routes import _route_workflow_runner
from local_life_agent.engine.subgraphs.orchestration_router_shadow import h_orchestration_router_shadow
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY, WorkflowRegistry, WorkflowRegistryError
from local_life_agent.planning.orchestration_router import route_orchestration


def _base_state(**overrides):
    state = {
        "trace_id": "trace_phase2",
        "turn_id": "turn_phase2",
        "top_intent": "local_life",
        "task_type": "recommendation",
        "raw_text": "附近推荐火锅",
        "normalized_text": "附近推荐火锅",
        "semantic_frame": {"confidence": 0.91},
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "workflow_name": "discovery_decision",
        "workflow_callable": "planning_subgraph",
        "response_mode": "recommendation",
        "orchestration_pattern": "discovery_decision",
    }
    state.update(overrides)
    return state


def _call_names_from_function(fn) -> set[str]:
    tree = ast.parse(inspect.getsource(fn))
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
    return calls


def test_route_workflow_runner_uses_only_existing_routing_fields():
    base = _base_state(workflow_name="discovery_decision", workflow_callable="planning_subgraph", response_mode="recommendation")
    variant = _base_state(
        task_type="clarification_reply",
        raw_text="这家有券吗",
        normalized_text="这家有券吗",
        semantic_frame={"confidence": 0.12, "task_type": "clarification_reply"},
        workflow_name="discovery_decision",
        workflow_callable="planning_subgraph",
        response_mode="recommendation",
    )

    assert _route_workflow_runner(base) == "planning_subgraph"
    assert _route_workflow_runner(variant) == "planning_subgraph"


def test_route_workflow_runner_source_does_not_read_query_or_intent_fields():
    source = inspect.getsource(_route_workflow_runner)
    for forbidden in ("query", "semantic_frame", "task_type", "raw_text", "top_intent"):
        assert forbidden not in source


def test_shadow_router_matches_canonical_router_for_routing_fields():
    state = _base_state(
        task_type="comparison",
        raw_text="海底捞和巴奴哪个更适合聚餐",
        normalized_text="海底捞和巴奴哪个更适合聚餐",
        semantic_frame={
            "confidence": 0.93,
            "comparison_intent": True,
            "comparison_targets": [
                {"reference": "explicit", "shop_name": "海底捞"},
                {"reference": "explicit", "shop_name": "巴奴"},
            ],
        },
        workflow_name="discovery_decision",
        workflow_callable="planning_subgraph",
        response_mode="comparison",
        orchestration_pattern="discovery_decision",
    )

    canonical = route_orchestration(state)
    shadow = h_orchestration_router_shadow(state)

    for key in ("workflow_name", "orchestration_pattern", "response_mode", "next_action", "workflow_reason"):
        assert shadow[key] == canonical[key]
    assert shadow["orchestration_decision"].model_dump()["workflow_name"] == canonical["orchestration_decision"].model_dump()["workflow_name"]


def test_shadow_router_ast_has_no_independent_business_routing_calls():
    calls = _call_names_from_function(h_orchestration_router_shadow)
    assert "route_orchestration" in calls
    assert "build_orchestration_decision" not in calls
    assert "resolve_workflow_with_policy" not in calls
    assert "normalize_route_task" not in calls


def test_workflow_registry_lookup_is_name_only_guard():
    source = inspect.getsource(WorkflowRegistry.lookup)
    for forbidden in ("query", "semantic_frame", "task_type", "raw_text", "top_intent"):
        assert forbidden not in source

    registration = WORKFLOW_REGISTRY.lookup("discovery_decision")
    assert registration.workflow_name == "discovery_decision"
    assert registration.is_real is True

    with pytest.raises(WorkflowRegistryError):
        WORKFLOW_REGISTRY.lookup("not_registered_workflow")


def test_workflow_runner_falls_back_instead_of_guessing_from_text():
    from local_life_agent.engine.workflow_runner import h_workflow_runner

    result = h_workflow_runner(
        _base_state(
            workflow_name="",
            workflow_callable="",
            orchestration_decision=None,
            task_type="recommendation",
            raw_text="附近推荐火锅",
            normalized_text="附近推荐火锅",
            semantic_frame={"confidence": 0.89, "task_type": "recommendation"},
        )
    )

    assert result["workflow_run_status"] == "fallback"
    assert result["workflow_registered"] is False
    assert result["workflow_runner_error"] in {"WORKFLOW_DECISION_MISSING", "WORKFLOW_NAME_MISSING"}
    assert result["response_mode"] == "fallback"

