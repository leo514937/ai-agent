"""Tests for staleness detection."""
from learning_agent_service.local_life.realtime_conflict_resolver import (
    detect_staleness,
    get_staleness_warning,
)


def test_detect_staleness_deprecated():
    metadata = {"deprecated": True}
    is_stale, reason = detect_staleness(metadata)
    assert is_stale
    assert reason == "deprecated"


def test_detect_staleness_stale():
    metadata = {"stale": True}
    is_stale, reason = detect_staleness(metadata)
    assert is_stale
    assert reason == "stale"


def test_detect_staleness_fresh():
    metadata = {"import_time": "2026-06-11T00:00:00+00:00"}
    is_stale, reason = detect_staleness(metadata)
    assert not is_stale


def test_get_staleness_warning_deprecated():
    warning = get_staleness_warning("deprecated", "海底捞")
    assert warning is not None
    assert "海底捞" in warning


def test_get_staleness_warning_stale():
    warning = get_staleness_warning("stale")
    assert warning is not None


def test_get_staleness_warning_age():
    warning = get_staleness_warning("age_100000")
    assert warning is not None