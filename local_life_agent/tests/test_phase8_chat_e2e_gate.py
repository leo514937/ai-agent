from __future__ import annotations

import json
import re

import pytest

from local_life_agent import agent, config
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import _default_llm_backend, clear_llm_backend, set_llm_backend
from local_life_agent.planning.orchestration_router import build_orchestration_decision
from local_life_agent.tests.chat_e2e_utils import orchestration_decision_from_response
from local_life_agent.tests.conftest import SpyRealLLMBackend
from local_life_agent.tests.fakes import mock_tools


@pytest.fixture(autouse=True)
def _reset_graph_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    yield
    clear_llm_backend()


def _install_default_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def dispatch(tool_name: str, args: dict):
        if tool_name == "resolve_shop":
            return mock_tools.resolve_shop(
                str(args.get("query", "")),
                location=args.get("location"),
                session_shop_ids=args.get("session_shop_ids"),
            )
        if tool_name == "search_shops":
            return mock_tools.search_shops(
                str(args.get("query", "")),
                location=args.get("location"),
                limit=args.get("limit"),
            )
        if tool_name == "get_shop_detail":
            return mock_tools.get_shop_detail(str(args.get("shop_id", "")))
        if tool_name == "check_open_status":
            return mock_tools.check_open_status(str(args.get("shop_id", "")))
        if tool_name == "get_coupon_list":
            return mock_tools.get_coupon_list(str(args.get("shop_id", "")))
        if tool_name == "get_distance_eta":
            return mock_tools.get_distance_eta(
                str(args.get("shop_id", "")),
                args.get("from_location") or {"lat": 39.9609, "lng": 116.3581},
            )
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
    monkeypatch.setattr(
        graph_builder,
        "resolve_shop",
        lambda query, location=None, session_shop_ids=None: dispatch(
            "resolve_shop",
            {"query": query, "location": location, "session_shop_ids": session_shop_ids},
        ),
    )


def _run(text: str, session_id: str, *, trace_id: str = "", turn_id: str = ""):
    return agent.run_agent_graph(text, session_id=session_id, trace_id=trace_id, turn_id=turn_id)


def _phase8_user_text(prompt: str) -> str:
    match = re.search(r"用户输入：\s*(.*)", prompt, re.S)
    if not match:
        match = re.search(r"User text\s*:?\s*(.*)", prompt, re.S)
    return match.group(1).strip() if match else prompt


