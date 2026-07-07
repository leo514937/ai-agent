from __future__ import annotations

from ..answer.composers import (
    ClarificationComposer,
    ComparisonComposer,
    DirectResponseComposer,
    ExplorationPlanComposer,
    RecommendationComposer,
    SingleShopFactComposer,
    SystemFallbackComposer,
    compose_deterministic_response,
)
from ..domain.schemas import DecisionPlan


def test_single_shop_fact_composer_covers_multiple_facets():
    plan = DecisionPlan(
        answer_type="single_shop_query",
        selected_targets=[
            {
                "shop_name": "川味轩(知春路店)",
                "open_status": "open",
                "coupon_status": "has_coupon",
                "coupon_titles": ["券A", "券B"],
                "distance_km": 1.2,
                "eta_minutes": 10,
                "rating": 4.8,
                "avg_price": 58,
            }
        ],
        grounded_facts={
            "open_status": "open",
            "coupon_titles": ["券A", "券B"],
            "coupon_count": 2,
            "distance_km": 1.2,
            "eta_minutes": 10,
            "rating": 4.8,
            "avg_price": 58,
        },
        facet_statuses={
            "open_status": "grounded",
            "coupon": "grounded",
            "distance": "grounded",
            "rating": "grounded",
            "avg_price": "grounded",
        },
    )
    text = SingleShopFactComposer().compose(plan).answer_text
    assert "营业中" in text
    assert "券A" in text
    assert "距离约" in text
    assert "评分为" in text
    assert "人均约" in text


def test_direct_clarify_fallback_composers_return_meaningful_text():
    direct_plan = DecisionPlan(answer_type="general")
    clarify_plan = DecisionPlan(answer_type="clarification", required_disclaimers=["请提供完整店名。"])
    fallback_plan = DecisionPlan(answer_type="error")

    assert "可以帮你" in DirectResponseComposer().compose(direct_plan).answer_text
    assert "请提供" in ClarificationComposer().compose(clarify_plan).answer_text
    assert "暂时无法处理" in SystemFallbackComposer().compose(fallback_plan).answer_text


def test_compose_deterministic_response_dispatches_to_minimal_composers():
    plan = DecisionPlan(answer_type="single_shop_query", selected_targets=[{"shop_name": "川味轩(知春路店)"}])
    directive = compose_deterministic_response(plan)
    assert "川味轩" in directive.answer_text


def test_recommendation_composer_preserves_rank_order():
    plan = DecisionPlan(
        answer_type="recommendation",
        overall_ranking=[
            {"shop_name": "川味轩(知春路店)", "reason": "评分更高"},
            {"shop_name": "海底捞(牡丹园店)", "reason": "距离更近"},
            {"shop_name": "蜀香居(学院路店)", "reason": "优惠更多"},
        ],
        best_for={"综合推荐": {"shop_name": "川味轩(知春路店)", "reason": "排序第一"}},
        uncertainty_notes=["海底捞(牡丹园店)优惠暂时无法确认"],
    )
    text = RecommendationComposer().compose(plan).answer_text
    assert text.index("川味轩(知春路店)") < text.index("海底捞(牡丹园店)")
    assert "综合推荐" in text
    assert "优惠暂时无法确认" in text


def test_comparison_composer_preserves_winner_and_tradeoff():
    plan = DecisionPlan(
        answer_type="comparison",
        selected_targets=[
            {"shop_name": "川味轩(知春路店)", "rating": 4.9, "reason": "评分领先"},
            {"shop_name": "海底捞(牡丹园店)", "rating": 4.7, "reason": "距离更近"},
        ],
        best_for={"评分": {"shop_name": "川味轩(知春路店)", "reason": "评分最高"}},
        comparison_support_status="grounded",
        uncertainty_notes=["距离暂时无法确认"],
    )
    text = ComparisonComposer().compose(plan).answer_text
    assert "川味轩(知春路店)" in text
    assert "海底捞(牡丹园店)" in text
    assert "评分最高" in text
    assert "距离暂时无法确认" in text


def test_exploration_plan_composer_preserves_stages():
    plan = DecisionPlan(
        answer_type="exploration_plan",
        exploration_stages=[
            {"stage_type": "eat", "candidate_query": "先找正餐", "status": "ok"},
            {"stage_type": "coffee", "candidate_query": "再找咖啡", "status": "partial"},
        ],
        stage_queries=["先找正餐", "再找咖啡"],
        stage_statuses=["ok", "partial"],
    )
    text = ExplorationPlanComposer().compose(plan).answer_text
    assert "先找正餐" in text
    assert "再找咖啡" in text
    assert "partial" in text or "不完整" in text
