from __future__ import annotations

import os
from typing import Any

import pytest

from local_life_agent import agent, config
from local_life_agent.agent import run_agent_graph
from local_life_agent.answer.answer_plan_builder import build_answer_plan
from local_life_agent.answer.generator import _build_decision_plan
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.session.store import get_session_store, reset_session_store
from local_life_agent.target.reference_resolver import resolve_references
from local_life_agent.tools.mock_tools import (
    check_open_status,
    get_coupon_list,
    get_distance_eta,
    get_shop_detail,
    resolve_shop,
    search_shops,
)

from .conftest import SpyRealLLMBackend


def _accept_dispatch(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "resolve_shop":
        query = str(args.get("query", "")).strip()
        if "山城一锅" in query:
            return {
                "status": "RESOLVED",
                "shop": {
                    "shop_id": "shop_shancheng",
                    "shop_name": "山城一锅",
                    "category": "火锅",
                    "rating": 4.2,
                },
                "confidence": 0.95,
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
                "shop_id": shop_id,
                "data": {
                    "shop_id": shop_id,
                    "shop_name": "山城一锅",
                    "category": "火锅",
                    "rating": 4.2,
                    "avg_price": 90.0,
                    "tags": ["火锅", "川菜"],
                },
            }
        if tool_name == "check_open_status":
            return {
                "success": True,
                "result_status": "ok",
                "shop_id": shop_id,
                "data": {"shop_id": shop_id, "shop_name": "山城一锅", "open_status": "open"},
            }
        if tool_name == "get_coupon_list":
            return {
                "success": True,
                "result_status": "empty",
                "shop_id": shop_id,
                "data": [],
            }
        if tool_name == "get_distance_eta":
            return {
                "success": True,
                "result_status": "ok",
                "shop_id": shop_id,
                "data": {
                    "shop_id": shop_id,
                    "shop_name": "山城一锅",
                    "distance_km": 0.8,
                    "eta_minutes": 8,
                },
            }

    if tool_name == "get_shop_detail":
        return get_shop_detail(shop_id)
    if tool_name == "check_open_status":
        return check_open_status(shop_id)
    if tool_name == "get_coupon_list":
        return get_coupon_list(shop_id)
    if tool_name == "get_distance_eta":
        return get_distance_eta(shop_id, args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
    raise AssertionError(f"Unexpected tool: {tool_name}")


def _resolve_shop_for_e2e(query: str, location: dict[str, Any] | None = None, session_shop_ids: list[str] | None = None) -> dict[str, Any]:
    compact = str(query or "").strip()
    if compact == "海底捞":
        return {
            "status": "RESOLVED",
            "shop": {
                "shop_id": "shop_007",
                "shop_name": "海底捞(牡丹园店)",
                "category": "火锅",
                "rating": 4.7,
            },
            "confidence": 0.95,
        }
    if compact == "山城一锅":
        return {
            "status": "RESOLVED",
            "shop": {
                "shop_id": "shop_shancheng",
                "shop_name": "山城一锅",
                "category": "火锅",
                "rating": 4.2,
            },
            "confidence": 0.95,
        }
    return resolve_shop(compact, location=location, session_shop_ids=session_shop_ids)


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_session_store()
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _accept_dispatch)
    monkeypatch.setattr(graph_builder, "resolve_shop", _resolve_shop_for_e2e)
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    yield
    clear_llm_backend()
    reset_session_store()


def _install_spy(spy: SpyRealLLMBackend) -> SpyRealLLMBackend:
    set_llm_backend(spy)
    return spy


def _assert_main_llm_metadata(response: Any) -> dict[str, Any]:
    assert response.debug is not None
    frame = response.debug.semantic_frame
    assert frame.get("semantic_source") in {"real_llm", "spy_real_llm"}
    assert frame.get("llm_called") is True
    assert not frame.get("fallback_reason")
    return frame


def _build_decision_artifact(response: Any) -> Any:
    assert response.debug is not None
    execution_plan = response.debug.execution_plan
    task_type = str(execution_plan.get("task_type", "") or "")
    answer_plan = build_answer_plan(task_type, response.debug.evidence_pack, None)
    return _build_decision_plan(answer_plan, response.debug.evidence_pack)


def _ranking_names(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("shop_name", "")).strip() for item in items if str(item.get("shop_name", "")).strip()]


def test_top_intent_router_uses_injected_spy_backend(spy_backend: SpyRealLLMBackend, poison_fallback: None) -> None:
    spy = _install_spy(spy_backend)

    response = run_agent_graph("附近推荐火锅", "e2e_top_intent_spy")

    frame = _assert_main_llm_metadata(response)
    assert spy.call_count >= 2
    assert any(h in prompt for prompt in spy.prompts for h in ("# Top Intent Router", "# 顶层意图路由"))
    assert any(h in prompt for prompt in spy.prompts for h in ("# Local Life Semantic Parser", "# 本地生活语义解析器"))
    assert frame.get("ranking_signals", {}).get("spy_marker") == spy.sentinel_id


def test_hard_guard_inputs_can_bypass_llm(spy_backend: SpyRealLLMBackend) -> None:
    spy = _install_spy(spy_backend)

    response = run_agent_graph("你好", "e2e_hard_guard_chat")

    assert spy.call_count == 0
    assert response.answer_text


