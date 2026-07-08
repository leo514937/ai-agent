"""Regression tests for stage 14 multi-shop comparison."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from .. import agent
from ..agent import run_agent_graph
from ..answer.composers.deterministic import compose_deterministic_response
from ..answer.evidence_builder import build_evidence
from ..answer.generator import generate_answer
from ..answer.verifier import verify_answer
from ..engine import graph_builder
from ..planning.orchestration_router import normalize_route_task
from ..domain.schemas import DecisionPlan
from ..llm.client import _default_llm_backend, clear_llm_backend, set_llm_backend
from ..session.store import get_session_store, reset_session_store
from ..domain.state import SessionState
from .fakes.comparison_planner import plan_comparison
from .fakes.mock_tools import (
    check_open_status,
    get_coupon_list,
    get_distance_eta,
    get_shop_detail,
    resolve_shop,
    search_shops,
)
from .fakes.verifier import fake_verifier_verify


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


def _user_text_from_prompt(prompt: str) -> str:
    match = re.search(r"用户输入：\s*(.*)", prompt, re.S)
    if not match:
        match = re.search(r"User text\s*:?\s*(.*)", prompt, re.S)
    return match.group(1).strip() if match else prompt


def _comparison_llm_backend_impl(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.0,
    timeout_ms: int = 3000,
    **kwargs: Any,
):
    user_text = _user_text_from_prompt(prompt)
    if "顶层意图路由" in prompt or "意图分类器" in prompt:
        return {
            "ok": True,
            "content": {"top_intent": "local_life", "confidence": 0.99, "reason": "comparison_test_backend"},
            "confidence": 0.99,
            "raw": json.dumps({"top_intent": "local_life"}, ensure_ascii=False),
            "error_code": "",
            "error_message": "",
        }
    if "本地生活语义解析器" not in prompt and "本地生活语义框架提取器" not in prompt:
        return _default_llm_backend(prompt, system_prompt, temperature, timeout_ms, **kwargs)

    semantic: dict[str, Any] = {
        "top_intent": "local_life",
        "intent": "local_life",
        "task_type": "recommendation",
        "primary_task": "recommendation",
        "workflow_hint": "recommendation",
        "facets": [],
        "merchant_mentions": [],
        "brand_mentions": [],
        "branch_mentions": [],
        "reference_mentions": [],
        "comparison_targets": [],
        "ordinal_references": [],
        "deictic_references": [],
        "focused_facets": [],
        "comparison_focus": "",
        "hard_constraints": {},
        "soft_preferences": {},
        "ranking_signals": {"query_terms": ["火锅"]},
        "follow_up": None,
        "confidence": 0.95,
        "need_context": False,
        "missing_slots": [],
        "comparison_intent": False,
        "comparison_structure": "unknown",
        "comparison_facets": [],
    }

    if "附近推荐火锅" in user_text or "推荐几家火锅" in user_text or "推荐几家" in user_text:
        semantic.update(
            {
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "workflow_hint": "recommendation",
                "hard_constraints": {"category": "火锅"},
                "soft_preferences": {"nearby_preferred": True},
                "ranking_signals": {"query_terms": ["火锅"], "category": "火锅", "nearby_preferred": True},
                "confidence": 0.96,
            }
        )
    elif "这三家" in user_text and ("哪个好" in user_text or "哪个更好" in user_text or "谁更好" in user_text or "哪家更好" in user_text or "比" in user_text or "对比" in user_text):
        semantic.update(
            {
                "task_type": "comparison",
                "primary_task": "comparison",
                "workflow_hint": "comparison",
                "comparison_intent": True,
                "comparison_structure": "deictic",
                "comparison_targets": [{"shop_name": "这三家", "reference": "deictic", "source_text": "这三家"}],
                "deictic_references": ["这三家"],
                "reference_mentions": ["这三家"],
                "need_context": False,
                "confidence": 0.97,
            }
        )
    elif ("第一家" in user_text or "第二家" in user_text or "第三家" in user_text) and ("哪个好" in user_text or "哪个更好" in user_text or "谁更好" in user_text or "哪家更好" in user_text or "比" in user_text or "对比" in user_text):
        ordinal_refs = [token for token in ("第一家", "第二家", "第三家") if token in user_text]
        explicit_mentions = [token for token in ("海底捞", "山城一锅") if token in user_text]
        semantic.update(
            {
                "task_type": "comparison",
                "primary_task": "comparison",
                "workflow_hint": "comparison",
                "comparison_intent": True,
                "comparison_structure": "multi_target" if len(ordinal_refs) + len(explicit_mentions) >= 2 else "ordinal",
                "comparison_targets": (
                    [{"shop_name": token, "reference": "ordinal", "source_text": token} for token in ordinal_refs]
                    + [{"shop_name": token, "reference": "explicit", "source_text": token} for token in explicit_mentions]
                ),
                "ordinal_references": ordinal_refs,
                "merchant_mentions": explicit_mentions,
                "reference_mentions": ordinal_refs,
                "need_context": False,
                "confidence": 0.97,
            }
        )
    elif "第一家和海底捞比呢" in user_text or "第一家和海底捞比" in user_text:
        semantic.update(
            {
                "task_type": "comparison",
                "primary_task": "comparison",
                "workflow_hint": "comparison",
                "comparison_intent": True,
                "comparison_structure": "multi_target",
                "comparison_targets": [
                    {"shop_name": "第一家", "reference": "ordinal", "source_text": "第一家"},
                    {"shop_name": "海底捞", "reference": "explicit", "source_text": "海底捞"},
                ],
                "ordinal_references": ["第一家"],
                "merchant_mentions": ["海底捞"],
                "reference_mentions": ["第一家"],
                "need_context": False,
                "confidence": 0.97,
            }
        )
    elif "这家" in user_text and ("哪个好" in user_text or "比" in user_text or "有券" in user_text or "营业" in user_text):
        semantic.update(
            {
                "task_type": "single_shop_query",
                "primary_task": "coupon_query" if "券" in user_text else "open_status" if "营业" in user_text else "single_shop_query",
                "workflow_hint": "single_shop_query",
                "facets": [{"name": "coupon", "required": True}] if "券" in user_text else [{"name": "open_status", "required": True}],
                "deictic_references": ["这家"],
                "reference_mentions": ["这家"],
                "need_context": True,
                "confidence": 0.96,
            }
        )
    elif ("第一家" in user_text or "第二家" in user_text or "第三家" in user_text) and ("有券" in user_text or "营业" in user_text):
        ordinal_refs = [token for token in ("第一家", "第二家", "第三家") if token in user_text]
        semantic.update(
            {
                "task_type": "single_shop_query",
                "primary_task": "coupon_query" if "券" in user_text else "open_status",
                "workflow_hint": "single_shop_query",
                "facets": [{"name": "coupon", "required": True}] if "券" in user_text else [{"name": "open_status", "required": True}],
                "ordinal_references": ordinal_refs,
                "reference_mentions": ordinal_refs,
                "need_context": True,
                "confidence": 0.96,
            }
        )
    elif "便宜一点" in user_text:
        semantic.update(
            {
                "task_type": "recommendation",
                "primary_task": "recommendation_refine",
                "workflow_hint": "recommendation",
                "soft_preferences": {"price_preference": "cheap"},
                "ranking_signals": {"query_terms": ["火锅"], "price_preference": "cheap"},
                "need_context": True,
                "confidence": 0.96,
            }
        )

    return {
        "ok": True,
        "content": semantic,
        "confidence": semantic.get("confidence", 0.95),
        "raw": json.dumps(semantic, ensure_ascii=False),
        "error_code": "",
        "error_message": "",
    }


@pytest.fixture(autouse=True)
def _comparison_llm_backend(monkeypatch: pytest.MonkeyPatch):
    """Use a comparison-aware backend so graph tests can reach the recovery path."""

    agent._GRAPH_CACHE = None
    set_llm_backend(_comparison_llm_backend_impl)
    monkeypatch.setattr(graph_builder, "call_llm", _comparison_llm_backend_impl)
    try:
        yield
    finally:
        clear_llm_backend()
        agent._GRAPH_CACHE = None


@pytest.fixture(autouse=True)
def _fake_verifier(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("local_life_agent.answer.b2_mini_verifier.B2MiniVerifier.verify", fake_verifier_verify)


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
    assert response.debug.turn_trace["comparison_requested"] is True
    assert response.debug.turn_trace["comparison_context_anchor"] is True
    assert "comparison_requested" in (response.debug.turn_trace["comparison_route_reason"] or "")


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
    assert response.debug.turn_trace["comparison_requested"] is True
    assert "comparison" in (response.debug.turn_trace["comparison_route_reason"] or "")


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
    assert response.debug.turn_trace["comparison_route_reason"]


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


def test_comparison_coupon_followup_prefers_comparison_context():
    state = {
        "raw_text": "第二家有券吗",
        "normalized_text": "第二家有券吗",
        "semantic_frame": {
            "task_type": "coupon_query",
            "primary_task": "coupon_query",
            "workflow_hint": "single_shop_query",
            "ordinal_references": ["第二家"],
            "comparison_targets": [],
            "facets": [{"name": "coupon", "required": True}],
            "comparison_intent": False,
        },
        "comparison_targets": [SHOP_B, SHOP_A],
        "session_state_before": {"comparison_targets": [SHOP_B, SHOP_A]},
        "session_state": {"comparison_targets": [SHOP_B, SHOP_A]},
    }

    assert normalize_route_task(state) == "shop_coupon"


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


def test_comparison_statistical_winner_is_structured_and_supported():
    evidence = {
        "comparison_matrix": {
            "status": "ok",
            "rows": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "overall_score": 98, "known_dimensions": 4, "rating": 4.9, "distance_km": 1.2},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "overall_score": 88, "known_dimensions": 4, "rating": 4.7, "distance_km": 1.6},
            ],
            "overall_ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "overall_score": 98, "known_dimensions": 4},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "overall_score": 88, "known_dimensions": 4},
            ],
            "statistical_winner": {
                "shop_id": "s1",
                "shop_name": "川味轩(知春路店)",
                "score": 98,
                "score_gap": 10,
                "reason": "综合得分 98 高于 88",
            },
            "winner_provenance": {
                "source": "comparison_matrix",
                "ranking_basis": ["overall_score", "known_dimensions", "rating", "distance_km"],
            },
        },
        "ranking_snapshot": {
            "status": "ok",
            "ranked": [
                {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "total_score": 98},
                {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "total_score": 88},
            ],
        },
        "forbidden_claims": [],
    }

    result = verify_answer("综合当前已知信息，整体更适合的是川味轩(知春路店)。", evidence, "comparison")

    assert result["passed"] is True
    comparison_claims = [claim for claim in result["expected_claims"] if claim["claim_type"] == "comparison_winner"]
    assert comparison_claims
    assert any(claim["source"] == "statistical_winner" for claim in comparison_claims)


def test_comparison_without_unique_winner_keeps_tradeoff_without_forced_winner():
    plan = DecisionPlan(
        answer_type="comparison",
        selected_targets=[
            {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
            {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)"},
        ],
        overall_ranking=[
            {"shop_id": "s1", "shop_name": "川味轩(知春路店)"},
            {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)"},
        ],
        best_for={
            "评分": {"shop_id": "s1", "shop_name": "川味轩(知春路店)", "reason": "评分更高"},
            "距离": {"shop_id": "s2", "shop_name": "海底捞(牡丹园店)", "reason": "距离更近"},
        },
        uncertainty_notes=["当前证据并列，暂时无法确认唯一赢家"],
        comparison_support_status="grounded",
        ranking_preserved=True,
        winner_uncertainty_note="当前证据并列，暂时无法确认唯一赢家",
    )

    directive = compose_deterministic_response(plan, trace_id="trace_cmp")

    assert "唯一赢家" in directive.answer_text
    assert "整体赢家" not in directive.answer_text
    assert "维度结论" in directive.answer_text
