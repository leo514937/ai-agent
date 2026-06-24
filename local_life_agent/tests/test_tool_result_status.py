"""Tests for ToolResult status standardisation — ok/empty/unknown/failed/timeout/unsupported."""

from __future__ import annotations

from local_life_agent.domain.enums import ToolResultStatus
from local_life_agent.domain.evidence import ToolStatus, FINAL_STATUSES, FAILURE_STATUSES


class TestToolResultStatusEnum:
    def test_timeout_exists(self):
        assert ToolResultStatus.timeout.value == "timeout"

    def test_unsupported_exists(self):
        assert ToolResultStatus.unsupported.value == "unsupported"


class TestToolStatus:
    def test_all_required_values(self):
        assert ToolStatus.OK.value == "ok"
        assert ToolStatus.EMPTY.value == "empty"
        assert ToolStatus.UNKNOWN.value == "unknown"
        assert ToolStatus.FAILED.value == "failed"
        assert ToolStatus.TIMEOUT.value == "timeout"
        assert ToolStatus.UNSUPPORTED.value == "unsupported"

    def test_final_statuses(self):
        assert "ok" in FINAL_STATUSES
        assert "empty" in FINAL_STATUSES
        assert "unknown" not in FINAL_STATUSES
        assert "failed" not in FINAL_STATUSES

    def test_failure_statuses(self):
        assert "unknown" in FAILURE_STATUSES
        assert "failed" in FAILURE_STATUSES
        assert "timeout" in FAILURE_STATUSES
        assert "unsupported" in FAILURE_STATUSES
        assert "ok" not in FAILURE_STATUSES
        assert "empty" not in FAILURE_STATUSES


class TestResultSemanticsUpdated:
    """Verify that result_semantics constants include the new statuses."""

    def test_timeout_in_failure_constants(self):
        from local_life_agent.tools.result_semantics import TOOL_FAILURE_STATUSES
        assert "timeout" in TOOL_FAILURE_STATUSES
        assert "unsupported" in TOOL_FAILURE_STATUSES
