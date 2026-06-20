"""Stage-11 multi-facet single-shop flow tests."""

from __future__ import annotations

import time

from local_life_agent import config as app_config

from ..agent import run_agent_graph
from ..engine import graph_builder as gb


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
