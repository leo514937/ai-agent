from __future__ import annotations

from local_life_agent.planning.orchestrator import DecisionReducer, EvidenceReducer, SubTaskDAG, WorkerResult


def test_subtask_dag_topological_sort_respects_dependencies():
    dag = SubTaskDAG.from_specs(
        [
            {"task_id": "task_a", "workflow_name": "direct_response"},
            {"task_id": "task_b", "workflow_name": "exploration_planning", "depends_on": ["task_a"]},
            {"task_id": "task_c", "workflow_name": "clarification_fallback", "depends_on": ["task_b"]},
        ]
    )

    assert [node.task_id for node in dag.topological_sort()] == ["task_a", "task_b", "task_c"]


def test_evidence_reducer_merges_tool_results_and_preserves_provenance():
    worker_results = [
        WorkerResult.from_patch(
            task_id="task_a",
            workflow_name="direct_response",
            patch={
                "evidence_pack": {"tool_results": {"call_1": {"tool_name": "search_shops"}}, "answerable_facets": ["distance"]},
                "response_directive": {"answer_source": "worker_a"},
            },
            provenance={"source": "worker_a"},
        ),
        WorkerResult.from_patch(
            task_id="task_b",
            workflow_name="exploration_planning",
            patch={
                "evidence_pack": {"tool_results": {"call_2": {"tool_name": "get_shop_detail"}}, "unknown_facets": ["coupon"]},
                "response_directive": {"answer_source": "worker_b"},
            },
            provenance={"source": "worker_b"},
        ),
    ]

    merged = EvidenceReducer.reduce(worker_results)

    assert set(merged["tool_results"].keys()) == {"call_1", "call_2"}
    assert merged["answerable_facets"] == ["distance"]
    assert merged["unknown_facets"] == ["coupon"]
    assert merged["provenance"][0]["task_id"] == "task_a"
    assert merged["provenance"][1]["task_id"] == "task_b"


def test_decision_reducer_prefers_consensus_winner():
    worker_results = [
        WorkerResult.from_patch(
            task_id="task_a",
            workflow_name="comparison_decision_workflow",
            patch={
                "decision_plan": {
                    "answer_type": "comparison",
                    "winner_shop_id": "shop_1",
                    "winner_shop_name": "A 店",
                    "overall_ranking": [{"shop_id": "shop_1", "rank": 1}],
                    "claims": [{"evidence_id": "e1"}],
                }
            },
        ),
        WorkerResult.from_patch(
            task_id="task_b",
            workflow_name="comparison_decision_workflow",
            patch={
                "decision_plan": {
                    "answer_type": "comparison",
                    "winner_shop_id": "shop_1",
                    "winner_shop_name": "A 店",
                    "overall_ranking": [{"shop_id": "shop_2", "rank": 2}],
                    "claims": [{"evidence_id": "e2"}],
                }
            },
        ),
    ]

    merged = DecisionReducer.reduce(worker_results)

    assert merged["answer_type"] == "comparison"
    assert merged["winner_shop_id"] == "shop_1"
    assert merged["winner_shop_name"] == "A 店"
    assert merged["statistical_winner"]["winner_shop_id"] == "shop_1" or merged["statistical_winner"]["shop_id"] == "shop_1"
    assert len(merged["overall_ranking"]) == 2


def test_decision_reducer_flags_conflicting_winners():
    worker_results = [
        WorkerResult.from_patch(
            task_id="task_a",
            workflow_name="comparison_decision_workflow",
            patch={"decision_plan": {"answer_type": "comparison", "winner_shop_id": "shop_1", "winner_shop_name": "A 店"}},
        ),
        WorkerResult.from_patch(
            task_id="task_b",
            workflow_name="comparison_decision_workflow",
            patch={"decision_plan": {"answer_type": "comparison", "winner_shop_id": "shop_2", "winner_shop_name": "B 店"}},
        ),
    ]

    merged = DecisionReducer.reduce(worker_results)

    assert merged["winner_shop_id"] == ""
    assert merged["statistical_winner"] is None
    assert merged["fallback_used"] is True
    assert merged["conflict_summary"]["has_conflict"] is True
