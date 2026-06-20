"""Regression tests for the multi-shop comparison flow."""

from __future__ import annotations

import pytest

from ..agent import run_agent_graph
from ..engine import graph_builder
from ..session.store import reset_session_store
from ..tools.mock_tools import check_open_status, get_coupon_list, get_distance_eta, get_shop_detail, resolve_shop, search_shops


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    reset_session_store()
    yield
    reset_session_store()


def _comparison_dispatch(tool_name: str, args: dict) -> dict:
    if tool_name == "search_shops":
        return search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
    if tool_name == "get_shop_detail":
        return get_shop_detail(str(args.get("shop_id", "")))
    if tool_name == "check_open_status":
        return check_open_status(str(args.get("shop_id", "")))
    if tool_name == "get_coupon_list":
        return get_coupon_list(str(args.get("shop_id", "")))
    if tool_name == "get_distance_eta":
        return get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
    raise AssertionError(f"Unexpected tool: {tool_name}")


def _comparison_dispatch_with_unknown_coupon(target_shop_id: str):
    def _dispatch(tool_name: str, args: dict) -> dict:
        if tool_name == "get_coupon_list" and str(args.get("shop_id", "")) == target_shop_id:
            return {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": "coupon unknown",
            }
        return _comparison_dispatch(tool_name, args)

    return _dispatch


def test_direct_comparison_builds_matrix_and_answer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)

    response = run_agent_graph("海底捞(牡丹园店)和川味轩(知春路店)对比一下", "cmp_direct")

    assert response.debug is not None
    plan = response.debug.execution_plan
    matrix = response.debug.evidence_pack.get("comparison_matrix") or {}

    assert plan.get("task_type") == "comparison"
    assert len(plan.get("tool_calls", [])) >= 4
    assert len(matrix.get("rows", [])) == 2
    assert matrix.get("dimension_winners") is not None
    assert "海底捞" in response.answer_text
    assert "川味轩" in response.answer_text
    assert "对比" in response.answer_text


def test_comparison_preserves_unknown_coupon_status(monkeypatch: pytest.MonkeyPatch):
    target = resolve_shop("海底捞(牡丹园店)")["shop"]["shop_id"]
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch_with_unknown_coupon(target))

    response = run_agent_graph("海底捞(牡丹园店)和川味轩(知春路店)对比一下", "cmp_unknown_coupon")

    assert response.debug is not None
    matrix = response.debug.evidence_pack.get("comparison_matrix") or {}
    rows = {row["shop_id"]: row for row in matrix.get("rows", []) if isinstance(row, dict)}
    target_row = rows[target]

    assert target_row["coupon_status"] == "unknown"
    assert "优惠暂无法确认" in response.answer_text


def test_comparison_followup_uses_previous_recommendation_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)

    first = run_agent_graph("附近推荐火锅", "cmp_followup")
    assert first.debug is not None
    ranked = first.debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    assert len(ranked) >= 2

    second = run_agent_graph("第一家和第二家对比一下", "cmp_followup")

    assert second.debug is not None
    assert second.debug.execution_plan.get("task_type") == "comparison"
    matrix = second.debug.evidence_pack.get("comparison_matrix") or {}
    assert len(matrix.get("rows", [])) == 2
    assert ranked[0]["shop_name"] in second.answer_text
    assert ranked[1]["shop_name"] in second.answer_text


def test_comparison_needs_two_targets():
    response = run_agent_graph("海底捞(牡丹园店)对比一下", "cmp_need_two")

    assert "至少需要两家店" in response.answer_text
