"""Tests for CandidateReview — deterministic sufficiency gate."""

from __future__ import annotations

import pytest

from ..domain.candidate import (
    CandidateSet,
    CandidateSource,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
)
from ..planning.candidate_review import (
    dedupe_candidates,
    min_required_for_goal,
    review_candidate_set,
)
from ..planning.review_policy import (
    NextAction,
    ReviewStatus,
    assert_p0_next_action_allowed,
)


def _candidate(shop_id: str, name: str, source: CandidateSource = CandidateSource.EXPLICIT) -> ResolvedCandidate:
    return ResolvedCandidate(
        shop_id=shop_id,
        shop_name=name,
        source=source,
    )


def _goal(goal_type: GoalType, **kw: object) -> LocalLifeGoalDraft:
    return LocalLifeGoalDraft(goal_type=goal_type, **kw)


def _set(candidates: list[ResolvedCandidate], status: CandidateStatus = CandidateStatus.RESOLVED,
         source: CandidateSource = CandidateSource.DISCOVERY, min_required: int = 1,
         max_allowed: int = 5) -> CandidateSet:
    return CandidateSet(
        status=status,
        source=source,
        candidates=candidates,
        min_required=min_required,
        max_allowed=max_allowed,
    )


# ===================================================================
# dedupe_candidates
# ===================================================================

class TestDedupe:
    def test_no_duplicates(self):
        candidates = [_candidate("s1", "A"), _candidate("s2", "B")]
        result = dedupe_candidates(candidates)
        assert len(result) == 2

    def test_duplicates_removed(self):
        candidates = [_candidate("s1", "A"), _candidate("s1", "A duplicate")]
        result = dedupe_candidates(candidates)
        assert len(result) == 1
        assert result[0].shop_id == "s1"

    def test_empty_shop_id_preserved(self):
        candidates = [
            _candidate("", "Unresolved A"),
            _candidate("", "Unresolved B"),
        ]
        result = dedupe_candidates(candidates)
        assert len(result) == 2

    def test_mixed_empty_and_real(self):
        candidates = [
            _candidate("", "Unresolved"),
            _candidate("s1", "Real A"),
            _candidate("s1", "Real A duplicate"),
        ]
        result = dedupe_candidates(candidates)
        assert len(result) == 2  # empty + real (deduped)


# ===================================================================
# min_required_for_goal
# ===================================================================

class TestMinRequired:
    def test_comparison_needs_2(self):
        goal = _goal(GoalType.COMPARISON)
        assert min_required_for_goal(goal) >= 2

    def test_single_shop_needs_1(self):
        goal = _goal(GoalType.SINGLE_SHOP_QUERY)
        assert min_required_for_goal(goal) == 1

    def test_recommendation_needs_1(self):
        goal = _goal(GoalType.RECOMMENDATION)
        assert min_required_for_goal(goal) == 1


# ===================================================================
# review_candidate_set — NOT_FOUND / AMBIGUOUS
# ===================================================================

class TestReviewStatusFailures:
    def test_not_found_returns_need_clarification(self):
        result = review_candidate_set(
            _goal(GoalType.COMPARISON),
            _set([], status=CandidateStatus.NOT_FOUND),
        )
        assert result.status == ReviewStatus.NEED_CLARIFICATION
        assert result.next_action == NextAction.CLARIFY

    def test_ambiguous_returns_need_clarification(self):
        result = review_candidate_set(
            _goal(GoalType.COMPARISON),
            _set([], status=CandidateStatus.AMBIGUOUS),
        )
        assert result.status == ReviewStatus.NEED_CLARIFICATION
        assert result.next_action == NextAction.CLARIFY


# ===================================================================
# review_candidate_set — discovery comparison
# ===================================================================

class TestDiscoveryComparison:
    def test_discovery_comparison_found_2_finish(self):
        """discovery comparison 找到2家 → FINISH"""
        candidates = [_candidate("s1", "KTV A", CandidateSource.DISCOVERY),
                      _candidate("s2", "KTV B", CandidateSource.DISCOVERY)]
        result = review_candidate_set(
            _goal(GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY),
            _set(candidates, source=CandidateSource.DISCOVERY, min_required=2),
        )
        assert result.status == ReviewStatus.ENOUGH
        assert result.next_action == NextAction.FINISH
        assert_p0_next_action_allowed(result)

    def test_discovery_comparison_found_1_clarify(self):
        """discovery comparison 只找到1家 → CLARIFY"""
        candidates = [_candidate("s1", "KTV A", CandidateSource.DISCOVERY)]
        result = review_candidate_set(
            _goal(GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY),
            _set(candidates, source=CandidateSource.DISCOVERY, min_required=2),
        )
        assert result.status == ReviewStatus.NEED_MORE_CANDIDATES
        assert result.next_action == NextAction.CLARIFY

    def test_discovery_comparison_found_0_clarify(self):
        candidates: list = []
        result = review_candidate_set(
            _goal(GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY),
            _set(candidates, source=CandidateSource.DISCOVERY, min_required=2),
        )
        assert result.status == ReviewStatus.NEED_MORE_CANDIDATES


