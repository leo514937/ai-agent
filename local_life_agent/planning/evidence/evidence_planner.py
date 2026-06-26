"""Unified EvidencePlanner — generates ExecutionPlan from CandidateSet + required/optional facets.

P1 responsibility:
  - For each candidate shop, emit tool calls for required + optional facets
  - Distinguish required/optional at the tool call level
  - Avoid duplicate tool calls (same shop_id + same facet)
  - Respect max_candidates budget
  - Does NOT judge evidence sufficiency (that is EvidenceReview's job)
  - Does NOT execute tools, does NOT bypass ToolCallGateway

"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ... import config
from ...config import TOOL_DEFAULT_TIMEOUT_MS
from ...domain.candidate import CandidateSet, GoalType, LocalLifeGoalDraft
from ...domain.enums import Facet
from ...domain.schemas import ExecutionPlan, ToolCallSpec
from ...tools.registry import get_registry
from ..llm_utils import invoke_structured_llm, model_validate_or_error

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
    args: dict[str, Any]
    if tool_name == "get_shop_review_summary":
        args = {"shop_ids": [shop_id]}
    else:
        args = {"shop_id": shop_id}
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
    if goal is None:
        raise ValueError("goal is required")
    if candidate_set is None:
        raise ValueError("candidate_set is required")

    required_facets = list(goal.required_facets or [])
    optional_facets = list(goal.optional_facets or [])
    if not required_facets and not optional_facets:
        goal_type = getattr(goal.goal_type, "value", goal.goal_type)
        if goal_type in {"recommendation", "comparison"}:
            required_facets = ["distance", "open_status", "coupon"]
            optional_facets = ["detail"]
        elif goal_type in {"single_shop_query", "refinement"}:
            required_facets = list(goal.evidence_needs or []) or ["detail"]
        else:
            raise ValueError("required_facets or optional_facets is required")
    all_facets = required_facets + [f for f in optional_facets if f not in required_facets]

    candidates = list(candidate_set.candidates or [])

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

    task_type = _goal_type_to_task_type(goal.goal_type)

    plan = ExecutionPlan(
        plan_id=f"evidence_plan_{candidate_set.source.value}_{task_type}",
        task_type=task_type,
        tool_calls=tool_calls,
        target_shop_ids=[c.shop_id for c in candidates if c.shop_id],
    )

    _logger.debug(
        "EvidencePlanner: plan_id=%s tool_calls=%d required=%s optional=%s",
        plan.plan_id,
        len(tool_calls),
        required_facets,
        optional_facets,
    )
    return plan


def plan_evidence_with_llm(
    goal: LocalLifeGoalDraft,
    candidate_set: CandidateSet,
    location: dict[str, Any] | None = None,
    *,
    semantic_frame: Any = None,
    raw_text: str = "",
    llm_call: Callable[..., dict[str, Any]] | None = None,
    strict: bool = False,
) -> tuple[ExecutionPlan | None, dict[str, Any]]:
    """Plan evidence/tool execution through an LLM."""
    registry = get_registry()
    allowed_tools = sorted(
        tool_name
        for tool_name in registry.list_tools()
        if tool_name != "resolve_shop"
    )
    replacements = {
        "{{TEXT}}": str(raw_text or ""),
        "{{GOAL_PLAN}}": goal.model_dump() if hasattr(goal, "model_dump") else dict(goal),
        "{{SEMANTIC_FRAME}}": semantic_frame.model_dump() if hasattr(semantic_frame, "model_dump") else (semantic_frame or {}),
        "{{CANDIDATE_SET}}": candidate_set.model_dump() if hasattr(candidate_set, "model_dump") else dict(candidate_set),
        "{{USER_LOCATION}}": location or config.MOCK_LOCATION,
        "{{ALLOWED_TOOLS}}": allowed_tools,
    }
    try:
        llm_result = invoke_structured_llm(
            prompt_name="evidence_planner",
            replacements=replacements,
            response_validator=ExecutionPlan.model_validate,
            llm_call=llm_call,
        )
    except Exception as exc:
        error = {"error_code": "EVIDENCE_PLANNER_PROMPT_ERROR", "error_message": str(exc), "llm_backend": "", "raw": ""}
        if strict:
            return None, error
        return plan_evidence(goal, candidate_set, location), error

    if not llm_result.get("ok"):
        error = {
            "error_code": llm_result.get("error_code") or "EVIDENCE_PLANNER_LLM_FAILED",
            "error_message": llm_result.get("error_message") or "evidence planner llm failed",
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        if strict:
            return None, error
        return plan_evidence(goal, candidate_set, location), error

    model, validation_error = model_validate_or_error(ExecutionPlan, llm_result.get("payload") or {})
    if model is None:
        error = {
            "error_code": "EXECUTION_PLAN_SCHEMA_INVALID",
            "error_message": validation_error,
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        if strict:
            return None, error
        return plan_evidence(goal, candidate_set, location), error

    plan = model
    if not plan.tool_calls and not plan.stages:
        error = {
            "error_code": "EXECUTION_PLAN_EMPTY",
            "error_message": "llm execution plan did not contain any tool calls or stages",
            "llm_backend": llm_result.get("llm_backend", ""),
            "raw": llm_result.get("raw", ""),
        }
        if strict:
            return None, error
        return plan_evidence(goal, candidate_set, location), error
    plan.plan_source = plan.plan_source or "llm_evidence_planner"
    return plan, {
        "error_code": "",
        "error_message": "",
        "llm_backend": llm_result.get("llm_backend", ""),
        "raw": llm_result.get("raw", ""),
    }


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
