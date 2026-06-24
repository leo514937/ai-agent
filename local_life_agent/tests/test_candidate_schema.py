"""Unit tests for P0 candidate & review schemas."""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from ..domain.candidate import (
    CandidateSet,
    CandidateSpec,
    CandidateSource,
    CandidateStatus,
    GoalType,
    LocalLifeGoalDraft,
    ResolvedCandidate,
)
from ..planning.review_policy import (
    NextAction,
    P0_ALLOWED_NEXT_ACTIONS,
    ReviewStage,
    ReviewStatus,
    SufficiencyCheckResult,
    assert_p0_next_action_allowed,
)


# ===================================================================
# CandidateStatus enum
# ===================================================================

class TestCandidateStatus:
    def test_values(self):
        assert CandidateStatus.RESOLVED.value == "resolved"
        assert CandidateStatus.AMBIGUOUS.value == "ambiguous"
        assert CandidateStatus.NOT_FOUND.value == "not_found"
        assert CandidateStatus.PARTIAL.value == "partial"
        assert CandidateStatus.TOO_MANY.value == "too_many"
        assert CandidateStatus.NEED_CLARIFICATION.value == "need_clarification"
        assert len(CandidateStatus) == 6

    def test_serialization(self):
        assert CandidateStatus("resolved") == CandidateStatus.RESOLVED
        assert CandidateStatus("not_found") == CandidateStatus.NOT_FOUND

    def test_json_roundtrip(self):
        data = json.dumps({"status": CandidateStatus.RESOLVED.value})
        restored = json.loads(data)
        assert CandidateStatus(restored["status"]) == CandidateStatus.RESOLVED


# ===================================================================
# CandidateSource enum
# ===================================================================

class TestCandidateSource:
    def test_values(self):
        assert CandidateSource.EXPLICIT.value == "explicit"
        assert CandidateSource.CONTEXT.value == "context"
        assert CandidateSource.DISCOVERY.value == "discovery"
        assert CandidateSource.MIXED.value == "mixed"
        assert len(CandidateSource) == 4

    def test_json_roundtrip(self):
        data = json.dumps({"source": CandidateSource.DISCOVERY.value})
        restored = json.loads(data)
        assert CandidateSource(restored["source"]) == CandidateSource.DISCOVERY


# ===================================================================
# GoalType enum
# ===================================================================

class TestGoalType:
    def test_values(self):
        assert GoalType.RECOMMENDATION.value == "recommendation"
        assert GoalType.COMPARISON.value == "comparison"
        assert GoalType.SINGLE_SHOP_QUERY.value == "single_shop_query"
        assert GoalType.REFINEMENT.value == "refinement"
        assert GoalType.UNSUPPORTED.value == "unsupported"
        assert len(GoalType) == 5

    def test_json_roundtrip(self):
        data = json.dumps({"goal": GoalType.COMPARISON.value})
        restored = json.loads(data)
        assert GoalType(restored["goal"]) == GoalType.COMPARISON


# ===================================================================
# LocalLifeGoalDraft
# ===================================================================

class TestLocalLifeGoalDraft:
    def test_defaults(self):
        draft = LocalLifeGoalDraft()
        assert draft.goal_type == GoalType.UNSUPPORTED
        assert draft.candidate_source == CandidateSource.DISCOVERY
        assert draft.candidate_category is None
        assert draft.candidate_limit is None
        assert draft.evidence_needs == []
        assert draft.required_facets == []
        assert draft.optional_facets == []
        assert draft.max_candidates == 5
        assert draft.source_origin == "llm"

    def test_comparison_draft(self):
        draft = LocalLifeGoalDraft(
            goal_type=GoalType.COMPARISON,
            candidate_source=CandidateSource.DISCOVERY,
            candidate_category="KTV",
            candidate_limit=2,
            evidence_needs=["coupon_list", "open_status"],
            required_facets=["coupon_list", "open_status"],
        )
        assert draft.goal_type == GoalType.COMPARISON
        assert draft.candidate_limit == 2
        assert "coupon_list" in draft.evidence_needs

    def test_json_roundtrip(self):
        draft = LocalLifeGoalDraft(
            goal_type=GoalType.RECOMMENDATION,
            candidate_source=CandidateSource.DISCOVERY,
            candidate_category="火锅",
            candidate_limit=3,
        )
        data = draft.model_dump_json()
        restored = LocalLifeGoalDraft.model_validate_json(data)
        assert restored == draft

    def test_invalid_goal_type_string_fails(self):
        with pytest.raises(ValidationError):
            LocalLifeGoalDraft.model_validate({"goal_type": "invalid_goal"})


