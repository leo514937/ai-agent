"""Stage-11 multi-facet single-shop flow tests."""

from __future__ import annotations

import time

from local_life_agent import config as app_config
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend

from ..agent import run_agent_graph
from ..engine import graph_builder as gb
from ..target import shop_resolver as shop_resolver_module
from ..target.shop_resolver import resolve_shop


def test_multi_facet_plan_executes_same_shop_in_parallel(monkeypatch):
    calls: list[tuple[str, dict]] = []
    original = gb.dispatch_tool_call

    def spy_dispatch(tool_name: str, kwargs: dict):
        calls.append((tool_name, dict(kwargs)))
        return original(tool_name, kwargs)

    monkeypatch.setattr(gb, "dispatch_tool_call", spy_dispatch)

    response = run_agent_graph("川味轩(知春路店)有券吗，顺便看现在营业吗，远不远？", "stage11_multi")

    assert response.answer_text
    assert response.debug is not None
    assert response.debug.execution_plan
    assert response.debug.tool_results
    assert {tool_name for tool_name, _ in calls} == {
        "get_coupon_list",
        "check_open_status",
        "get_distance_eta",
    }
    assert len(calls) == 3
    assert len({kwargs["shop_id"] for _, kwargs in calls}) == 1
    assert "有券" in response.answer_text
    assert "营业" in response.answer_text
    assert "距离" in response.answer_text


def test_optional_distance_timeout_does_not_block_other_facets(monkeypatch):
    original = gb.dispatch_tool_call
    original_deadline = app_config.DEADLINE_MS

    def slow_distance_dispatch(tool_name: str, kwargs: dict):
        if tool_name == "get_distance_eta":
            time.sleep(0.2)
        return original(tool_name, kwargs)

    monkeypatch.setattr(gb, "dispatch_tool_call", slow_distance_dispatch)
    monkeypatch.setattr(app_config, "DEADLINE_MS", 80)
    try:
        response = run_agent_graph("川味轩(知春路店)有券吗，顺便看现在营业吗，顺便看看距离远不远？", "stage11_timeout")
    finally:
        monkeypatch.setattr(app_config, "DEADLINE_MS", original_deadline)

    assert response.answer_text
    assert "有券" in response.answer_text
    assert "营业" in response.answer_text
    assert "暂时无法确认" in response.answer_text and "距离" in response.answer_text


def test_graph_semantic_parse_uses_llm_call(monkeypatch):
    backend_calls: list[dict[str, object]] = []
    call_count = {"value": 0}

    def backend(**kwargs):
        backend_calls.append(kwargs)
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": {
                    "top_intent": "local_life",
                    "confidence": 0.99,
                    "reason": "contains business intent",
                }
            }
        return {
            "content": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "distance_query",
                "facets": [{"name": "distance", "required": True}],
                "merchant_mentions": ["海底捞火锅(水晶城购物中心店)"],
                "reference_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.99,
                "need_context": False,
            }
        }

    set_llm_backend(backend)
    try:
        response = run_agent_graph("海底捞水晶城店多久能到", "stage11_llm_distance")
    finally:
        clear_llm_backend()

    assert backend_calls
    assert response.debug is not None
    assert response.debug.semantic_frame["facets"][0]["name"] == "distance"
    assert "get_distance_eta" in response.debug.execution_plan["stages"][0]["tool_names"]
    assert "距离" in response.answer_text
    assert "券" not in response.answer_text


def test_group_buy_query_maps_to_coupon_by_semantic_frame(monkeypatch):
    call_count = {"value": 0}

    def backend(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": {
                    "top_intent": "local_life",
                    "confidence": 0.99,
                    "reason": "contains business intent",
                }
            }
        return {
            "content": {
                "top_intent": "local_life",
                "task_type": "coupon_query",
                "primary_task": "coupon_query",
                "facets": [{"name": "coupon", "required": True}],
                "merchant_mentions": ["海底捞火锅(水晶城购物中心店)"],
                "reference_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.98,
                "need_context": False,
            }
        }

    set_llm_backend(backend)
    try:
        response = run_agent_graph("海底捞水晶城店有什么团购", "stage11_llm_coupon")
    finally:
        clear_llm_backend()

    assert response.debug is not None
    assert any(
        call.get("tool_name") == "get_coupon_list"
        for call in response.debug.execution_plan.get("tool_calls", [])
    )
    assert "券" in response.answer_text


def test_unrecognized_facet_does_not_default_coupon(monkeypatch):
    call_count = {"value": 0}

    def backend(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": {
                    "top_intent": "local_life",
                    "confidence": 0.99,
                    "reason": "contains business intent",
                }
            }
        return {
            "content": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "distance_query",
                "facets": [],
                "merchant_mentions": ["海底捞火锅(水晶城购物中心店)"],
                "reference_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.8,
                "need_context": False,
            }
        }

    set_llm_backend(backend)
    try:
        response = run_agent_graph("海底捞水晶城店多久能到", "stage11_no_facet")
    finally:
        clear_llm_backend()

    assert response.debug is not None
    tool_calls = response.debug.execution_plan.get("tool_calls", [])
    assert tool_calls
    assert any(call.get("facet") == "detail" for call in tool_calls)
    assert any(call.get("tool_name") == "get_shop_detail" for call in tool_calls)
    assert "券" not in response.answer_text


def test_optional_distance_failed_does_not_fallback_whole_request(monkeypatch):
    original = gb.dispatch_tool_call

    def flaky_dispatch(tool_name: str, kwargs: dict):
        if tool_name == "get_distance_eta":
            return {
                "call_id": kwargs.get("call_id", ""),
                "shop_id": kwargs.get("shop_id", ""),
                "tool_name": tool_name,
                "success": False,
                "result_status": "failed",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": "distance failed",
                "source": "mock",
                "degraded": True,
            }
        return original(tool_name, kwargs)

    monkeypatch.setattr(gb, "dispatch_tool_call", flaky_dispatch)

    response = run_agent_graph("川味轩(知春路店)有券吗，顺便看现在营业吗，顺便看看距离远不远？", "stage11_optional_failed")

    assert response.answer_text
    assert "有券" in response.answer_text
    assert "营业" in response.answer_text
    assert "距离" in response.answer_text
    assert "失败" in response.answer_text or "暂时无法确认" in response.answer_text


def test_shop_resolver_wrapper_uses_gateway(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_dispatch(tool_name: str, kwargs: dict):
        calls.append((tool_name, dict(kwargs)))
        return {
            "call_id": kwargs.get("call_id", ""),
            "shop_id": kwargs.get("query", ""),
            "tool_name": tool_name,
            "success": True,
            "result_status": "ok",
            "data": {
                "status": "RESOLVED",
                "shop": {
                    "shop_id": "shop_sc_01",
                    "shop_name": "海底捞火锅(水晶城购物中心店)",
                },
            },
            "error_code": None,
            "error_message": "",
            "source": "mock",
            "degraded": False,
        }

    monkeypatch.setattr(shop_resolver_module, "dispatch_tool_call", fake_dispatch)
    result = resolve_shop("海底捞水晶城店", location={"lat": 39.9609, "lng": 116.3581}, session_shop_ids=["shop_sc_01"])

    assert calls and calls[0][0] == "resolve_shop"
    assert result["success"] is True
