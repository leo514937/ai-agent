from __future__ import annotations

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine._routes import _route_workflow_runner
from local_life_agent.engine.graph_builder import (
    _GRAPH_EDGE_TABLE_ROWS,
    _GRAPH_HANDLERS,
    _GRAPH_NODE_TABLE_NEXT_HOPS,
    _WORKFLOW_RUNNER_ROUTES,
)
from local_life_agent.engine.workflow_registry import (
    WORKFLOW_REGISTRY,
    WorkflowRegistration,
    WorkflowRegistry,
)
from local_life_agent.engine.workflow_runner import h_workflow_runner
import local_life_agent.engine.workflow_runner as workflow_runner_module
import local_life_agent.engine.workflows.exploration_planning_workflow as exploration_workflow_module


def _build_discovery_decision() -> OrchestrationDecision:
    return OrchestrationDecision(
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
    )


def test_workflow_runner_dispatches_by_orchestration_decision(monkeypatch):
    calls: list[dict[str, str]] = []

    def spy_discovery_dispatch(state, decision):
        calls.append(
            {
                "workflow_name": decision.workflow_name,
                "task_type": str(state.get("task_type", "")),
                "response_mode": str(state.get("response_mode", "")),
            }
        )
        return {
            "workflow_name": decision.workflow_name,
            "workflow_run_status": "dispatched",
            "workflow_runner_reason": "spy discovery dispatch",
            "workflow_started_at": "2026-06-30T00:00:00Z",
            "workflow_finished_at": "2026-06-30T00:00:00Z",
            "workflow_callable": "spy_discovery_dispatch",
            "workflow_registered": True,
        }

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=spy_discovery_dispatch,
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="direct_response",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "unsupported", "workflow_runner_reason": "placeholder", "workflow_registered": True},
            status="unsupported",
            entry_node=None,
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="deterministic_tool",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "not_implemented", "workflow_runner_reason": "placeholder", "workflow_registered": True},
            status="not_implemented",
            entry_node=None,
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="clarification_fallback",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "not_implemented", "workflow_runner_reason": "placeholder", "workflow_registered": True},
            status="not_implemented",
            entry_node=None,
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "not_implemented", "workflow_runner_reason": "placeholder", "workflow_registered": True},
            status="not_implemented",
            entry_node=None,
        )
    )

    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    result = h_workflow_runner(
        {
            "trace_id": "trace_runner",
            "session_id": "session_1",
            "turn_id": "turn_1",
            "task_type": "chat",
            "response_mode": "direct_response",
            "workflow_name": "direct_response",
            "orchestration_pattern": "direct_response",
            "workflow_reason": "stale value",
            "orchestration_decision": _build_discovery_decision(),
            "event_log": [],
        }
    )

    assert calls == [
        {
            "workflow_name": "discovery_decision",
            "task_type": "chat",
            "response_mode": "direct_response",
        }
    ]
    assert result["workflow_name"] == "discovery_decision"
    assert result["workflow_run_status"] == "dispatched"
    assert result["workflow_registered"] is True
    assert result["workflow_callable"] == "spy_discovery_dispatch"
    assert result["response_mode"] == "recommendation"
    assert result["workflow_runner_error"] == ""
    assert result["workflow_candidate_reason"] == "recommendation route"


def test_workflow_runner_dispatches_exploration_workflow(monkeypatch):
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
                [{"shop_id": "shop_1", "shop_name": "咖啡店 A", "address": "A 路"}]
                if tool_name == "search_shops"
                else {"shop_id": kwargs.get("shop_id", ""), "shop_name": "咖啡店 A", "open_status": "open", "distance_km": 1.2, "eta_minutes": 10}
            ),
            "error_code": "",
            "error_message": "",
            "source": "test",
            "backend_source": "test",
            "degraded": False,
        },
    )
    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", WORKFLOW_REGISTRY)

    result = h_workflow_runner(
        {
            "trace_id": "trace_runner",
            "session_id": "session_1",
            "turn_id": "turn_1",
            "task_type": "coffee_then_dinner",
            "raw_text": "先喝咖啡然后吃晚饭",
            "response_mode": "exploration_plan",
            "workflow_name": "exploration_planning",
            "orchestration_pattern": "exploration_planning",
            "workflow_reason": "exploration route",
            "orchestration_decision": OrchestrationDecision(
                orchestration_pattern="exploration_planning",
                workflow_name="exploration_planning",
                workflow_reason="exploration route",
                task_complexity="high",
                requires_tool=True,
                requires_clarification=False,
                response_mode="exploration_plan",
                confidence=0.2,
                missing_fields=[],
                next_action="run_workflow",
            ),
            "user_context": {"lat": 39.9, "lng": 116.4},
            "event_log": [],
        }
    )

    assert result["workflow_run_status"] == "completed"
    assert result["response_mode"] == "exploration_plan"
    assert result["next_action"] == "run_workflow"
    assert result["workflow_runner_error"] == ""
    assert result["workflow_callable"] == "run_exploration_planning_workflow"
    assert result["workflow_registered"] is True


def test_workflow_runner_graph_contract_includes_runner():
    assert "workflow_runner" in _GRAPH_HANDLERS
    assert "workflow_runner" in _GRAPH_NODE_TABLE_NEXT_HOPS["orchestration_router_shadow"]
    assert ("orchestration_router_shadow", "shadow->runner", "workflow_runner") in _GRAPH_EDGE_TABLE_ROWS
    assert _route_workflow_runner({"workflow_name": "discovery_decision", "workflow_run_status": "dispatched"}) == "planning_subgraph"
    assert _route_workflow_runner({"workflow_name": "clarification_fallback", "workflow_run_status": "dispatched"}) == "response_subgraph"
    assert _route_workflow_runner({"workflow_name": "direct_response", "workflow_run_status": "dispatched"}) == "response_subgraph"
    assert _route_workflow_runner({"workflow_name": "exploration_planning", "workflow_run_status": "dispatched"}) == "response_subgraph"
    assert _route_workflow_runner({"workflow_name": "complex_orchestrator_workflow", "workflow_run_status": "dispatched", "response_mode": "exploration_plan"}) == "response_subgraph"
    assert _WORKFLOW_RUNNER_ROUTES["planning_subgraph"] == "planning_subgraph"
