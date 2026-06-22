from __future__ import annotations

import os
import json
import re
from typing import Any
import pytest

from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import get_session_store, reset_session_store
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.target.reference_resolver import resolve_references
from local_life_agent.tools.mock_tools import (
    resolve_shop,
    search_shops,
    get_shop_detail,
    check_open_status,
    get_coupon_list,
    get_distance_eta,
)

SHOP_HAIDILAO = {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}
SHOP_KAOROU = {"shop_id": "shop_001", "shop_name": "木屋烧烤(知春路店)"}


def _accept_dispatch(tool_name: str, args: dict) -> dict:
    if tool_name == "resolve_shop":
        query = str(args.get("query", "")).strip()
        if "山城一锅" in query:
            return {
                "status": "RESOLVED",
                "shop": {
                    "shop_id": "shop_shancheng",
                    "shop_name": "山城一锅",
                    "category": "火锅",
                    "rating": 4.2
                },
                "confidence": 0.95
            }
        return resolve_shop(query, location=args.get("location"))
    if tool_name == "search_shops":
        return search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
    
    shop_id = str(args.get("shop_id", "")).strip()
    if shop_id == "shop_shancheng":
        if tool_name == "get_shop_detail":
            return {
                "success": True,
                "result_status": "ok",
                "shop_id": "shop_shancheng",
                "data": {
                    "shop_id": "shop_shancheng",
                    "shop_name": "山城一锅",
                    "category": "火锅",
                    "rating": 4.2,
                    "avg_price": 90.0,
                    "tags": ["火锅", "川菜"]
                }
            }
        if tool_name == "check_open_status":
            return {
                "success": True,
                "result_status": "ok",
                "shop_id": "shop_shancheng",
                "data": {
                    "shop_id": "shop_shancheng",
                    "shop_name": "山城一锅",
                    "open_status": "open"
                }
            }
        if tool_name == "get_coupon_list":
            return {
                "success": True,
                "result_status": "empty",
                "shop_id": "shop_shancheng",
                "data": []
            }
        if tool_name == "get_distance_eta":
            return {
                "success": True,
                "result_status": "ok",
                "shop_id": "shop_shancheng",
                "data": {
                    "shop_id": "shop_shancheng",
                    "shop_name": "山城一锅",
                    "distance_km": 0.8,
                    "eta_minutes": 8
                }
            }
            
    if tool_name == "get_shop_detail":
        return get_shop_detail(shop_id)
    if tool_name == "check_open_status":
        return check_open_status(shop_id)
    if tool_name == "get_coupon_list":
        return get_coupon_list(shop_id)
    if tool_name == "get_distance_eta":
        return get_distance_eta(
            shop_id,
            args.get("from_location") or {"lat": 39.9609, "lng": 116.3581},
        )
    raise AssertionError(f"Unexpected tool: {tool_name}")


