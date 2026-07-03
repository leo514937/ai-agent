from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from ... import config
from ...domain.candidate import CandidateSet
from ...domain.schemas import ExecutionPlan, ToolCallSpec
from .facet_validator import FacetCandidate, FacetValidationResult, build_facet_candidates, validate_facet_candidates
from .tool_capabilities import (
    TOOL_CAPABILITY_REGISTRY,
    build_tool_call_dict,
    get_tool_capability,
    preferred_tool_for_facet,
    required_inputs_for_tool,
    tool_cost_weight,
)


class FacetBudgetPlan(BaseModel):
    max_facets: int = 8
    max_tool_calls: int = 6
    total_cost_budget: int = 10
    enrichment_top_k: int = 0
    selected_facets: list[str] = Field(default_factory=list)
    dropped_facets: list[str] = Field(default_factory=list)
    drop_reasons: dict[str, str] = Field(default_factory=dict)
    selected_tool_calls: list[dict] = Field(default_factory=list)
    blocked_tool_calls: list[dict] = Field(default_factory=list)


class EvidencePlannerResult(BaseModel):
    facet_candidates: list[FacetCandidate] = Field(default_factory=list)
    validation_result: FacetValidationResult | None = None
    budget_plan: FacetBudgetPlan | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    blocked_tool_calls: list[dict] = Field(default_factory=list)
    unsupported_facets: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    planning_warnings: list[str] = Field(default_factory=list)
    evidence_top_k: int = config.RECOMMENDATION_CANDIDATE_TOP_K
    budget_context_snapshot: dict[str, Any] | None = None


def _priority_rank(group: str | None) -> int:
    return {
        "user_explicit": 1,
        "reference_required": 2,
        "decision_required": 3,
        "safety_required": 4,
        "experience": 5,
        None: 6,
        "": 6,
    }.get(group or "", 6)


def _facet_cost(candidate: FacetCandidate, tool_name: str | None) -> int:
    if not tool_name:
        return 1
    return max(1, tool_cost_weight(tool_name))


