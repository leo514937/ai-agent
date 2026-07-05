from __future__ import annotations

import pytest

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.workflow_registry import (
    LEGAL_WORKFLOW_NAMES,
    WORKFLOW_REGISTRY,
    WORKFLOW_STATUS_REGISTERED,
    WorkflowRegistration,
    WorkflowRegistry,
    WorkflowRegistryError,
)
from local_life_agent.engine.workflows import exploration_planning_workflow as exploration_workflow_module


def _noop_workflow_handler(state, decision):
    return {
        "workflow_name": decision.workflow_name,
        "workflow_run_status": "dispatched",
        "workflow_runner_reason": "noop dispatch",
        "workflow_started_at": "2026-06-30T00:00:00Z",
        "workflow_finished_at": "2026-06-30T00:00:00Z",
        "workflow_callable": "noop_workflow_handler",
        "workflow_registered": True,
    }


def test_registry_can_register_discovery_decision():
    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=_noop_workflow_handler,
            status=WORKFLOW_STATUS_REGISTERED,
            entry_node="planning_subgraph",
            description="current main chain",
        )
    )

    registration = registry.lookup("discovery_decision")
    assert registration.workflow_name == "discovery_decision"
    assert registration.entry_node == "planning_subgraph"
    assert registration.status == WORKFLOW_STATUS_REGISTERED
    assert registration.is_real is True


def test_default_registry_covers_all_legal_workflow_names():
    assert set(WORKFLOW_REGISTRY.names()) == set(LEGAL_WORKFLOW_NAMES)
    assert WORKFLOW_REGISTRY.lookup("discovery_decision").is_real is True
    assert WORKFLOW_REGISTRY.lookup("direct_response").is_real is True
    assert WORKFLOW_REGISTRY.lookup("clarification_fallback").is_real is True
    assert WORKFLOW_REGISTRY.lookup("exploration_planning").is_real is True


def test_illegal_workflow_is_rejected():
    registry = WorkflowRegistry()

    with pytest.raises(WorkflowRegistryError, match="WORKFLOW_NOT_REGISTERED"):
        registry.lookup("forbidden_workflow")


def test_unregistered_workflow_is_rejected():
    registry = WorkflowRegistry()

    with pytest.raises(WorkflowRegistryError, match="WORKFLOW_NOT_REGISTERED"):
        registry.lookup("discovery_decision")


def test_exploration_planning_is_registered_callable(monkeypatch):
    monkeypatch.setattr(
        exploration_workflow_module,
        "dispatch_tool_call",
        lambda tool_name, kwargs: {
            "call_id": kwargs.get("call_id", ""),
            "shop_id": kwargs.get("shop_id", ""),
            "tool_name": tool_name,
            "success": True,
            "result_status": "ok",
            "data": (
                [{"shop_id": "shop_1", "shop_name": "测试店", "address": "测试路 1 号"}]
                if tool_name == "search_shops"
                else {"shop_id": kwargs.get("shop_id", ""), "shop_name": "测试店", "open_status": "open", "distance_km": 1.0, "eta_minutes": 8}
            ),
            "error_code": "",
            "error_message": "",
            "source": "test",
            "backend_source": "test",
            "degraded": False,
        },
    )

    registration = WORKFLOW_REGISTRY.lookup("exploration_planning")
    decision = OrchestrationDecision(
        orchestration_pattern="exploration_planning",
        workflow_name="exploration_planning",
        workflow_reason="exploration test",
        task_complexity="high",
        requires_tool=True,
        requires_clarification=False,
        response_mode="exploration_plan",
        confidence=0.1,
        missing_fields=[],
        next_action="run_workflow",
    )

    patch = registration.handler(
        {
            "raw_text": "先喝咖啡然后吃晚饭",
            "task_type": "coffee_then_dinner",
            "semantic_frame": {"task_type": "coffee_then_dinner"},
            "user_context": {"lat": 39.9, "lng": 116.4},
        },
        decision,
    )
    assert patch["workflow_run_status"] == "completed"
    assert patch["workflow_registered"] is True
    assert patch["response_mode"] == "exploration_plan"
    assert patch["workflow_callable"] == "run_exploration_planning_workflow"
    assert patch["workflow_candidate_reason"] == "exploration test"
