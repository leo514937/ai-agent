from __future__ import annotations

import threading
import time

from local_life_agent.domain.schemas import OrchestrationDecision
from local_life_agent.engine.workflows.complex_orchestrator_workflow import run_complex_orchestrator_workflow
from local_life_agent.engine import workflow_registry as workflow_registry_module
from local_life_agent.engine.workflow_registry import WorkflowRegistration, WorkflowRegistry
from local_life_agent.planning.orchestrator.dag_executor import execute_subtask_dag
from local_life_agent.planning.orchestrator.sub_task_dag import SubTaskDAG


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


def test_complex_orchestrator_runs_same_level_tasks_without_shared_state(monkeypatch):
    barrier = threading.Barrier(2, timeout=2)
    observed_before_mutation: list[object] = []

    def _handler(workflow_name: str):
        def _inner(state, decision):
            observed_before_mutation.append(state.get("mutated_in_worker"))
            if state.get("task_id") in {"task_a", "task_b"}:
                barrier.wait(timeout=2)
            state["mutated_in_worker"] = workflow_name
            return {
                "workflow_name": workflow_name,
                "workflow_run_status": "completed",
                "workflow_runner_reason": f"{workflow_name} done",
                "workflow_callable": f"fake_{workflow_name}",
                "workflow_registered": True,
                "decision_plan": {"answer_type": "exploration_plan"},
            }

        return _inner

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=_handler("exploration_planning"),
            status="registered",
            entry_node="response_subgraph",
        )
    )
    registry.register(
        WorkflowRegistration(
            workflow_name="comparison_decision_workflow",
            handler=_handler("comparison_decision_workflow"),
            status="registered",
            entry_node="planning_subgraph",
        )
    )
    monkeypatch.setattr(workflow_registry_module, "WORKFLOW_REGISTRY", registry)

    patch = run_complex_orchestrator_workflow(
        {
            "trace_id": "trace_parallel",
            "session_id": "session_parallel",
            "turn_id": "turn_parallel",
            "task_type": "super_complex",
            "orchestrator_budget": {"max_subtask_count": 3, "max_parallelism": 2, "subtask_timeout_ms": 500},
            "semantic_frame": {
                "task_type": "super_complex",
                "task_complexity": "super_complex",
                "complex_subtasks": [
                    {"task_id": "task_a", "workflow_name": "exploration_planning"},
                    {"task_id": "task_b", "workflow_name": "comparison_decision_workflow"},
                    {
                        "task_id": "task_c",
                        "workflow_name": "exploration_planning",
                        "depends_on": ["task_a", "task_b"],
                    },
                ],
            },
        }
    )

    assert patch["workflow_run_status"] == "completed"
    assert len(patch["worker_results"]) == 3
    assert observed_before_mutation == [None, None, None]
    assert [result["status"] for result in patch["worker_results"][:2]] == ["completed", "completed"]
    assert patch["worker_results"][2]["status"] == "completed"


def test_complex_orchestrator_marks_timeout_without_killing_thread(monkeypatch):
    seen: list[str] = []

    def slow_handler(state, decision):
        seen.append(state["task_id"])
        time.sleep(0.25)
        return {
            "workflow_name": state["workflow_name"],
            "workflow_run_status": "completed",
            "workflow_registered": True,
            "decision_plan": {"answer_type": "exploration_plan"},
        }

    registry = WorkflowRegistry()
    registry.register(
        WorkflowRegistration(
            workflow_name="exploration_planning",
            handler=slow_handler,
            status="registered",
            entry_node="response_subgraph",
        )
    )
    monkeypatch.setattr(workflow_registry_module, "WORKFLOW_REGISTRY", registry)

    dag = SubTaskDAG.from_specs(
        [
            {"task_id": "task_a", "workflow_name": "exploration_planning"},
            {"task_id": "task_b", "workflow_name": "exploration_planning", "depends_on": ["task_a"]},
        ]
    )
    bundle = execute_subtask_dag(
        {
            "trace_id": "trace_timeout",
            "session_id": "session_timeout",
            "turn_id": "turn_timeout",
            "orchestrator_subtask_timeout_ms": 50,
        },
        OrchestrationDecision(
            orchestration_pattern="complex_orchestrator_workflow",
            workflow_name="complex_orchestrator_workflow",
            workflow_reason="complex orchestrator workflow",
            task_complexity="super_complex",
            requires_tool=True,
            requires_clarification=False,
            response_mode="exploration_plan",
            confidence=0.9,
            missing_fields=[],
            next_action="run_workflow",
        ),
        dag,
        registry_lookup=lambda workflow_name: workflow_registry_module.WORKFLOW_REGISTRY.lookup(workflow_name),
    )

    assert seen == ["task_a"]
    assert bundle.worker_results[0].timed_out is True
    assert bundle.worker_results[0].status == "timed_out"
    assert bundle.worker_results[1].skipped is True
    assert bundle.worker_results[1].status == "skipped_dependency_failed"


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
