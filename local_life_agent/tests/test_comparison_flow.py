"""Regression tests for stage 14 multi-shop comparison."""

from __future__ import annotations

from typing import Any

import pytest

from ..agent import run_agent_graph
from ..answer.evidence_builder import build_evidence
from ..answer.generator import generate_answer
from ..answer.verifier import verify_answer
from ..engine import graph_builder
from ..planning.comparison_planner import plan_comparison
from ..session.store import get_session_store, reset_session_store
from ..domain.state import SessionState
from .fakes.mock_tools import (
    check_open_status,
    get_coupon_list,
    get_distance_eta,
    get_shop_detail,
    resolve_shop,
    search_shops,
)


SHOP_A = {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}
SHOP_B = {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}
SHOP_C = {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"}
SHOP_D = {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"}
SHOP_E = {"shop_id": "shop_sc_03", "shop_name": "蜀香居(学院路店)"}
SHOP_F = {"shop_id": "shop_009", "shop_name": "远方烧烤(清河店)"}


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store()
    yield
    reset_session_store()


def _target(shop: dict[str, str]) -> dict[str, Any]:
    return {"resolved_shop": dict(shop)}


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
        return get_distance_eta(
            str(args.get("shop_id", "")),
            args.get("from_location") or {"lat": 39.9609, "lng": 116.3581},
        )
    raise AssertionError(f"Unexpected tool: {tool_name}")


def _tool_names(response) -> list[str]:
    if response.debug is None:
        return []
    return [
        str(result.get("tool_name", "") if isinstance(result, dict) else getattr(result, "tool_name", ""))
        for result in response.debug.tool_results.values()
    ]


def _comparison_trace_nodes(response) -> list[str]:
    if response.debug is None:
        return []
    return [str(item.get("node", "")) for item in response.debug.execution_trace]


def _comparison_plan(targets: list[dict[str, Any]], focus_facets: list[str] | None = None) -> dict[str, Any]:
    return plan_comparison(targets, focus_facets=focus_facets, location={"lat": 39.9609, "lng": 116.3581})


def _comparison_evidence(
    tool_results: dict[str, dict[str, Any]],
    targets: list[dict[str, Any]],
    *,
    focus_facets: list[str] | None = None,
) -> dict[str, Any]:
    plan = _comparison_plan(targets, focus_facets=focus_facets)
    return build_evidence(
        tool_results,
        {},
        execution_plan=plan,
        comparison_targets=targets,
    )


def _result(
    call_id: str,
    tool_name: str,
    shop_id: str,
    *,
    result_status: str,
    data: Any,
    success: bool | None = None,
    error_code: str | None = None,
    error_message: str = "",
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "tool_name": tool_name,
        "shop_id": shop_id,
        "success": result_status == "ok" if success is None else success,
        "result_status": result_status,
        "data": data,
        "error_code": error_code,
        "error_message": error_message,
    }


def _matrix_row(matrix: dict[str, Any], shop_id: str) -> dict[str, Any]:
    for row in matrix.get("rows", []):
        if isinstance(row, dict) and row.get("shop_id") == shop_id:
            return row
    raise AssertionError(f"missing row for {shop_id}")


def test_compare_three_from_last_recommendation_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)
    get_session_store().save(
        "cmp_three",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
    )

    response = run_agent_graph("这三家哪个好？", "cmp_three")

    assert response.debug is not None
    assert response.debug.execution_plan.get("task_type") == "comparison"
    assert response.debug.session_state_after.get("comparison_targets", [])[:3] == [SHOP_A, SHOP_B, SHOP_C]
    assert "search_shops" not in _tool_names(response)
    assert "evidence_planner" in _comparison_trace_nodes(response)
    assert len((response.debug.evidence_pack.get("comparison_matrix") or {}).get("rows", [])) == 3


def test_compare_first_item_and_explicit_shop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)
    monkeypatch.setattr(
        graph_builder,
        "resolve_shop",
        lambda query, **_: {
            "status": "RESOLVED",
            "shop": SHOP_B,
            "candidates": [],
            "confidence": 0.95,
            "error_code": None,
        } if query == "海底捞" else resolve_shop(query),
    )
    get_session_store().save(
        "cmp_first_explicit",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_D, SHOP_E]),
    )

    response = run_agent_graph("第一家和海底捞比呢？", "cmp_first_explicit")

    assert response.debug is not None
    assert response.debug.execution_plan.get("task_type") == "comparison"
    targets = response.debug.session_state_after.get("comparison_targets", [])
    assert targets
    assert targets[0] == SHOP_A
    assert len({item["shop_id"] for item in targets}) >= 2
    assert "search_shops" not in _tool_names(response)


