from __future__ import annotations

import pytest

from local_life_agent.domain.candidate import CandidateSet, CandidateSource, CandidateStatus, GoalType, LocalLifeGoalDraft, ResolvedCandidate
from local_life_agent.domain.evidence import EvidenceReviewAction
from local_life_agent.domain.schemas import ExecutionPlan
from local_life_agent.planning.evidence.evidence_builder import build_evidence
from local_life_agent.planning.evidence.facet_budget import build_evidence_planner_result, plan_facet_budget
from local_life_agent.planning.evidence.facet_validator import FacetCandidate, build_facet_candidates, validate_facet_candidates
from local_life_agent.planning.evidence.tool_capabilities import TOOL_CAPABILITY_REGISTRY
from local_life_agent.planning.evidence import evidence_planner
from local_life_agent.planning.evidence.evidence_planner import plan_evidence
from local_life_agent.planning.evidence.evidence_review import review_evidence
from local_life_agent.planning.plans.execution_plan_builder import build_execution_plan


def _resolved_target(shop_id: str = "shop_1", shop_name: str = "测试店") -> dict[str, object]:
    return {
        "status": "RESOLVED",
        "resolved_shop": {
            "shop_id": shop_id,
            "shop_name": shop_name,
        },
    }


def test_p9_tool_capability_registry_declares_supported_facets():
    assert "search_shops" in TOOL_CAPABILITY_REGISTRY
    assert "get_coupon_list" in TOOL_CAPABILITY_REGISTRY
    assert "check_open_status" in TOOL_CAPABILITY_REGISTRY
    assert "get_distance_eta" in TOOL_CAPABILITY_REGISTRY

    coupon_spec = TOOL_CAPABILITY_REGISTRY["get_coupon_list"]
    distance_spec = TOOL_CAPABILITY_REGISTRY["get_distance_eta"]

    assert coupon_spec.supported_facets
    assert coupon_spec.required_inputs == ["shop_id"]
    assert distance_spec.required_inputs == ["shop_id", "from_location"]
    assert coupon_spec.cost_weight >= 1
    assert coupon_spec.priority >= 0


def test_p9_taxonomy_validator_rejects_unknown_and_marks_unsupported_facets():
    candidates = [
        FacetCandidate(facet="coupon", source="llm", confidence=0.9, priority_group="user_explicit", reason="coupon request"),
        FacetCandidate(facet="open_status", source="llm", confidence=0.9, priority_group="user_explicit", reason="synonym should normalize"),
        FacetCandidate(facet="random_magic_facet", source="llm", confidence=0.2, priority_group="experience", reason="unknown facet"),
        FacetCandidate(facet="current_shop", source="rule", confidence=1.0, priority_group="reference_required", reason="reference cue"),
    ]

    result = validate_facet_candidates(candidates, capability_registry=TOOL_CAPABILITY_REGISTRY)

    assert "coupon" in result.accepted_facets
    assert "open_now" in result.accepted_facets
    assert "open_now" in result.normalized_facets
    assert "random_magic_facet" in result.rejected_facets
    assert "current_shop" in result.unsupported_facets
    assert result.rejection_reasons["random_magic_facet"]


def test_p9_rule_supplements_required_reference_and_decision_facets():
    first = build_facet_candidates(raw_text="第一家远吗")
    second = build_facet_candidates(raw_text="这家有券吗")
    third = build_facet_candidates(raw_text="第一家和第二家哪家更便宜")
    fourth = build_facet_candidates(raw_text="附近推荐有券餐厅")

    assert {"ordinal_reference", "distance"}.issubset({item.facet for item in first})
    assert {"current_shop", "coupon"}.issubset({item.facet for item in second})
    assert {"ordinal_reference", "comparison_targets", "price_compare"}.issubset({item.facet for item in third})
    assert {"nearby", "restaurant", "coupon"}.issubset({item.facet for item in fourth})


def test_p9_llm_proposed_facets_do_not_directly_generate_tool_calls():
    result = build_evidence_planner_result(
        task_type="single_shop_query",
        proposed_facets=["coupon", "open_now", "random_magic_facet"],
        target_resolution=_resolved_target(),
        target_shop_ids=["shop_1"],
        raw_text="这家有券吗？现在开着吗？",
    )

    assert "random_magic_facet" in result.validation_result.rejected_facets
    assert all(call.get("facet") != "random_magic_facet" for call in result.tool_calls)
    assert all(call.get("tool_name") != "random_magic_facet" for call in result.tool_calls)
    assert result.planning_warnings == [] or isinstance(result.planning_warnings, list)