def plan_facet_budget(
    candidates: list[FacetCandidate] | list[Any],
    validation_result: FacetValidationResult,
    *,
    capability_registry: dict[str, Any] | None = None,
    max_facets: int = 8,
    max_tool_calls: int = 6,
    total_cost_budget: int = 10,
) -> FacetBudgetPlan:
    registry = capability_registry or TOOL_CAPABILITY_REGISTRY
    candidate_map: dict[str, FacetCandidate] = {}
    for item in candidates or []:
        candidate = item if isinstance(item, FacetCandidate) else FacetCandidate.model_validate(item)
        facet = str(candidate.facet or "").strip()
        if not facet:
            continue
        candidate_map.setdefault(facet, candidate)

    ordered_candidates = sorted(
        candidate_map.values(),
        key=lambda item: (
            _priority_rank(item.priority_group),
            -(float(item.confidence or 0.0)),
            _facet_cost(item, preferred_tool_for_facet(item.facet) or ""),
            item.facet,
        ),
    )

    plan = FacetBudgetPlan(
        max_facets=max_facets,
        max_tool_calls=max_tool_calls,
        total_cost_budget=total_cost_budget,
        enrichment_top_k=min(max_facets, max_tool_calls, total_cost_budget),
    )
    accepted = set(validation_result.accepted_facets or [])
    unsupported = set(validation_result.unsupported_facets or [])
    rejected = set(validation_result.rejected_facets or [])
    cost_used = 0

    for candidate in ordered_candidates:
        facet = candidate.facet
        if facet in rejected:
            plan.dropped_facets.append(facet)
            plan.drop_reasons[facet] = validation_result.rejection_reasons.get(facet, "rejected")
            plan.blocked_tool_calls.append(
                {"facet": facet, "reason": plan.drop_reasons[facet], "source": candidate.source, "priority_group": candidate.priority_group}
            )
            continue
        if facet in unsupported:
            plan.dropped_facets.append(facet)
            plan.drop_reasons[facet] = validation_result.rejection_reasons.get(facet, "unsupported_facet")
            plan.blocked_tool_calls.append(
                {"facet": facet, "reason": plan.drop_reasons[facet], "source": candidate.source, "priority_group": candidate.priority_group}
            )
            continue
        if facet not in accepted:
            continue
        if len(plan.selected_facets) >= max_facets:
            plan.dropped_facets.append(facet)
            plan.drop_reasons[facet] = "budget_exceeded:max_facets"
            plan.blocked_tool_calls.append({"facet": facet, "reason": plan.drop_reasons[facet], "source": candidate.source})
            continue
        tool_name = preferred_tool_for_facet(facet)
        if not tool_name and facet in registry:
            tool_name = facet
        cost = _facet_cost(candidate, tool_name)
        if cost_used + cost > total_cost_budget:
            plan.dropped_facets.append(facet)
            plan.drop_reasons[facet] = "budget_exceeded:total_cost_budget"
            plan.blocked_tool_calls.append({"facet": facet, "reason": plan.drop_reasons[facet], "source": candidate.source, "cost_weight": cost})
            continue
        plan.selected_facets.append(facet)
        cost_used += cost

    if len(plan.selected_facets) > max_tool_calls:
        overflow = plan.selected_facets[max_tool_calls:]
        plan.selected_facets = plan.selected_facets[:max_tool_calls]
        for facet in overflow:
            plan.dropped_facets.append(facet)
            plan.drop_reasons.setdefault(facet, "budget_exceeded:max_tool_calls")
            plan.blocked_tool_calls.append({"facet": facet, "reason": plan.drop_reasons[facet]})

    if plan.dropped_facets:
        plan.drop_reasons = dict(plan.drop_reasons)

    return plan