# ===================================================================
# CandidateSpec
# ===================================================================

class TestCandidateSpec:
    def test_defaults(self):
        spec = CandidateSpec()
        assert spec.source == CandidateSource.DISCOVERY
        assert spec.category == ""
        assert spec.query == ""
        assert spec.explicit_mentions == []

    def test_explicit_spec(self):
        spec = CandidateSpec(
            source=CandidateSource.EXPLICIT,
            category="火锅",
            explicit_mentions=["海底捞", "山城一锅"],
        )
        assert spec.source == CandidateSource.EXPLICIT
        assert len(spec.explicit_mentions) == 2

    def test_discovery_spec(self):
        spec = CandidateSpec(
            source=CandidateSource.DISCOVERY,
            category="KTV",
            query="KTV",
            sort_by=[{"field": "rating", "order": "desc"}],
            limit=2,
            filters={"nearby": True},
        )
        assert spec.query == "KTV"
        assert spec.sort_by == [{"field": "rating", "order": "desc"}]
        assert spec.limit == 2

    def test_json_roundtrip(self):
        spec = CandidateSpec(
            source=CandidateSource.EXPLICIT,
            category="火锅",
            explicit_mentions=["海底捞"],
        )
        data = spec.model_dump_json()
        restored = CandidateSpec.model_validate_json(data)
        assert restored == spec


# ===================================================================
# ResolvedCandidate
# ===================================================================

class TestResolvedCandidate:
    def test_defaults(self):
        rc = ResolvedCandidate()
        assert rc.shop_id == ""
        assert rc.shop_name == ""
        assert rc.source == CandidateSource.DISCOVERY
        assert rc.confidence == 1.0

    def test_with_values(self):
        rc = ResolvedCandidate(
            shop_id="shop_001",
            shop_name="海底捞(牡丹园店)",
            source=CandidateSource.EXPLICIT,
            rank=1,
            confidence=0.95,
            rating=4.8,
        )
        assert rc.shop_id == "shop_001"
        assert rc.rating == 4.8

    def test_json_roundtrip(self):
        rc = ResolvedCandidate(
            shop_id="shop_001",
            shop_name="Test Shop",
            source=CandidateSource.EXPLICIT,
        )
        data = rc.model_dump_json()
        restored = ResolvedCandidate.model_validate_json(data)
        assert restored == rc


# ===================================================================
# CandidateSet
# ===================================================================

class TestCandidateSet:
    def test_defaults(self):
        cs = CandidateSet()
        assert cs.status == CandidateStatus.NOT_FOUND
        assert cs.candidates == []
        assert cs.min_required == 2
        assert cs.max_allowed == 5

    def test_resolved_set(self):
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.DISCOVERY,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="KTV A", source=CandidateSource.DISCOVERY, rank=1),
                ResolvedCandidate(shop_id="s2", shop_name="KTV B", source=CandidateSource.DISCOVERY, rank=2),
            ],
            min_required=2,
            max_allowed=5,
        )
        assert len(cs.candidates) == 2
        assert cs.status == CandidateStatus.RESOLVED

    def test_not_found_set(self):
        cs = CandidateSet(
            status=CandidateStatus.NOT_FOUND,
            source=CandidateSource.DISCOVERY,
            candidates=[],
        )
        assert cs.status == CandidateStatus.NOT_FOUND
        assert len(cs.candidates) == 0

    def test_json_roundtrip(self):
        cs = CandidateSet(
            status=CandidateStatus.RESOLVED,
            source=CandidateSource.EXPLICIT,
            candidates=[
                ResolvedCandidate(shop_id="s1", shop_name="Shop A", source=CandidateSource.EXPLICIT),
            ],
        )
        data = cs.model_dump_json()
        restored = CandidateSet.model_validate_json(data)
        assert restored == cs
        assert restored.candidates[0].shop_id == "s1"

    def test_min_required_default_not_overwritten(self):
        """Verify that default min_required/max_allowed survive partial construction."""
        cs = CandidateSet(status=CandidateStatus.RESOLVED, source=CandidateSource.EXPLICIT)
        assert cs.min_required == 2
        assert cs.max_allowed == 5