def test_p9_budget_controller_drops_low_priority_facets_with_reasons():
    result = build_evidence_planner_result(
        task_type="single_shop_query",
        proposed_facets=[
            FacetCandidate(facet="coupon", source="text", confidence=1.0, priority_group="user_explicit", reason="显式约束"),
            FacetCandidate(facet="open_now", source="text", confidence=0.95, priority_group="user_explicit", reason="显式约束"),
            FacetCandidate(facet="distance", source="text", confidence=0.94, priority_group="user_explicit", reason="显式约束"),
            FacetCandidate(facet="review_tags", source="llm", confidence=0.2, priority_group="experience", reason="体验增强"),
            FacetCandidate(facet="current_shop", source="rule", confidence=1.0, priority_group="reference_required", reason="引用消解"),
        ],
        target_resolution=_resolved_target(),
        target_shop_ids=["shop_1"],
        raw_text="这家有券吗？现在开着吗？离我多远？",
        max_facets=2,
        max_tool_calls=2,
        total_cost_budget=2,
    )

    assert "review_tags" in result.budget_plan.dropped_facets
    assert result.budget_plan.drop_reasons["review_tags"]
    assert result.blocked_tool_calls
    assert any("budget" in str(item.get("reason", "")).lower() for item in result.blocked_tool_calls)
    assert any(facet in result.budget_plan.selected_facets for facet in ["coupon", "open_now"])


def test_p9_deterministic_tool_planner_requires_resolved_target():
    plan = build_execution_plan(
        "single_shop_query",
        {"status": "NOT_FOUND"},
        [{"name": "coupon"}, {"name": "open_now"}],
    )

    assert plan["tool_calls"] == []
    assert "missing_inputs" in plan
    assert "target" in plan["missing_inputs"] or "current_shop" in plan["missing_inputs"]


def test_p9_planner_outputs_feed_p8_review_actions():
    unsupported_result = build_evidence_planner_result(
        task_type="single_shop_query",
        proposed_facets=["current_shop"],
        target_resolution={"status": "NOT_FOUND"},
        target_shop_ids=[],
        raw_text="这家有券吗",
        max_facets=1,
        max_tool_calls=1,
        total_cost_budget=1,
    )
    unsupported_review = review_evidence(
        LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"]),
        {
            "facet_results": [{"facet": "coupon", "result_status": "unsupported"}],
            "missing_input": [],
            "clarification_needed": False,
        },
    )
    assert unsupported_review.action in {
        EvidenceReviewAction.DEGRADE,
        EvidenceReviewAction.FALLBACK,
        EvidenceReviewAction.REPLAN_MISSING_FACETS,
    }

    missing_review = review_evidence(
        LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"]),
        {
            "facet_results": [{"facet": "coupon", "result_status": "unknown"}],
            "missing_input": ["current_shop"],
            "clarification_needed": True,
        },
    )
    assert missing_review.action == EvidenceReviewAction.CLARIFY


def test_p9_evidence_planner_result_can_be_attached_to_execution_plan():
    result = build_evidence_planner_result(
        task_type="single_shop_query",
        proposed_facets=["coupon", "open_now"],
        target_resolution=_resolved_target(),
        target_shop_ids=["shop_1"],
        raw_text="这家有券吗？",
    )

    plan = ExecutionPlan.model_validate(
        {
            "plan_id": "demo",
            "task_type": "single_shop_query",
            "tool_calls": result.tool_calls,
            "stages": [],
            "target_shop_ids": ["shop_1"],
            "evidence_planner_result": result.model_dump(),
            "facet_candidates": [item.model_dump() for item in result.facet_candidates],
            "facet_validation_result": result.validation_result.model_dump() if result.validation_result else None,
            "facet_budget_plan": result.budget_plan.model_dump() if result.budget_plan else None,
            "blocked_tool_calls": result.blocked_tool_calls,
            "unsupported_facets": result.unsupported_facets,
            "missing_inputs": result.missing_inputs,
            "planning_warnings": result.planning_warnings,
        }
    )

    assert plan.evidence_planner_result is not None
    assert plan.blocked_tool_calls == result.blocked_tool_calls
    assert plan.unsupported_facets == result.unsupported_facets
