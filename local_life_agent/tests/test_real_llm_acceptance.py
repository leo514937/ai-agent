from __future__ import annotations

import os
from typing import Any
import pytest

from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import get_session_store, reset_session_store
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.target.reference_resolver import resolve_references
from .conftest import SpyRealLLMBackend
from local_life_agent.tests.fakes.mock_tools import (
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





@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    reset_session_store()
    # Explicitly configure real llm modes and verbalizer
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(config, "LLM_BACKEND", "real_llm")
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(config, "TOOL_BACKEND", "db")
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
    assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "spy_real_llm")
    assert response.debug.semantic_frame.get("llm_called") is True
    assert not response.debug.semantic_frame.get("fallback_reason")
    assert response.debug is not None


def test_spy_e2e_query_2_comparison():
    """2. 海底捞和山城一锅哪个好？"""
    spy = SpyRealLLMBackend()
    set_llm_backend(spy)
    
    response = run_agent_graph("海底捞和山城一锅哪个好？", "session_q2")
    
    assert spy.call_count > 0
    assert response.debug is not None
    assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "spy_real_llm")
    assert response.debug.semantic_frame.get("llm_called") is True
    assert not response.debug.semantic_frame.get("fallback_reason")
    assert response.debug.answer_source in ("llm_verbalizer", "", "fallback")


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
    assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "spy_real_llm")
    assert response.debug.semantic_frame.get("llm_called") is True
    assert not response.debug.semantic_frame.get("fallback_reason")
    # Answer may be verbalized or go through clarification/disambiguation
    assert response.debug.answer_source in ("llm_verbalizer", "", "fallback")


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
    
    # Resolve reference using the actual function to verify resolution
    res = resolve_references("第一家有券吗", session_state, sf)
    assert res.get("status") == "resolved"
    
    assert sf.get("semantic_source") in ("real_llm", "spy_real_llm")
    assert sf.get("llm_called") is True
    assert not sf.get("fallback_reason")
    # Only check LLM path was taken; answer may be fallback if tools fail


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
        assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "spy_real_llm")
        assert response.debug.semantic_frame.get("llm_called") is True
        assert not response.debug.semantic_frame.get("fallback_reason")
        
        # Test comparison
        response_comp = run_agent_graph("海底捞(牡丹园店)和木屋烧烤(知春路店)哪个好？", "session_real_llm_comp")
        assert response_comp.debug is not None
        assert response_comp.debug.semantic_frame.get("semantic_source") in ("real_llm", "spy_real_llm")
        assert response_comp.debug.semantic_frame.get("llm_called") is True
        assert not response_comp.debug.semantic_frame.get("fallback_reason")
        
    finally:
        clear_llm_backend()
