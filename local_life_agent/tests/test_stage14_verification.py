"""Verification tests for Stage 14 multi-shop comparison enhancements."""

from __future__ import annotations

from typing import Any
import pytest

from local_life_agent.semantic.slot_extractor import _extract_deictic
from local_life_agent.target.reference_resolver import resolve_references
from local_life_agent.answer.evidence_builder import build_evidence
from local_life_agent.domain.schemas import ComparisonMatrix, EvidencePack, ComparisonCell
from local_life_agent.domain.state import SessionState
from local_life_agent.session.store import get_session_store, reset_session_store
from local_life_agent.agent import run_agent_graph


SHOP_A = {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}
SHOP_B = {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}
SHOP_C = {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"}


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    reset_session_store()
    yield
    reset_session_store()


def test_group_deictic_extraction():
    """Verify group deictic references are extracted correctly by slot_extractor."""
    assert "这六家" in _extract_deictic("这六家哪家好")
    assert "前五家" in _extract_deictic("前五家哪个最近")
    assert "这两家" in _extract_deictic("这两家对比一下")
    assert "这三家" in _extract_deictic("这三家有什么优惠吗")


def test_group_deictic_size_parsing():
    """Verify group deictic reference sizes are parsed correctly via resolve_references."""
    session = SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C])

    res_three = resolve_references(session, {"deictic_references": ["这三家"]})
    assert len(res_three.get("comparison_targets", [])) == 3

    res_several = resolve_references(session, {"deictic_references": ["这几家"]})
    assert len(res_several.get("comparison_targets", [])) == 3


def test_resolve_deictic_reference_with_group():
    """Verify resolution of group deictic references using session recommendation list."""
    session = SessionState(
        last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]
    )

    # "这三家" -> should resolve first 3 shops
    res_three = resolve_references(session, {"deictic_references": ["这三家"]})
    targets_three = res_three.get("comparison_targets", [])
    assert res_three["status"] == "resolved"
    assert len(targets_three) == 3
    assert targets_three[2].get("resolved_shop", {}).get("shop_id") == SHOP_C["shop_id"]


def test_deictic_priority_clarification():
    """Verify that when a deictic reference is ambiguous, status reflects that."""
    session = SessionState(
        last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C],
        current_shop={}
    )

    res = resolve_references(session, {
        "deictic_references": ["这家"],
        "comparison_targets": [
            {"reference": "deictic", "source_text": "这家", "shop_name": "这家"},
            {"reference": "explicit", "source_text": "海底捞", "shop_name": "海底捞"}
        ]
    })
    assert res.get("status") in ("unresolved", "resolved")


def test_comparison_matrix_cells_validation():
    """Verify that the comparison matrix builds standard cells, unknown/failed cells, overall_ranking and validates correctly."""
    tool_results = {
        "detail_a": {
            "tool_name": "get_shop_detail",
            "shop_id": SHOP_A["shop_id"],
            "result_status": "ok",
            "data": {"shop_name": SHOP_A["shop_name"], "rating": 4.8}
        },
        "coupon_a": {
            "tool_name": "get_coupon_list",
            "shop_id": SHOP_A["shop_id"],
            "result_status": "ok",
            "data": [{"title": "88折"}]
        },
        "detail_b": {
            "tool_name": "get_shop_detail",
            "shop_id": SHOP_B["shop_id"],
            "result_status": "ok",
            "data": {"shop_name": SHOP_B["shop_name"], "rating": 4.5}
        },
        "coupon_b": {
            "tool_name": "get_coupon_list",
            "shop_id": SHOP_B["shop_id"],
            "result_status": "unknown",
            "data": None
        }
    }

    plan_dict = {
        "plan_id": "p123",
        "task_type": "comparison",
        "tool_calls": [
            {"call_id": "detail_a", "tool_name": "get_shop_detail", "target_shop_id": SHOP_A["shop_id"]},
            {"call_id": "coupon_a", "tool_name": "get_coupon_list", "target_shop_id": SHOP_A["shop_id"]},
            {"call_id": "detail_b", "tool_name": "get_shop_detail", "target_shop_id": SHOP_B["shop_id"]},
            {"call_id": "coupon_b", "tool_name": "get_coupon_list", "target_shop_id": SHOP_B["shop_id"]},
        ]
    }

    comparison_targets = [
        {"resolved_shop": SHOP_A},
        {"resolved_shop": SHOP_B}
    ]

    evidence = build_evidence(
        tool_results=tool_results,
        resolved_target={},
        execution_plan=plan_dict,
        comparison_targets=comparison_targets
    )

    assert "comparison_matrix" in evidence
    matrix_dict = evidence["comparison_matrix"]

    matrix = ComparisonMatrix.model_validate(matrix_dict)
    assert matrix.matrix_id == "cmp_p123"
    assert len(matrix.cells) == 8

    rating_cell_a = next(c for c in matrix.cells if c.shop_id == SHOP_A["shop_id"] and c.facet == "rating")
    assert rating_cell_a.dimension == "rating"
    assert rating_cell_a.status == "ok"
    assert rating_cell_a.result_status == "ok"
    assert rating_cell_a.eligible_for_comparison is True

    unknown_coupon_b = next(c for c in matrix.unknown_cells if c.shop_id == SHOP_B["shop_id"] and c.facet == "coupon")
    assert unknown_coupon_b.status == "unknown"
    assert unknown_coupon_b.result_status == "unknown"
    assert unknown_coupon_b.eligible_for_comparison is False

    assert len(matrix.overall_ranked) == 2
    assert len(matrix.overall_ranking) == 2
    assert matrix.overall_ranking[0]["shop_id"] == SHOP_A["shop_id"]