# ===================================================================
# review_candidate_set — trimming
# ===================================================================

class TestTrimming:
    def test_auto_trim_when_exceeds_max_allowed(self):
        """对比10家，允许自动裁剪 → 保留5家，trimmed=True"""
        candidates = [
            _candidate(f"s{i}", f"Shop {i}", CandidateSource.DISCOVERY)
            for i in range(10)
        ]
        result = review_candidate_set(
            _goal(GoalType.COMPARISON, candidate_source=CandidateSource.DISCOVERY, candidate_limit=10),
            _set(candidates, source=CandidateSource.DISCOVERY, max_allowed=5),
        )
        assert result.status == ReviewStatus.ENOUGH
        assert result.next_action == NextAction.FINISH
        assert result.trace_payload.get("trimmed") is True
        assert result.trace_payload.get("original_count") == 10
        assert result.trace_payload.get("kept_count") == 5

    def test_within_limit_no_trim(self):
        candidates = [_candidate("s1", "A"), _candidate("s2", "B")]
        result = review_candidate_set(
            _goal(GoalType.COMPARISON),
            _set(candidates, max_allowed=5),
        )
        assert result.status == ReviewStatus.ENOUGH
        assert result.next_action == NextAction.FINISH
        assert not result.trace_payload.get("trimmed")


# ===================================================================
# review_candidate_set — single shop query
# ===================================================================

class TestSingleShop:
    def test_single_shop_unique_ok(self):
        candidates = [_candidate("s1", "Single Shop")]
        result = review_candidate_set(
            _goal(GoalType.SINGLE_SHOP_QUERY),
            _set(candidates),
        )
        assert result.status == ReviewStatus.ENOUGH

    def test_single_shop_multiple_needs_clarification(self):
        """单店查询解析出多个候选 → NEED_CLARIFICATION"""
        candidates = [_candidate("s1", "Shop A"), _candidate("s2", "Shop B")]
        result = review_candidate_set(
            _goal(GoalType.SINGLE_SHOP_QUERY),
            _set(candidates),
        )
        assert result.status == ReviewStatus.NEED_CLARIFICATION
        assert result.next_action == NextAction.CLARIFY


# ===================================================================
# review_candidate_set — mixed dedup
# ===================================================================

class TestMixedDedup:
    def test_mixed_dedup_insufficient(self):
        """mixed 去重后不足2家 → 不能继续比较"""
        candidates = [
            _candidate("s1", "海底捞", CandidateSource.EXPLICIT),
            _candidate("s1", "海底捞", CandidateSource.DISCOVERY),  # duplicate
        ]
        result = review_candidate_set(
            _goal(GoalType.COMPARISON, candidate_source=CandidateSource.MIXED),
            _set(candidates, source=CandidateSource.MIXED, min_required=2),
        )
        assert result.status == ReviewStatus.NEED_MORE_CANDIDATES
        assert result.next_action == NextAction.CLARIFY


# ===================================================================
# P0 next_action assertion tests
# ===================================================================

class TestP0NextAction:
    def test_expand_search_fails_p0_assertion(self):
        candidates = [_candidate("s1", "A")]
        from ..planning.review_policy import (
            NextAction, ReviewStage, ReviewStatus, SufficiencyCheckResult,
        )
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_CANDIDATES,
            next_action=NextAction.EXPAND_SEARCH,
        )
        with pytest.raises(ValueError, match="P0 forbids"):
            assert_p0_next_action_allowed(result)

    def test_replan_evidence_fails_p0_assertion(self):
        from ..planning.review_policy import (
            NextAction, ReviewStage, ReviewStatus, SufficiencyCheckResult,
        )
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_EVIDENCE,
            next_action=NextAction.REPLAN_EVIDENCE,
        )
        with pytest.raises(ValueError, match="P0 forbids"):
            assert_p0_next_action_allowed(result)
