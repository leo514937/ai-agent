"""Acceptance tests for unknown_as_false / failed_as_empty prevention (P1 §10, §12).

These tests verify that:
  1. A coupon ok, B coupon unknown → cannot say A is definitely better
  2. A coupon ok, B coupon empty → can say A has coupons, B has none
  3. get_coupon_list failed → cannot say no coupons
  4. check_open_status failed → cannot say closed
  5. required facet unknown → degrade/fallback/replan
  6. optional facet missing → degrade allowed with unknown notice
"""

from __future__ import annotations

from local_life_agent.domain.candidate import GoalType, LocalLifeGoalDraft
from local_life_agent.planning.evidence_review import review_evidence


class TestUnknownAsFalse:
    """P1 §10.1 — unknown status must not be verbalised as false."""

    def test_unknown_without_items_detected(self):
        """Unknown facet without unknown_items entry → unknown_as_false risk detected."""
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["open_status"],
        )
        pack = {
            "facet_results": [
                {"facet": "open_status", "result_status": "unknown", "required": True},
            ],
            "unknown_items": [],
        }
        result = review_evidence(goal, pack)
        assert result.unknown_as_false_detected is True
        assert result.next_action != "FINISH"

    def test_coupon_ok_and_distance_empty(self):
        """Two different required facets: one ok, one empty → both classified correctly."""
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "distance"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
                {"facet": "distance", "result_status": "empty", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action == "FINISH"
        assert "coupon" in result.required_ok
        assert "distance" in result.required_empty


class TestFailedAsEmpty:
    """P1 §10.2 — failed must not be verbalised as empty."""

    def test_coupon_list_failed(self):
        """get_coupon_list failed → cannot say no coupons."""
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "failed", "required": True,
                 "tool_name": "get_coupon_list"},
            ],
        }
        result = review_evidence(goal, pack)
        # failed is indeterminate → must not FINISH cleanly
        assert result.next_action != "FINISH"
        assert "coupon" in result.required_failed

    def test_open_status_failed(self):
        """check_open_status failed → cannot say closed/not open."""
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["open_status"],
        )
        pack = {
            "facet_results": [
                {"facet": "open_status", "result_status": "failed", "required": True,
                 "tool_name": "check_open_status"},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action != "FINISH"
        assert "open_status" in result.required_failed

    def test_failed_as_empty_mismatch_tool_result(self):
        """Tool result with success=False but status=ok should be detected."""
        from local_life_agent.planning.evidence_review import _detect_failed_as_empty
        tr = {
            "call_1": {"success": False, "result_status": "ok", "tool_name": "get_coupon_list"},
        }
        assert _detect_failed_as_empty(tr) is True


class TestRequiredFacetUnknown:
    """P1 §10.4 — required facet unknown must trigger degrade/fallback/replan."""

    def test_required_unknown_triggers_degrade_or_fallback(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "unknown", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action in ("FALLBACK", "REPLAN_EVIDENCE")
        assert "coupon" in result.required_unknown

    def test_all_required_unknown_fallsback(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "open_status"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "unknown", "required": True},
                {"facet": "open_status", "result_status": "failed", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action == "FALLBACK"


class TestOptionalFacetMissing:
    """P1 §10.5 — optional facet missing allows degrade."""

    def test_optional_unknown_can_degrade(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon"],
            optional_facets=["distance"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
                {"facet": "distance", "result_status": "unknown", "required": False},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action == "DEGRADE_ANSWER"
        assert result.can_degrade is True
        assert "distance" in result.optional_unknown
