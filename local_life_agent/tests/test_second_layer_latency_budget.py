from __future__ import annotations

from time import perf_counter

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


def test_latency_budget_benchmark_covers_core_scenarios():
    scenarios = [
        ("simple fact query", "海底捞(牡丹园店)现在营业吗？", "latency_simple_fact"),
        ("recommendation", "附近有没有适合约会、现在营业、最好有券的火锅？", "latency_recommendation"),
        ("comparison", "海底捞(牡丹园店)和川味轩(知春路店)哪个好？", "latency_comparison"),
        ("single coupon", "海底捞(牡丹园店)有券吗？", "latency_coupon"),
        ("clarification", "这家和海底捞比呢？", "latency_clarify"),
        ("exploration", "帮我安排先吃饭再喝咖啡的约会路线", "latency_exploration"),
    ]

    summary = {"scenarios": 0, "latency_ms": [], "tool_call_count": [], "llm_called": [], "rewrite_count": []}
    for label, text, session_id in scenarios:
        started = perf_counter()
        response = run_agent_graph(text, session_id)
        elapsed_ms = int((perf_counter() - started) * 1000)
        debug = response.debug
        assert debug is not None
        assert debug.turn_trace.get("total_duration_ms") is not None
        assert elapsed_ms >= 0
        summary["scenarios"] += 1
        summary["latency_ms"].append(int(debug.turn_trace.get("total_duration_ms") or 0))
        summary["tool_call_count"].append(int(debug.turn_trace.get("tool_call_count") or 0))
        summary["llm_called"].append(bool(debug.turn_trace.get("llm_called")))
        summary["rewrite_count"].append(int(debug.turn_trace.get("rewrite_count") or 0))
        assert debug.turn_trace.get("trace_id")
        assert debug.turn_trace.get("spans")
        assert debug.turn_trace.get("stage_spans")
        assert summary["latency_ms"][-1] >= 0, label

    assert summary["scenarios"] == 6
    assert max(summary["latency_ms"]) < 20000
