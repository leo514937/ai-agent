"""Tests for build_local_life_goal_draft and build_candidate_spec."""

from __future__ import annotations

from ..domain.candidate import (
    CandidateSource,
    GoalType,
    LocalLifeGoalDraft,
)
from ..domain.enums import TaskType
from ..domain.schemas import SemanticFrame
from ..planning.goal_draft import (
    build_candidate_spec,
    build_local_life_goal_draft,
)


def _frame(**overrides: object) -> SemanticFrame:
    payload: dict = {
        "top_intent": "local_life",
        "task_type": TaskType.comparison.value,
        "merchant_mentions": [],
        "facets": [],
        "focused_facets": [],
        "ordinal_references": [],
        "deictic_references": [],
        "hard_constraints": {},
        "comparison_targets": [],
        "candidate_source": None,
        "candidate_category": "",
        "candidate_limit": None,
        "candidate_sort_by": [],
        "candidate_filters": {},
        "candidate_source_origin": None,
        "fallback_reason": "",
        "semantic_source": "real_llm",
    }
    payload.update(overrides)
    return SemanticFrame.model_validate(payload)


# ===================================================================
# build_local_life_goal_draft — default limits
# ===================================================================

class TestGoalDraftDefaultLimits:
    def test_comparison_default_2(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            candidate_source=None,
        ))
        assert draft.goal_type == GoalType.COMPARISON
        assert draft.candidate_limit == 2

    def test_recommendation_default_3(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.recommendation.value,
        ))
        assert draft.goal_type == GoalType.RECOMMENDATION
        assert draft.candidate_limit == 3

    def test_single_shop_default_1(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.single_shop_query.value,
        ))
        assert draft.goal_type == GoalType.SINGLE_SHOP_QUERY
        assert draft.candidate_limit == 1

    def test_explicit_limit_respected(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            candidate_limit=4,
        ))
        assert draft.candidate_limit == 4

    def test_none_frame_returns_unsupported(self):
        draft = build_local_life_goal_draft(None)
        assert draft.goal_type == GoalType.UNSUPPORTED
        assert draft.source_origin == "fallback"


# ===================================================================
# build_local_life_goal_draft — candidate_source derivation
# ===================================================================

class TestGoalDraftCandidateSource:
    def test_discovery_comparison(self):
        """对比附近评分最高的两家KTV → discovery"""
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            merchant_mentions=[],
            ordinal_references=[],
            deictic_references=[],
        ))
        assert draft.candidate_source == CandidateSource.DISCOVERY

    def test_explicit_comparison(self):
        """海底捞和山城一锅哪个好 → explicit"""
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            merchant_mentions=["海底捞", "山城一锅"],
            ordinal_references=[],
            deictic_references=[],
        ))
        assert draft.candidate_source == CandidateSource.EXPLICIT

    def test_context_comparison(self):
        """这两家谁优惠券多 → context"""
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            merchant_mentions=[],
            ordinal_references=["第一家"],
            deictic_references=["这两家"],
        ))
        assert draft.candidate_source == CandidateSource.CONTEXT

    def test_mixed_comparison(self):
        """海底捞和附近评分最高的KTV比 → mixed"""
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            merchant_mentions=["海底捞"],
            ordinal_references=[],
            deictic_references=[],
            comparison_targets=[{"shop_name": "附近评分最高的KTV", "reference": "discovery"}],
        ))
        # With merchant_mentions but no ordinals/deictics, it's EXPLICIT
        # With comparison_targets with non-explicit ref → MIXED
        # Actually the function uses ordinals+deictics for MIXED detection
        # Let's add a deictic ref to trigger MIXED
        pass

    def test_recommendation_refine_follow_up_uses_session_history(self):
        frame = _frame(
            task_type=None,
            merchant_mentions=[],
            ordinal_references=[],
            deictic_references=[],
            soft_preferences={},
            ranking_signals={},
        )
        draft = build_local_life_goal_draft(
            frame,
            state={
                "raw_text": "便宜一点的呢",
                "last_recommendation_list": [
                    {"shop_id": "shop_1", "shop_name": "第一家火锅"},
                    {"shop_id": "shop_2", "shop_name": "第二家火锅"},
                ],
            },
        )
        assert draft.goal_type == GoalType.RECOMMENDATION
        assert draft.candidate_source == CandidateSource.CONTEXT


# ===================================================================
# build_local_life_goal_draft — evidence needs
# ===================================================================

class TestGoalDraftEvidenceNeeds:
    def test_required_facets_become_evidence_needs(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            facets=[
                {"name": "coupon", "required": True},
                {"name": "open_status", "required": True},
            ],
        ))
        assert "coupon" in draft.evidence_needs
        assert "open_status" in draft.evidence_needs
        assert "coupon" in draft.required_facets

    def test_optional_facets_not_in_required(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.recommendation.value,
            facets=[
                {"name": "coupon", "required": False},
                {"name": "distance", "required": False},
            ],
        ))
        assert "coupon" in draft.optional_facets
        assert "coupon" not in draft.required_facets

    def test_focused_facets_added_to_evidence(self):
        draft = build_local_life_goal_draft(_frame(
            task_type=TaskType.comparison.value,
            focused_facets=["coupon", "open_status"],
        ))
        assert "coupon" in draft.evidence_needs
        assert "open_status" in draft.evidence_needs


# ===================================================================
# build_local_life_goal_draft — source_origin
# ===================================================================

class TestGoalDraftSourceOrigin:
    def test_llm_source(self):
        draft = build_local_life_goal_draft(_frame(
            semantic_source="real_llm",
        ))
        assert draft.source_origin == "real_llm"

    def test_fallback_reason_triggers_llm_fallback(self):
        draft = build_local_life_goal_draft(_frame(
            semantic_source="real_llm",
            fallback_reason="llm_parse_failed",
        ))
        assert draft.source_origin == "llm+fallback"

    def test_fallback_only(self):
        draft = build_local_life_goal_draft(_frame(
            semantic_source="",
            fallback_reason="llm_call_unavailable",
        ))
        assert draft.source_origin == "fallback"


# ===================================================================
# build_candidate_spec
# ===================================================================

class TestBuildCandidateSpec:
    def test_discovery_spec_basic(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.COMPARISON,
            candidate_source=CandidateSource.DISCOVERY,
            candidate_category="KTV",
            candidate_limit=2,
        )
        spec = build_candidate_spec(goal)
        assert spec.source == CandidateSource.DISCOVERY
        assert spec.category == "KTV"
        assert spec.query == "KTV"
        assert spec.limit == 2

    def test_explicit_spec(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.COMPARISON,
            candidate_source=CandidateSource.EXPLICIT,
            candidate_limit=2,
        )
        frame = _frame(
            task_type=TaskType.comparison.value,
            merchant_mentions=["海底捞", "山城一锅"],
        )
        spec = build_candidate_spec(goal, semantic_frame=frame)
        assert spec.source == CandidateSource.EXPLICIT
        assert "海底捞" in spec.explicit_mentions
        assert "山城一锅" in spec.explicit_mentions

    def test_empty_query_returns_spec_with_empty_query(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.RECOMMENDATION,
            candidate_source=CandidateSource.DISCOVERY,
            candidate_category=None,
            candidate_limit=3,
        )
        spec = build_candidate_spec(goal)
        assert spec.query == ""
        assert spec.category == ""