def test_recommendation_main_path_uses_llm_end_to_end(
    spy_backend: SpyRealLLMBackend,
    poison_fallback: None,
) -> None:
    spy = _install_spy(spy_backend)

    response = run_agent_graph("附近有没有适合约会、现在营业、最好有券的火锅？", "e2e_recommendation")

    frame = _assert_main_llm_metadata(response)
    decision_plan = _build_decision_artifact(response)
    ranked = response.debug.evidence_pack.get("ranking_snapshot", {}).get("ranked") or []

    assert response.debug.answer_source == "llm_verbalizer"
    assert len(ranked) > 0
    assert decision_plan.answer_type == "recommendation"
    assert len(decision_plan.overall_ranking) > 0
    assert ranked[0].get("reason_codes")
    assert "template_fallback" not in response.debug.answer_source
    assert "无券" not in response.answer_text
    assert "未营业" not in response.answer_text
    assert frame.get("ranking_signals", {}).get("spy_marker") == spy.sentinel_id
    assert any(spy.sentinel_id in (item.get("raw") or "") for item in spy.responses)


def test_comparison_main_path_uses_llm_end_to_end(
    spy_backend: SpyRealLLMBackend,
    poison_fallback: None,
) -> None:
    spy = _install_spy(spy_backend)

    response = run_agent_graph("海底捞和山城一锅哪个好？", "e2e_comparison")

    _assert_main_llm_metadata(response)
    decision_plan = _build_decision_artifact(response)
    matrix = response.debug.evidence_pack.get("comparison_matrix", {})
    overall_ranked = matrix.get("overall_ranked") or []

    assert response.debug.answer_source == "llm_verbalizer"
    assert decision_plan.answer_type == "comparison"
    assert len(decision_plan.overall_ranking) >= 2
    assert matrix.get("dimension_winners")
    assert _ranking_names(decision_plan.overall_ranking) == _ranking_names(overall_ranked)
    assert "unknown" not in str(matrix.get("dimension_winners", {}).get("coupon", "")).lower()
    assert spy.call_count >= 3


def test_ordinal_reference_prefers_semantic_frame(
    spy_backend: SpyRealLLMBackend,
    poison_fallback: None,
) -> None:
    spy = _install_spy(spy_backend)

    run_agent_graph("附近推荐火锅", "e2e_ordinal")
    response = run_agent_graph("第一家有券吗", "e2e_ordinal")

    frame = _assert_main_llm_metadata(response)
    resolved = resolve_references("第一家有券吗", response.debug.session_state_before, frame)
    recommendation_list = response.debug.session_state_before.get("last_recommendation_list") or []

    assert frame.get("task_type") == "coupon_query"
    assert frame.get("ordinal_references") == ["第一家"]
    assert resolved.get("resolution_source") == "semantic_frame"
    assert resolved.get("target") is not None
    assert recommendation_list
    assert resolved["target"]["shop_id"] == recommendation_list[0]["shop_id"]
    assert response.debug.answer_source in {"llm_verbalizer", "template", "template_fallback"}
    assert spy.call_count >= 3


def test_recommendation_follow_up_stays_on_llm_main_path(
    spy_backend: SpyRealLLMBackend,
    poison_fallback: None,
) -> None:
    spy = _install_spy(spy_backend)

    run_agent_graph("附近推荐火锅", "e2e_follow_up")
    response = run_agent_graph("便宜一点的呢", "e2e_follow_up")

    frame = _assert_main_llm_metadata(response)
    decision_plan = _build_decision_artifact(response)

    assert frame.get("task_type") == "recommendation"
    assert frame.get("primary_task") == "recommendation_refine"
    assert frame.get("need_context") is True
    assert (frame.get("follow_up") or {}).get("is_follow_up") is True
    assert response.debug.session_state_before.get("last_recommendation_list")
    assert decision_plan.answer_type == "recommendation"
    assert response.debug.answer_source == "llm_verbalizer"
    assert spy.call_count >= 4


def test_deictic_comparison_clarifies_missing_current_shop(
    spy_backend: SpyRealLLMBackend,
    poison_fallback: None,
) -> None:
    spy = _install_spy(spy_backend)

    response = run_agent_graph("这家和海底捞比呢？", "e2e_deictic")

    frame = _assert_main_llm_metadata(response)
    trace = response.debug.execution_trace

    assert frame.get("task_type") == "comparison"
    assert frame.get("deictic_references") == ["这家"]
    assert "补充另一家店名" in response.answer_text
    assert "海底捞是哪家" not in response.answer_text
    assert any(item.get("node") == "target_resolve" and item.get("status") == "NEED_CLARIFICATION" for item in trace)
    assert spy.call_count >= 2


def test_real_llm_optional_integration_e2e() -> None:
    api_key_env_name = os.environ.get("REAL_LLM_API_KEY_ENV", config.REAL_LLM_API_KEY_ENV)
    api_key = os.environ.get(api_key_env_name)
    if not api_key:
        pytest.skip("real_llm integration skipped because API key is missing")

    from local_life_agent.llm.openai_backend import OpenAICompatibleBackend

    backend = OpenAICompatibleBackend()
    set_llm_backend(backend)

    scenarios = [
        ("附近有没有适合约会、现在营业、最好有券的火锅？", "real_e2e_recommend"),
        ("海底捞(牡丹园店)和川味轩(知春路店)哪个好？", "real_e2e_compare"),
        ("附近推荐火锅", "real_e2e_follow_turn1"),
        ("便宜一点的呢", "real_e2e_follow_turn1"),
        ("附近推荐火锅", "real_e2e_ordinal_turn1"),
        ("第一家有券吗", "real_e2e_ordinal_turn1"),
    ]

    for text, session_id in scenarios:
        response = run_agent_graph(text, session_id)
        assert response.debug is not None
        frame = response.debug.semantic_frame
        assert frame.get("semantic_source") == "real_llm"
        assert frame.get("llm_called") is True
        assert not frame.get("fallback_reason")
