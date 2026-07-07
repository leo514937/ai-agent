from __future__ import annotations

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.workflows.complex_orchestrator_workflow import run_complex_orchestrator_workflow
from local_life_agent.engine import workflow_registry as workflow_registry_module
from local_life_agent.engine.workflow_registry import WorkflowRegistration, WorkflowRegistry


def _handler_factory(workflow_name: str):
    def _handler(state, decision):
        return {
            "workflow_name": workflow_name,
            "workflow_run_status": "completed",
            "workflow_runner_reason": f"{workflow_name} done",
            "workflow_started_at": "2026-07-01T00:00:00Z",
            "workflow_finished_at": "2026-07-01T00:00:00Z",
            "workflow_callable": f"fake_{workflow_name}",
            "workflow_registered": True,
            "evidence_pack": {
                "tool_results": {f"{workflow_name}_call": {"tool_name": workflow_name}},
                "citations": [{"source": workflow_name}],
                "answerable_facets": ["detail"] if workflow_name != "comparison_decision_workflow" else ["comparison"],
            },
            "decision_plan": {
                "answer_type": "comparison" if "comparison" in workflow_name else "exploration_plan",
                "winner_shop_id": "shop_1",
                "winner_shop_name": "A 店",
                "overall_ranking": [{"shop_id": "shop_1", "rank": 1}],
                "claims": [{"evidence_id": f"{workflow_name}_e1"}],
            },
            "response_directive": {"answer_source": workflow_name, "preview_text": f"{workflow_name} preview"},
        }

    return _handler


def test_complex_orchestrator_workflow_uses_dag_and_reducers(monkeypatch):
    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="comparison_decision_workflow",
            handler=_handler_factory("comparison_decision_workflow"),
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=_handler_factory("exploration_planning"),
            status="registered",
            entry_node="response_subgraph",
        )
    )
    monkeypatch.setattr(workflow_registry_module, "WORKFLOW_REGISTRY", registry)

    patch = run_complex_orchestrator_workflow(
        {
            "trace_id": "trace_complex",
            "task_type": "super_complex",
            "semantic_frame": {
                "task_type": "super_complex",
                "task_complexity": "super_complex",
                "complex_subtasks": [
                    {"task_id": "task_a", "workflow_name": "comparison_decision_workflow"},
                    {"task_id": "task_b", "workflow_name": "exploration_planning", "depends_on": ["task_a"]},
                ],
            },
            "raw_text": "请帮我做复杂任务编排",
        },
    )

    assert patch["workflow_name"] == "complex_orchestrator_workflow"
    assert patch["workflow_run_status"] == "completed"
    assert patch["response_mode"] == "exploration_plan"
    assert patch["workflow_registered"] is True
    assert patch["answer_source"] == "complex_orchestrator_workflow"
    assert patch["preview_text"]
    assert "sub_task_dag" in patch
    assert len(patch["worker_results"]) == 2
    assert patch["response_contract_v2"].answer_source == "complex_orchestrator_workflow"
    assert patch["response_contract_v1"].answer_source == "complex_orchestrator_workflow"


def test_complex_orchestrator_default_answer_text_is_deterministic(monkeypatch):
    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=_handler_factory("exploration_planning"),
            status="registered",
            entry_node="response_subgraph",
        )
    )
    monkeypatch.setattr(workflow_registry_module, "WORKFLOW_REGISTRY", registry)

    patch = run_complex_orchestrator_workflow(
        {
            "trace_id": "trace_complex_2",
            "task_type": "super_complex",
            "semantic_frame": {"task_type": "super_complex", "task_complexity": "super_complex"},
            "raw_text": "复杂任务",
        },
    )

    assert patch["workflow_run_status"] == "completed"
    assert patch["response_directive"].answer_source == "complex_orchestrator_workflow"
