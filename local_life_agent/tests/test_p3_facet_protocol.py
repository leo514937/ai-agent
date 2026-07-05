from __future__ import annotations

from local_life_agent.answer.answer_plan_builder import build_answer_plan
from local_life_agent.domain.facets import (
    LOCAL_LIFE_FACET_TAXONOMY,
    FacetSet,
    QueryFacet,
    TargetResolutionResult,
    build_target_resolution_result,
    normalize_query_facets,
)
from local_life_agent.domain.schemas import EvidencePack, SemanticFrame
from local_life_agent.engine.workflows.deterministic_tool_workflow import _resolve_single_shop_target
from local_life_agent.planning.decision.decision_planner import plan_decision
from local_life_agent.planning.evidence.evidence_builder import build_evidence
from local_life_agent.planning.goal.goal_planner import plan_goal
from local_life_agent.planning.orchestration_router import build_orchestration_decision
from local_life_agent.planning.plans.execution_plan_builder import build_recommendation_execution_plan


def _facet_names(facet_set: FacetSet) -> set[str]:
    return {facet.name for facet in facet_set.facets}


def _facet_groups(facet_set: FacetSet) -> set[str]:
    return {facet.group for facet in facet_set.facets if facet.group}


def test_local_life_facet_taxonomy_contains_required_groups():
    assert set(LOCAL_LIFE_FACET_TAXONOMY) == {"location", "category", "scene", "status", "deal", "price", "quality", "preference", "reference"}


def test_local_life_facet_taxonomy_contains_required_facets():
    required = {
        "location": {"nearby", "distance", "business_area", "travel_time"},
        "category": {"restaurant", "hotpot", "coffee", "dessert", "parent_child", "entertainment", "shopping"},
        "scene": {"date_scene", "family_with_kids", "friends_party", "quiet", "lively", "business_meeting", "work_study", "late_night"},
        "status": {"open_now", "open_late", "reservation_available", "queue_status"},
        "deal": {"coupon", "discount", "group_buy", "cost_performance"},
        "price": {"avg_price", "budget", "budget_around_x", "price_compare"},
        "quality": {"rating", "review_tags", "popularity", "service", "environment", "taste"},
        "preference": {"not_too_noisy", "kid_friendly", "parking", "private_room", "spicy", "light_food", "vegetarian"},
        "reference": {"current_shop", "ordinal_reference", "previous_recommendation", "comparison_targets"},
    }

    for group, facets in required.items():
        assert group in LOCAL_LIFE_FACET_TAXONOMY
        assert facets.issubset(set(LOCAL_LIFE_FACET_TAXONOMY[group]))

    frame = SemanticFrame.model_validate(
        {
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "confidence": 0.91,
            "facets": [
                {"name": "nearby", "group": "location"},
                {"name": "restaurant", "group": "category"},
                {"name": "date_scene", "group": "scene"},
                {"name": "open_now", "group": "status"},
                {"name": "coupon", "group": "deal"},
                {"name": "budget_around_x", "group": "price", "value": 100},
                {"name": "rating", "group": "quality"},
                {"name": "kid_friendly", "group": "preference"},
                {"name": "current_shop", "group": "reference"},
            ],
        }
    )

    facet_set = normalize_query_facets(frame, raw_text="附近推荐几家适合约会、现在营业、最好有券、人均100左右的餐厅")

    assert {
        "nearby",
        "restaurant",
        "date_scene",
        "open_now",
        "coupon",
        "budget_around_x",
        "rating",
        "kid_friendly",
        "current_shop",
    }.issubset(_facet_names(facet_set))
    assert {"location", "category", "scene", "status", "deal", "price", "quality", "preference", "reference"}.issubset(_facet_groups(facet_set))


def test_unknown_facet_does_not_become_route_task():
    frame = SemanticFrame.model_validate(
        {
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "confidence": 0.88,
            "facets": [{"name": "mystery_facet", "group": ""}],
        }
    )

    facet_set = normalize_query_facets(frame, raw_text="附近推荐火锅")
    goal = plan_goal(frame, raw_text="附近推荐火锅")

    assert any(facet.name == "mystery_facet" and facet.group == "" for facet in facet_set.facets)
    assert goal.goal_type == "recommendation"
    assert goal.goal_summary


def test_target_resolution_result_resolved_current_shop():
    result = TargetResolutionResult.model_validate(
        {
            "resolved": True,
            "target_shop": {"shop_id": "shop_1", "shop_name": "测试店"},
            "source": "current_shop",
            "confidence": 1.0,
            "owner": "orchestration_router",
            "resolution_reason": "current_shop_reference",
            "reference_type": "current_shop",
        }
    )

    assert result.resolved is True
    assert result.target_shop == {"shop_id": "shop_1", "shop_name": "测试店"}
    assert result.source == "current_shop"
    assert result.owner == "orchestration_router"
    assert result.model_dump()["reference_type"] == "current_shop"


