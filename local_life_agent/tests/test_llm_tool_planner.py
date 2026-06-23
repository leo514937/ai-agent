"""Contract tests for the constrained LLM tool planner."""

from __future__ import annotations

from typing import Any

import pytest

from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.engine import graph_builder
from local_life_agent.observability.trace import build_turn_trace
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.planning.llm_tool_planner import build_tool_plan
from local_life_agent.planning.plan_validator import ExecutionPlanValidator
from local_life_agent.domain.schemas import ExecutionPlan, ToolCallSpec
from local_life_agent.tools import mock_tools
from local_life_agent.planning.tool_plan_adapter import build_execution_plan_with_tool_planner


def _single_shop_frame() -> dict[str, Any]:
    return {
        "task_type": "single_shop_query",
        "primary_task": "single_shop_query",
        "confidence": 0.96,
        "semantic_source": "rule_based",
        "llm_backend": "",
    }


def _recommendation_frame() -> dict[str, Any]:
    return {
        "task_type": "recommendation",
        "primary_task": "recommendation",
        "confidence": 0.97,
        "semantic_source": "rule_based",
        "llm_backend": "",
        "soft_preferences": {"scene_terms": ["约会"]},
        "ranking_signals": {"query_terms": ["火锅"], "coupon_preferred": True},
    }


def _recommendation_frame_with_constraints() -> dict[str, Any]:
    return {
        "task_type": "recommendation",
        "primary_task": "推荐一下",
        "confidence": 0.97,
        "semantic_source": "rule_based",
        "llm_backend": "",
        "constraints": {"cuisine": "火锅"},
        "soft_preferences": {},
        "ranking_signals": {},
    }


def _empty_recommendation_frame() -> dict[str, Any]:
    return {
        "task_type": "recommendation",
        "primary_task": "推荐一下",
        "confidence": 0.97,
        "semantic_source": "rule_based",
        "llm_backend": "",
        "soft_preferences": {},
        "ranking_signals": {},
        "hard_constraints": {},
        "constraints": {},
    }


def _comparison_frame() -> dict[str, Any]:
    return {
        "task_type": "comparison",
        "primary_task": "comparison",
        "confidence": 0.97,
        "semantic_source": "rule_based",
        "llm_backend": "",
        "focused_facets": ["review_summary"],
    }


def _comparison_state(shop_count: int = 6) -> dict[str, Any]:
    return {
        "trace_id": "trace_comparison_limit",
        "turn_id": "turn_comparison_limit",
        "session_id": "session_001",
        "raw_text": "对比这些店",
        "task_type": "comparison",
        "top_intent": "local_life",
        "semantic_frame": _comparison_frame(),
        "comparison_targets": [
            {
                "resolved_shop": {
                    "shop_id": f"shop_{idx:02d}",
                    "shop_name": f"店{idx:02d}",
                }
            }
            for idx in range(1, shop_count + 1)
        ],
        "user_context": {"lat": 39.9609, "lng": 116.3581},
    }


def _recommendation_state(frame: dict[str, Any], raw_text: str = "附近推荐火锅") -> dict[str, Any]:
    return {
        "trace_id": "trace_recommendation",
        "turn_id": "turn_recommendation",
        "session_id": "session_001",
        "raw_text": raw_text,
        "task_type": "recommendation",
        "top_intent": "local_life",
        "semantic_frame": frame,
        "user_context": {"lat": 39.9609, "lng": 116.3581},
    }


def _valid_candidate_payload() -> dict[str, Any]:
    return {
        "content": {
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "purpose": "recall and enrich candidates",
            "confidence": 0.91,
            "tool_intents": [
                {"tool_name": "search_shops", "purpose": "召回候选店", "required": True, "priority": 1},
                {"tool_name": "get_shop_cards", "purpose": "汇总候选店事实", "required": False, "priority": 2},
                {"tool_name": "get_shop_review_summary", "purpose": "补充口碑摘要", "required": False, "priority": 3},
            ],
            "notes": ["LLM candidate"],
        }
    }


def _comparison_candidate_payload() -> dict[str, Any]:
    return {
        "content": {
            "task_type": "comparison",
            "primary_task": "comparison",
            "purpose": "compare candidates",
            "confidence": 0.91,
            "tool_intents": [
                {"tool_name": "get_shop_cards", "purpose": "汇总候选店事实", "required": False, "priority": 1},
                {"tool_name": "get_shop_review_summary", "purpose": "补充口碑摘要", "required": False, "priority": 2},
            ],
            "notes": ["LLM candidate"],
        }
    }