def _build_tool_call_items(
    *,
    task_type: str,
    selected_facets: list[str],
    candidate_map: dict[str, FacetCandidate],
    target_shop_ids: list[str] | None,
    target_resolution: dict[str, Any] | None,
    location: dict[str, Any] | None,
    query: str,
    tool_call_builder: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    builder = tool_call_builder or build_tool_call_dict
    target_shop_ids = [str(item).strip() for item in (target_shop_ids or []) if str(item).strip()]
    target_resolution = target_resolution or {}
    location = location or {}
    missing_inputs: list[str] = []
    planning_warnings: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    blocked_tool_calls: list[dict[str, Any]] = []

    resolved_shop = target_resolution.get("resolved_shop") or target_resolution.get("target_shop") or target_resolution.get("shop") or {}
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()
    resolved_shop_id = str((resolved_shop or {}).get("shop_id", "") or "").strip()
    if not target_shop_ids and resolved_shop_id:
        target_shop_ids = [resolved_shop_id]

    has_target = bool(target_shop_ids)
    if task_type in {"single_shop_query", "comparison"} and not has_target:
        missing_inputs.extend([item for item in ("target", "current_shop") if item not in missing_inputs])
        planning_warnings.append("missing_required_target")
        blocked_tool_calls.append({"facet": "target", "reason": "missing_required_input", "missing_inputs": ["target", "current_shop"]})
        return [], blocked_tool_calls, missing_inputs, planning_warnings

    call_index = 0
    for facet in selected_facets:
        candidate = candidate_map.get(facet, FacetCandidate(facet=facet))
        tool_name = preferred_tool_for_facet(facet, task_type=task_type, has_target=has_target)
        if not tool_name:
            blocked_tool_calls.append({"facet": facet, "reason": "unsupported_facet", "source": candidate.source})
            continue
        capability = get_tool_capability(tool_name)
        required_inputs = required_inputs_for_tool(tool_name)
        if tool_name == "search_shops":
            call_index += 1
            call_id = f"call_{facet}_{call_index}"
            call = builder(
                tool_name,
                facet,
                call_id=call_id,
                target_shop_id="",
                required=True,
                location=location,
                query=query or facet,
                group_id="facet_budget",
            )
            call["priority"] = _priority_rank(candidate.priority_group)
            tool_calls.append(call)
            continue

        # Shop-scoped tools.
        if not target_shop_ids:
            blocked_tool_calls.append({"facet": facet, "reason": "missing_required_input", "missing_inputs": required_inputs or ["target"]})
            missing_inputs.extend([item for item in required_inputs if item not in missing_inputs])
            continue

        if "from_location" in required_inputs and not location:
            blocked_tool_calls.append({"facet": facet, "reason": "missing_required_input", "missing_inputs": ["from_location"]})
            if "from_location" not in missing_inputs:
                missing_inputs.append("from_location")
            continue

        if "shop_ids" in required_inputs and len(target_shop_ids) > 1 and tool_name in {"get_shop_review_summary", "get_shop_cards"}:
            call_index += 1
            call_id = f"call_{facet}_{call_index}"
            call = builder(
                tool_name,
                facet,
                call_id=call_id,
                target_shop_id=target_shop_ids[0],
                required=True,
                location=location,
                shop_ids=target_shop_ids,
                group_id="facet_budget",
            )
            call["priority"] = _priority_rank(candidate.priority_group)
            tool_calls.append(call)
            continue

        for target_shop_id in target_shop_ids:
            call_index += 1
            call_id = f"call_{facet}_{call_index}"
            call = builder(
                tool_name,
                facet,
                call_id=call_id,
                target_shop_id=target_shop_id,
                required=True,
                location=location,
                group_id="facet_budget",
            )
            call["priority"] = _priority_rank(candidate.priority_group)
            tool_calls.append(call)

    return tool_calls, blocked_tool_calls, missing_inputs, planning_warnings


def build_evidence_planner_result(
    *,
    task_type: str,
    proposed_facets: list[Any] | None = None,
    semantic_frame: dict[str, Any] | Any | None = None,
    session_state: dict[str, Any] | Any | None = None,
    raw_text: str = "",
    target_shop_ids: list[str] | None = None,
    target_resolution: dict[str, Any] | None = None,
    location: dict[str, Any] | None = None,
    max_facets: int = 8,
    max_tool_calls: int = 6,
    total_cost_budget: int = 10,
    tool_call_builder: Callable[..., Any] | None = None,
) -> EvidencePlannerResult:
    facet_candidates = build_facet_candidates(
        proposed_facets,
        semantic_frame=semantic_frame,
        session_state=session_state,
        raw_text=raw_text,
    )
    validation_result = validate_facet_candidates(facet_candidates, capability_registry=TOOL_CAPABILITY_REGISTRY)
    budget_plan = plan_facet_budget(
        facet_candidates,
        validation_result,
        capability_registry=TOOL_CAPABILITY_REGISTRY,
        max_facets=max_facets,
        max_tool_calls=max_tool_calls,
        total_cost_budget=total_cost_budget,
    )

    candidate_map = {candidate.facet: candidate for candidate in facet_candidates}
    tool_calls, blocked_tool_calls, missing_inputs, planning_warnings = _build_tool_call_items(
        task_type=task_type,
        selected_facets=budget_plan.selected_facets,
        candidate_map=candidate_map,
        target_shop_ids=target_shop_ids,
        target_resolution=target_resolution,
        location=location,
        query=raw_text,
        tool_call_builder=tool_call_builder,
    )

    # Apply a final tool-call budget trim.
    selected_tool_calls = list(tool_calls)
    if len(selected_tool_calls) > max_tool_calls:
        overflow = selected_tool_calls[max_tool_calls:]
        selected_tool_calls = selected_tool_calls[:max_tool_calls]
        for call in overflow:
            blocked_tool_calls.append({**call, "reason": "budget_exceeded:max_tool_calls"})
            planning_warnings.append("tool_call_budget_trimmed")

    total_cost = 0
    trimmed_tool_calls: list[dict[str, Any]] = []
    for call in selected_tool_calls:
        tool_name = str(call.get("tool_name", "") or "")
        cost = max(1, tool_cost_weight(tool_name))
        if total_cost + cost > total_cost_budget:
            blocked_tool_calls.append({**call, "reason": "budget_exceeded:total_cost_budget"})
            planning_warnings.append("tool_call_budget_trimmed")
            continue
        total_cost += cost
        trimmed_tool_calls.append(call)

    selected_tool_calls = trimmed_tool_calls
    selected_facets = list(dict.fromkeys([str(call.get("facet", "")).strip() for call in selected_tool_calls if str(call.get("facet", "")).strip()]))
    unsupported_facets = list(dict.fromkeys(validation_result.unsupported_facets))
    missing_inputs = list(dict.fromkeys(missing_inputs))
    planning_warnings.extend([f"{facet}:{reason}" for facet, reason in budget_plan.drop_reasons.items()])
    planning_warnings = list(dict.fromkeys([item for item in planning_warnings if item]))

    budget_plan.selected_facets = selected_facets or list(budget_plan.selected_facets)
    budget_plan.selected_tool_calls = list(selected_tool_calls)
    budget_plan.blocked_tool_calls.extend(blocked_tool_calls)

    return EvidencePlannerResult(
        facet_candidates=facet_candidates,
        validation_result=validation_result,
        budget_plan=budget_plan,
        tool_calls=selected_tool_calls,
        blocked_tool_calls=list(budget_plan.blocked_tool_calls),
        unsupported_facets=unsupported_facets,
        missing_inputs=missing_inputs,
        planning_warnings=planning_warnings,
    )


def plan_evidence_result_from_candidate_set(
    *,
    goal: Any,
    candidate_set: CandidateSet,
    location: dict[str, Any] | None = None,
) -> EvidencePlannerResult:
    proposed_facets = list(getattr(goal, "required_facets", []) or []) + list(getattr(goal, "optional_facets", []) or [])
    return build_evidence_planner_result(
        task_type=str(getattr(getattr(goal, "goal_type", ""), "value", getattr(goal, "goal_type", "")) or ""),
        proposed_facets=proposed_facets,
        target_shop_ids=[str(item.shop_id).strip() for item in (candidate_set.candidates or []) if str(getattr(item, "shop_id", "") or "").strip()],
        location=location,
        raw_text="",
        max_facets=8,
        max_tool_calls=6,
        total_cost_budget=10,
    )


def evidence_planner_result_to_execution_plan(result: EvidencePlannerResult, *, plan_id: str, task_type: str) -> ExecutionPlan:
    return ExecutionPlan.model_validate(
        {
            "plan_id": plan_id,
            "task_type": task_type,
            "tool_calls": result.tool_calls,
            "stages": [
                {
                    "stage_id": "stage_1",
                    "description": "Generated by evidence planner capability budget",
                    "tool_names": [str(call.get("tool_name", "") or "") for call in result.tool_calls],
                    "depends_on": [],
                    "max_parallelism": max(1, min(len(result.tool_calls), config.MAX_CONCURRENCY)),
                }
            ] if result.tool_calls else [],
            "facet_candidates": [item.model_dump() for item in result.facet_candidates],
            "facet_validation_result": result.validation_result.model_dump() if result.validation_result else None,
            "facet_budget_plan": result.budget_plan.model_dump() if result.budget_plan else None,
            "blocked_tool_calls": result.blocked_tool_calls,
            "unsupported_facets": result.unsupported_facets,
            "missing_inputs": result.missing_inputs,
            "planning_warnings": result.planning_warnings,
            "evidence_planner_result": result.model_dump(),
        }
    )
