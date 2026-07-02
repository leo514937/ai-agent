from __future__ import annotations

from local_life_agent.domain.graph_state import GraphState
from local_life_agent.domain.schemas import AnswerPlan, DecisionPlan, EvidencePack, ExplorationPlan, OrchestrationDecision
from local_life_agent.engine._routes import _route_workflow_runner
from local_life_agent.engine.subgraphs import execution_review_subgraph as execution_review_subgraph_module
from local_life_agent.engine.workflow_registry import LEGAL_WORKFLOW_NAMES, WORKFLOW_REGISTRY
from local_life_agent.engine.graph_builder import _WORKFLOW_RUNNER_ROUTES
from local_life_agent.engine.workflows.exploration_planning_workflow import run_exploration_planning_workflow


_FORBIDDEN_MULTI_OWNER_FIELDS = {
    "workflow_names",
    "final_responses",
    "state_update_plans",
    "evidence_packs",
    "decision_plans",
    "answer_plans",
}


def test_graph_state_and_schemas_remain_single_owner():
    graph_state_fields = set(GraphState.__annotations__)
    assert not (graph_state_fields & _FORBIDDEN_MULTI_OWNER_FIELDS)
    assert {"workflow_name", "final_response", "state_update_plan", "evidence_pack", "answer_plan"}.issubset(graph_state_fields)

    schema_field_sets = [
        set(OrchestrationDecision.model_fields),
        set(EvidencePack.model_fields),
        set(AnswerPlan.model_fields),
        set(DecisionPlan.model_fields),
        set(ExplorationPlan.model_fields),
    ]
    for field_set in schema_field_sets:
        assert not (field_set & _FORBIDDEN_MULTI_OWNER_FIELDS)


def test_workflow_registry_and_runner_stay_single_dispatch():
    assert set(WORKFLOW_REGISTRY.names()) == set(LEGAL_WORKFLOW_NAMES)
    assert all(isinstance(destination, str) for destination in _WORKFLOW_RUNNER_ROUTES.values())
    assert _route_workflow_runner({"workflow_name": "exploration_planning"}) == "response_subgraph"

    registration = WORKFLOW_REGISTRY.lookup("exploration_planning")
    assert registration.entry_node == "response_subgraph"


def test_exploration_planning_remains_separate_from_execution_review():
    source = run_exploration_planning_workflow.__code__.co_names
    assert "execution_review_subgraph" not in source


def test_execution_review_subgraph_uses_internal_batch_aggregation_terms():
    doc = execution_review_subgraph_module.__doc__ or ""
    assert "workflow-internal batch tool/evidence aggregation" in doc
    assert "workflow-level MapReduce" not in doc
