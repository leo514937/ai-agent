from __future__ import annotations

from local_life_agent.planning.orchestrator import (
    DecisionReducer,
    EvidenceReducer,
    OrchestratorExecutionReport,
    SubTaskDAG,
    WorkerResult,
)


def test_subtask_dag_topological_sort_respects_dependencies():
    dag = SubTaskDAG.from_specs(
        [
            {"task_id": "task_a", "workflow_name": "direct_response"},
            {"task_id": "task_b", "workflow_name": "exploration_planning", "depends_on": ["task_a"]},
            {"task_id": "task_c", "workflow_name": "clarification_fallback", "depends_on": ["task_b"]},
        ]
    )

    assert [node.task_id for node in dag.topological_sort()] == ["task_a", "task_b", "task_c"]


def test_subtask_dag_topological_levels_group_same_depth_nodes():
    dag = SubTaskDAG.from_specs(
        [
            {"task_id": "task_a", "workflow_name": "direct_response"},
            {"task_id": "task_b", "workflow_name": "exploration_planning"},
            {"task_id": "task_c", "workflow_name": "clarification_fallback", "depends_on": ["task_a", "task_b"]},
            {"task_id": "task_d", "workflow_name": "comparison_decision_workflow", "depends_on": ["task_b"]},
        ]
    )

    assert [[node.task_id for node in level] for level in dag.topological_levels()] == [
        ["task_a", "task_b"],
        ["task_c", "task_d"],
    ]


def test_worker_result_round_trip_keeps_runtime_fields():
    worker = WorkerResult.from_patch(
        task_id="task_a",
        workflow_name="direct_response",
        patch={
            "workflow_run_status": "completed",
            "duration_ms": 88,
            "timed_out": False,
            "skipped": False,
            "blocked_by": ["task_b"],
            "cache_hit": True,
            "error_code": "",
            "deadline_ms": 250,
        },
    )

    cloned = WorkerResult.from_dict(worker.to_dict())

    assert cloned.duration_ms == 88
    assert cloned.timed_out is False
    assert cloned.skipped is False
    assert cloned.blocked_by == ["task_b"]
    assert cloned.cache_hit is True
    assert cloned.deadline_ms == 250


def test_execution_report_tracks_worker_runtime_snapshot():
    worker = WorkerResult.from_patch(
        task_id="task_a",
        workflow_name="exploration_planning",
        patch={"workflow_run_status": "completed", "cache_hit": True},
        provenance={"depends_on": []},
        trace_summary={"started_at": "2026-07-07T00:00:00Z", "finished_at": "2026-07-07T00:00:01Z"},
    )
    report = OrchestratorExecutionReport.from_worker_result(
        worker,
        duration_ms=123,
        cache_hit=True,
    )

    assert report.task_id == "task_a"
    assert report.workflow_name == "exploration_planning"
    assert report.duration_ms == 123
    assert report.cache_hit is True
    assert report.started_at == "2026-07-07T00:00:00Z"
    assert report.finished_at == "2026-07-07T00:00:01Z"


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
