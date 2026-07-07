from __future__ import annotations

from local_life_agent.planning.orchestrator import ConflictResolver, WorkerResult


def test_conflict_resolver_detects_winner_and_answer_type_conflicts():
    report = ConflictResolver.resolve(
        [
            WorkerResult.from_patch(
                task_id="task_a",
                workflow_name="comparison_decision_workflow",
                patch={"decision_plan": {"answer_type": "comparison", "winner_shop_id": "shop_1"}},
            ),
            WorkerResult.from_patch(
                task_id="task_b",
                workflow_name="recommendation_decision_workflow",
                patch={"decision_plan": {"answer_type": "recommendation", "winner_shop_id": "shop_2"}},
            ),
        ]
    )

    assert report.has_conflict is True
    assert "winner_conflict:shop_1,shop_2" in report.conflicts
    assert "answer_type_conflict:comparison,recommendation" in report.conflicts
    assert report.uncertainty_notices


def test_conflict_resolver_keeps_consensus_winner():
    report = ConflictResolver.resolve(
        [
            WorkerResult.from_patch(
                task_id="task_a",
                workflow_name="comparison_decision_workflow",
                patch={"decision_plan": {"answer_type": "comparison", "winner_shop_id": "shop_1"}},
            ),
            WorkerResult.from_patch(
                task_id="task_b",
                workflow_name="comparison_decision_workflow",
                patch={"decision_plan": {"answer_type": "comparison", "winner_shop_id": "shop_1"}},
            ),
        ]
    )

    assert report.has_conflict is False
    assert report.winner_shop_id == "shop_1"
    assert report.conflicts == []
