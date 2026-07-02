from __future__ import annotations

from typing import Any

import pytest

from local_life_agent.tests.fixtures.complex_query_matrix import (
    CASE_BY_NAME,
    P6_COMPLEX_QUERY_MATRIX_CASES,
    P6_SMOKE_CASES,
)
from local_life_agent.tests.helpers.complex_query_harness import (
    response_debug,
    run_case_turns,
    load_golden_trace,
)


def _to_name_list(items: Any) -> list[str]:
    names: list[str] = []
    if not items:
        return names
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("facet") or item.get("shop_name") or item.get("shop_id") or "").strip()
        else:
            name = str(item).strip()
        if name:
            names.append(name)
    return names


def _semantic_facets(state: dict[str, Any], debug: dict[str, Any]) -> list[str]:
    semantic = state.get("semantic_frame") or debug.get("semantic_frame") or {}
    facet_set = semantic.get("facet_set") or {}
    facets = semantic.get("facets") or facet_set.get("facets") or []
    return _to_name_list(facets)


def _triage_names(state: dict[str, Any], key: str) -> list[str]:
    evidence = state.get("evidence_pack") or {}
    return _to_name_list(evidence.get(key) or [])


def _state_update_set_fields(state: dict[str, Any]) -> dict[str, Any]:
    update_plan = state.get("state_update_plan") or {}
    return dict(update_plan.get("set_fields") or {})


def _state_update_clear_fields(state: dict[str, Any]) -> list[str]:
    update_plan = state.get("state_update_plan") or {}
    return [str(item) for item in (update_plan.get("clear_fields") or []) if str(item).strip()]


