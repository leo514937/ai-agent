"""Tests for EvidencePlanner — plans tool calls from CandidateSet + required/optional facets."""

from __future__ import annotations

import pytest

from local_life_agent.domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
)
from local_life_agent.domain.schemas import ExecutionPlan
from local_life_agent.planning.evidence_planner import plan_evidence


class TestPlanEvidence:
    """plan_evidence() basic behaviour."""

    def test_empty_candidate_set_returns_empty_plan(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "open_status"],
        )
        cs = CandidateSet(status=CandidateStatus.NOT_FOUND, source=CandidateSource.DISCOVERY)
        plan = plan_evidence(goal, cs)
        assert isinstance(plan, ExecutionPlan)
        assert plan.tool_calls == []

    def test_single_shop_required_facets(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "open_status"],
            optional_facets=["distance"],
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
            ],
        )
        plan = plan_evidence(goal, cs)
        assert len(plan.tool_calls) == 3
        call_facets = {c.facet for c in plan.tool_calls}
        assert call_facets == {"coupon", "open_status", "distance"}
        call_names = {c.tool_name for c in plan.tool_calls}
        assert call_names == {"get_coupon_list", "check_open_status", "get_distance_eta"}

    def test_required_marked_correctly(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.COMPARISON,
            required_facets=["coupon"],
            optional_facets=["distance"],
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
            ],
        )
        plan = plan_evidence(goal, cs)
        for tc in plan.tool_calls:
            if tc.facet == "coupon":
                assert tc.required is True
            elif tc.facet == "distance":
                assert tc.required is False

    def test_comparison_two_shops(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.COMPARISON,
            required_facets=["coupon", "open_status"],
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
                ResolvedCandidate(shop_id="s2", shop_name="Shop B", rank=2),
            ],
        )
        plan = plan_evidence(goal, cs)
        assert len(plan.tool_calls) == 4  # 2 shops × 2 facets
        shop_ids = {tc.target_shop_id for tc in plan.tool_calls}
        assert shop_ids == {"s1", "s2"}

    def test_dedup_same_shop_same_facet(self):
        """Same shop_id should not duplicate tool calls for same facet."""
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "coupon"],  # duplicate in list
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
            ],
        )
        plan = plan_evidence(goal, cs)
        coupon_calls = [tc for tc in plan.tool_calls if tc.facet == "coupon"]
        assert len(coupon_calls) == 1  # deduplicated

    def test_plan_id_contains_source_and_type(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon"],
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.EXPLICIT,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
            ],
        )
        plan = plan_evidence(goal, cs)
        assert "explicit" in plan.plan_id
        assert "single_shop_query" in plan.plan_id

    def test_max_parallelism_set(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "open_status", "distance", "detail"],
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
            ],
        )
        plan = plan_evidence(goal, cs)
        for tc in plan.tool_calls:
            assert tc.max_parallelism >= 1

    def test_no_facets_raises(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
        )
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", rank=1),
            ],
        )
        with pytest.raises(ValueError):
            plan_evidence(goal, cs)