def test_compare_this_shop_without_current_shop_must_clarify(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)
    get_session_store().save(
        "cmp_this_shop",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C], current_shop=None),
    )

    response = run_agent_graph("这家和海底捞比呢？", "cmp_this_shop")

    assert response.debug is not None
    assert response.debug.session_state_after.get("pending_clarification") is not None
    assert response.debug.session_state_after.get("comparison_targets", []) in ([], None)
    assert "evidence_planner" not in _comparison_trace_nodes(response)
    assert "get_coupon_list" not in _tool_names(response)


def test_compare_duplicate_targets_blocked():
    plan = _comparison_plan([_target(SHOP_A), _target(SHOP_A)])

    assert plan.get("tool_calls") == []


def test_ambiguous_explicit_shop_goes_to_pending_clarification(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)

    def _ambiguous_resolve(query: str, **_: Any) -> dict[str, Any]:
        if query == "海底捞":
            return {
                "status": "AMBIGUOUS",
                "shop": None,
                "candidates": [
                    {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"], "address": "牡丹园"},
                    {"shop_id": SHOP_C["shop_id"], "shop_name": SHOP_C["shop_name"], "address": "水晶城"},
                ],
                "confidence": 0.61,
                "error_code": None,
            }
        return resolve_shop(query)

    monkeypatch.setattr(graph_builder, "resolve_shop", _ambiguous_resolve)
    get_session_store().save(
        "cmp_pending_1",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_D, SHOP_E]),
    )

    response = run_agent_graph("第一家和海底捞比呢？", "cmp_pending_1")

    assert response.debug is not None
    pending = response.debug.session_state_after.get("pending_clarification")
    assert pending is not None
    assert pending.get("original_task_type") == "comparison"
    assert pending.get("candidate_targets")
    assert "evidence_planner" not in _comparison_trace_nodes(response)
    assert _tool_names(response) == []


def test_pending_reply_restores_comparison_task(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)

    def _ambiguous_resolve(query: str, **_: Any) -> dict[str, Any]:
        if query == "海底捞":
            return {
                "status": "AMBIGUOUS",
                "shop": None,
                "candidates": [
                    {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"], "address": "牡丹园"},
                    {"shop_id": SHOP_C["shop_id"], "shop_name": SHOP_C["shop_name"], "address": "水晶城"},
                ],
                "confidence": 0.61,
                "error_code": None,
            }
        return resolve_shop(query)

    monkeypatch.setattr(graph_builder, "resolve_shop", _ambiguous_resolve)
    get_session_store().save(
        "cmp_pending_2",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_D, SHOP_E]),
    )

    first = run_agent_graph("第一家和海底捞比呢？", "cmp_pending_2")
    assert first.debug is not None
    assert first.debug.session_state_after.get("pending_clarification") is not None

    second = run_agent_graph("1", "cmp_pending_2")

    assert second.debug is not None
    assert second.debug.session_state_after.get("pending_clarification") is None
    assert second.debug.execution_plan.get("task_type") == "comparison"
    assert len(second.debug.session_state_after.get("comparison_targets", [])) >= 2
    assert "evidence_planner" in _comparison_trace_nodes(second)


def test_two_or_three_shops_full_dimensions():
    plan = _comparison_plan([_target(SHOP_A), _target(SHOP_B), _target(SHOP_C)])
    tool_calls = plan.get("tool_calls", [])
    facets = {call.get("facet") for call in tool_calls}

    assert len(tool_calls) == 12
    assert facets == {"detail", "open_status", "coupon", "distance"}
    assert all(call.get("target_shop_id") for call in tool_calls)


def test_four_or_five_shops_focused_dimensions_only():
    plan = _comparison_plan(
        [_target(SHOP_A), _target(SHOP_B), _target(SHOP_C), _target(SHOP_D), _target(SHOP_E)],
        focus_facets=["coupon"],
    )
    tool_calls = plan.get("tool_calls", [])

    assert tool_calls
    assert {call.get("facet") for call in tool_calls} == {"coupon"}
    assert len(tool_calls) == 5


def test_more_than_five_targets_blocked():
    plan = _comparison_plan(
        [_target(SHOP_A), _target(SHOP_B), _target(SHOP_C), _target(SHOP_D), _target(SHOP_E), _target(SHOP_F)]
    )

    assert plan.get("tool_calls") == []


