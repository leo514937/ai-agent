from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from local_life_agent import agent, config
from local_life_agent.agent import run_agent_graph
from local_life_agent.engine import graph_builder
from local_life_agent.tools.gateway import dispatch_tool_call as real_dispatch_tool_call


LOG_PATH = Path(__file__).resolve().parents[2] / "var" / "python_service.log"


def _phase0_dispatch(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "") or "")
    shop_id = str(args.get("shop_id", "") or "")

    if "工具失败" in query:
        return {
            "call_id": str(args.get("call_id", "")),
            "shop_id": shop_id,
            "tool_name": tool_name,
            "success": False,
            "result_status": "failed",
            "data": None,
            "error_code": "NETWORK_ERROR",
            "error_message": "phase0 simulated failure",
            "backend_source": "phase0_fake",
            "tool_backend": "phase0_fake",
            "source": "phase0_fake",
            "degraded": False,
            "fallback_from": None,
            "http_status": None,
            "endpoint": None,
        }

    if "工具空结果" in query:
        return {
            "call_id": str(args.get("call_id", "")),
            "shop_id": shop_id,
            "tool_name": tool_name,
            "success": True,
            "result_status": "empty",
            "data": [],
            "error_code": None,
            "error_message": "",
            "backend_source": "phase0_fake",
            "tool_backend": "phase0_fake",
            "source": "phase0_fake",
            "degraded": False,
            "fallback_from": None,
            "http_status": None,
            "endpoint": None,
        }

    if tool_name == "resolve_shop":
        return real_dispatch_tool_call(
            "resolve_shop",
            {
                "query": query,
                "location": args.get("location"),
                "session_shop_ids": args.get("session_shop_ids"),
            },
        )
    if tool_name == "search_shops":
        return real_dispatch_tool_call(
            "search_shops",
            {"query": str(args.get("query", "")), "location": args.get("location"), "limit": args.get("limit")},
        )
    if tool_name == "get_shop_detail":
        return real_dispatch_tool_call("get_shop_detail", {"shop_id": shop_id})
    if tool_name == "check_open_status":
        return real_dispatch_tool_call("check_open_status", {"shop_id": shop_id})
    if tool_name == "get_coupon_list":
        return real_dispatch_tool_call("get_coupon_list", {"shop_id": shop_id})
    if tool_name == "get_distance_eta":
        return real_dispatch_tool_call(
            "get_distance_eta",
            {"shop_id": shop_id, "from_location": args.get("from_location") or {"lat": 39.9609, "lng": 116.3581}},
        )
    if tool_name == "get_shop_cards":
        return real_dispatch_tool_call(
            "get_shop_cards",
            {
                "shop_ids": list(args.get("shop_ids", []) or []),
                "user_location": args.get("user_location"),
                "need_coupon_brief": bool(args.get("need_coupon_brief", True)),
                "need_open_status": bool(args.get("need_open_status", True)),
                "need_distance_eta": bool(args.get("need_distance_eta", True)),
                "max_items": args.get("max_items"),
            },
        )
    if tool_name == "get_shop_review_summary":
        return real_dispatch_tool_call(
            "get_shop_review_summary",
            {
                "shop_ids": list(args.get("shop_ids", []) or []),
                "aspects": args.get("aspects"),
                "scene": args.get("scene"),
                "max_reviews": args.get("max_reviews"),
            },
        )
    if tool_name == "get_deal_list":
        return real_dispatch_tool_call(
            "get_deal_list",
            {
                "shop_id": shop_id,
                "people_count": args.get("people_count"),
                "budget_per_person": args.get("budget_per_person"),
                "deal_type": args.get("deal_type"),
                "only_available": bool(args.get("only_available", True)),
            },
        )
    return {
        "call_id": str(args.get("call_id", "")),
        "shop_id": shop_id,
        "tool_name": tool_name,
        "success": False,
        "result_status": "failed",
        "data": None,
        "error_code": "TOOL_NOT_REGISTERED",
        "error_message": f"Tool '{tool_name}' is not registered",
        "backend_source": "phase0_fake",
        "tool_backend": "phase0_fake",
        "source": "phase0_fake",
        "degraded": False,
        "fallback_from": None,
        "http_status": None,
        "endpoint": None,
    }


@pytest.fixture(autouse=True)
def _phase0_runtime(monkeypatch: pytest.MonkeyPatch):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _phase0_dispatch)
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    yield
    LOG_PATH.write_text("", encoding="utf-8")


PHASE0_SAMPLES = [
    "普通问候",
    "能力说明",
    "附近有什么咖啡店",
    "推荐一家适合约会的日料，别太贵",
    "第一家和第三家哪个好",
    "第二家离我多远",
    "换个便宜点的",
    "这家现在营业吗",
    "无位置时推荐附近店",
    "无历史候选时说“第二家”",
    "工具失败",
    "工具空结果",
    "证据不足",
]


@pytest.mark.parametrize("query", PHASE0_SAMPLES)
def test_phase0_main_path_samples_are_observable(query: str):
    response = run_agent_graph(query, session_id=f"phase0_{abs(hash(query))}")

    assert response.trace_id
    assert response.debug is not None
    assert response.debug.turn_trace["trace_id"] == response.trace_id
    assert LOG_PATH.read_bytes()
    assert response.debug.turn_trace["answer_source"] is not None
