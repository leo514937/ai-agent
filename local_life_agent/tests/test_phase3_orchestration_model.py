"""Phase 3 orchestration model convergence boundary tests.

These tests freeze the current division of responsibilities:
LangGraph is the outer orchestrator, workflow_runner is dispatch-only,
workflow_registry is whitelist-only, and the remaining workflows are
stage handlers / adapters rather than a second top-level scheduler.
"""

from __future__ import annotations

import ast
import inspect

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine._routes import _route_workflow_runner
from local_life_agent.engine.graph_builder import _GRAPH_EDGE_TABLE_ROWS, _WORKFLOW_RUNNER_ROUTES
from local_life_agent.engine.workflow_registry import WORKFLOW_REGISTRY, WorkflowRegistration, WorkflowRegistry
from local_life_agent.engine.workflow_runner import h_workflow_runner
import local_life_agent.engine.workflow_runner as workflow_runner_module


def _base_state(**overrides):
    state = {
        "trace_id": "trace_phase3",
        "session_id": "session_phase3",
        "turn_id": "turn_phase3",
        "task_type": "recommendation",
        "raw_text": "附近推荐火锅",
        "normalized_text": "附近推荐火锅",
        "semantic_frame": {"confidence": 0.91, "task_type": "recommendation"},
        "workflow_name": "discovery_decision",
        "workflow_reason": "recommendation route",
        "orchestration_pattern": "discovery_decision",
        "response_mode": "recommendation",
        "event_log": [],
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


def test_phase3_workflow_runner_dispatches_only_from_orchestration_decision(monkeypatch):
    calls: list[dict[str, str]] = []

    def spy_handler(state, decision):
        calls.append(
            {
                "workflow_name": decision.workflow_name,
                "task_type": str(state.get("task_type", "")),
                "raw_text": str(state.get("raw_text", "")),
            }
        )
        return {
            "workflow_name": decision.workflow_name,
            "workflow_run_status": "dispatched",
            "workflow_runner_reason": "spy dispatch",
            "workflow_started_at": "2026-07-05T00:00:00Z",
            "workflow_finished_at": "2026-07-05T00:00:00Z",
            "workflow_callable": "spy_handler",
            "workflow_registered": True,
        }

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=spy_handler,
            status="registered",
            entry_node="planning_subgraph",
        )
    )

    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    result = h_workflow_runner(
        _base_state(
            task_type="clarification_reply",
            raw_text="这家有券吗",
            normalized_text="这家有券吗",
            semantic_frame={"confidence": 0.12, "task_type": "clarification_reply"},
            orchestration_decision=OrchestrationDecision(
                orchestration_pattern="discovery_decision",
                workflow_name="discovery_decision",
                workflow_reason="recommendation route",
                task_complexity="medium",
                requires_tool=True,
                requires_clarification=False,
                response_mode="recommendation",
                confidence=0.92,
                missing_fields=[],
                next_action="run_workflow",
            ),
        )
    )

    assert calls == [
        {
            "workflow_name": "discovery_decision",
            "task_type": "clarification_reply",
            "raw_text": "这家有券吗",
        }
    ]
    assert result["workflow_name"] == "discovery_decision"
    assert result["workflow_run_status"] == "dispatched"
    assert result["workflow_registered"] is True
    assert result["workflow_callable"] == "spy_handler"
    assert result["response_mode"] == "recommendation"


def test_phase3_workflow_registry_stays_name_only_and_entry_node_bound():
    source = inspect.getsource(WorkflowRegistry.lookup)
    for forbidden in ("query", "semantic_frame", "task_type", "raw_text", "top_intent"):
        assert forbidden not in source

    discovery = WORKFLOW_REGISTRY.lookup("discovery_decision")
    assert discovery.entry_node == "planning_subgraph"
    assert discovery.is_real is True

    for workflow_name in ("direct_response", "deterministic_tool", "clarification_fallback", "exploration_planning"):
        registration = WORKFLOW_REGISTRY.lookup(workflow_name)
        assert registration.entry_node == "response_subgraph"


def test_phase3_outer_graph_keeps_workflow_runner_as_the_only_dispatch_hop():
    assert ("orchestration_router_shadow", "shadow->runner", "workflow_runner") in _GRAPH_EDGE_TABLE_ROWS
    assert _route_workflow_runner({"workflow_name": "discovery_decision", "workflow_run_status": "dispatched"}) == "planning_subgraph"
    assert _route_workflow_runner({"workflow_name": "direct_response", "workflow_run_status": "dispatched"}) == "response_subgraph"
    assert _route_workflow_runner({"workflow_name": "clarification_fallback", "workflow_run_status": "dispatched"}) == "response_subgraph"
    assert _route_workflow_runner({"workflow_name": "exploration_planning", "workflow_run_status": "dispatched"}) == "response_subgraph"
    assert _WORKFLOW_RUNNER_ROUTES["planning_subgraph"] == "planning_subgraph"