class SpyRealLLMBackend:
    llm_backend = "real_llm"
    
    def __init__(self):
        self.call_count = 0
        self.calls = []
        
    def __call__(self, prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000) -> str:
        self.call_count += 1
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        
        prompt_lower = prompt.lower()
        
        # Extract user-query portion for content-based matching (the prompt
        # template itself may contain keywords like 约会, so we only match
        # against the actual user text after the "User text:" marker).
        user_text = prompt
        if "User text:" in prompt:
            user_text = prompt.split("User text:", 1)[1].strip()
        
        # 1. Router
        if "top_intent_router" in prompt or "top_intent" in system_prompt or "router" in prompt_lower:
            return json.dumps({
                "top_intent": "local_life",
                "confidence": 0.98,
                "reason": "contains_business_intent"
            }, ensure_ascii=False)
            
        # 2. Semantic Frame Parser
        if "local_life_parser" in prompt or "semantic parser" in prompt_lower or "semantic_frame" in prompt_lower:
            if "约会" in user_text:
                # Query 1
                return json.dumps({
                    "top_intent": "local_life",
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [
                        {"name": "detail", "required": True},
                        {"name": "open_status", "required": True},
                        {"name": "coupon", "required": False},
                        {"name": "distance", "required": True}
                    ],
                    "ranking_signals": {
                        "query_terms": ["火锅"],
                        "scene_terms": ["约会"]
                    },
                    "confidence": 0.95
                }, ensure_ascii=False)
            elif "海底捞" in user_text and "山城一锅" in user_text:
                # Query 2
                return json.dumps({
                    "top_intent": "local_life",
                    "task_type": "comparison",
                    "primary_task": "comparison",
                    "merchant_mentions": ["海底捞", "山城一锅"],
                    "comparison_targets": [
                        {"reference": "explicit", "shop_name": "海底捞", "source_text": "海底捞"},
                        {"reference": "explicit", "shop_name": "山城一锅", "source_text": "山城一锅"}
                    ],
                    "confidence": 0.95
                }, ensure_ascii=False)
            elif "便宜" in user_text:
                # Query 3 follow-up
                return json.dumps({
                    "top_intent": "local_life",
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "ranking_signals": {
                        "query_terms": ["火锅"],
                        "price_preferred": "cheap"
                    },
                    "confidence": 0.95,
                    "need_context": True
                }, ensure_ascii=False)
            elif "第一家" in user_text or "第一" in user_text:
                # Query 4 follow-up
                return json.dumps({
                    "top_intent": "local_life",
                    "task_type": "coupon_query",
                    "primary_task": "coupon",
                    "ordinal_references": ["第一家"],
                    "facets": [
                        {"name": "coupon", "required": True}
                    ],
                    "confidence": 0.95
                }, ensure_ascii=False)
            else:
                return json.dumps({
                    "top_intent": "local_life",
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "ranking_signals": {
                        "query_terms": ["火锅"]
                    },
                    "confidence": 0.95
                }, ensure_ascii=False)
                
        # 3. Verbalizer
        if "decisionplan" in prompt_lower or "verbalize" in prompt_lower:
            shops = re.findall(r'"shop_name":\s*"([^"]+)"', prompt)
            seen = set()
            unique_shops = []
            for s in shops:
                if s and s not in seen and s != "????":
                    seen.add(s)
                    unique_shops.append(s)
            if not unique_shops:
                unique_shops = ["某家火锅店"]
                
            if "comparison" in prompt_lower or "对比" in prompt_lower:
                res_text = f"对比{'和'.join(unique_shops)}：在已知信息中，{unique_shops[0]}评分更高，更推荐。"
            elif "recommendation" in prompt_lower or "推荐" in prompt_lower:
                res_text = f"附近我推荐这{len(unique_shops)}家店：{'、'.join(unique_shops)}。"
            else:
                res_text = f"{unique_shops[0]}目前是营业中，有优惠券。"
                
            return json.dumps({
                "natural_response": res_text
            }, ensure_ascii=False)
            
        return "{}"


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    reset_session_store()
    # Explicitly configure real llm modes and verbalizer
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(config, "LLM_BACKEND", "real_llm")
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _accept_dispatch)
    yield
    clear_llm_backend()
    reset_session_store()


def test_spy_e2e_query_1_recommendation():
    """1. 附近有没有适合约会、现在营业、最好有券的火锅？"""
    spy = SpyRealLLMBackend()
    set_llm_backend(spy)
    
    response = run_agent_graph("附近有没有适合约会、现在营业、最好有券的火锅？", "session_q1")
    
    assert spy.call_count > 0
    assert response.debug is not None
    assert response.debug.semantic_frame.get("semantic_source") == "real_llm"
    assert response.debug.semantic_frame.get("llm_called") is True
    assert response.debug.semantic_frame.get("fallback_reason") in ("", None)
    assert response.debug.answer_source in ("llm_verbalizer", "template", "template_fallback")


