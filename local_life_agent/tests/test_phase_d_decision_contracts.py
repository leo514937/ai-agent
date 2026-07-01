from __future__ import annotations

from local_life_agent.planning.decision.decision_planner import plan_decision


def test_decision_planner_prefers_evidence_over_rank_snapshot_order():
    decision = plan_decision(
        goal_plan={"goal_type": "recommendation", "goal_summary": "推荐"},
        candidate_set={"candidates": [{"shop_id": "shop_ranked"}, {"shop_id": "shop_compat"}]},
        evidence_pack={
            "target_shop_ids": ["shop_ranked", "shop_compat"],
            "ranking_snapshot": {
                "ranked": [{"shop_id": "shop_ranked", "shop_name": "主字段店铺"}],
                "ranked_shops": [{"shop_id": "shop_compat", "shop_name": "兼容字段店铺"}],
            },
            "evidence_items": [
                {
                    "evidence_id": "evi_compat_rating",
                    "shop_id": "shop_compat",
                    "shop_name": "兼容字段店铺",
                    "facet": "rating",
                    "result_status": "ok",
                    "value": 4.9,
                }
            ],
            "facet_results": [],
            "unknown_items": [],
        },
    )

    assert decision.winner_shop_id == "shop_compat"
    assert decision.ranking[0]["shop_id"] == "shop_ranked"


def test_decision_planner_does_not_use_snapshot_as_winner_fallback():
    decision = plan_decision(
        goal_plan={"goal_type": "recommendation", "goal_summary": "推荐"},
        candidate_set={"candidates": [{"shop_id": "shop_ranked"}, {"shop_id": "shop_compat"}]},
        evidence_pack={
            "target_shop_ids": ["shop_ranked", "shop_compat"],
            "ranking_snapshot": {
                "ranked": [{"shop_id": "shop_ranked", "shop_name": "主字段店铺"}],
                "ranked_shops": [{"shop_id": "shop_compat", "shop_name": "兼容字段店铺"}],
            },
            "facet_results": [],
            "unknown_items": [],
        },
    )

    assert decision.winner_shop_id is None
    assert decision.winner_evidence_refs == []
    assert decision.insufficient_evidence is True
    assert decision.next_action == "insufficient_evidence"
    assert "claim_refs" in decision.missing_fields
    assert "ranking_snapshot" not in decision.winner_evidence_refs
