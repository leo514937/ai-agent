"""Independent workflow entry for comparison decisions.

This workflow only emits the dispatch patch. The actual planning work
still runs once in the shared planning subgraph through the normal graph
edge, but comparison turns now have a dedicated registry entry and trace
identity separate from the legacy discovery_decision alias.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...domain.graph_state import GraphState
from ...domain.schemas import OrchestrationDecision


def _coerce_decision(state: GraphState, decision: OrchestrationDecision | None) -> OrchestrationDecision:
    if isinstance(decision, OrchestrationDecision):
        return decision
    raw = state.get("orchestration_decision")
    if isinstance(raw, OrchestrationDecision):
        return raw
    return OrchestrationDecision.model_validate(
        {
            "orchestration_pattern": "discovery_decision",
            "workflow_name": "discovery_decision",
            "workflow_entry_name": "comparison_decision_workflow",
            "workflow_reason": str(state.get("workflow_reason", "") or "comparison decision workflow"),
            "task_complexity": "medium",
            "requires_tool": True,
            "requires_clarification": False,
            "response_mode": "comparison",
            "confidence": float(state.get("confidence", 0.0) or 0.0),
            "missing_fields": [],
            "next_action": "run_workflow",
        }
    )


def run_comparison_decision_workflow(
    state: GraphState,
    decision: OrchestrationDecision | None = None,
) -> dict[str, Any]:
    """Emit a dispatch patch for the comparison planning path."""

    normalized_decision = _coerce_decision(state, decision)
    timestamp = datetime.now(timezone.utc).isoformat()
    response_mode = str(normalized_decision.response_mode or "comparison")
    next_action = str(normalized_decision.next_action or "run_workflow")
    workflow_reason = str(normalized_decision.workflow_reason or "comparison decision workflow")
    return {
        "workflow_name": "comparison_decision_workflow",
        "workflow_entry_name": "comparison_decision_workflow",
        "workflow_callable": "run_comparison_decision_workflow",
        "workflow_run_status": "dispatched",
        "workflow_registered": True,
        "workflow_runner_reason": workflow_reason,
        "workflow_candidate_reason": workflow_reason,
        "workflow_started_at": timestamp,
        "workflow_finished_at": timestamp,
        "orchestration_pattern": str(normalized_decision.orchestration_pattern or "discovery_decision"),
        "response_mode": response_mode,
        "next_action": next_action,
    }