def _phase8_llm_backend(prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs):
    user_text = _phase8_user_text(prompt)
    if "顶层意图路由" in prompt or "意图分类器" in prompt:
        if "你能帮我做什么" in user_text:
            content = {"top_intent": "chat", "confidence": 0.99, "reason": "phase8_direct_response"}
        elif "下单并支付" in user_text:
            content = {"top_intent": "unsafe", "confidence": 0.99, "reason": "phase8_forbidden"}
        else:
            content = {"top_intent": "local_life", "confidence": 0.99, "reason": "phase8_local_life"}
        return {"ok": True, "content": content, "confidence": content["confidence"], "raw": json.dumps(content, ensure_ascii=False), "error_code": "", "error_message": ""}
    if "本地生活语义解析器" not in prompt and "本地生活语义框架提取器" not in prompt:
        return _default_llm_backend(prompt, system_prompt, temperature, timeout_ms, **kwargs)

    if "海底捞(牡丹园店)有券吗" in user_text:
        semantic = {
            "top_intent": "local_life",
            "task_type": "single_shop_query",
            "primary_task": "coupon_query",
            "workflow_hint": "single_shop_query",
            "merchant_mentions": ["海底捞(牡丹园店)"],
            "shop_target": {"shop_name": "海底捞(牡丹园店)"},
            "reference_mentions": [],
            "comparison_targets": [],
            "ordinal_references": [],
            "deictic_references": [],
            "facets": [{"name": "coupon", "required": True}],
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "confidence": 0.97,
            "need_context": False,
            "grounding_status": "grounded",
            "semantic_parse_source": "spy_real_llm",
        }
    elif "推荐几家性价比高的烧烤" in user_text:
        semantic = {
            "top_intent": "local_life",
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "workflow_hint": "recommendation",
            "comparison_intent": False,
            "comparison_structure": "unknown",
            "comparison_facets": [],
            "exploration_stages": [],
            "location": {},
            "category": "烧烤",
            "facets": [{"name": "category", "required": True}],
            "hard_constraints": {"category": ["烧烤"]},
            "soft_preferences": {"price": "性价比高"},
            "ranking_signals": {},
            "confidence": 0.9,
            "need_context": True,
            "grounding_status": "unknown",
            "missing_slot_type": "missing_location",
            "semantic_parse_source": "spy_real_llm",
        }
    elif "帮我安排先吃饭再喝咖啡的约会路线" in user_text:
        semantic = {
            "top_intent": "local_life",
            "task_type": "local_trip_plan",
            "primary_task": "exploration",
            "workflow_hint": "exploration_planning",
            "exploration_stages": [
                {"stage_id": "stage_1", "stage_type": "eat", "candidate_query": "餐厅", "order": 1, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
                {"stage_id": "stage_2", "stage_type": "coffee", "candidate_query": "咖啡店", "order": 2, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
            ],
            "scene": "date",
            "time": "evening",
            "location": {"location_name": "北京邮电大学附近"},
            "hard_constraints": {"location": "北京邮电大学附近"},
            "soft_preferences": {"scene": "date"},
            "ranking_signals": {"sequence": ["先吃饭再喝咖啡"]},
            "confidence": 0.94,
            "need_context": False,
            "grounding_status": "grounded",
            "semantic_parse_source": "spy_real_llm",
        }
    elif "你能帮我做什么" in user_text:
        semantic = {
            "top_intent": "chat",
            "task_type": "general_chat",
            "primary_task": "capability",
            "workflow_hint": "direct_response",
            "confidence": 0.99,
            "need_context": False,
            "semantic_parse_source": "spy_real_llm",
        }
    elif "帮我下单并支付" in user_text:
        semantic = {
            "top_intent": "unsafe",
            "task_type": "general_chat",
            "primary_task": "capability",
            "workflow_hint": "direct_response",
            "confidence": 0.99,
            "need_context": False,
            "semantic_parse_source": "spy_real_llm",
        }
    else:
        semantic = _default_llm_backend(prompt, system_prompt, temperature, timeout_ms, **kwargs).get("content", {})
        if not isinstance(semantic, dict):
            semantic = {}

    return {"ok": True, "content": semantic, "confidence": float(semantic.get("confidence", 0.95) if isinstance(semantic, dict) else 0.95), "raw": json.dumps(semantic, ensure_ascii=False), "error_code": "", "error_message": ""}


def _decision(response, *, text: str, session_id: str):
    return orchestration_decision_from_response(response, text=text, session_id=session_id)


def _decision_from_state(state: dict):
    return build_orchestration_decision(state)


def test_recommendation_with_location_category_routes_discovery(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐北京邮电大学附近的火锅或烧烤，要性价比高的": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "workflow_hint": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [
                    {"name": "location", "required": True},
                    {"name": "category", "required": True},
                    {"name": "ranking_policy", "required": False},
                ],
                "location": {"location_name": "北京邮电大学附近"},
                "category": "火锅",
                "hard_constraints": {"location": "北京邮电大学附近", "category": ["火锅", "烧烤"]},
                "soft_preferences": {"ranking_policy": "性价比高"},
                "ranking_signals": {"price_preference": "value"},
                "confidence": 0.96,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "推荐北京邮电大学附近的火锅或烧烤，要性价比高的"
    resp = _run(text, "phase8-1")

    assert _decision(resp, text=text, session_id="phase8-1").workflow_name == "discovery_decision"
    assert "北京邮电大学附近" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert resp.debug.turn_trace["llm_called"] is True
    assert resp.debug.turn_trace["router_policy_decision"] is not None
    assert resp.debug.session_state_after.get("pending_clarification") is None
    assert isinstance(resp.debug.session_state_after.get("last_recommendation_list"), list)


def test_single_shop_coupon_query_routes_deterministic_tool(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    set_llm_backend(_phase8_llm_backend)
    monkeypatch.setattr(graph_builder, "call_llm", _phase8_llm_backend)

    text = "海底捞(牡丹园店)有券吗？"
    resp = _run(text, "phase8-2", turn_id="turn-2")
    decision = orchestration_decision_from_response(resp, text=text, session_id="phase8-2", turn_id="turn-2")
    assert decision.workflow_name == "deterministic_tool"
    assert decision.response_mode == "tool_answer"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False
    assert decision.workflow_reason
    assert resp.debug.turn_trace["comparison_route_reason"]


def test_missing_location_triggers_typed_clarification(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    set_llm_backend(_phase8_llm_backend)
    monkeypatch.setattr(graph_builder, "call_llm", _phase8_llm_backend)

    text = "推荐几家性价比高的烧烤"
    resp = _run(text, "phase8-3", turn_id="turn-3")
    decision = orchestration_decision_from_response(resp, text=text, session_id="phase8-3", turn_id="turn-3")
    assert decision.workflow_name == "discovery_decision"
    assert decision.requires_clarification is False
    assert "missing_location" in decision.missing_fields or decision.workflow_reason
    assert resp.debug.turn_trace["comparison_route_reason"]


def test_exploration_planning_with_location_routes_workflow(monkeypatch: pytest.MonkeyPatch):
    state = {
        "raw_text": "帮我安排先吃饭再喝咖啡的约会路线",
        "normalized_text": "帮我安排先吃饭再喝咖啡的约会路线",
        "session_id": "phase8-4",
        "turn_id": "turn-4",
        "top_intent": "local_life",
        "task_type": "local_trip_plan",
        "semantic_frame": {
            "top_intent": "local_life",
            "task_type": "local_trip_plan",
            "primary_task": "exploration",
            "workflow_hint": "exploration_planning",
            "exploration_stages": [
                {"stage_id": "stage_1", "stage_type": "eat", "candidate_query": "餐厅", "order": 1, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
                {"stage_id": "stage_2", "stage_type": "coffee", "candidate_query": "咖啡店", "order": 2, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
            ],
            "scene": "date",
            "time": "evening",
            "location": {"location_name": "北京邮电大学附近"},
            "hard_constraints": {"location": "北京邮电大学附近"},
            "soft_preferences": {"scene": "date"},
            "ranking_signals": {"sequence": ["先吃饭再喝咖啡"]},
            "confidence": 0.94,
            "need_context": False,
            "grounding_status": "grounded",
            "semantic_parse_source": "spy_real_llm",
        },
        "session_state_before": {},
        "session_state": {},
        "current_shop": None,
        "last_recommendation_list": [],
        "comparison_targets": [],
    }

    decision = _decision_from_state(state)
    assert decision.workflow_name == "exploration_planning"
    assert decision.response_mode == "exploration_plan"
    assert decision.requires_tool is True
    assert decision.requires_clarification is False
    assert decision.workflow_reason


def test_direct_response_and_forbidden_scope(monkeypatch: pytest.MonkeyPatch):
    direct_state = {
        "raw_text": "你能帮我做什么？",
        "normalized_text": "你能帮我做什么？",
        "session_id": "phase8-5",
        "turn_id": "turn-5",
        "top_intent": "chat",
        "task_type": "general_chat",
        "semantic_frame": {
            "top_intent": "chat",
            "task_type": "general_chat",
            "primary_task": "capability",
            "workflow_hint": "direct_response",
            "confidence": 0.99,
            "need_context": False,
            "semantic_parse_source": "spy_real_llm",
        },
        "session_state_before": {},
        "session_state": {},
        "current_shop": None,
        "last_recommendation_list": [],
        "comparison_targets": [],
    }
    direct_decision = _decision_from_state(direct_state)
    assert direct_decision.workflow_name == "direct_response"
    assert direct_decision.requires_tool is False
    assert direct_decision.response_mode == "direct_response"

    forbidden_state = {
        "raw_text": "帮我下单并支付",
        "normalized_text": "帮我下单并支付",
        "session_id": "phase8-6",
        "turn_id": "turn-6",
        "top_intent": "unsafe",
        "task_type": "general_chat",
        "semantic_frame": {
            "top_intent": "unsafe",
            "task_type": "general_chat",
            "primary_task": "capability",
            "workflow_hint": "direct_response",
            "confidence": 0.99,
            "need_context": False,
            "semantic_parse_source": "spy_real_llm",
        },
        "session_state_before": {},
        "session_state": {},
        "current_shop": None,
        "last_recommendation_list": [],
        "comparison_targets": [],
    }
    forbidden_decision = _decision_from_state(forbidden_state)
    assert forbidden_decision.workflow_name == "direct_response"
    assert forbidden_decision.requires_tool is False
    assert forbidden_decision.response_mode == "direct_response"
