from __future__ import annotations

from local_life_agent.planning.orchestrator import WorkerResult


def test_worker_result_from_patch_copies_state_deeply():
    patch = {"nested": {"value": 1}}
    worker = WorkerResult.from_patch(task_id="task_a", workflow_name="direct_response", patch=patch)

    worker.state_patch["nested"]["value"] = 2

    assert patch["nested"]["value"] == 1
    assert worker.clone_state_patch()["nested"]["value"] == 2