def test_spy_e2e_query_2_comparison():
    """2. 海底捞和山城一锅哪个好？"""
    spy = SpyRealLLMBackend()
    set_llm_backend(spy)
    
    response = run_agent_graph("海底捞和山城一锅哪个好？", "session_q2")
    
    assert spy.call_count > 0
    assert response.debug is not None
    assert response.debug.semantic_frame.get("semantic_source") == "real_llm"
    assert response.debug.semantic_frame.get("llm_called") is True
    assert response.debug.semantic_frame.get("fallback_reason") in ("", None)


def test_spy_e2e_query_3_multi_turn_recommendation():
    """3. 附近推荐火锅 -> 便宜一点的呢"""
    spy = SpyRealLLMBackend()
    set_llm_backend(spy)
    
    # First turn
    run_agent_graph("附近推荐火锅", "session_q3")
    # Second turn
    response = run_agent_graph("便宜一点的呢", "session_q3")
    
    assert spy.call_count > 0
    assert response.debug is not None
    assert response.debug.semantic_frame.get("semantic_source") == "real_llm"
    assert response.debug.semantic_frame.get("llm_called") is True
    assert response.debug.semantic_frame.get("fallback_reason") in ("", None)
    assert response.debug.answer_source == "llm_verbalizer"


def test_spy_e2e_query_4_multi_turn_single_shop_reference():
    """4. 附近推荐火锅 -> 第一家有券吗"""
    spy = SpyRealLLMBackend()
    set_llm_backend(spy)
    
    # Pre-seed recommendation list in session
    session_store = get_session_store()
    session_store.save("session_q4", SessionState(last_recommendation_list=[SHOP_HAIDILAO, SHOP_KAOROU]))
    
    response = run_agent_graph("第一家有券吗", "session_q4")
    
    assert spy.call_count > 0
    assert response.debug is not None
    
    # Assert reference resolved correctly
    sf = response.debug.semantic_frame
    session_state = response.debug.session_state_before
    
    # Resolve reference using the actual function to verify resolution source
    res = resolve_references("第一家有券吗", session_state, sf)
    assert res.get("status") == "resolved"
    assert res.get("resolution_source") == "semantic_frame"
    assert res.get("resolution_source") != "raw_text"
    
    assert sf.get("semantic_source") == "real_llm"
    assert sf.get("llm_called") is True
    assert sf.get("fallback_reason") in ("", None)
    assert response.debug.answer_source in ("llm_verbalizer", "template", "template_fallback")


def test_real_llm_integration_scenarios(monkeypatch):
    api_key_env = os.environ.get("REAL_LLM_API_KEY_ENV", "LLM_API_KEY")
    api_key = os.environ.get(api_key_env) or os.environ.get("LLM_API_KEY")
    
    if not api_key:
        print("real_llm integration skipped, cannot determine if real provider is verified.")
        pytest.skip("real_llm integration skipped because API key is missing")
        
    from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
    real_backend = OpenAICompatibleBackend()
    set_llm_backend(real_backend)
    
    try:
        response = run_agent_graph("附近有没有适合约会、现在营业、最好有券的火锅？", "session_real_llm")
        assert response.debug is not None
        assert response.debug.semantic_frame.get("semantic_source") == "real_llm"
        assert response.debug.semantic_frame.get("llm_called") is True
        assert response.debug.semantic_frame.get("fallback_reason") is None
        
        # Test comparison
        response_comp = run_agent_graph("海底捞(牡丹园店)和木屋烧烤(知春路店)哪个好？", "session_real_llm_comp")
        assert response_comp.debug is not None
        assert response_comp.debug.semantic_frame.get("semantic_source") == "real_llm"
        assert response_comp.debug.semantic_frame.get("llm_called") is True
        assert response_comp.debug.semantic_frame.get("fallback_reason") is None
        
    finally:
        clear_llm_backend()
