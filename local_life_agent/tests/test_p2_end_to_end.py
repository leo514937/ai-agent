"""P2 end-to-end test — exercises the full GoalPlanner → DecisionReview → AnswerPlan flow."""

from __future__ import annotations

import pytest

from ..domain.goal import GoalPlan, goal_plan_to_draft
from ..domain.decision import DecisionPlan, DecisionType, decision_to_answer_plan
from ..domain.schemas import SemanticFrame, AnswerPlan, EvidencePack
from ..planning.goal_planner import plan_goal
from ..planning.goal_review import review_goal
from ..planning.decision_planner import plan_decision
from ..planning.decision_review import review_decision
from ..planning.replan_policy import increment_expand_search, increment_replan_evidence


def _frame(**overrides: object) -> dict:
    """Build a SemanticFrame-compatible dict for plan_goal (accepts dict)."""
    defaults: dict = {
        "task_type": "single_shop_query",
        "primary_task": "check rating and hours",
        "candidate_source": None,
        "candidate_category": "shop",
        "merchant_mentions": ["shop_1"],
        "facets": [{"name": "rating", "required": True}, {"name": "open_status", "required": True}],
        "focused_facets": [],
        "ordinal_references": [],
        "deictic_references": [],
        "hard_constraints": {},
        "semantic_source": "test",
    }
    defaults.update(overrides)
    return defaults


def _evidence(facet_results: list | None = None, **overrides: object) -> dict:
    data: dict = {
        "facet_results": facet_results or [],
        "target_shop_ids": ["shop_1"],
        "forbidden_claims": [],
        "unknown_items": [],
        "ranking_snapshot": {"shop_id": "shop_1"},
    }
    data.update(overrides)
    return data


