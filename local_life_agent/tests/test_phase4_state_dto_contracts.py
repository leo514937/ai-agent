from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from local_life_agent.domain.decision import DecisionPlan as CanonicalDecisionPlan
from local_life_agent.domain.evidence import EvidenceReviewResult
from local_life_agent.domain.facets import TargetResolutionResult
from local_life_agent.domain.graph_state import GraphState
from local_life_agent.domain.serialization import to_plain_dict, to_plain_list
from local_life_agent.domain.shop_entity import ShopCandidate
from local_life_agent.domain.state import SessionState, SessionWriteDirective, StateUpdatePlan
from local_life_agent.domain.state_validation import describe_graph_state_contracts
from local_life_agent.domain import schemas as legacy_schemas
from local_life_agent.semantic.slot_extractor import extract_slots


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class _DemoDataclass:
    name: str
    payload: dict[str, Any]


class _DemoModel(BaseModel):
    name: str
    payload: dict[str, Any]


def _session_writeback_callsites() -> list[str]:
    hits: list[str] = []
    for path in (ROOT / "local_life_agent").rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "setattr(session_state" in text:
            hits.append(path.relative_to(ROOT).as_posix())
    return sorted(hits)


def test_phase4_graph_and_session_contracts_keep_core_fields_in_known_layers():
    contracts = {item["field_name"]: item for item in describe_graph_state_contracts()}

    assert contracts["session_state"]["owner"] == "state_update_plan"
    assert contracts["evidence_pack"]["owner"] == "execution_review_subgraph"
    assert contracts["orchestration_decision"]["owner"] == "orchestration_router"
    assert contracts["tool_results"]["compatibility_fields"] == ["tool_result_set"]

    graph_fields = GraphState.__annotations__
    for field_name in (
        "review_results",
        "budget_context",
        "rewrite_count",
        "fallback_reason",
        "answer_verify_passed",
        "state_update_plan",
        "session_state_before",
        "session_state_after",
    ):
        assert field_name in graph_fields

    session_fields = SessionState.model_fields
    for field_name in (
        "current_shop",
        "current_shop_meta",
        "last_recommendation_list",
        "pending_clarification",
        "comparison_targets",
        "review_results",
        "replan_counters",
    ):
        assert field_name in session_fields


def test_phase4_session_writeback_is_centralized_in_state_update_plan():
    assert _session_writeback_callsites() == ["local_life_agent/engine/subgraphs/state_update_plan.py"]

    directive = StateUpdatePlan(
        set_fields={"current_shop": {"shop_id": "shop_1"}},
        clear_fields=["pending_clarification"],
        source="state_update_planner",
        evidence_ref="ev_1",
        ttl=120,
        location_context={"city": "beijing"},
        reason="resolved",
        blocked=True,
        blocked_reason="loop_guard",
    )
    clone = SessionWriteDirective(
        set_fields=directive.set_fields,
        clear_fields=directive.clear_fields,
        source=directive.source,
        evidence_ref=directive.evidence_ref,
        ttl=directive.ttl,
        location_context=directive.location_context,
        reason=directive.reason,
        blocked=directive.blocked,
        blocked_reason=directive.blocked_reason,
    ).clone()

    assert directive.blocked is True
    assert directive.blocked_reason == "loop_guard"
    assert directive.evidence_ref == "ev_1"
    assert directive.ttl == 120
    assert clone.blocked is True
    assert clone.blocked_reason == "loop_guard"
    assert clone.evidence_ref == "ev_1"
    assert clone.ttl == 120


def test_phase4_dto_authority_modules_are_explicit():
    assert CanonicalDecisionPlan.__module__ == "local_life_agent.domain.decision"
    assert EvidenceReviewResult.__module__ == "local_life_agent.domain.evidence"
    assert ShopCandidate.__module__ == "local_life_agent.domain.shop_entity"
    assert TargetResolutionResult.__module__ == "local_life_agent.domain.facets"

    assert legacy_schemas.DecisionPlan is not CanonicalDecisionPlan
    assert legacy_schemas.ShopCandidate is not ShopCandidate


def test_phase4_slot_extractor_stays_anchor_and_candidate_focused():
    result = extract_slots("海底捞(牡丹园店)和巴奴哪个更适合聚餐，要性价比高", "local_life")

    assert result["comparison_intent"] is True
    assert result["merchant_mentions"]
    assert result["comparison_targets"]
    assert result["preference_signals"]
    assert result["shop_target"] is None
    assert "shop_id" not in result
    assert result["workflow_hint"] == "comparison"


def test_phase4_serialization_helpers_cover_common_python_shapes():
    dataclass_value = _DemoDataclass(name="demo", payload={"nested": [1, 2, 3]})
    model_value = _DemoModel(name="model", payload={"nested": [4, 5]})

    assert to_plain_dict(None) == {}
    assert to_plain_dict({"a": 1}) == {"a": 1}
    assert to_plain_dict(dataclass_value) == {"name": "demo", "payload": {"nested": [1, 2, 3]}}
    assert to_plain_dict(model_value) == {"name": "model", "payload": {"nested": [4, 5]}}

    assert to_plain_list(None) == []
    assert to_plain_list([1, 2]) == [1, 2]
    assert to_plain_list((1, 2)) == [1, 2]
    assert to_plain_list({"x": 1}) == [{"x": 1}]
    assert to_plain_list("scalar") == ["scalar"]
