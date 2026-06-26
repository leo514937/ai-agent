"""Comparison planner for multi-shop comparison flows.

When a CandidateSet is available in the graph state, delegates to
``evidence_planner.plan_evidence()``.
"""

from __future__ import annotations

from typing import Any

from ..domain.candidate import CandidateSet, LocalLifeGoalDraft
from ..domain.schemas import ExecutionPlan
from .evidence_planner import plan_evidence


def plan_comparison_with_candidate_set(
    goal: LocalLifeGoalDraft,
    candidate_set: CandidateSet,
    location: dict[str, Any] | None = None,
) -> ExecutionPlan:
    """Shell that delegates to EvidencePlanner when a CandidateSet is available.

    This is the P1-compatible entry point called by the graph builder when
    a CandidateSet is present for comparison flows.
    """
    return plan_evidence(
        goal=goal,
        candidate_set=candidate_set,
        location=location,
    )