def test_comparison_matrix_contains_isolated_cells():
    evidence = _comparison_evidence(
        {
            "detail_a": _result("detail_a", "get_shop_detail", SHOP_A["shop_id"], result_status="ok", data={"shop_name": SHOP_A["shop_name"], "rating": 4.8}),
            "coupon_a": _result("coupon_a", "get_coupon_list", SHOP_A["shop_id"], result_status="ok", data=[{"title": "88折"}]),
            "detail_b": _result("detail_b", "get_shop_detail", SHOP_B["shop_id"], result_status="ok", data={"shop_name": SHOP_B["shop_name"], "rating": 4.6}),
            "coupon_b": _result("coupon_b", "get_coupon_list", SHOP_B["shop_id"], result_status="empty", data=[]),
        },
        [_target(SHOP_A), _target(SHOP_B)],
    )

    matrix = evidence.get("comparison_matrix") or {}
    assert matrix.get("cells")


def test_unknown_coupon_not_treated_as_worse():
    evidence = _comparison_evidence(
        {
            "detail_a": _result("detail_a", "get_shop_detail", SHOP_A["shop_id"], result_status="ok", data={"shop_name": SHOP_A["shop_name"], "rating": 4.8}),
            "coupon_a": _result("coupon_a", "get_coupon_list", SHOP_A["shop_id"], result_status="ok", data=[{"title": "88折"}]),
            "detail_b": _result("detail_b", "get_shop_detail", SHOP_B["shop_id"], result_status="ok", data={"shop_name": SHOP_B["shop_name"], "rating": 4.8}),
            "coupon_b": _result(
                "coupon_b",
                "get_coupon_list",
                SHOP_B["shop_id"],
                result_status="unknown",
                data=None,
                success=False,
                error_code="NETWORK_ERROR",
            ),
        },
        [_target(SHOP_A), _target(SHOP_B)],
    )

    matrix = evidence.get("comparison_matrix") or {}
    row_b = _matrix_row(matrix, SHOP_B["shop_id"])
    answer = generate_answer({"answer_type": "comparison"}, evidence)

    assert row_b["coupon_status"] == "unknown"
    assert not (matrix.get("dimension_winners") or {}).get("coupon")
    assert "无法确认" in answer
    assert "一定比" not in answer


def test_failed_cell_not_treated_as_worse():
    evidence = _comparison_evidence(
        {
            "distance_a": _result(
                "distance_a",
                "get_distance_eta",
                SHOP_A["shop_id"],
                result_status="ok",
                data={"distance_km": 0.8, "eta_minutes": 10},
            ),
            "distance_b": _result(
                "distance_b",
                "get_distance_eta",
                SHOP_B["shop_id"],
                result_status="failed",
                data=None,
                success=False,
                error_code="TOOL_TIMEOUT",
                error_message="timeout",
            ),
        },
        [_target(SHOP_A), _target(SHOP_B)],
    )

    matrix = evidence.get("comparison_matrix") or {}
    assert not (matrix.get("dimension_winners") or {}).get("distance")
    assert any("距离" in note for note in matrix.get("uncertainty_notes", []))


def test_dimension_with_only_one_valid_cell_has_no_strong_winner():
    evidence = _comparison_evidence(
        {
            "distance_a": _result(
                "distance_a",
                "get_distance_eta",
                SHOP_A["shop_id"],
                result_status="ok",
                data={"distance_km": 0.8, "eta_minutes": 10},
            ),
        },
        [_target(SHOP_A), _target(SHOP_B)],
    )

    matrix = evidence.get("comparison_matrix") or {}
    assert not (matrix.get("dimension_winners") or {}).get("distance")


def test_dimension_winners_generated_by_system():
    evidence = _comparison_evidence(
        {
            "detail_a": _result("detail_a", "get_shop_detail", SHOP_A["shop_id"], result_status="ok", data={"shop_name": SHOP_A["shop_name"], "rating": 4.9}),
            "detail_b": _result("detail_b", "get_shop_detail", SHOP_B["shop_id"], result_status="ok", data={"shop_name": SHOP_B["shop_name"], "rating": 4.5}),
        },
        [_target(SHOP_A), _target(SHOP_B)],
    )

    matrix = evidence.get("comparison_matrix") or {}
    winners = (matrix.get("dimension_winners") or {}).get("rating") or []

    assert winners
    assert winners[0]["shop_id"] == SHOP_A["shop_id"]
    assert _matrix_row(matrix, winners[0]["shop_id"])["rating"] == winners[0]["value"]


def test_overall_ranking_ignores_unknown_dimensions():
    evidence = _comparison_evidence(
        {
            "detail_a": _result("detail_a", "get_shop_detail", SHOP_A["shop_id"], result_status="ok", data={"shop_name": SHOP_A["shop_name"], "rating": 4.8}),
            "detail_b": _result("detail_b", "get_shop_detail", SHOP_B["shop_id"], result_status="ok", data={"shop_name": SHOP_B["shop_name"], "rating": 4.8}),
            "coupon_b": _result("coupon_b", "get_coupon_list", SHOP_B["shop_id"], result_status="unknown", data=None, success=False),
        },
        [_target(SHOP_A), _target(SHOP_B)],
    )

    matrix = evidence.get("comparison_matrix") or {}
    assert any("优惠" in note for note in matrix.get("uncertainty_notes", []))
    assert len(matrix.get("overall_ranked", [])) == 2


