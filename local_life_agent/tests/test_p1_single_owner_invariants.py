from __future__ import annotations

from typing import get_origin, get_type_hints

import pytest

from local_life_agent.domain.graph_state import GraphState
from local_life_agent.domain.schemas import AnswerPlan, DecisionPlan, EvidencePack, ExplorationPlan, OrchestrationDecision
from local_life_agent.engine import workflow_runner as workflow_runner_module
from local_life_agent.engine._routes import _route_workflow_runner
from local_life_agent.engine.workflow_registry import LEGAL_WORKFLOW_NAMES, WORKFLOW_REGISTRY, WorkflowRegistration, WorkflowRegistry
from local_life_agent.engine.workflow_runner import h_workflow_runner
from local_life_agent.planning.orchestration_router import route_orchestration


_FORBIDDEN_MULTI_OWNER_FIELDS = {
    "workflow_names",
    "final_responses",
    "state_update_plans",
    "evidence_packs",
    "decision_plans",
    "answer_plans",
    "workflow_results",
    "workflow_outputs",
    "merged_final_response",
    "merged_state_update_plan",
}


def _is_list_like(annotation: object) -> bool:
    return get_origin(annotation) in {list, tuple, set}


def _build_state(workflow_name: object) -> dict[str, object]:
    return {
        "trace_id": "trace_p1",
        "session_id": "session_p1",
        "turn_id": "turn_p1",
        "workflow_name": workflow_name,
        "orchestration_pattern": "discovery_decision",
        "workflow_reason": "p1 test",
        "orchestration_decision": {
            "orchestration_pattern": "discovery_decision",
            "workflow_name": "discovery_decision",
            "workflow_reason": "p1 test",
            "task_complexity": "medium",
            "requires_tool": True,
            "requires_clarification": False,
            "response_mode": "recommendation",
            "confidence": 0.8,
            "missing_fields": [],
            "next_action": "run_workflow",
        },
        "event_log": [],
    }


def test_graph_state_workflow_name_is_single_value():
    workflow_name_type = get_type_hints(GraphState)["workflow_name"]
    assert workflow_name_type is str
    assert not _is_list_like(workflow_name_type)


def test_orchestration_decision_workflow_name_rejects_list():
    with pytest.raises(Exception):
        OrchestrationDecision.model_validate(
            {
                "orchestration_pattern": "discovery_decision",
                "workflow_name": ["discovery_decision", "deterministic_tool"],
                "workflow_reason": "invalid list",
                "task_complexity": "medium",
                "requires_tool": True,
                "requires_clarification": False,
                "response_mode": "recommendation",
                "confidence": 0.8,
                "missing_fields": [],
                "next_action": "run_workflow",
            }
        )


def test_workflow_registry_lookup_returns_single_registration():
    registration = WORKFLOW_REGISTRY.lookup("discovery_decision")
    assert isinstance(registration, WorkflowRegistration)
    assert registration.workflow_name == "discovery_decision"
    assert registration.handler is not None


def test_workflow_registry_has_no_multi_lookup_api():
    for api_name in ("lookup_many", "dispatch_many", "fanout", "lookup_all"):
        assert not hasattr(WORKFLOW_REGISTRY, api_name)


def test_workflow_registry_names_are_unique():
    names = WORKFLOW_REGISTRY.names()
    assert len(names) == len(set(names))
    assert set(names) == set(LEGAL_WORKFLOW_NAMES)


def test_workflow_runner_dispatches_exactly_one_handler(monkeypatch):
    calls: list[str] = []

    def discovery_handler(state, decision):
        calls.append(decision.workflow_name)
        return {
            "workflow_name": decision.workflow_name,
            "workflow_run_status": "dispatched",
            "workflow_runner_reason": "discovery dispatch",
            "workflow_started_at": "2026-06-30T00:00:00Z",
            "workflow_finished_at": "2026-06-30T00:00:00Z",
            "workflow_callable": "discovery_handler",
            "workflow_registered": True,
        }

    def unexpected_handler(state, decision):
        raise AssertionError("unexpected second handler call")

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=discovery_handler,
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="direct_response",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="deterministic_tool",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="clarification_fallback",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )

    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    result = h_workflow_runner(_build_state("discovery_decision"))

    assert calls == ["discovery_decision"]
    assert result["workflow_run_status"] == "dispatched"
    assert result["workflow_callable"] == "discovery_handler"
    assert result["workflow_registered"] is True


def test_workflow_runner_does_not_iterate_workflow_name_list(monkeypatch):
    calls: list[str] = []

    def unexpected_handler(state, decision):
        calls.append(decision.workflow_name)
        raise AssertionError("list input should not dispatch any handler")

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=unexpected_handler,
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="direct_response",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="deterministic_tool",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="clarification_fallback",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=unexpected_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )

    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    state = {
        "trace_id": "trace_p1",
        "session_id": "session_p1",
        "turn_id": "turn_p1",
        "workflow_name": ["discovery_decision", "deterministic_tool"],
        "orchestration_pattern": "discovery_decision",
        "workflow_reason": "p1 test",
        "event_log": [],
    }
    result = h_workflow_runner(state)

    assert calls == []
    assert result["workflow_run_status"] == "fallback"
    assert result["workflow_registered"] is False
    assert result["workflow_callable"] == ""


