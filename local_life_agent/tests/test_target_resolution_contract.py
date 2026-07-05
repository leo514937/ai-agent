"""Phase 7 target-resolution contract tests.

These tests keep the protocol observable without changing the broader
recommendation / comparison / clarification behavior.
"""

from __future__ import annotations

from local_life_agent.domain.facets import build_target_resolution_result
from local_life_agent.domain.graph_state_model import GraphStateModel


def test_target_resolution_status_is_observable_for_reference_sources() -> None:
    explicit = build_target_resolution_result(
        {"merchant_mentions": ["海底捞"], "task_type": "single_shop_query"},
        session_state={},
        raw_text="海底捞有券吗",
    )
    deictic = build_target_resolution_result(
        {"deictic_references": ["这家"], "task_type": "single_shop_query"},
        session_state={"current_shop": {"shop_id": "shop_1", "shop_name": "测试店"}},
        raw_text="这家有券吗",
    )
    ordinal = build_target_resolution_result(
        {"ordinal_references": ["第三家"], "task_type": "single_shop_query"},
        session_state={"last_recommendation_list": [{"shop_id": "shop_1", "shop_name": "第一家"}, {"shop_id": "shop_2", "shop_name": "第二家"}]},
        raw_text="第三家有券吗",
    )
    comparison = build_target_resolution_result(
        {
            "comparison_targets": [
                {"shop_id": "shop_1", "shop_name": "第一家"},
                {"shop_id": "shop_2", "shop_name": "第二家"},
            ],
            "task_type": "comparison",
        },
        session_state={},
        raw_text="第一家和第二家哪个好",
    )

    assert explicit.status == "ambiguous"
    assert deictic.status == "resolved"
    assert ordinal.status == "not_found"
    assert comparison.status == "resolved"


def test_target_resolution_status_exposes_graph_state_field() -> None:
    model = GraphStateModel.model_validate(
        {
            "trace_id": "t-1",
            "target_resolution_status": "resolved",
            "target_resolution": {"resolved": True, "status": "resolved", "target_shop": {"shop_id": "s1", "shop_name": "测试店"}},
        }
    )

    assert model.target_resolution_status == "resolved"
    assert model.target_resolution is not None
    assert model.target_resolution.status == "resolved"