def test_all_unknown_gives_no_strong_overall_conclusion():
    evidence = _comparison_evidence({}, [_target(SHOP_A), _target(SHOP_B)])
    answer = generate_answer({"answer_type": "comparison"}, evidence)

    assert "更占优" not in answer
    assert "无法" in answer or "不足" in answer


def test_verifier_blocks_unknown_as_worse():
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_id": SHOP_A["shop_id"], "shop_name": SHOP_A["shop_name"], "coupon_status": "has_coupon"},
                {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"], "coupon_status": "unknown"},
            ],
            "dimension_winners": {},
            "overall_ranked": [],
        }
    }

    result = verify_answer(f"{SHOP_B['shop_name']}优惠更差。", evidence, "comparison")

    assert result["passed"] is False


def test_verifier_blocks_unprovided_dimension_winner():
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_id": SHOP_A["shop_id"], "shop_name": SHOP_A["shop_name"]},
                {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"]},
            ],
            "dimension_winners": {"rating": [{"shop_id": SHOP_A["shop_id"], "shop_name": SHOP_A["shop_name"]}]},
            "overall_ranked": [],
        }
    }

    result = verify_answer(f"{SHOP_A['shop_name']}优惠胜出。", evidence, "comparison")

    assert result["passed"] is False


def test_verifier_blocks_ranking_changed_by_answer():
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_id": SHOP_A["shop_id"], "shop_name": SHOP_A["shop_name"]},
                {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"]},
            ],
            "dimension_winners": {},
            "overall_ranked": [
                {"shop_id": SHOP_A["shop_id"], "shop_name": SHOP_A["shop_name"]},
                {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"]},
            ],
        }
    }

    result = verify_answer(f"总体看{SHOP_B['shop_name']}更好。", evidence, "comparison")

    assert result["passed"] is False


def test_verifier_blocks_shop_not_in_matrix():
    evidence = {
        "comparison_matrix": {
            "rows": [
                {"shop_id": SHOP_A["shop_id"], "shop_name": SHOP_A["shop_name"]},
                {"shop_id": SHOP_B["shop_id"], "shop_name": SHOP_B["shop_name"]},
            ],
            "dimension_winners": {},
            "overall_ranked": [],
        }
    }

    result = verify_answer("不存在的店铺更好。", evidence, "comparison")

    assert result["passed"] is False


def test_comparison_success_writes_comparison_result_not_overwrite_recommendation_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)

    first = run_agent_graph("附近推荐火锅", "cmp_session")
    assert first.debug is not None
    ranked = first.debug.session_state_after.get("last_recommendation_list", [])
    assert len(ranked) >= 2

    second = run_agent_graph("第一家和第二家对比一下", "cmp_session")

    assert second.debug is not None
    session_after = second.debug.session_state_after
    assert session_after.get("comparison_result")
    assert session_after.get("last_recommendation_list") == ranked
    assert session_after.get("current_shop") in (None, {})


def test_after_comparison_second_item_reference_still_works(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)

    first = run_agent_graph("附近推荐火锅", "cmp_followup")
    assert first.debug is not None

    second = run_agent_graph("第一家和第二家对比一下", "cmp_followup")
    assert second.debug is not None

    third = run_agent_graph("第二家有券吗", "cmp_followup")

    assert third.debug is not None
    assert "get_coupon_list" in _tool_names(third)
    assert third.debug.session_state_after.get("current_shop") is not None


def test_comparison_flow_does_not_enter_recommendation_flow(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)
    get_session_store().save(
        "cmp_flow_reco",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
    )

    response = run_agent_graph("这三家哪个好？", "cmp_flow_reco")

    assert response.debug is not None
    assert "search_shops" not in _tool_names(response)
    assert "evidence_planner" in _comparison_trace_nodes(response)
    assert response.debug.execution_plan.get("task_type") == "comparison"


def test_comparison_flow_does_not_enter_single_shop_flow(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)
    get_session_store().save(
        "cmp_flow_single",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
    )

    response = run_agent_graph("第一家和第二家哪个更好？", "cmp_flow_single")

    assert response.debug is not None
    assert response.debug.execution_plan.get("task_type") == "comparison"
    assert len(response.debug.session_state_after.get("comparison_targets", [])) >= 2
    assert response.debug.session_state_after.get("current_shop") in (None, {})