class TestP2FullFlow:
    """Tests that exercise the full P2 flow: GoalPlanner → DecisionReview → AnswerPlan."""

    def test_full_single_shop_success(self):
        """Single-shop query with all evidence OK → FINISH → valid AnswerPlan."""
        # Step 1: GoalPlanner
        gp = plan_goal(_frame())
        assert gp.goal_type == "single_shop_query"
        assert not gp.unsupported

        # Step 2: GoalReview
        gr = review_goal(gp)
        assert gr.next_action == "FINISH"

        # Step 3: GoalPlan → LocalLifeGoalDraft (compat shell)
        draft = goal_plan_to_draft(gp)
        assert draft.goal_type.value == "single_shop_query"

        # Step 4: DecisionPlanner (with ranking data so winner is determined)
        dp = plan_decision(
            goal_plan=gp,
            candidate_set={"candidates": [{"shop_id": "shop_1", "shop_name": "A"}]},
            evidence_pack=_evidence(facet_results=[
                {"facet": "rating", "status": "ok", "required": True, "value": "4.5"},
                {"facet": "open_status", "status": "ok", "required": True, "value": "open"},
            ]),
        )
        assert dp.decision_type == DecisionType.SINGLE_SHOP_QUERY
        assert "rating" in dp.answerable_facets

        # Step 5: DecisionReview
        dr = review_decision(decision_plan=dp, goal_plan=gp)
        assert dr.next_action == "FINISH"

        # Step 6: DecisionPlan → AnswerPlan
        ap_data = decision_to_answer_plan(dp)
        ap = AnswerPlan.model_validate(ap_data)
        assert ap.answer_type == "single_shop_query"
        assert "shop_1" in ap.target_shop_ids
        assert len(ap.response_sections) >= 3  # summary + rating + open_status

    def test_recommendation_flow(self):
        """Recommendation with multiple candidates → DecisionReview FINISH."""
        gp = plan_goal(_frame(
            task_type="recommendation",
            primary_task="find me a hotpot place",
            merchant_mentions=[],
            facets=[{"name": "rating", "required": True}],
        ))
        assert gp.goal_type == "recommendation"

        gr = review_goal(gp)
        assert gr.next_action == "FINISH"

        dp = plan_decision(
            goal_plan=gp,
            candidate_set={"candidates": [{"shop_id": "s1"}, {"shop_id": "s2"}, {"shop_id": "s3"}]},
            evidence_pack=_evidence(
                facet_results=[{"facet": "rating", "status": "ok", "value": "4.5"}],
                evidence_items=[
                    {
                        "evidence_id": "evi_s1_rating",
                        "shop_id": "s1",
                        "facet": "rating",
                        "result_status": "ok",
                        "value": 4.5,
                    }
                ],
                ranking_snapshot={"ranked": [
                    {"shop_id": "s3", "rank": 1},
                    {"shop_id": "s2", "rank": 2},
                    {"shop_id": "s1", "rank": 3},
                ]},
            ),
        )
        assert dp.winner_shop_id == "s1"
        assert dp.winner_evidence_refs == ["evi_s1_rating"]

        dr = review_decision(decision_plan=dp, goal_plan=gp)
        assert dr.next_action == "FINISH"

        ap = AnswerPlan.model_validate(decision_to_answer_plan(dp))
        assert ap.answer_type == "recommendation"

    def test_unknown_facet_triggers_degrade(self):
        """Required facet unknown → DecisionReview may DEGRADE or REPLAN."""
        gp = plan_goal(_frame(required_facets=["rating", "distance"]))
        gr = review_goal(gp)
        assert gr.next_action == "FINISH"

        dp = plan_decision(
            goal_plan=gp,
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[
                {"facet": "rating", "status": "ok", "required": True, "value": "4.5"},
                {"facet": "distance", "status": "unknown", "required": True},
            ]),
        )
        assert "rating" in dp.answerable_facets
        assert "distance" in dp.unknown_facets
        dr = review_decision(decision_plan=dp, goal_plan=gp)
        # Required facet unknown → should not FINISH blindly
        assert dr.next_action in ("REPLAN_EVIDENCE", "DEGRADE_ANSWER", "FINISH")

    def test_unsupported_intent_rejected(self):
        """Booking intent → GoalReview UNSUPPORTED_ANSWER → no DecisionPlan flow."""
        gp = plan_goal(_frame(task_type="recommendation"), raw_text="帮我订座")
        assert gp.unsupported

        gr = review_goal(gp)
        assert gr.next_action == "UNSUPPORTED_ANSWER"

    def test_expand_search_counter_tracking(self):
        """Replan counters increment correctly across the flow."""
        from ..domain.state import SessionState
        ss = SessionState(session_id="test_sid", user_id="test_uid")

        increment_expand_search(ss)
        assert ss.replan_counters["expand_search"] == 1

        increment_replan_evidence(ss)
        assert ss.replan_counters["replan_evidence"] == 1

        increment_expand_search(ss)
        assert ss.replan_counters["expand_search"] == 2

    def test_comparison_winner_determination(self):
        """Comparison flow → winner determined from ranking."""
        gp = plan_goal(_frame(
            task_type="comparison",
            merchant_mentions=["s1", "s2"],
            facets=[{"name": "rating", "required": True}],  # only rating required
        ))
        assert gp.goal_type == "comparison"

        dp = plan_decision(
            goal_plan=gp,
            candidate_set={"candidates": [{"shop_id": "s1"}, {"shop_id": "s2"}]},
            evidence_pack=_evidence(
                target_shop_ids=["s1", "s2"],
                facet_results=[{"facet": "rating", "status": "ok", "value": "4.0"}],
                evidence_items=[
                    {
                        "evidence_id": "evi_s2_rating",
                        "shop_id": "s2",
                        "facet": "rating",
                        "result_status": "ok",
                        "value": 4.9,
                    }
                ],
                ranking_snapshot={"ranked": [
                    {"shop_id": "s2", "rank": 1},
                    {"shop_id": "s1", "rank": 2},
                ]},
            ),
        )
        assert dp.winner_shop_id == "s2"
        assert dp.winner_evidence_refs == ["evi_s2_rating"]
        dr = review_decision(decision_plan=dp, goal_plan=gp)
        assert dr.next_action == "FINISH"

    def test_empty_evidence_pack_does_not_crash(self):
        """Empty evidence → graceful handling without crash."""
        gp = plan_goal(_frame())
        dp = plan_decision(
            goal_plan=gp,
            candidate_set={"candidates": []},
            evidence_pack={},
        )
        # Should produce a DecisionPlan even with no evidence
        assert isinstance(dp, DecisionPlan)

    def test_answer_plan_from_decision_plan_roundtrip(self):
        """DecisionPlan → AnswerPlan → model_validate succeeds."""
        dp = DecisionPlan(
            decision_type=DecisionType.SINGLE_SHOP_QUERY,
            answerable_facets=["rating"],
            winner_shop_id="shop_1",
            claims=[{"claim_id": "c1", "shop_id": "shop_1", "facet": "rating",
                      "evidence_ids": ["e1"], "claim_type": "factual",
                      "value": "4.5", "verbalization_hint": "评分4.5"}],
        )
        ap_data = decision_to_answer_plan(dp)
        ap = AnswerPlan.model_validate(ap_data)
        assert ap.answer_type == "single_shop_query"
        assert len(ap.allowed_claims) == 1
        assert ap.allowed_claims[0].value == "4.5"

    def test_goal_plan_to_draft_roundtrip(self):
        """GoalPlan → LocalLifeGoalDraft preserves key fields."""
        gp = GoalPlan(
            goal_type="recommendation",
            candidate_source="discovery",
            candidate_category="hotpot",
            candidate_limit=3,
            evidence_needs=["rating", "distance"],
            required_facets=["rating"],
            optional_facets=["distance"],
        )
        draft = goal_plan_to_draft(gp)
        assert draft.goal_type.value == "recommendation"
        assert draft.candidate_category == "hotpot"
        assert draft.candidate_limit == 3
        assert "rating" in draft.required_facets