def test_workflow_runner_merges_single_workflow_patch_once(monkeypatch):
    merge_hits: list[str] = []

    def discovery_handler(state, decision):
        merge_hits.append("handler_called")
        return {
            "workflow_name": decision.workflow_name,
            "workflow_run_status": "dispatched",
            "workflow_runner_reason": "merged once",
            "workflow_started_at": "2026-06-30T00:00:00Z",
            "workflow_finished_at": "2026-06-30T00:00:00Z",
            "workflow_callable": "discovery_handler",
            "workflow_registered": True,
            "response_mode": "recommendation",
            "next_action": "run_workflow",
            "custom_marker": "kept",
        }

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=discovery_handler,
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="direct_response",
            handler=discovery_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="deterministic_tool",
            handler=discovery_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="clarification_fallback",
            handler=discovery_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=discovery_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )

    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    result = h_workflow_runner(_build_state("discovery_decision"))

    assert merge_hits == ["handler_called"]
    assert result["custom_marker"] == "kept"
    assert result["workflow_run_status"] == "dispatched"
    assert result["workflow_callable"] == "discovery_handler"
    assert result["response_mode"] == "recommendation"


def test_routes_do_not_generate_workflow_fanout():
    assert _route_workflow_runner({"workflow_name": "discovery_decision"}) == "planning_subgraph"
    assert _route_workflow_runner({"workflow_name": "direct_response"}) == "response_subgraph"
    assert _route_workflow_runner({"workflow_name": "exploration_planning"}) == "response_subgraph"

    complex_queries = [
        "附近推荐几家适合约会、现在营业、最好有券、人均100左右的餐厅",
        "推荐附近火锅，第一家远吗",
        "第一家和第二家哪家更适合带娃，哪家更便宜",
        "帮我安排一个先吃饭再喝咖啡的约会路线",
    ]
    for query in complex_queries:
        decision = route_orchestration(
            {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "semantic_frame": {"confidence": 0.8, "primary_task": "recommendation"},
                "current_shop": None,
                "pending_clarification": None,
                "raw_text": query,
            }
        )
        assert isinstance(decision["workflow_name"], str)
        assert not isinstance(decision["workflow_name"], (list, tuple, set))


def test_no_multi_workflow_owner_fields_in_graph_state_and_schemas():
    graph_state_fields = set(GraphState.__annotations__)
    schema_field_sets = [
        set(OrchestrationDecision.model_fields),
        set(EvidencePack.model_fields),
        set(AnswerPlan.model_fields),
        set(DecisionPlan.model_fields),
        set(ExplorationPlan.model_fields),
    ]

    for field_set in [graph_state_fields, *schema_field_sets]:
        assert not (field_set & _FORBIDDEN_MULTI_OWNER_FIELDS)


def test_graph_state_single_output_objects_are_not_lists():
    assert not _is_list_like(GraphState.__annotations__["evidence_pack"])
    assert not _is_list_like(GraphState.__annotations__["answer_plan"])
    assert not _is_list_like(GraphState.__annotations__["final_response"])
    assert not _is_list_like(GraphState.__annotations__["state_update_plan"])
    assert not _is_list_like(GraphState.__annotations__["p2_decision_plan"])
    assert not _is_list_like(GraphState.__annotations__["workflow_name"])


def test_workflow_result_does_not_return_multiple_final_responses(monkeypatch):
    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="discovery_decision",
            handler=lambda state, decision: {
                "workflow_name": decision.workflow_name,
                "workflow_run_status": "dispatched",
                "workflow_runner_reason": "single response",
                "workflow_started_at": "2026-06-30T00:00:00Z",
                "workflow_finished_at": "2026-06-30T00:00:00Z",
                "workflow_callable": "single_response_handler",
                "workflow_registered": True,
                "final_response": "ok",
            },
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="direct_response",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "dispatched", "workflow_registered": True},
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="deterministic_tool",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "dispatched", "workflow_registered": True},
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="clarification_fallback",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "dispatched", "workflow_registered": True},
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=lambda state, decision: {"workflow_name": decision.workflow_name, "workflow_run_status": "dispatched", "workflow_registered": True},
            status="registered",
            entry_node="response_subgraph",
        )
    )

    monkeypatch.setattr(workflow_runner_module, "WORKFLOW_REGISTRY", registry)

    result = h_workflow_runner(_build_state("discovery_decision"))

    assert result["final_response"] == "ok"
    assert not isinstance(result["final_response"], (list, tuple, set))


def test_workflow_result_does_not_return_multiple_state_update_plans():
    assert not _is_list_like(GraphState.__annotations__["state_update_plan"])