def test_target_resolution_result_unresolved_missing_current_shop():
    result = build_target_resolution_result(
        {"deictic_references": ["这家"], "task_type": "single_shop_query"},
        session_state={},
        raw_text="这家有券吗",
    )

    assert result.resolved is False
    assert result.status == "missing"
    assert result.source == "current_shop"
    assert result.unresolved_reason == "missing_current_shop"
    assert result.owner == "orchestration_router"


def test_target_resolution_result_ordinal_reference_source():
    result = build_target_resolution_result(
        {"ordinal_references": ["第一家"], "task_type": "single_shop_query"},
        session_state={"last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "第一家"}]},
        raw_text="第一家有券吗",
    )

    assert result.resolved is True
    assert result.status == "resolved"
    assert result.source == "last_recommendation_list"
    assert result.reference_type == "ordinal_reference"
    assert result.target_shop == {"shop_id": "shop_1", "shop_name": "第一家", "address": "", "alias": []}


def test_target_resolution_result_defaults_are_backward_compatible():
    result = TargetResolutionResult()

    assert result.resolved is False
    assert result.status == "missing"
    assert result.target_shop is None
    assert result.confidence == 0.0
    assert result.model_dump()["comparison_targets"] == []


def test_target_resolution_result_statuses_cover_reference_sources():
    explicit = build_target_resolution_result(
        {"merchant_mentions": ["海底捞"], "task_type": "single_shop_query"},
        session_state={},
        raw_text="海底捞有券吗",
    )
    comparison = build_target_resolution_result(
        {
            "comparison_targets": [{"shop_id": "shop_1", "shop_name": "第一家"}],
            "task_type": "comparison",
        },
        session_state={},
        raw_text="第一家和第二家哪个好",
    )
    ordinal_not_found = build_target_resolution_result(
        {"ordinal_references": ["第三家"], "task_type": "single_shop_query"},
        session_state={"last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "第一家"}]},
        raw_text="第三家有券吗",
    )

    assert explicit.status == "ambiguous"
    assert comparison.status == "partial"
    assert ordinal_not_found.status == "not_found"


def test_multi_constraint_recommendation_facets_are_retained():
    raw_text = "附近推荐几家适合约会、现在营业、最好有券、人均100左右的餐厅"
    semantic_frame = SemanticFrame.model_validate(
        {
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "confidence": 0.92,
            "facets": normalize_query_facets(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "confidence": 0.92,
                },
                session_state={"current_shop": {"shop_id": "shop_9", "shop_name": "上下文店"}},
                raw_text=raw_text,
            ).facets,
        }
    )

    facet_set = normalize_query_facets(
        semantic_frame,
        session_state={"current_shop": {"shop_id": "shop_9", "shop_name": "上下文店"}},
        raw_text=raw_text,
    )
    assert {"nearby", "restaurant", "date_scene", "open_now", "coupon", "budget_around_x"}.issubset(_facet_names(facet_set))
    assert "current_shop" not in _facet_names(facet_set)

    goal = plan_goal(semantic_frame, session_state={"current_shop": {"shop_id": "shop_9", "shop_name": "上下文店"}}, raw_text=raw_text)
    execution_plan = build_recommendation_execution_plan(
        semantic_frame.model_dump(),
        fallback_query=raw_text,
    )
    evidence_pack = EvidencePack.model_validate(
        build_evidence(
            tool_results={"call_1": {"status": "ok", "data": {}}},
            resolved_target={"status": "RESOLVED", "resolved_shop": {"shop_id": "shop_9", "shop_name": "上下文店"}},
            execution_plan=execution_plan,
            recommendation_candidates=[],
            comparison_targets=[],
        )
    )
    decision_plan = plan_decision(goal_plan=goal, evidence_pack=evidence_pack)
    answer_plan = build_answer_plan("recommendation", evidence_pack.model_dump())

    assert goal.facets
    assert any(facet.name == "coupon" for facet in goal.facets)
    assert any(facet.name == "budget_around_x" for facet in goal.facets)
    assert any(facet.get("name") == "coupon" for facet in execution_plan["plan"]["facets"])
    assert evidence_pack.facets
    assert decision_plan.facets
    assert answer_plan["facets"]


def test_recommendation_plus_ordinal_reference_facets_are_explicit():
    raw_text = "推荐附近火锅，第一家远吗"
    facet_set = normalize_query_facets(
        {"task_type": "single_shop_query", "primary_task": "shop_distance"},
        session_state={"last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "第一家"}]},
        raw_text=raw_text,
    )

    assert {"hotpot", "nearby", "ordinal_reference", "distance"}.issubset(_facet_names(facet_set))
    assert facet_set.target_resolution.resolved is True
    assert facet_set.target_resolution.source == "last_recommendation_list"


def test_single_target_multi_facet_query_with_current_shop():
    raw_text = "这家有券吗？现在开着吗？离我多远？"
    state = {
        "semantic_frame": {
            "task_type": "single_shop_query",
            "primary_task": "shop_coupon",
            "deictic_references": ["这家"],
            "reference_mentions": ["这家"],
            "facets": normalize_query_facets(
                {"task_type": "single_shop_query", "primary_task": "shop_coupon"},
                session_state={"current_shop": {"shop_id": "shop_1", "shop_name": "测试店"}},
                raw_text=raw_text,
            ).facets,
        },
        "raw_text": raw_text,
        "session_state": {"current_shop": {"shop_id": "shop_1", "shop_name": "测试店"}},
        "target_resolution": build_target_resolution_result(
            {
                "task_type": "single_shop_query",
                "primary_task": "shop_coupon",
                "deictic_references": ["这家"],
                "reference_mentions": ["这家"],
            },
            session_state={"current_shop": {"shop_id": "shop_1", "shop_name": "测试店"}},
            raw_text=raw_text,
        ).model_dump(),
    }

    target, pending, reason = _resolve_single_shop_target(state)

    assert pending is None
    assert reason == "current_shop_reference"
    assert target and target["shop_id"] == "shop_1"
    assert target["shop_name"] == "测试店"


def test_single_target_multi_facet_query_without_current_shop_clarifies():
    raw_text = "这家有券吗？现在开着吗？离我多远？"
    state = {
        "semantic_frame": {
            "task_type": "single_shop_query",
            "primary_task": "shop_coupon",
            "deictic_references": ["这家"],
            "reference_mentions": ["这家"],
        },
        "raw_text": raw_text,
        "session_state": {},
        "target_resolution": build_target_resolution_result(
            {"task_type": "single_shop_query", "primary_task": "shop_coupon", "deictic_references": ["这家"], "reference_mentions": ["这家"]},
            session_state={},
            raw_text=raw_text,
        ).model_dump(),
    }

    target, pending, reason = _resolve_single_shop_target(state)

    assert target is None
    assert pending is not None
    assert reason == "missing_current_shop"


def test_comparison_query_preserves_reference_and_preference_facets():
    raw_text = "第一家和第二家哪家更适合带娃，哪家更便宜？"
    facet_set = normalize_query_facets(
        {
            "task_type": "comparison",
            "primary_task": "comparison",
            "comparison_targets": [{"shop_id": "shop_1", "shop_name": "第一家"}, {"shop_id": "shop_2", "shop_name": "第二家"}],
        },
        session_state={"last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "第一家"}, {"shop_id": "shop_2", "shop_name": "第二家"}]},
        raw_text=raw_text,
    )

    assert {"ordinal_reference", "comparison_targets", "kid_friendly", "price_compare"}.issubset(_facet_names(facet_set))
    assert facet_set.target_resolution.resolved is True
    assert facet_set.target_resolution.source == "comparison_targets"
    assert len(facet_set.target_resolution.comparison_targets) >= 2


def test_comparison_query_with_insufficient_targets_clarifies():
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "comparison",
            "semantic_frame": {
                "confidence": 0.8,
                "comparison_targets": [{"reference": "ordinal", "source_text": "第一家", "shop_name": "第一家"}],
                "ordinal_references": ["第一家"],
            },
            "last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "第一家"}],
            "raw_text": "第一家和第二家哪家更适合带娃",
        }
    )

    assert decision.workflow_name == "clarification_fallback"
    assert decision.requires_clarification is True


def test_exploration_planning_facets_are_retained():
    raw_text = "帮我安排一个先吃饭再喝咖啡的约会路线"
    facet_set = normalize_query_facets(
        {"task_type": "date_plan", "primary_task": "route_plan"},
        raw_text=raw_text,
    )
    decision = build_orchestration_decision(
        {
            "top_intent": "local_life",
            "task_type": "date_plan",
            "semantic_frame": {"confidence": 0.63},
            "raw_text": raw_text,
        }
    )
    goal = plan_goal({"task_type": "date_plan", "primary_task": "route_plan"}, raw_text=raw_text)

    assert {"restaurant", "coffee", "date_scene"}.issubset(_facet_names(facet_set))
    assert decision.workflow_name == "exploration_planning"
    assert goal.facets
    assert any(facet.name == "coffee" for facet in goal.facets)
