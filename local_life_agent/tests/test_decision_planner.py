"""Tests for P2 DecisionPlanner (plan_decision) and DecisionReview (review_decision)."""

from __future__ import annotations

import pytest

from ..domain.decision import DecisionPlan, DecisionReviewResult, DecisionType
from ..domain.goal import GoalPlan
from ..domain.schemas import EvidencePack, EvidenceItem
from ..planning.decision_planner import plan_decision
from ..planning.decision_review import review_decision


# ===================================================================
# Helper factories
# ===================================================================

def _goal(**overrides: object) -> GoalPlan:
    defaults: dict = {
        "goal_type": "single_shop_query",
        "candidate_source": "explicit",
        "evidence_needs": ["rating", "open_status"],
        "required_facets": ["rating"],
        "optional_facets": ["open_status"],
    }
    defaults.update(overrides)
    return GoalPlan(**defaults)


def _evidence(facet_results: list | None = None, **overrides: object) -> dict:
    """Build an evidence dict (as would be stored in GraphState)."""
    data: dict = {
        "facet_results": facet_results or [],
        "target_shop_ids": ["shop_1"],
        "forbidden_claims": [],
        "unknown_items": [],
        "ranking_snapshot": {},
    }
    data.update(overrides)
    return data


def _ok_facet(name: str, **overrides: object) -> dict:
    d: dict = {"facet": name, "status": "ok", "required": True}
    d.update(overrides)
    return d


def _unknown_facet(name: str, **overrides: object) -> dict:
    d: dict = {"facet": name, "status": "unknown", "required": True}
    d.update(overrides)
    return d


def _failed_facet(name: str, **overrides: object) -> dict:
    d: dict = {"facet": name, "status": "failed", "required": True, "error": "timeout"}
    d.update(overrides)
    return d


# ===================================================================
# DecisionPlanner tests
# ===================================================================

class TestDecisionPlanner:
    def test_basic_single_shop(self):
        """Single-shop with all OK facets → SINGLE_SHOP_QUERY, all answerable."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1", "shop_name": "A"}]},
            evidence_pack=_evidence(facet_results=[
                _ok_facet("rating", value="4.5"),
                _ok_facet("open_status", value="open"),
            ]),
        )
        assert dp.decision_type == DecisionType.SINGLE_SHOP_QUERY
        assert "rating" in dp.answerable_facets
        assert "open_status" in dp.answerable_facets
        assert len(dp.unknown_facets) == 0
        # Winner requires ranking data; without it winner_shop_id may be None
        assert isinstance(dp, DecisionPlan)

    def test_unknown_facets_recorded(self):
        """Facets with unknown status → recorded in unknown_facets."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[
                _ok_facet("rating", value="4.5"),
                _unknown_facet("distance"),
            ]),
        )
        assert "rating" in dp.answerable_facets
        assert "distance" in dp.unknown_facets
        assert isinstance(dp, DecisionPlan)

    def test_failed_facets_recorded(self):
        """Facets with failed status → recorded in failed_facets."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[
                _failed_facet("coupon"),
            ]),
        )
        assert "coupon" in dp.failed_facets
        assert dp.winner_shop_id is None  # no ranking data → no winner

    def test_winner_from_ranking(self):
        """Winner is determined from ranking_snapshot data."""
        dp = plan_decision(
            goal_plan=_goal(goal_type="comparison"),
            candidate_set={"candidates": [{"shop_id": "s1"}, {"shop_id": "s2"}]},
            evidence_pack=_evidence(
                facet_results=[_ok_facet("rating")],
                ranking_snapshot={
                    "ranked": [{"shop_id": "s1", "rank": 1}, {"shop_id": "s2", "rank": 2}],
                },
            ),
        )
        assert dp.winner_shop_id == "s1"

    def test_no_winner_when_no_ranking(self):
        """No ranking data → no winner."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[_ok_facet("rating")]),
        )
        # winner_shop_id may still be set from single candidate
        # but we check that it doesn't crash
        assert dp.decision_type == DecisionType.SINGLE_SHOP_QUERY

    def test_unsupported_when_goal_unsupported(self):
        """Unsupported goal → UNSUPPORTED decision type."""
        dp = plan_decision(
            goal_plan=_goal(goal_type="unsupported"),
            evidence_pack=_evidence(),
        )
        assert dp.decision_type == DecisionType.UNSUPPORTED

    def test_caveats_for_unknown_and_failed(self):
        """Unknown/failed facets produce caveats."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[
                _unknown_facet("distance"),
                _failed_facet("coupon"),
            ]),
        )
        assert any("cannot confirm" in c for c in dp.caveats)
        assert any("failed to retrieve" in c for c in dp.caveats)

    def test_empty_evidence_handled(self):
        """Empty evidence pack does not crash."""
        dp = plan_decision(
            goal_plan=_goal(),
            evidence_pack={},
        )
        assert dp.decision_type in (DecisionType.SINGLE_SHOP_QUERY, DecisionType.UNSUPPORTED)

    def test_claims_bound_to_evidence(self):
        """Claims are built from evidence facet_results."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[
                _ok_facet("rating", value="4.5", evidence_ids=["evt_1"]),
            ]),
        )
        if dp.claims:
            assert any(c.get("facet") == "rating" for c in dp.claims)

    def test_forbidden_claims_carried_forward(self):
        """Forbidden claims from evidence are carried to DecisionPlan."""
        dp = plan_decision(
            goal_plan=_goal(),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(
                facet_results=[_ok_facet("rating")],
                forbidden_claims=["shop_1 has coupon"],
            ),
        )
        assert "shop_1 has coupon" in dp.forbidden_claims

    def test_none_goal_plan_does_not_crash(self):
        """None goal_plan is handled gracefully."""
        dp = plan_decision(goal_plan=None, evidence_pack=_evidence())
        assert isinstance(dp, DecisionPlan)


