"""Tests for P2 GoalPlanner (plan_goal) and GoalReview (review_goal)."""

from __future__ import annotations

import pytest

from ..domain.enums import Facet, TaskType
from ..domain.goal import GoalPlan, GoalReviewResult, GoalSource
from ..domain.state import SessionState
from ..planning.goal_planner import plan_goal
from ..planning.goal_review import review_goal


# ===================================================================
# Helper: build SemanticFrame as dict (plan_goal accepts dict|SemanticFrame)
# ===================================================================

def _frame(**overrides: object) -> dict:
    """Build a SemanticFrame-compatible dict with sensible defaults."""
    defaults: dict = {
        "task_type": "recommendation",
        "primary_task": "find a good hotpot place",
        "facets": [],
        "focused_facets": [],
        "merchant_mentions": [],
        "ordinal_references": [],
        "deictic_references": [],
        "hard_constraints": {},
        "semantic_source": "test",
        "candidate_source": None,
        "candidate_category": "hotpot",
        "candidate_limit": None,
    }
    defaults.update(overrides)
    return defaults


def _session(**overrides: object) -> SessionState:
    defaults: dict = {
        "session_id": "test_sid",
        "user_id": "test_uid",
        "replan_counters": {},
    }
    defaults.update(overrides)
    return SessionState(**defaults)


# ===================================================================
# GoalPlanner tests
# ===================================================================

class TestGoalPlanner:
    def test_recommendation_goal(self):
        """Recommendation frame → GoalPlan with correct goal_type."""
        gp = plan_goal(_frame(task_type="recommendation"))
        assert gp.goal_type == "recommendation"
        assert gp.candidate_source in ("discovery",)
        assert not gp.unsupported
        assert "hotpot" in gp.goal_summary

    def test_comparison_goal(self):
        """Comparison frame → GoalPlan with comparison type."""
        gp = plan_goal(_frame(
            task_type="comparison",
            merchant_mentions=[{"shop_id": "s1", "shop_name": "A"}, {"shop_id": "s2", "shop_name": "B"}],
        ))
        assert gp.goal_type == "comparison"
        assert gp.candidate_source == "explicit"
        assert gp.candidate_limit == 2
        assert not gp.unsupported

    def test_single_shop_goal(self):
        """Single-shop frame → GoalPlan with single_shop_query type."""
        gp = plan_goal(_frame(
            task_type="single_shop_query",
            merchant_mentions=[{"shop_id": "s1", "shop_name": "A"}],
        ))
        assert gp.goal_type == "single_shop_query"
        assert gp.candidate_limit == 1

    def test_coupon_query_maps_to_single_shop(self):
        """coupon_query task_type → single_shop_query goal_type."""
        gp = plan_goal(_frame(task_type="coupon_query"))
        assert gp.goal_type == "single_shop_query"

    def test_unsupported_booking_intent(self):
        """Booking/reservation intent → unsupported goal."""
        gp = plan_goal(_frame(task_type="recommendation"), raw_text="帮我订座")
        assert gp.unsupported
        assert "booking" in gp.unsupported_reason.lower() or "订座" in gp.unsupported_reason

    def test_unsupported_reservation_phrase_in_primary_task(self):
        """Reservation phrasing in primary_task should share the same unsupported detection."""
        gp = plan_goal(_frame(
            task_type="recommendation",
            primary_task="make a reservation for tonight",
        ))
        assert gp.unsupported
        assert "reservation" in gp.unsupported_reason.lower()

    def test_clarification_reply_maps_to_refinement(self):
        """clarification_reply task_type → refinement goal_type."""
        gp = plan_goal(_frame(task_type="clarification_reply"))
        assert gp.goal_type == "refinement"

    def test_general_chat_maps_to_unsupported(self):
        """general_chat task_type → unsupported goal_type."""
        gp = plan_goal(_frame(task_type="general_chat"))
        assert gp.unsupported

    def test_facets_extracted(self):
        """Required and optional facets are extracted from the frame."""
        gp = plan_goal(_frame(
            task_type="recommendation",
            facets=[
                {"name": "rating", "required": True},
                {"name": "distance", "required": False},
                {"name": "coupon", "required": True},
            ],
        ))
        assert "rating" in gp.required_facets
        assert "coupon" in gp.required_facets
        assert "distance" in gp.optional_facets
        assert "rating" in gp.evidence_needs
        assert "distance" in gp.evidence_needs

    def test_candidate_source_discovery(self):
        """No mentions → candidate_source discovery."""
        gp = plan_goal(_frame(task_type="recommendation"))
        assert gp.candidate_source == "discovery"

    def test_candidate_source_explicit(self):
        """Merchant mentions → candidate_source explicit."""
        gp = plan_goal(_frame(
            task_type="single_shop_query",
            merchant_mentions=[{"shop_id": "s1", "shop_name": "A"}],
        ))
        assert gp.candidate_source == "explicit"

    def test_candidate_source_context(self):
        """Ordinal references → candidate_source context."""
        gp = plan_goal(_frame(
            task_type="recommendation",
            ordinal_references=["第一家", "第二家"],
        ))
        assert gp.candidate_source == "context"

    def test_candidate_limit_from_hard_constraints(self):
        """candidate_limit from hard_constraints if not set directly."""
        gp = plan_goal(_frame(
            task_type="recommendation",
            hard_constraints={"count": "5"},
        ))
        assert gp.candidate_limit == 5

    def test_session_state_passed(self):
        """SessionState is accepted without error."""
        ss = _session()
        gp = plan_goal(_frame(task_type="recommendation"), session_state=ss)
        assert gp.goal_type == "recommendation"

    def test_none_frame_handled(self):
        """None frame → unsupported goal_type, not crashing."""
        gp = plan_goal(None)
        assert gp.goal_type == "unsupported"