# ===================================================================
# Review Policy
# ===================================================================

class TestReviewStage:
    def test_values(self):
        assert ReviewStage.CANDIDATE_REVIEW.value == "candidate_review"
        assert len(ReviewStage) == 5


class TestReviewStatus:
    def test_values(self):
        assert ReviewStatus.ENOUGH.value == "enough"
        assert ReviewStatus.NEED_MORE_CANDIDATES.value == "need_more_candidates"
        assert len(ReviewStatus) == 7


class TestNextAction:
    def test_values(self):
        assert NextAction.FINISH.value == "FINISH"
        assert NextAction.CLARIFY.value == "CLARIFY"
        assert NextAction.FALLBACK.value == "FALLBACK"

    def test_p0_allowed_set(self):
        assert NextAction.FINISH in P0_ALLOWED_NEXT_ACTIONS
        assert NextAction.CLARIFY in P0_ALLOWED_NEXT_ACTIONS
        assert NextAction.FALLBACK in P0_ALLOWED_NEXT_ACTIONS
        assert NextAction.EXPAND_SEARCH not in P0_ALLOWED_NEXT_ACTIONS
        assert NextAction.REPLAN_EVIDENCE not in P0_ALLOWED_NEXT_ACTIONS
        assert NextAction.DEGRADE_ANSWER not in P0_ALLOWED_NEXT_ACTIONS


class TestSufficiencyCheckResult:
    def test_defaults(self):
        result = SufficiencyCheckResult()
        assert result.stage == ReviewStage.CANDIDATE_REVIEW
        assert result.status == ReviewStatus.ENOUGH
        assert result.next_action == NextAction.FINISH
        assert result.reason == ""
        assert result.confidence == "medium"

    def test_need_more_candidates(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_CANDIDATES,
            next_action=NextAction.CLARIFY,
            reason="discovery found only 1 of 2 required candidates",
        )
        assert result.status == ReviewStatus.NEED_MORE_CANDIDATES
        assert result.next_action == NextAction.CLARIFY

    def test_trimmed(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.ENOUGH,
            next_action=NextAction.FINISH,
            reason="trimmed from 10 to 5",
            trace_payload={"trimmed": True, "original_count": 10, "kept_count": 5},
        )
        assert result.trace_payload["original_count"] == 10
        assert result.trace_payload["kept_count"] == 5

    def test_json_roundtrip(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.ENOUGH,
            next_action=NextAction.FINISH,
            reason="2 candidates resolved",
        )
        data = result.model_dump_json()
        restored = SufficiencyCheckResult.model_validate_json(data)
        assert restored == result

    def test_p0_assertion_passes_for_finish(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.ENOUGH,
            next_action=NextAction.FINISH,
        )
        assert_p0_next_action_allowed(result)  # must not raise

    def test_p0_assertion_passes_for_clarify(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_CLARIFICATION,
            next_action=NextAction.CLARIFY,
        )
        assert_p0_next_action_allowed(result)

    def test_p0_assertion_fails_for_expand_search(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_CANDIDATES,
            next_action=NextAction.EXPAND_SEARCH,
        )
        with pytest.raises(ValueError, match="P0 forbids next_action"):
            assert_p0_next_action_allowed(result)

    def test_p0_assertion_fails_for_replan_evidence(self):
        result = SufficiencyCheckResult(
            stage=ReviewStage.CANDIDATE_REVIEW,
            status=ReviewStatus.NEED_MORE_EVIDENCE,
            next_action=NextAction.REPLAN_EVIDENCE,
        )
        with pytest.raises(ValueError, match="P0 forbids next_action"):
            assert_p0_next_action_allowed(result)


# ===================================================================
# No mixed status strings
# ===================================================================

class TestNoStatusMixing:
    """Key states must use enums, not free strings."""

    def test_candidate_status_not_mixed(self):
        """CandidateStatus values must not collide with ReviewStatus values."""
        candidate_values = {e.value for e in CandidateStatus}
        review_values = {e.value for e in ReviewStatus}
        # "resolved" and "enough" must not overlap
        assert "resolved" not in review_values
        assert "enough" not in candidate_values
        assert "not_found" not in review_values
        assert "need_more_candidates" not in candidate_values