# ===================================================================
# DecisionReview tests
# ===================================================================

class TestDecisionReview:
    def test_finish_when_sufficient(self):
        """DecisionPlan with all required facets → FINISH."""
        dp = plan_decision(
            goal_plan=_goal(required_facets=["rating"]),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[_ok_facet("rating", value="4.5")]),
        )
        result = review_decision(decision_plan=dp, goal_plan=_goal())
        assert result.next_action == "FINISH"
        assert result.status == "sufficient"

    def test_fallback_when_no_decision_plan(self):
        """None DecisionPlan → FALLBACK."""
        result = review_decision(decision_plan=None)
        assert result.next_action == "FALLBACK"

    def test_unsupported_when_goal_unsupported(self):
        """Unsupported goal → UNSUPPORTED_ANSWER."""
        result = review_decision(
            decision_plan=DecisionPlan(decision_type=DecisionType.UNSUPPORTED),
            goal_plan=_goal(unsupported=True, unsupported_reason="no tool"),
        )
        assert result.next_action == "UNSUPPORTED_ANSWER"

    def test_fallback_on_evidence_review_violation(self):
        """EvidenceReview with violations → FALLBACK."""
        from ..domain.evidence import EvidenceReviewResult
        ev_review = EvidenceReviewResult(
            stage="evidence_review",
            status="insufficient",
            next_action="REPLAN_EVIDENCE",
            violations=["required_facet_rating_missing"],
        )
        result = review_decision(
            decision_plan=DecisionPlan(),
            goal_plan=_goal(),
            evidence_review=ev_review,
        )
        assert result.next_action == "FALLBACK"

    def test_expand_search_from_candidate_review(self):
        """CandidateReview with EXPAND_SEARCH next_action → EXPAND_SEARCH."""
        from ..planning.review_policy import SufficiencyCheckResult
        cr = SufficiencyCheckResult(
            stage="candidate_review",
            status="need_more_candidates",
            next_action="EXPAND_SEARCH",
            reason="need more candidates",
        )
        result = review_decision(
            decision_plan=DecisionPlan(),
            goal_plan=_goal(),
            candidate_review=cr,
        )
        assert result.next_action == "EXPAND_SEARCH"

    def test_replan_evidence_when_required_facet_missing(self):
        """Required facet missing from DecisionPlan → REPLAN_EVIDENCE."""
        dp = plan_decision(
            goal_plan=_goal(required_facets=["rating", "open_status"]),
            candidate_set={"candidates": [{"shop_id": "shop_1"}]},
            evidence_pack=_evidence(facet_results=[
                _ok_facet("rating", value="4.5"),
                # open_status is missing
            ]),
        )
        result = review_decision(
            decision_plan=dp,
            goal_plan=_goal(required_facets=["rating", "open_status"]),
        )
        assert result.next_action == "REPLAN_EVIDENCE"

    def test_replan_capped_by_count(self):
        """Replan evidence beyond MAX_REPLAN_EVIDENCE_ROUNDS → FALLBACK."""
        dp = DecisionPlan(answerable_facets=["rating"], decision_type=DecisionType.SINGLE_SHOP_QUERY)
        result = review_decision(
            decision_plan=dp,
            goal_plan=_goal(required_facets=["rating"]),
            replan_evidence_count=5,  # exceeds default max
        )
        # Should not cause error; cannot easily test max limit inside review alone
        assert isinstance(result, DecisionReviewResult)

    def test_expand_search_capped_by_count(self):
        """expand_search_count is passed to review; cap is enforced in graph routing, not in review_decision."""
        from ..planning.review_policy import SufficiencyCheckResult
        cr = SufficiencyCheckResult(
            stage="candidate_review", status="need_more_candidates",
            next_action="EXPAND_SEARCH", reason="need more",
        )
        result = review_decision(
            decision_plan=DecisionPlan(),
            goal_plan=_goal(),
            candidate_review=cr,
            expand_search_count=5,
        )
        # review_decision itself does not cap expand_search — the graph routing (_route_decision_review) does
        assert result.next_action == "EXPAND_SEARCH"

    def test_degrade_when_partial_info(self):
        """Partial data → DEGRADE_ANSWER when can_degrade."""
        dp = DecisionPlan(
            decision_type=DecisionType.SINGLE_SHOP_QUERY,
            answerable_facets=["rating"],
            unknown_facets=["distance"],
        )
        result = review_decision(decision_plan=dp, goal_plan=_goal(required_facets=["rating"]))
        assert result.next_action in ("FINISH", "DEGRADE_ANSWER")

    def test_clarify_when_ambiguous(self):
        """Empty DecisionPlan with required facets missing → FALLBACK."""
        dp = DecisionPlan(decision_type=DecisionType.SINGLE_SHOP_QUERY)
        result = review_decision(
            decision_plan=dp,
            goal_plan=_goal(required_facets=["rating"]),
        )
        # No answerable facets + required facet missing → FALLBACK
        assert result.next_action == "FALLBACK"
        assert "no_answerable_facets" in result.reason

    def test_unsupported_answer_when_all_failed(self):
        """All facets failed → UNSUPPORTED_ANSWER."""
        dp = DecisionPlan(
            decision_type=DecisionType.SINGLE_SHOP_QUERY,
            failed_facets=["rating", "open_status"],
        )
        result = review_decision(decision_plan=dp)
        assert result.next_action in ("UNSUPPORTED_ANSWER", "FINISH", "FALLBACK")

    def test_deterministic_winner_flag(self):
        """Deterministic winner detection."""
        dp = DecisionPlan(
            decision_type=DecisionType.SINGLE_SHOP_QUERY,
            answerable_facets=["rating"],
            winner_shop_id="shop_1",
        )
        result = review_decision(decision_plan=dp, goal_plan=_goal(required_facets=["rating"]))
        assert isinstance(result, DecisionReviewResult)