def _session_after(state: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    return state.get("session_state_after") or debug.get("session_state_after") or {}


def _trace_loaded(case: dict[str, Any]) -> dict[str, Any]:
    trace = load_golden_trace(str(case["golden_trace"]))
    assert trace["query"] == (case.get("query") or (case.get("turns") or [""])[0])
    assert "expected" in trace
    assert "workflow_name" in trace["expected"]
    assert "facets" in trace["expected"]
    assert "target_resolution" in trace["expected"]
    assert "state_update_expectations" in trace["expected"]
    return trace


def _assert_not_writeback(session_after: dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert not session_after.get(field), field


@pytest.mark.parametrize("case", P6_COMPLEX_QUERY_MATRIX_CASES, ids=[case["name"] for case in P6_COMPLEX_QUERY_MATRIX_CASES])
def test_p6_complex_query_matrix(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    records, backend = run_case_turns(case, monkeypatch)
    assert records

    _trace_loaded(case)

    if case["name"] == "clarification_resume":
        assert len(records) == 2
        first_response, first_state = records[0]
        second_response, second_state = records[1]
        first_debug = response_debug(first_response)
        second_debug = response_debug(second_response)
        first_session = _session_after(first_state, first_debug)
        second_session = _session_after(second_state, second_debug)

        assert first_state.get("workflow_name") == "discovery_decision"
        assert first_state.get("response_mode") == "clarify"
        assert first_session.get("pending_clarification") is not None
        assert first_session.get("current_shop") is None

        assert second_state.get("response_mode") == "clarify"
        assert second_session.get("pending_clarification") is not None
        assert second_session.get("current_shop") is None
        assert second_session.get("last_recommendation_list") in (None, [])
        return

    if case["name"] == "conflicting_multi_turn_preference":
        assert len(records) == 2
        first_response, first_state = records[0]
        second_response, second_state = records[1]
        first_debug = response_debug(first_response)
        second_debug = response_debug(second_response)
        first_session = _session_after(first_state, first_debug)
        second_session = _session_after(second_state, second_debug)

        assert first_state.get("workflow_name") == "discovery_decision"
        assert first_state.get("response_mode") == "answer"
        assert first_session.get("last_recommendation_list")

        assert second_state.get("response_mode") == "clarify"
        assert second_session.get("last_recommendation_list")
        assert second_session.get("current_shop") is None
        return

    response, state = records[-1]
    debug = response_debug(response)
    session_after = _session_after(state, debug)
    semantic_facets = _semantic_facets(state, debug)
    update_set_fields = _state_update_set_fields(state)
    update_clear_fields = _state_update_clear_fields(state)
    evidence_pack = state.get("evidence_pack") or {}
    answer_plan = state.get("answer_plan") or {}

    assert state.get("state_update_plan") is not None
    assert state.get("response_mode") in {"answer", "clarify", "direct"}

    if case["name"] == "multi_constraint_recommendation":
        assert state.get("workflow_name") == "discovery_decision"
        assert state.get("response_mode") == "clarify"
        assert session_after.get("pending_clarification") is not None
        _assert_not_writeback(session_after, "current_shop", "last_recommendation_list", "comparison_targets")

    elif case["name"] == "multi_dimensional_comparison":
        assert state.get("workflow_name") == "discovery_decision"
        assert state.get("response_mode") == "answer"
        assert (state.get("target_resolution") or {}).get("resolved") is True
        assert len(session_after.get("comparison_targets") or []) >= 2
        assert session_after.get("current_shop") is None
        assert update_set_fields.get("comparison_targets") is not None or session_after.get("comparison_targets")

    elif case["name"] == "single_shop_multi_facet":
        assert state.get("workflow_name") in {"discovery_decision", "deterministic_tool"}
        assert state.get("response_mode") == "answer"
        assert (state.get("target_resolution") or {}).get("resolved") is True
        assert (state.get("target_resolution") or {}).get("source") == "current_shop"
        assert "distance" in _triage_names(state, "answerable_facets")
        assert session_after.get("current_shop") is not None
        assert session_after.get("comparison_targets") in (None, [])
        assert "current_shop" in update_set_fields or session_after.get("current_shop") is not None

    elif case["name"] == "reference_failure":
        assert state.get("response_mode") == "clarify"
        assert session_after.get("pending_clarification") is not None
        _assert_not_writeback(session_after, "current_shop", "last_recommendation_list", "comparison_targets")

    elif case["name"] == "recommendation_plus_reference_dependency":
        assert state.get("workflow_name") == "deterministic_tool"
        assert state.get("response_mode") == "direct"
        assert "distance" in semantic_facets
        assert (state.get("target_resolution") or {}).get("resolved") is True
        assert session_after.get("current_shop") is not None
        assert session_after.get("last_recommendation_list") is not None

    elif case["name"] == "partial_tool_failure":
        assert state.get("workflow_name") == "discovery_decision"
        assert state.get("response_mode") == "answer"
        assert "coupon" in _triage_names(state, "failed_facets")
        assert "distance" in _triage_names(state, "answerable_facets")
        assert session_after.get("current_shop") is not None
        assert session_after.get("last_recommendation_list") in (None, [])

    elif case["name"] == "empty_search_result":
        assert state.get("workflow_name") == "discovery_decision"
        assert state.get("response_mode") == "clarify"
        assert (state.get("target_resolution") or {}).get("resolved") is False
        assert session_after.get("pending_clarification") is not None
        _assert_not_writeback(session_after, "current_shop", "last_recommendation_list", "comparison_targets")

    elif case["name"] == "answer_verify_failure":
        assert state.get("workflow_name") == "discovery_decision"
        assert state.get("response_mode") == "answer"
        assert state.get("answer_verify_passed") is False
        assert state.get("rewrite_count", 0) >= 1
        assert state.get("final_safety_status") == "fallback"
        assert "coupon" in _triage_names(state, "answerable_facets")
        assert "distance" in _triage_names(state, "answerable_facets")
        assert session_after.get("current_shop") is not None
        assert update_set_fields.get("current_shop") is not None

    else:
        pytest.fail(f"Unhandled P6 matrix case: {case['name']}")


@pytest.mark.parametrize("case", P6_SMOKE_CASES, ids=[case["name"] for case in P6_SMOKE_CASES])
def test_p6_smoke_cases(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    records, backend = run_case_turns(case, monkeypatch)
    assert records

    response, state = records[-1]
    debug = response_debug(response)
    session_after = _session_after(state, debug)
    semantic_facets = _semantic_facets(state, debug)

    assert state.get("state_update_plan") is not None
    assert state.get("response_mode") in {"answer", "clarify", "direct"}

    if case["name"] == "all_tools_timeout_smoke":
        assert state.get("workflow_name") == "discovery_decision"
        assert "coupon" in _triage_names(state, "failed_facets")
        assert "distance" in _triage_names(state, "failed_facets")
        assert session_after.get("current_shop") is not None

    elif case["name"] == "malformed_llm_output_smoke":
        assert state.get("workflow_name") in {"clarification_fallback", "discovery_decision", "direct_response"}
        assert backend.tool_calls == []
        assert not (state.get("comparison_targets") or [])
        assert not (session_after.get("last_recommendation_list") or [])

    elif case["name"] == "contradictory_multi_turn_smoke":
        assert len(records) == 2
        first_response, first_state = records[0]
        second_response, second_state = records[1]
        first_debug = response_debug(first_response)
        second_debug = response_debug(second_response)
        assert _session_after(second_state, second_debug).get("last_recommendation_list") is not None
        assert _session_after(second_state, second_debug).get("current_shop") is None
    else:
        pytest.fail(f"Unhandled P6 smoke case: {case['name']}")
