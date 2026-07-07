from __future__ import annotations

import pytest

from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.tests.conftest import SpyRealLLMBackend
from local_life_agent.tests.fakes import mock_tools


def _install_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def dispatch(tool_name: str, args: dict):
        if tool_name == "resolve_shop":
            return mock_tools.resolve_shop(
                str(args.get("query", "")),
                location=args.get("location"),
                session_shop_ids=args.get("session_shop_ids"),
            )
        if tool_name == "search_shops":
            return mock_tools.search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
        if tool_name == "get_shop_detail":
            return mock_tools.get_shop_detail(str(args.get("shop_id", "")))
        if tool_name == "check_open_status":
            return mock_tools.check_open_status(str(args.get("shop_id", "")))
        if tool_name == "get_coupon_list":
            return mock_tools.get_coupon_list(str(args.get("shop_id", "")))
        if tool_name == "get_distance_eta":
            return mock_tools.get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
        if tool_name == "get_shop_review_summary":
            return mock_tools.get_shop_review_summary(
                list(args.get("shop_ids") or []),
                aspects=args.get("aspects"),
                scene=args.get("scene"),
                max_reviews=args.get("max_reviews"),
            )
        if tool_name == "get_deal_list":
            return mock_tools.get_deal_list(
                str(args.get("shop_id", "")),
                people_count=args.get("people_count"),
                budget_per_person=args.get("budget_per_person"),
                deal_type=args.get("deal_type"),
                only_available=args.get("only_available", True),
            )
        return {"success": False, "result_status": "failed", "error_code": "TOOL_NOT_REGISTERED", "data": None}

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    monkeypatch.setattr(graph_builder, "resolve_shop", lambda query, location=None, session_shop_ids=None: dispatch("resolve_shop", {"query": query, "location": location, "session_shop_ids": session_shop_ids}))


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(config, "TOOL_BACKEND", "db")
    _install_dispatch(monkeypatch)
    spy = SpyRealLLMBackend()
    set_llm_backend(spy)
    monkeypatch.setattr(graph_builder, "call_llm", spy)
    yield
    clear_llm_backend()


def test_cost_benchmark_reports_core_runtime_signals():
    scenarios = [
        ("simple fact query", "海底捞(牡丹园店)现在营业吗？", "cost_simple_fact"),
        ("recommendation", "附近有没有适合约会、现在营业、最好有券的火锅？", "cost_recommendation"),
        ("comparison", "海底捞(牡丹园店)和川味轩(知春路店)哪个好？", "cost_comparison"),
        ("single coupon", "海底捞(牡丹园店)有券吗？", "cost_coupon"),
        ("clarification", "这家和海底捞比呢？", "cost_clarify"),
        ("exploration", "帮我安排先吃饭再喝咖啡的约会路线", "cost_exploration"),
    ]

    summary = {
        "latency_ms": 0,
        "tool_call_count": 0,
        "llm_call_count": 0,
        "cache_hit_count": 0,
        "fallback_count": 0,
        "rewrite_count": 0,
        "scenarios": 0,
    }
    for label, text, session_id in scenarios:
        response = run_agent_graph(text, session_id)
        debug = response.debug
        assert debug is not None
        summary["scenarios"] += 1
        summary["latency_ms"] += int(debug.turn_trace.get("total_duration_ms") or 0)
        summary["tool_call_count"] += int(debug.turn_trace.get("tool_call_count") or 0)
        summary["llm_call_count"] += 1 if debug.turn_trace.get("llm_called") else 0
        summary["rewrite_count"] += int(debug.turn_trace.get("rewrite_count") or 0)
        summary["fallback_count"] += 1 if debug.turn_trace.get("fallback_used") else 0
        summary["cache_hit_count"] += sum(
            1
            for item in (debug.tool_results or {}).values()
            if isinstance(item, dict) and item.get("tool_result_cache_hit")
        )
        assert debug.turn_trace.get("stage_spans"), label
        assert debug.turn_trace.get("response_mode") is not None

    assert summary["scenarios"] == 6
    assert summary["tool_call_count"] >= 0
    assert summary["llm_call_count"] >= 0
    assert summary["cache_hit_count"] >= 0
    assert summary["fallback_count"] >= 0
    assert summary["rewrite_count"] >= 0
