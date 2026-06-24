"""Unified EvidencePlanner — generates ToolPlan from CandidateSet + required/optional facets.

P1 responsibility:
  - For each candidate shop, emit tool calls for required + optional facets
  - Distinguish required/optional at the tool call level
  - Avoid duplicate tool calls (same shop_id + same facet)
  - Respect max_candidates budget
  - Does NOT judge evidence sufficiency (that is EvidenceReview's job)
  - Does NOT execute tools, does NOT bypass ToolCallGateway

Legacy facet_planner.py and comparison_planner.py are kept as thin shells
that delegate here when a CandidateSet is present.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import config
from ..config import TOOL_DEFAULT_TIMEOUT_MS
from ..domain.candidate import CandidateSet, GoalType, LocalLifeGoalDraft
from ..domain.enums import Facet
from ..domain.schemas import ExecutionPlan, ToolCallSpec

_logger = logging.getLogger(__name__)

# Map facet names to tool names
_FACET_TO_TOOL: dict[str, str] = {
    "coupon": "get_coupon_list",
    "open_status": "check_open_status",
    "distance": "get_distance_eta",
    "detail": "get_shop_detail",
    "deal": "get_deal_list",
    "review_summary": "get_shop_review_summary",
    "environment": "get_shop_cards",
    "shop_cards": "get_shop_cards",
    "price": "get_shop_detail",
    "rating": "get_shop_detail",
    "taste": "get_shop_review_summary",
    "service": "get_shop_review_summary",
    "scene_fit": "get_shop_review_summary",
}

# Facets that map to detail tool (single call covers multiple facets)
_DETAIL_FACETS = frozenset({"detail", "price", "rating"})


def _dedup_key(shop_id: str, facet: str) -> str:
    return f"{shop_id}:{facet}"


def _facet_to_tool(facet: str) -> str:
    return _FACET_TOOL.get(facet, "get_shop_detail")


def _build_tool_call(
    shop_id: str,
    shop_name: str,
    facet: str,
    required: bool,
    index: int,
    location: dict[str, Any] | None = None,
) -> ToolCallSpec:
    """Build a single ToolCallSpec for a shop facet."""
    tool_name = _facet_to_tool(facet)
    args: dict[str, Any] = {"shop_id": shop_id}
    if tool_name == "get_distance_eta":
        args["from_location"] = location or config.MOCK_LOCATION
    if tool_name == "get_shop_cards":
        args = {"shop_ids": [shop_id], "need_coupon_brief": True, "need_open_status": True, "need_distance_eta": True}
    return ToolCallSpec(
        call_id=f"call_{facet}_{index}",
        tool_name=tool_name,
        args=args,
        target_shop_id=shop_id,
        required=required,
        facet=facet,
        timeout_ms=TOOL_DEFAULT_TIMEOUT_MS,
        retry_policy={"max_attempts": 3 if required else 0, "backoff_ms": 200},
        max_parallelism=config.MAX_CONCURRENCY,
    )


def plan_evidence(
    goal: LocalLifeGoalDraft,
    candidate_set: CandidateSet,
    semantic_frame: dict[str, Any] | None = None,
    comparison_targets: list[dict[str, Any]] | None = None,
    location: dict[str, Any] | None = None,
) -> ExecutionPlan:
    """Generate a unified ExecutionPlan from CandidateSet + evidence needs.

    Args:
        goal: The local life goal draft (carries required_facets, optional_facets).
        candidate_set: The resolved candidate set.
        semantic_frame: Optional semantic frame for additional context.
        comparison_targets: Optional list of comparison targets (for comparison flows).
        location: User location for distance queries.

    Returns:
        An ExecutionPlan with tool calls for each candidate shop.
    """
    required_facets = list(goal.required_facets or [])
    optional_facets = list(goal.optional_facets or [])
    all_facets = required_facets + [f for f in optional_facets if f not in required_facets]

    # Determine which shops to plan for
    candidates = list(candidate_set.candidates or [])
    shop_ids_from_comparison: set[str] = set()

    if comparison_targets:
        for item in comparison_targets:
            sid = str(item.get("shop_id", "") or "").strip()
            if sid:
                shop_ids_from_comparison.add(sid)

    # Deduplicate by shop_id + facet
    seen: set[str] = set()
    tool_calls: list[ToolCallSpec] = []
    index = 0

    # First: process candidate shops from CandidateSet
    for candidate in candidates:
        shop_id = str(candidate.shop_id or "").strip()
        shop_name = str(candidate.shop_name or "").strip()
        if not shop_id:
            continue

        for facet in all_facets:
            dk = _dedup_key(shop_id, facet)
            if dk in seen:
                continue
            seen.add(dk)
            index += 1
            required = facet in required_facets
            tool_calls.append(
                _build_tool_call(shop_id, shop_name, facet, required, index, location)
            )

    # Second: process additional comparison targets not covered by CandidateSet
    if comparison_targets:
        for item in comparison_targets:
            sid = str(item.get("shop_id", "") or "").strip()
            sname = str(item.get("shop_name", "") or "").strip()
            if not sid or sid in {c.shop_id for c in candidates}:
                continue
            for facet in all_facets:
                dk = _dedup_key(sid, facet)
                if dk in seen:
                    continue
                seen.add(dk)
                index += 1
                required = facet in required_facets
                tool_calls.append(
                    _build_tool_call(sid, sname, facet, required, index, location)
                )

    task_type = _goal_type_to_task_type(goal.goal_type)

    plan = ExecutionPlan(
        plan_id=f"evidence_plan_{candidate_set.source.value}_{task_type}",
        task_type=task_type,
        tool_calls=tool_calls,
        target_shop_ids=list({c.shop_id for c in candidates if c.shop_id} | shop_ids_from_comparison),
    )

    _logger.debug(
        "EvidencePlanner: plan_id=%s tool_calls=%d required=%s optional=%s",
        plan.plan_id,
        len(tool_calls),
        required_facets,
        optional_facets,
    )
    return plan


def _goal_type_to_task_type(goal_type: GoalType) -> str:
    mapping = {
        GoalType.RECOMMENDATION: "recommendation",
        GoalType.COMPARISON: "comparison",
        GoalType.SINGLE_SHOP_QUERY: "single_shop_query",
        GoalType.REFINEMENT: "recommendation",
        GoalType.UNSUPPORTED: "unknown",
    }
    return mapping.get(goal_type, "unknown")


# Map facet names to tool names (expanded)
_FACET_TOOL: dict[str, str] = {
    "coupon": "get_coupon_list",
    "open_status": "check_open_status",
    "distance": "get_distance_eta",
    "detail": "get_shop_detail",
    "deal": "get_deal_list",
    "review_summary": "get_shop_review_summary",
    "environment": "get_shop_cards",
    "shop_cards": "get_shop_cards",
    "price": "get_shop_detail",
    "rating": "get_shop_detail",
    "taste": "get_shop_review_summary",
    "service": "get_shop_review_summary",
    "scene_fit": "get_shop_review_summary",
}
