from __future__ import annotations

from typing import Any

import pytest

from local_life_agent.domain.contextualized_turn import ContextualizedTurn
from local_life_agent.domain.focus_context import FocusContext
from local_life_agent.domain.freshness import FreshnessMeta
from local_life_agent.domain.graph_state import GraphState
from local_life_agent.domain.location_context import LocationContext
from local_life_agent.engine.subgraphs import understanding_subgraph as us


def test_trace_dtos_are_serializable() -> None:
    turn = ContextualizedTurn.from_trace(
        original_text="便宜一点的呢",
        normalized_text="便宜一点的呢",
        contextualized_query="便宜一点的呢",
        rewrite_type="semantic_follow_up",
        context_used=["semantic_frame.follow_up"],
        confidence=0.42,
    )
    focus = FocusContext.from_trace(
        focus_type="comparison_targets",
        focus_object={"shop_id": "shop_1", "shop_name": "海底捞"},
        comparison_targets=[{"shop_id": "shop_1", "shop_name": "海底捞"}],
        focus_source="context_recovery",
        confidence=0.75,
    )
    freshness = FreshnessMeta.from_trace(
        freshness_class="cached",
        cache_hit=True,
        location_fingerprint="北京|39.9|116.3|provided|test",
        budget_context_snapshot={"budget_left": 10},
    )
    location = LocationContext.from_trace(
        location_name="北京邮电大学",
        lat=39.9609,
        lng=116.3581,
        location_status="provided",
        location_source="test",
        location_fingerprint="北京邮电大学|39.9609|116.3581|provided|test",
    )

    assert turn.model_dump()["rewrite_type"] == "semantic_follow_up"
    assert focus.model_dump()["focus_type"] == "comparison_targets"
    assert freshness.model_dump(mode="json")["cache_hit"] is True
    assert location.model_dump()["location_status"] == "provided"


def test_graph_state_has_new_trace_fields() -> None:
    hints = GraphState.__annotations__
    for field in ("contextualized_turn", "focus_context", "freshness_meta", "location_context"):
        assert field in hints


def test_context_recovery_populates_trace_only_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_recover_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "semantic_frame": {
                "follow_up": {"kind": "price"},
                "confidence": 0.33,
            },
            "context_resolution": {"status": "OK"},
            "reference_resolution_source": "semantic_frame",
        }

    monkeypatch.setattr("local_life_agent.target.context_recovery.recover_context", fake_recover_context)

    state = {
        "raw_text": "便宜一点的呢",
        "normalized_text": "便宜一点的呢",
        "active_turn_result": {},
        "user_location": {
            "location_name": "北京邮电大学",
            "lat": 39.9609,
            "lng": 116.3581,
            "location_status": "provided",
            "location_source": "test",
        },
        "budget_context": {"budget_left": 10},
        "evidence_cache_hit": True,
    }

    result = us._h_context_recovery(state)

    assert isinstance(result["contextualized_turn"], ContextualizedTurn)
    assert result["contextualized_turn"].rewrite_type == "semantic_follow_up"
    assert "semantic_frame.follow_up" in result["contextualized_turn"].context_used
    assert isinstance(result["focus_context"], FocusContext)
    assert result["focus_context"].focus_type == "none"
    assert isinstance(result["freshness_meta"], FreshnessMeta)
    assert result["freshness_meta"].cache_hit is True
    assert isinstance(result["location_context"], LocationContext)
    assert result["location_context"].location_status == "provided"


def test_context_recovery_prefers_active_turn_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_recover_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "semantic_frame": {
                "comparison_targets": [{"shop_id": "shop_1", "shop_name": "海底捞"}],
                "confidence": 0.7,
            },
            "comparison_reference_signal": {
                "status": "SIGNAL_ONLY",
                "reason": "comparison_reference_signal",
                "reference_signal": {"comparison_targets": [{"shop_id": "shop_1", "shop_name": "海底捞"}]},
            },
            "context_resolution": {
                "status": "SIGNAL_ONLY",
                "reference_signal": {"comparison_targets": [{"shop_id": "shop_1", "shop_name": "海底捞"}]},
            },
            "reference_resolution_source": "first_layer_reference_signal",
        }

    monkeypatch.setattr("local_life_agent.target.context_recovery.recover_context", fake_recover_context)

    state = {
        "raw_text": "第二个怎么样",
        "normalized_text": "第二个怎么样",
        "active_turn_result": {
            "route": "pending_restored",
            "source": "rule",
            "reason": "ordinal_第二个",
            "selected_index": 2,
            "selected_candidate": {"shop_id": "shop_2", "shop_name": "山城一锅"},
            "confidence": 1.0,
        },
    }

    result = us._h_context_recovery(state)
    focus = result["focus_context"]
    assert isinstance(focus, FocusContext)
    assert focus.focus_type == "recommendation_item"
    assert focus.recommendation_item["shop_id"] == "shop_2"
    assert focus.focus_index == 2
    assert isinstance(result["contextualized_turn"], ContextualizedTurn)
    assert result["contextualized_turn"].rewrite_type == "recommendation_item_reference"
    assert "context_recovery.reference_signal" in result["contextualized_turn"].context_used