def _invalid_candidate_payload() -> dict[str, Any]:
    return {
        "content": {
            "task_type": "single_shop_query",
            "primary_task": "single_shop_query",
            "purpose": "bad tool",
            "confidence": 0.9,
            "tool_intents": [
                {"tool_name": "create_order", "purpose": "illegal", "required": True, "priority": 1},
            ],
            "notes": [],
        }
    }


def _mock_dispatch(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "search_shops":
        return mock_tools.search_shops(str(kwargs.get("query", "")), location=kwargs.get("location"), limit=kwargs.get("limit"))
    if tool_name == "get_shop_cards":
        return mock_tools.get_shop_cards(
            kwargs.get("shop_ids", []),
            user_location=kwargs.get("user_location"),
            need_coupon_brief=kwargs.get("need_coupon_brief", True),
            need_open_status=kwargs.get("need_open_status", True),
            need_distance_eta=kwargs.get("need_distance_eta", True),
            max_items=kwargs.get("max_items"),
        )
    if tool_name == "get_shop_review_summary":
        return mock_tools.get_shop_review_summary(
            kwargs.get("shop_ids", []),
            aspects=kwargs.get("aspects", []),
            scene=kwargs.get("scene"),
            max_reviews=kwargs.get("max_reviews"),
        )
    if tool_name == "get_coupon_list":
        return mock_tools.get_coupon_list(str(kwargs.get("shop_id", "")))
    if tool_name == "check_open_status":
        return mock_tools.check_open_status(str(kwargs.get("shop_id", "")))
    if tool_name == "get_distance_eta":
        return mock_tools.get_distance_eta(str(kwargs.get("shop_id", "")), kwargs.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
    if tool_name == "get_deal_list":
        return mock_tools.get_deal_list(
            str(kwargs.get("shop_id", "")),
            people_count=kwargs.get("people_count"),
            budget_per_person=kwargs.get("budget_per_person"),
            deal_type=kwargs.get("deal_type"),
            only_available=kwargs.get("only_available", True),
        )
    if tool_name == "get_shop_detail":
        return mock_tools.get_shop_detail(str(kwargs.get("shop_id", "")))
    if tool_name == "resolve_shop":
        return mock_tools.resolve_shop(str(kwargs.get("query", "")), location=kwargs.get("location"), session_shop_ids=kwargs.get("session_shop_ids"))
    raise AssertionError(f"Unexpected tool: {tool_name}")


def test_llm_tool_planner_accepts_valid_candidate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_TOOL_PLANNER", True)
    set_llm_backend(lambda **_kwargs: _valid_candidate_payload())
    try:
        decision = build_tool_plan(
            raw_text="附近推荐火锅",
            top_intent="local_life",
            semantic_frame=_recommendation_frame(),
        )
    finally:
        clear_llm_backend()

    assert decision.tool_plan_source == "llm_tool_plan"
    assert decision.tool_plan_validated is True
    assert decision.tool_plan_fallback_reason is None
    assert decision.tool_plan is not None
    assert [item.tool_name for item in decision.tool_plan.tool_intents] == [
        "search_shops",
        "get_shop_cards",
        "get_shop_review_summary",
    ]


def test_llm_tool_planner_invalid_tool_falls_back(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_TOOL_PLANNER", True)
    set_llm_backend(lambda **_kwargs: _invalid_candidate_payload())
    try:
        decision = build_tool_plan(
            raw_text="川味轩有券吗",
            top_intent="local_life",
            semantic_frame=_single_shop_frame(),
        )
    finally:
        clear_llm_backend()

    assert decision.tool_plan_source == "rule_based"
    assert decision.tool_plan_validated is False
    assert decision.tool_plan_fallback_reason == "llm_tool_plan_invalid_tool_name"
    assert decision.tool_plan is None


def test_comparison_targets_are_truncated_to_five(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_TOOL_PLANNER", True)
    set_llm_backend(lambda **_kwargs: _comparison_candidate_payload())
    try:
        result = build_execution_plan_with_tool_planner(_comparison_state(6))
    finally:
        clear_llm_backend()

    plan = result["execution_plan"]
    validator = ExecutionPlanValidator()
    report = validator.validate(plan, resolved_shop_ids={f"shop_{idx:02d}" for idx in range(1, 7)})

    assert result["tool_plan_reason"] == "comparison_targets_truncated"
    assert len(plan.target_shop_ids) == 5
    assert len(plan.tool_calls) == 2
    assert plan.target_shop_ids == [f"shop_{idx:02d}" for idx in range(1, 6)]
    assert report.passed

    trace = build_turn_trace({**_comparison_state(6), **result}, user_text="对比这些店")
    assert trace.tool_plan_reason == "comparison_targets_truncated"


def test_recommendation_query_recovers_from_constraints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_TOOL_PLANNER", True)
    set_llm_backend(lambda **_kwargs: _valid_candidate_payload())
    try:
        result = build_execution_plan_with_tool_planner(_recommendation_state(_recommendation_frame_with_constraints(), raw_text="推荐一下"))
    finally:
        clear_llm_backend()

    plan = result["execution_plan"]
    assert result["tool_plan_reason"] == "fallback_query_from_semantic_frame"
    assert result["recommendation_query"] == "火锅"
    assert plan.tool_calls[0].tool_name == "search_shops"
    assert plan.tool_calls[0].args["query"] == "火锅"

    trace = build_turn_trace({**_recommendation_state(_recommendation_frame_with_constraints(), raw_text="推荐一下"), **result}, user_text="附近推荐火锅")
    assert trace.tool_plan_reason == "fallback_query_from_semantic_frame"


def test_recommendation_empty_query_falls_back_without_empty_search(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_TOOL_PLANNER", True)
    set_llm_backend(lambda **_kwargs: _valid_candidate_payload())
    try:
        result = build_execution_plan_with_tool_planner(_recommendation_state(_empty_recommendation_frame(), raw_text="推荐一下"))
    finally:
        clear_llm_backend()

    plan = result["execution_plan"]
    assert result["tool_plan_fallback_reason"] == "clarify_required_empty_query"
    assert result["tool_plan_reason"] == "empty_recommendation_query"
    assert all(
        not (call.tool_name == "search_shops" and str(call.args.get("query", "")).strip() == "")
        for call in plan.tool_calls
    )

    trace = build_turn_trace({**_recommendation_state(_empty_recommendation_frame(), raw_text="推荐一下"), **result}, user_text="推荐一下")
    assert trace.tool_plan_reason == "empty_recommendation_query"
    assert trace.tool_plan_fallback_reason == "clarify_required_empty_query"


def test_validator_rejects_comparison_over_limit():
    validator = ExecutionPlanValidator()
    plan = ExecutionPlan(
        task_type="comparison",
        target_shop_ids=[f"shop_{idx:02d}" for idx in range(1, 7)],
        tool_calls=[
            ToolCallSpec(
                call_id="call_shop_cards",
                tool_name="get_shop_cards",
                args={"shop_ids": [f"shop_{idx:02d}" for idx in range(1, 7)]},
            )
        ],
    )

    report = validator.validate(plan)

    assert not report.passed
    assert any("comparison_target_limit_exceeded" in error for error in report.errors)


def test_graph_records_tool_plan_trace_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_TOOL_PLANNER", True)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _mock_dispatch)
    call_count = {"value": 0}

    def backend(**_kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": {
                    "top_intent": "local_life",
                    "confidence": 0.99,
                    "reason": "contains business intent",
                }
            }
        if call_count["value"] == 2:
            return {
                "content": {
                    "top_intent": "local_life",
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [],
                    "merchant_mentions": [],
                    "reference_mentions": [],
                    "hard_constraints": {},
                    "soft_preferences": {
                        "scene_terms": ["约会"],
                        "coupon_preferred": True,
                        "open_now_preferred": True,
                        "nearby_preferred": True,
                    },
                    "ranking_signals": {
                        "query_terms": ["火锅"],
                        "coupon_preferred": True,
                        "open_now_preferred": True,
                        "nearby_preferred": True,
                    },
                    "follow_up": None,
                    "confidence": 0.97,
                    "need_context": False,
                }
            }
        return _valid_candidate_payload()

    set_llm_backend(backend)
    try:
        response = run_agent_graph("附近推荐火锅，最好有券、现在营业、离我近一点", "tool_plan_trace")
    finally:
        clear_llm_backend()

    assert response.debug is not None
    turn_trace = response.debug.turn_trace
    assert turn_trace["tool_plan_source"] == "llm_tool_plan"
    assert turn_trace["tool_plan_validated"] is True
    assert turn_trace["tool_plan_fallback_reason"] is None
    assert "call_shop_cards" in response.debug.tool_results
    assert response.debug.execution_plan
