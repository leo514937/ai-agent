"""Tests for EvidenceReview — evidence sufficiency checks, unknown_as_false, failed_as_empty."""

from __future__ import annotations

import pytest

from local_life_agent.domain.candidate import GoalType, LocalLifeGoalDraft
from local_life_agent.domain.evidence import EvidenceReviewResult, ToolStatus
from local_life_agent.planning.evidence_review import (
    _classify_status,
    _detect_failed_as_empty,
    _detect_unknown_as_false,
    review_evidence,
)


class TestClassifyStatus:
    def test_ok_and_partial_map_to_ok(self):
        assert _classify_status("ok") == ToolStatus.OK
        assert _classify_status("partial") == ToolStatus.OK

    def test_empty_maps_to_empty(self):
        assert _classify_status("empty") == ToolStatus.EMPTY

    def test_failure_statuses_map_to_failed(self):
        for s in ("failed", "error", "circuit_open", "backend_unavailable"):
            assert _classify_status(s) == ToolStatus.FAILED, f"{s} should map to FAILED"

    def test_timeout_maps_to_timeout(self):
        assert _classify_status("timeout") == ToolStatus.TIMEOUT

    def test_unsupported_maps_to_unsupported(self):
        assert _classify_status("unsupported") == ToolStatus.UNSUPPORTED

    def test_unknown_maps_to_unknown(self):
        assert _classify_status("unknown") == ToolStatus.UNKNOWN
        assert _classify_status("garbage") == ToolStatus.UNKNOWN
        assert _classify_status("") == ToolStatus.UNKNOWN


class TestReviewEvidenceRequiredOk:
    """Required facets all OK → FINISH."""

    def test_all_required_ok_finish(self):
        goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action == "FINISH"
        assert result.status == "sufficient"
        assert "coupon" in result.required_ok

    def test_all_required_empty_finish(self):
        goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "empty", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action == "FINISH"
        assert "coupon" in result.required_empty


class TestReviewEvidenceRequiredUnknown:
    """Required facets unknown/failed → DEGRADE_ANSWER or FALLBACK."""

    def test_required_unknown_with_ok_degrade(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon", "open_status"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
                {"facet": "open_status", "result_status": "unknown", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        assert result.next_action in ("DEGRADE_ANSWER", "REPLAN_EVIDENCE")
        assert result.status in ("degraded_with_warnings", "partial_insufficient")
        assert "open_status" in result.required_unknown

    def test_all_required_unknown_fallback(self):
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
        assert result.status == "insufficient"
        assert "coupon" in result.required_unknown
        assert "open_status" in result.required_failed

    def test_no_required_facets_finish(self):
        goal = LocalLifeGoalDraft(goal_type=GoalType.RECOMMENDATION, required_facets=[])
        pack = {"facet_results": []}
        result = review_evidence(goal, pack)
        assert result.next_action == "FINISH"
        assert result.reason == "no_required_facets"


class TestReviewEvidenceOptional:
    """Optional facets → DEGRADE_ANSWER allowed."""

    def test_optional_unknown_degrade(self):
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


class TestDetectUnknownAsFalse:
    def test_unknown_without_unknown_items_detected(self):
        goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "unknown", "required": True},
            ],
            "unknown_items": [],
        }
        result = review_evidence(goal, pack)
        assert result.unknown_as_false_detected is True

    def test_unknown_with_unknown_items_not_detected(self):
        goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "unknown", "required": True},
            ],
            "unknown_items": [{"facet": "coupon", "reason": "timeout"}],
        }
        result = review_evidence(goal, pack)
        # unknown_as_false depends on missing unknown_items coverage
        assert result.unknown_as_false_detected is False


class TestDetectFailedAsEmpty:
    def test_failed_but_status_ok_detected(self):
        tool_results = {
            "call_1": {
                "tool_name": "get_coupon_list",
                "success": False,
                "result_status": "ok",  # mismatch: success=False but status=ok
            },
        }
        assert _detect_failed_as_empty(tool_results) is True

    def test_failed_with_correct_status_not_detected(self):
        tool_results = {
            "call_1": {
                "tool_name": "get_coupon_list",
                "success": False,
                "result_status": "failed",
                "error_code": "TOOL_TIMEOUT",
            },
        }
        assert _detect_failed_as_empty(tool_results) is False


class TestReviewEvidenceTrace:
    def test_trace_payload_contains_all_fields(self):
        goal = LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            required_facets=["coupon"],
            optional_facets=["distance"],
        )
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "failed", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        trace = result.trace_payload
        assert "required" in trace
        assert "optional" in trace
        assert "next_action" in trace
        # failed status without unknown_items entry → unknown_as_false detected
        assert trace["unknown_as_false_detected"] is True
        assert trace["next_action"] in ("FALLBACK",)

    def test_review_result_serializable(self):
        goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
            ],
        }
        result = review_evidence(goal, pack)
        dumped = result.model_dump()
        assert dumped["next_action"] == "FINISH"
        assert dumped["stage"] == "evidence_review"

    def test_review_evidence_does_not_print_debug_output(self, capsys: pytest.CaptureFixture[str]):
        goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, required_facets=["coupon"])
        pack = {
            "facet_results": [
                {"facet": "coupon", "result_status": "ok", "required": True},
            ],
        }
        review_evidence(goal, pack)
        captured = capsys.readouterr()
        assert captured.out == ""
