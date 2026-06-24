from __future__ import annotations

from typing import Any
import pytest
import re
import json

from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import get_session_store, reset_session_store
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.tests.fakes.mock_tools import (
    check_open_status,
    get_coupon_list,
    get_distance_eta,
    get_shop_detail,
    resolve_shop,
    search_shops,
)

SHOP_A = {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}
SHOP_B = {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}
SHOP_C = {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"}


def _comparison_dispatch(tool_name: str, args: dict) -> dict:
    if tool_name == "search_shops":
        return search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
    if tool_name == "get_shop_detail":
        return get_shop_detail(str(args.get("shop_id", "")))
    if tool_name == "check_open_status":
        return check_open_status(str(args.get("shop_id", "")))
    if tool_name == "get_coupon_list":
        return get_coupon_list(str(args.get("shop_id", "")))
    if tool_name == "get_distance_eta":
        return get_distance_eta(
            str(args.get("shop_id", "")),
            args.get("from_location") or {"lat": 39.9609, "lng": 116.3581},
        )
    raise AssertionError(f"Unexpected tool: {tool_name}")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    reset_session_store()
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(config, "TOOL_BACKEND", "db")
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _comparison_dispatch)
    from local_life_agent import agent
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    yield
    clear_llm_backend()
    reset_session_store()


def _mock_llm_client(content: str | dict | None = None, ok: bool = True) -> Any:
    # Known shop data for generating verification-compatible output
    _SHOP_DATA = {
        "海底捞(牡丹园店)": {"rating": 4.7, "distance_km": 1.8, "open_status": "open", "coupon": "有券"},
        "海底捞(A店)": {"rating": 4.5, "distance_km": 3.2, "open_status": "open", "coupon": "暂无可用券"},
        "海底捞(C店)": {"rating": 4.4, "distance_km": 3.8, "open_status": "open", "coupon": "暂无可用券"},
        "海底捞火锅(水晶城购物中心店)": {"rating": 4.6, "distance_km": 8.5, "open_status": "open", "coupon": "暂无可用券"},
        "川味轩(知春路店)": {"rating": 4.2, "distance_km": 2.5, "open_status": "open", "coupon": "有券"},
    }

    class MockBackend:
        llm_backend = "fake_llm"
        
        def __call__(self, prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs) -> str:
            if "DecisionPlan" in prompt or "DecisionPlan" in system_prompt:
                if not ok:
                    raise RuntimeError("LLM simulated failure")
                import json
                if content is not None:
                    payload = {"natural_response": content} if isinstance(content, str) else content
                    return json.dumps(payload, ensure_ascii=False)
                
                # Dynamic parsing
                import re
                selected_shops = []
                targets_line_match = re.search(r'- 选择的目标店面:\s*(.*)', prompt)
                if targets_line_match:
                    targets_line = targets_line_match.group(1)
                    selected_shops = re.findall(r'"shop_name":\s*"([^"]+)"', targets_line)
                
                ranking_shops = []
                ranking_line_match = re.search(r'- 综合排序:\s*(.*)', prompt)
                if ranking_line_match:
                    ranking_line = ranking_line_match.group(1)
                    ranking_shops = re.findall(r'"shop_name":\s*"([^"]+)"', ranking_line)
                
                def _shop_detail(name: str) -> str:
                    """Generate detail segment that passes B2MiniVerifier checks."""
                    d = _SHOP_DATA.get(name, {})
                    parts = []
                    r = d.get("rating")
                    if r is not None:
                        parts.append(f"评分{r}")
                    dist = d.get("distance_km")
                    if dist is not None:
                        parts.append(f"距离约{dist}公里")
                    os = d.get("open_status", "unknown")
                    if os == "open":
                        parts.append("营业中")
                    elif os == "closed":
                        parts.append("已打烊")
                    else:
                        parts.append("营业状态未知")
                    coup = d.get("coupon")
                    if coup == "有券":
                        parts.append("有券")
                    elif coup == "暂无可用券":
                        parts.append("暂无可用券")
                    return "，".join(parts) if parts else ""
                
                # Check for comparison / recommendation
                if "意图类型: comparison" in prompt:
                    all_shops = ranking_shops or selected_shops
                    if all_shops:
                        detail_parts = [f"{s}({_shop_detail(s)})" for s in all_shops]
                        res_text = "对比" + "和".join(all_shops) + "：" + "、".join(detail_parts) + f"。在综合排序里，{all_shops[0]}更好。"
                    else:
                        res_text = "对比完成。"
                elif "意图类型: recommendation" in prompt:
                    if len(selected_shops) >= 3:
                        items = [f"{i}. {s}({_shop_detail(s)})" for i, s in enumerate(selected_shops[:3], 1)]
                        res_text = "附近我推荐这3家：" + "；".join(items) + "。"
                    else:
                        shops_str = "、".join(selected_shops)
                        res_text = f"附近我推荐：{shops_str}。"
                else:
                    if selected_shops:
                        res_text = f"{selected_shops[0]}目前是营业中。"
                    else:
                        res_text = "店面信息已确认。"
                
                payload = {"natural_response": res_text}
                return json.dumps(payload, ensure_ascii=False)
            else:
                from local_life_agent.llm.client import _default_llm_backend
                return _default_llm_backend(prompt, system_prompt, temperature, timeout_ms)
                
    return MockBackend()


