"""Facet planner for the single-shop multi-facet flow.

P1: EvidencePlanner-compatible shell.
When a CandidateSet is available in the graph state, delegates to
``evidence_planner.plan_evidence()``. Otherwise falls back to the
legacy ``plan_facets()`` behaviour.
"""

from __future__ import annotations

from typing import Any

from ..domain.candidate import CandidateSet, LocalLifeGoalDraft
from ..domain.enums import Facet
from ..domain.schemas import ExecutionPlan
from .evidence_planner import plan_evidence


def _facet_name(item: Any) -> str:
    if isinstance(item, dict):
        raw = item.get("name") or item.get("facet") or item.get("facet_name") or ""
        if hasattr(raw, "value"):
            return str(raw.value)
        return str(raw)
    if hasattr(item, "name"):
        raw = getattr(item, "name")
        if hasattr(raw, "value"):
            return str(raw.value)
        return str(raw)
    if hasattr(item, "value"):
        return str(item.value)
    return str(item)


def _facet_required(item: Any) -> bool:
    if isinstance(item, dict):
        return bool(item.get("required", False))
    return bool(getattr(item, "required", False))


def plan_facets(task_type: str, semantic_frame: dict) -> list[dict[str, Any]]:
    """Decide which facets to query based on task type and user request."""
    facets = semantic_frame.get("facets") or []
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in facets:
        name = _facet_name(item).strip()
        if not name or name in seen:
            continue
        if name not in {facet.value for facet in Facet}:
            continue
        seen.add(name)
        ordered.append({"name": name, "required": _facet_required(item)})

    return ordered


def plan_facets_with_candidate_set(
    goal: LocalLifeGoalDraft,
    candidate_set: CandidateSet,
    semantic_frame: dict[str, Any] | None = None,
    comparison_targets: list[dict[str, Any]] | None = None,
    location: dict[str, Any] | None = None,
) -> ExecutionPlan:
    """Shell that delegates to EvidencePlanner when a CandidateSet is available.

    This is the P1-compatible entry point called by the graph builder when
    a CandidateSet is present. Falls back to legacy plan_facets logic when
    the CandidateSet is empty or goal is unsupported.
    """
    return plan_evidence(
        goal=goal,
        candidate_set=candidate_set,
        semantic_frame=semantic_frame,
        comparison_targets=comparison_targets,
        location=location,
    )
