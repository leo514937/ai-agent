"""Verification tests for Stage 14 multi-shop comparison enhancements."""

from __future__ import annotations

from typing import Any
import pytest

from local_life_agent.semantic.slot_extractor import _extract_deictic
from local_life_agent.target.reference_resolver import (
    _parse_list_size,
    _resolve_deictic_reference,
    resolve_comparison_targets,
)
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
    """Verify group deictic reference sizes are parsed correctly."""
    assert _parse_list_size("这六家") == 6
    assert _parse_list_size("前五家") == 5
    assert _parse_list_size("这两家") == 2
    assert _parse_list_size("这三家") == 3


def test_resolve_deictic_reference_with_group():
    """Verify resolution of group deictic references using session recommendation list."""
    session = SessionState(
        last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]
    )
    
    # "这两家" -> should resolve first 2 shops
    res = _resolve_deictic_reference("这两家", session)
    assert res["status"] == "resolved_list"
    assert len(res["targets"]) == 2
    assert res["targets"][0]["shop_id"] == SHOP_A["shop_id"]
    assert res["targets"][1]["shop_id"] == SHOP_B["shop_id"]

    # "这三家" -> should resolve 3 shops
    res_three = _resolve_deictic_reference("这三家", session)
    assert res_three["status"] == "resolved_list"
    assert len(res_three["targets"]) == 3
    assert res_three["targets"][2]["shop_id"] == SHOP_C["shop_id"]


def test_deictic_priority_clarification():
    """Verify that when a deictic reference is ambiguous, it triggers clarification immediately."""
    session = SessionState(
        last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C],
        current_shop={}  # no active current shop
    )
    
    # Resolving comparison target with "这家" (deictic) and "海底捞" (explicit)
    semantic_frame = {
        "task_type": "comparison",
        "comparison_targets": [
            {"reference": "deictic", "source_text": "这家", "shop_name": "这家"},
            {"reference": "explicit", "source_text": "海底捞", "shop_name": "海底捞"}
        ]
    }
    
    res = resolve_comparison_targets("这家和海底捞对比一下", session, semantic_frame)
    # The resolution status should be NEED_CLARIFICATION because "这家" is ambiguous (no current shop)
    assert res["status"] == "NEED_CLARIFICATION"
    assert res["ambiguous_target"]["reference"] == "deictic"


def test_comparison_matrix_cells_validation():
    """Verify that the comparison matrix builds standard cells, unknown/failed cells, overall_ranking and validates correctly."""
    # Test case where Shop A has coupon/rating/etc, Shop B has unknown coupon status
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

    # Check that comparison matrix has been populated and validated
    assert "comparison_matrix" in evidence
    matrix_dict = evidence["comparison_matrix"]

    # Validate that we can model_validate it as ComparisonMatrix
    matrix = ComparisonMatrix.model_validate(matrix_dict)
    assert matrix.matrix_id == "cmp_p123"
    assert len(matrix.cells) == 8  # 2 shops * 4 facets each
    
    # Verify cells structure: mapped dimension to facet, result_status to status
    rating_cell_a = next(c for c in matrix.cells if c.shop_id == SHOP_A["shop_id"] and c.facet == "rating")
    assert rating_cell_a.dimension == "rating"
    assert rating_cell_a.status == "ok"
    assert rating_cell_a.result_status == "ok"
    assert rating_cell_a.eligible_for_comparison is True

    # Verify unknown_cells are collected correctly
    unknown_coupon_b = next(c for c in matrix.unknown_cells if c.shop_id == SHOP_B["shop_id"] and c.facet == "coupon")
    assert unknown_coupon_b.status == "unknown"
    assert unknown_coupon_b.result_status == "unknown"
    assert unknown_coupon_b.eligible_for_comparison is False

    # Check overall_ranking and overall_ranked
    assert len(matrix.overall_ranked) == 2
    assert len(matrix.overall_ranking) == 2
    assert matrix.overall_ranking[0]["shop_id"] == SHOP_A["shop_id"]  # rating 4.8 vs 4.5