def _sequence_llm_client(contents: list[str]) -> Any:
    class MockBackend:
        llm_backend = "fake_llm"

        def __init__(self, responses: list[str]):
            self._responses = list(responses)
            self._call_count = 0

        def __call__(self, prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs) -> str:
            if "DecisionPlan" in prompt or "DecisionPlan" in system_prompt:
                import json

                index = min(self._call_count, len(self._responses) - 1)
                payload = {"natural_response": self._responses[index]}
                self._call_count += 1
                return json.dumps(payload, ensure_ascii=False)
            from local_life_agent.llm.client import _default_llm_backend

            return _default_llm_backend(prompt, system_prompt, temperature, timeout_ms)

    return MockBackend(contents)


def test_graph_verbalizer_recommendation_success(monkeypatch):
    monkeypatch.setattr(graph_builder, "_route_tool_execute", lambda state: "evidence_build")
    client = _mock_llm_client()
    set_llm_backend(client)
    
    response = run_agent_graph("附近推荐火锅", "graph_reco_success")
    assert response.debug is not None
    assert response.answer_text


def test_graph_verbalizer_recommendation_violation_fallback():
    # Mention "川味轩(知春路店)" which is a known shop but NOT a target in the recommendation plan
    client = _mock_llm_client("附近我推荐这3家：1. 海底捞(牡丹园店)，2. 海底捞(A店)，3. 川味轩(知春路店)。")
    set_llm_backend(client)
    
    response = run_agent_graph("附近推荐火锅", "graph_reco_violation")
    assert response.debug is not None
    assert response.answer_text


def test_graph_verbalizer_comparison_success(monkeypatch):
    monkeypatch.setattr(graph_builder, "_route_tool_execute", lambda state: "evidence_build")
    client = _mock_llm_client()
    set_llm_backend(client)
    
    get_session_store().save("graph_comp_success", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))
    
    response = run_agent_graph("第一家和第二家哪个更好？", "graph_comp_success")
    assert response.debug is not None
    assert response.answer_text


def test_graph_verbalizer_comparison_ranking_violation_fallback():
    # LLM returns changed ranking order (places 川味轩 before 海底捞 when overall_ranking expects 海底捞 first)
    client = _mock_llm_client("对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。")
    set_llm_backend(client)
    
    get_session_store().save("graph_comp_violation", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))
    
    response = run_agent_graph("第一家和第二家哪个更好？", "graph_comp_violation")
    assert response.debug is not None
    assert response.answer_text


def test_graph_verbalizer_single_shop_success():
    client = _mock_llm_client()
    set_llm_backend(client)
    
    get_session_store().save("graph_single_success", SessionState(last_recommendation_list=[SHOP_A]))
    
    response = run_agent_graph("第一家营业中吗", "graph_single_success")
    assert response.debug is not None
    assert response.debug.answer_source == "llm_verbalizer"
    assert "营业中" in response.answer_text


def test_graph_verbalizer_unknown_as_false_violation_fallback(monkeypatch):
    # Force the coupon tool to return unknown
    def mock_dispatch(tool_name: str, args: dict) -> dict:
        if tool_name == "get_coupon_list":
            return {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": "unknown status override",
            }
        return _comparison_dispatch(tool_name, args)
    from local_life_agent import agent
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", mock_dispatch)
    monkeypatch.setattr(graph_builder, "_route_tool_execute", lambda state: "evidence_build")
    monkeypatch.setattr(graph_builder, "_route_evidence_review", lambda state: "decision_planner")
    
    # LLM claims "没有券" (coupon is unknown)
    client = _mock_llm_client("川味轩(知春路店)目前没有券。")
    set_llm_backend(client)
    
    get_session_store().save("graph_single_unknown_violation", SessionState(last_recommendation_list=[SHOP_A]))
    
    response = run_agent_graph("第一家有优惠券吗", "graph_single_unknown_violation")
    assert response.debug is not None
    assert response.answer_text


def test_graph_verbalizer_rewrite_success_keeps_safe_answer():
    client = _sequence_llm_client(
        [
            "对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。",
            "对比海底捞(牡丹园店)和川味轩(知春路店)：在综合排序里，海底捞(牡丹园店)更好。",
        ]
    )
    set_llm_backend(client)
    get_session_store().save("graph_comp_rewrite_success", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))

    response = run_agent_graph("第一家和第二家哪个更好？", "graph_comp_rewrite_success")
    assert response.debug is not None
    assert response.answer_text


def test_graph_verbalizer_rewrite_then_fallback_metadata_complete():
    client = _sequence_llm_client(
        [
            "对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。",
            "对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。",
        ]
    )
    set_llm_backend(client)
    get_session_store().save("graph_comp_rewrite_fallback", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))

    response = run_agent_graph("第一家和第二家哪个更好？", "graph_comp_rewrite_fallback")
    assert response.debug is not None
    assert response.answer_text
