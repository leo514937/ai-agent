"""Tests for P2 ReplanPolicy — loop guards, counters, and suggestions."""

from __future__ import annotations

import pytest

from ..planning.replan_policy import (
    check_expand_search_allowed,
    check_replan_evidence_allowed,
    check_rewrite_allowed,
    increment_expand_search,
    increment_replan_evidence,
    increment_rewrite,
    get_expand_search_suggestions,
    get_replan_evidence_suggestions,
)
from ..domain.state import SessionState


def _session(**overrides: object) -> SessionState:
    defaults: dict = {
        "session_id": "test_sid",
        "user_id": "test_uid",
        "replan_counters": {"expand_search": 0, "replan_evidence": 0, "rewrite": 0},
    }
    defaults.update(overrides)
    return SessionState(**defaults)


class TestReplanCounters:
    def test_initial_counters_zero(self):
        """New session has zero counters."""
        ss = _session()
        assert ss.replan_counters.get("expand_search") == 0
        assert ss.replan_counters.get("replan_evidence") == 0
        assert ss.replan_counters.get("rewrite") == 0

    def test_increment_expand_search(self):
        """increment_expand_search increases counter by 1."""
        ss = _session()
        increment_expand_search(ss)
        assert ss.replan_counters["expand_search"] == 1
        increment_expand_search(ss)
        assert ss.replan_counters["expand_search"] == 2

    def test_increment_replan_evidence(self):
        """increment_replan_evidence increases counter by 1."""
        ss = _session()
        increment_replan_evidence(ss)
        assert ss.replan_counters["replan_evidence"] == 1

    def test_increment_rewrite(self):
        """increment_rewrite increases counter by 1."""
        ss = _session()
        increment_rewrite(ss)
        assert ss.replan_counters["rewrite"] == 1

    def test_increment_on_none_state_does_not_crash(self):
        """Calling increments with None does not crash."""
        increment_expand_search(None)
        increment_replan_evidence(None)
        increment_rewrite(None)


class TestExpandSearchAllowance:
    def test_expand_search_allowed_initially(self):
        """expand_search is allowed when counter < max."""
        ss = _session()
        allowed, reason = check_expand_search_allowed(ss)
        assert allowed
        assert "allowed" in reason

    def test_expand_search_disallowed_when_at_max(self):
        """expand_search is disallowed when counter >= max."""
        ss = _session(replan_counters={"expand_search": 999, "replan_evidence": 0, "rewrite": 0})
        allowed, reason = check_expand_search_allowed(ss)
        assert not allowed
        assert "limit reached" in reason

    def test_expand_search_allowed_from_dict(self):
        """Plain dict session state is also accepted."""
        state = {"replan_counters": {"expand_search": 0}}
        allowed, reason = check_expand_search_allowed(state)
        assert allowed

    def test_expand_search_allowed_no_state(self):
        """None session state → defaults to 0 → allowed."""
        allowed, reason = check_expand_search_allowed(None)
        assert allowed


class TestReplanEvidenceAllowance:
    def test_replan_evidence_allowed_initially(self):
        """replan_evidence is allowed when counter < max."""
        ss = _session()
        allowed, reason = check_replan_evidence_allowed(ss)
        assert allowed
        assert "allowed" in reason

    def test_replan_evidence_disallowed_when_at_max(self):
        """replan_evidence is disallowed when counter >= max."""
        ss = _session(replan_counters={"expand_search": 0, "replan_evidence": 999, "rewrite": 0})
        allowed, reason = check_replan_evidence_allowed(ss)
        assert not allowed
        assert "limit reached" in reason


class TestRewriteAllowance:
    def test_rewrite_allowed_initially(self):
        """rewrite is allowed when counter < max."""
        ss = _session()
        allowed, reason = check_rewrite_allowed(ss)
        assert allowed

    def test_rewrite_allowed_with_explicit_count(self):
        """Explicit rewrite count can override session state."""
        allowed, reason = check_rewrite_allowed(current_count=0)
        assert allowed

    def test_rewrite_disallowed_when_at_max(self):
        """rewrite is disallowed when counter >= max."""
        allowed, reason = check_rewrite_allowed(current_count=999)
        assert not allowed
        assert "limit reached" in reason


class TestSuggestions:
    def test_expand_search_suggestions_have_content(self):
        """get_expand_search_suggestions returns non-empty list."""
        suggestions = get_expand_search_suggestions()
        assert len(suggestions) >= 2
        assert any("category" in s for s in suggestions)

    def test_expand_search_suggestions_with_goal(self):
        """GoalPlan with category → includes category suggestion."""
        from ..domain.goal import GoalPlan
        gp = GoalPlan(goal_type="recommendation", candidate_category="hotpot")
        suggestions = get_expand_search_suggestions(gp)
        assert any("hotpot" in s for s in suggestions)

    def test_replan_evidence_suggestions_have_content(self):
        """get_replan_evidence_suggestions returns non-empty list."""
        suggestions = get_replan_evidence_suggestions()
        assert len(suggestions) >= 2

    def test_replan_evidence_suggestions_with_review(self):
        """EvidenceReview with failed facets → includes retry suggestion."""
        from ..domain.evidence import EvidenceReviewResult
        ev = EvidenceReviewResult(
            stage="evidence_review",
            status="insufficient",
            required_failed=["coupon"],
        )
        suggestions = get_replan_evidence_suggestions(ev)
        assert any("coupon" in s for s in suggestions)

    def test_replan_suggestions_include_unknown(self):
        """EvidenceReview with unknown facets → includes re-query suggestion."""
        from ..domain.evidence import EvidenceReviewResult
        ev = EvidenceReviewResult(
            stage="evidence_review",
            status="partial",
            required_unknown=["distance"],
        )
        suggestions = get_replan_evidence_suggestions(ev)
        assert any("distance" in s for s in suggestions)
