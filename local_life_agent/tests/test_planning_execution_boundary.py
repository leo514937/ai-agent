"""Boundary tests for planning vs execution DB/tool calls."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from local_life_agent.domain.candidate import CandidateSource, GoalType, LocalLifeGoalDraft
from local_life_agent.domain.schemas import ExecutionPlan, SemanticFrame, ToolCallSpec
from local_life_agent.engine import graph_builder
from local_life_agent.engine.subgraphs import planning_subgraph as ps
from local_life_agent.engine.subgraphs.execution_review_subgraph import _h_tool_execute
from local_life_agent.planning.review_policy import NextAction, ReviewStatus


def _state(sf: SemanticFrame | dict[str, Any], *, raw_text: str) -> dict[str, Any]:
    return {
        "raw_text": raw_text,
        "normalized_text": raw_text,
        "semantic_frame": sf,
        "session_state": {},
        "session_state_before": {},
        "event_log": [],
        "turn_id": "turn_boundary",
        "session_id": "session_boundary",
    }


def _recommendation_goal() -> LocalLifeGoalDraft:
    return LocalLifeGoalDraft(
        goal_type=GoalType.RECOMMENDATION,
        candidate_source=CandidateSource.DISCOVERY,
        requested_count=5,
        min_required=1,
        max_allowed=5,
        source_origin="test",
    )


def test_planning_recommendation_does_not_call_business_tools(monkeypatch):
    sf = SemanticFrame(
        task_type="recommendation",
        candidate_source=CandidateSource.DISCOVERY.value,
        candidate_category="火锅",
        merchant_mentions=[],
        reference_mentions=[],
        comparison_targets=[],
        ordinal_references=[],
        deictic_references=[],
    )

    monkeypatch.setattr(ps, "build_local_life_goal_draft", lambda *_args, **_kwargs: _recommendation_goal())

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_dispatch(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        calls.append((tool_name, dict(kwargs)))
        if tool_name == "resolve_shop":
            return graph_builder.resolve_shop(
                str(kwargs.get("query", "")),
                location=kwargs.get("location"),
                session_shop_ids=kwargs.get("session_shop_ids"),
            )
        raise AssertionError(f"{tool_name} should not run during planning")

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", fake_dispatch)

    result = ps._h_target_resolve_candidate_set(_state(sf, raw_text="北邮附近推荐火锅"), sf)

    assert result["target_resolution_status"] in {"MISSING", "PARTIAL", "RESOLVED", "NOT_FOUND"}
    assert "candidate_set" not in result
    assert all(tool_name == "resolve_shop" for tool_name, _ in calls)
    assert not any(tool_name in {"search_shops", "get_coupon_list", "check_open_status", "get_distance_eta"} for tool_name, _ in calls)


def test_planning_single_shop_grounding_stays_out_of_candidate_retrieval(monkeypatch):
    sf = SemanticFrame(
        task_type="single_shop_query",
        candidate_source=CandidateSource.EXPLICIT.value,
        merchant_mentions=["川味轩(知春路店)"],
        reference_mentions=[],
        comparison_targets=[],
        ordinal_references=[],
        deictic_references=[],
    )

    monkeypatch.setattr(
        ps,
        "build_local_life_goal_draft",
        lambda *_args, **_kwargs: LocalLifeGoalDraft(
            goal_type=GoalType.SINGLE_SHOP_QUERY,
            candidate_source=CandidateSource.EXPLICIT,
            requested_count=1,
            min_required=1,
            max_allowed=1,
            source_origin="test",
        ),
    )

    def fake_resolve_shop_entity(*_args, **_kwargs):
        return SimpleNamespace(
            model_dump=lambda: {
                "status": "resolved",
                "shop_id": "shop_001",
                "shop_name": "川味轩(知春路店)",
                "confidence": 1.0,
                "selected_candidate": {"raw": {"address": "知春路"}},
                "candidates": [],
                "resolution_reason": "explicit_reference_resolved",
            },
            trace=[],
        )

    monkeypatch.setattr(ps, "resolve_shop_entity", fake_resolve_shop_entity)

    monkeypatch.setattr(ps, "resolve_shop_entities", lambda *args, **kwargs: [fake_resolve_shop_entity()])
    monkeypatch.setattr(ps, "review_candidate_set", lambda *_args, **_kwargs: SimpleNamespace(next_action=NextAction.FINISH, status=ReviewStatus.ENOUGH, reason="ok"))

    result = ps._h_target_resolve_candidate_set(_state(sf, raw_text="川味轩(知春路店)有券吗"), sf)

    assert result["target_resolution_status"] == "RESOLVED"
    assert result["candidate_set"].status.name == "RESOLVED"
    assert len(result["candidate_set"].candidates) == 1
    assert result["candidate_set"].candidates[0].shop_id == "shop_001"


def test_execution_only_then_calls_tools(monkeypatch):
    plan = ExecutionPlan.model_validate(
        {
            "plan_id": "single_shop_plan",
            "task_type": "single_shop_query",
            "facets": [],
            "optional_facets": [],
            "dependencies": [],
            "target_resolution": {"status": "resolved"},
            "tool_calls": [
                ToolCallSpec(
                    call_id="call_coupon",
                    tool_name="get_coupon_list",
                    args={"shop_id": "shop_001"},
                    target_shop_id="shop_001",
                    required=True,
                    facet="coupon",
                ).model_dump(),
                ToolCallSpec(
                    call_id="call_open",
                    tool_name="check_open_status",
                    args={"shop_id": "shop_001"},
                    target_shop_id="shop_001",
                    required=True,
                    facet="open_status",
                ).model_dump(),
                ToolCallSpec(
                    call_id="call_distance",
                    tool_name="get_distance_eta",
                    args={"shop_id": "shop_001", "from_location": {"lat": 40.0, "lng": 116.0}},
                    target_shop_id="shop_001",
                    required=False,
                    facet="distance",
                ).model_dump(),
            ],
            "stages": [
                {
                    "stage_id": "stage_1",
                    "description": "execute facets",
                    "tool_names": ["get_coupon_list", "check_open_status", "get_distance_eta"],
                    "depends_on": [],
                    "max_parallelism": 3,
                }
            ],
            "target_shop_ids": ["shop_001"],
            "timeout_policy": {"default_timeout_ms": 3000},
            "degradation_policy": {"empty_results": "degrade_answer"},
        }
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_dispatch(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        calls.append((tool_name, dict(kwargs)))
        return {
            "call_id": tool_name,
            "tool_name": tool_name,
            "shop_id": kwargs.get("shop_id", ""),
            "success": True,
            "result_status": "ok",
            "data": {"tool_name": tool_name},
            "source": "fake",
        }

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", fake_dispatch)

    result = _h_tool_execute({"validated_plan": plan, "execution_plan": plan, "precomputed_tool_results": {}})

    assert [tool_name for tool_name, _ in calls] == [
        "get_coupon_list",
        "check_open_status",
        "get_distance_eta",
    ]
    assert result["tool_results"]
    assert len(result["tool_results"]) == 3