# ===================================================================
# GoalReview tests
# ===================================================================

class TestGoalReview:
    def test_finish_on_clear_recommendation(self):
        """Clear recommendation goal → FINISH."""
        gp = plan_goal(_frame(task_type="recommendation"))
        result = review_goal(gp)
        assert result.next_action == "FINISH"
        assert result.status == "enough"

    def test_finish_on_clear_comparison(self):
        """Clear comparison goal → FINISH."""
        gp = plan_goal(_frame(
            task_type="comparison",
            merchant_mentions=[{"shop_id": "s1", "shop_name": "A"}, {"shop_id": "s2", "shop_name": "B"}],
        ))
        result = review_goal(gp)
        assert result.next_action == "FINISH"

    def test_unsupported_on_booking(self):
        """Booking intent (English keyword) → UNSUPPORTED_ANSWER."""
        gp = plan_goal(_frame(task_type="recommendation"), raw_text="book a table for tonight")
        result = review_goal(gp)
        assert result.next_action == "UNSUPPORTED_ANSWER"

    def test_review_catches_booking_marker_from_goal_summary(self):
        """GoalReview should use the shared unsupported detection as a deterministic fallback."""
        gp = GoalPlan(
            goal_type="recommendation",
            goal_summary="need a reservation for 2 people",
            candidate_source="discovery",
            requested_count=1,
            min_required=1,
            max_allowed=5,
            unsupported=False,
        )
        result = review_goal(gp)
        assert result.next_action == "UNSUPPORTED_ANSWER"

    def test_unsupported_when_goal_is_unsupported(self):
        """GoalPlan with unsupported=True → UNSUPPORTED_ANSWER."""
        gp = GoalPlan(goal_type="unsupported", unsupported=True, unsupported_reason="test")
        result = review_goal(gp)
        assert result.next_action == "UNSUPPORTED_ANSWER"

    def test_clarify_on_ambiguous_frame(self):
        """Vague / missing information → CLARIFY if the goal requires explicit candidates."""
        gp = plan_goal(_frame(task_type="comparison"))
        result = review_goal(gp)
        # Comparison with no explicit candidates → needs clarification
        assert result.next_action in ("CLARIFY", "FINISH")

    def test_clarify_on_no_goal_type(self):
        """Empty goal_type → CLARIFY."""
        gp = GoalPlan(goal_type="", candidate_source="discovery")
        result = review_goal(gp)
        assert result.next_action in ("CLARIFY", "UNSUPPORTED_ANSWER")

    def test_none_goal_plan_handled(self):
        """None goal_plan → UNSUPPORTED_ANSWER."""
        result = review_goal(None)
        assert result.next_action == "UNSUPPORTED_ANSWER"

    def test_fallback_on_empty_frame(self):
        """Empty frame that produces empty GoalPlan → FALLBACK or UNSUPPORTED."""
        gp = plan_goal(_frame(task_type="general_chat"))
        result = review_goal(gp)
        assert result.next_action in ("UNSUPPORTED_ANSWER", "FALLBACK")

    def test_goal_source_preserved(self):
        """GoalSource is preserved through goal_plan_to_draft mapping."""
        gp = plan_goal(_frame(task_type="recommendation"))
        assert gp.goal_source == GoalSource.SEMANTIC_FRAME
