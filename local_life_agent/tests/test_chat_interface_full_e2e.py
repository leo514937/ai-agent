from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from local_life_agent import agent, app as app_module, config
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.tests.chat_e2e_utils import orchestration_decision_from_response, state_after, state_before
from local_life_agent.tests.conftest import SpyRealLLMBackend
from local_life_agent.tests.fakes import mock_tools


pytestmark = pytest.mark.e2e


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


def _tool_names(response) -> list[str]:
    debug = getattr(response, "debug", None)
    if debug is None:
        return []
    tool_results = getattr(debug, "tool_results", None) or {}
    if isinstance(tool_results, dict):
        return sorted({str(item.get("tool_name", "") or "") for item in tool_results.values() if isinstance(item, dict) and item.get("tool_name")})
    return []


def _assert_decision(response, *, text: str, session_id: str, expected_workflow: str) -> None:
    decision = orchestration_decision_from_response(response, text=text, session_id=session_id)
    assert decision.workflow_name == expected_workflow


def test_discovery_with_location_category_and_preference(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐北京邮电大学附近的火锅或烧烤，要性价比高的": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
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
    resp = _run(text, "chat-e2e-1")

    _assert_decision(resp, text=text, session_id="chat-e2e-1", expected_workflow="discovery_decision")
    assert "北京邮电大学附近" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert "火锅" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert "性价比高" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert resp.debug.turn_trace["llm_called"] is True
    assert resp.debug.turn_trace["semantic_frame"]["task_type"] == "recommendation"
    assert "router_policy_decision" in resp.debug.turn_trace
    assert "target_resolution_status" in resp.debug.turn_trace
    assert "evidence_status" in resp.debug.turn_trace
    assert "state_update_plan" in resp.debug.turn_trace
    assert resp.debug.session_state_after.get("pending_clarification") is None
    assert isinstance(resp.debug.session_state_after.get("last_recommendation_list"), list)
    assert resp.answer_text


def test_recommendation_without_location_degrades_but_does_not_ask_for_shop_name(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    text = "推荐几家性价比高的烧烤"
    resp = _run(text, "chat-e2e-2")

    _assert_decision(resp, text=text, session_id="chat-e2e-2", expected_workflow="discovery_decision")
    assert "完整店名" not in resp.answer_text
    assert "店名" not in resp.answer_text
    assert resp.debug.session_state_after.get("current_shop") is None


def test_single_shop_fact_without_target_prompts_clarification(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "这家有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": [],
                "reference_mentions": ["这家"],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": ["这家"],
                "facets": [{"name": "coupon", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.91,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    text = "这家有券吗？"
    resp = _run(text, "chat-e2e-3")

    _assert_decision(resp, text=text, session_id="chat-e2e-3", expected_workflow="clarification_fallback")
    assert resp.debug.session_state_after.get("pending_clarification") is not None
    assert "完整店名" in resp.answer_text


def test_explicit_shop_coupon_query_uses_deterministic_tool(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "海底捞西直门店有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": ["海底捞西直门店"],
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
            }
        }
    )
    set_llm_backend(backend)

    text = "海底捞西直门店有券吗？"
    resp = _run(text, "chat-e2e-4")

    _assert_decision(resp, text=text, session_id="chat-e2e-4", expected_workflow="deterministic_tool")
    assert resp.debug.session_state_after.get("current_shop")
    assert resp.debug.session_state_after.get("pending_clarification") is None
    assert "券" in resp.answer_text


def test_recommendation_then_ordinal_coupon_reference(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    first_text = "推荐附近性价比高的火锅"
    first = _run(first_text, "chat-e2e-5")
    _assert_decision(first, text=first_text, session_id="chat-e2e-5", expected_workflow="discovery_decision")
    assert first.debug.session_state_after.get("last_recommendation_list")

    backend = SpyRealLLMBackend(
        scenario_payloads={
            "第一家有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": [],
                "reference_mentions": ["第一家"],
                "comparison_targets": [],
                "ordinal_references": ["第一家"],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    second_text = "第一家有券吗？"
    second = _run(second_text, "chat-e2e-5")
    _assert_decision(second, text=second_text, session_id="chat-e2e-5", expected_workflow="deterministic_tool")
    assert second.debug.session_state_after.get("current_shop")
    assert second.debug.session_state_after.get("pending_clarification") is None


def test_recommendation_refine_follow_up_prefers_history_not_clarification(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "附近推荐火锅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "workflow_hint": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "category", "required": True}],
                "hard_constraints": {"category": ["火锅"]},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.9,
                "need_context": False,
                "grounding_status": "grounded",
                "semantic_parse_source": "spy_real_llm",
            },
            "便宜一点的呢": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation_refine",
                "workflow_hint": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "follow_up": {"is_follow_up": True, "refine_action": "cheaper"},
                "soft_preferences": {"price_preference": "lower_price"},
                "ranking_signals": {"price_preference": "lower_price"},
                "confidence": 0.2,
                "need_context": True,
                "grounding_status": "unknown",
                "semantic_parse_source": "spy_real_llm",
            }
        }
    )
    set_llm_backend(backend)

    first = _run("附近推荐火锅", "chat-e2e-5b")
    assert first.debug.session_state_after.get("last_recommendation_list")

    second_text = "便宜一点的呢"
    second = _run(second_text, "chat-e2e-5b")

    _assert_decision(second, text=second_text, session_id="chat-e2e-5b", expected_workflow="discovery_decision")
    assert "你想查哪一家" not in second.answer_text
    assert second.debug.session_state_after.get("last_recommendation_list")
    assert second.debug.semantic_frame.get("primary_task") == "recommendation_refine"
    assert second.debug.semantic_frame.get("follow_up", {}).get("refine_action") == "cheaper"


def test_comparison_follow_up_second_item_coupon_uses_comparison_context(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "海底捞(牡丹园店)和川味轩(知春路店)哪个好？": {
                "top_intent": "local_life",
                "task_type": "comparison",
                "primary_task": "comparison",
                "workflow_hint": "comparison",
                "merchant_mentions": ["海底捞(牡丹园店)", "川味轩(知春路店)"],
                "reference_mentions": [],
                "comparison_targets": [
                    {"shop_id": "900007", "shop_name": "海底捞(牡丹园店)"},
                    {"shop_id": "900016", "shop_name": "川味轩(知春路店)"},
                ],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "comparison_intent": True,
                "comparison_structure": "multi_target",
                "confidence": 0.95,
                "need_context": False,
                "grounding_status": "grounded",
                "semantic_parse_source": "spy_real_llm",
            },
            "第二家有券吗": {
                "top_intent": "local_life",
                "task_type": "coupon_query",
                "primary_task": "coupon_query",
                "workflow_hint": "single_shop_query",
                "merchant_mentions": [],
                "reference_mentions": ["第二家"],
                "comparison_targets": [],
                "ordinal_references": ["第二家"],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": True}],
                "follow_up": {"is_follow_up": True, "refine_action": "coupon_lookup"},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.23,
                "need_context": True,
                "grounding_status": "unknown",
                "semantic_parse_source": "spy_real_llm",
            },
        }
    )
    set_llm_backend(backend)

    first = _run("海底捞(牡丹园店)和川味轩(知春路店)哪个好？", "chat-e2e-5c")
    _assert_decision(first, text="海底捞(牡丹园店)和川味轩(知春路店)哪个好？", session_id="chat-e2e-5c", expected_workflow="discovery_decision")
    assert first.debug.session_state_after.get("comparison_result")
    assert len(first.debug.session_state_after.get("comparison_targets") or []) >= 2

    second = _run("第二家有券吗", "chat-e2e-5c")

    _assert_decision(second, text="第二家有券吗", session_id="chat-e2e-5c", expected_workflow="deterministic_tool")
    assert "get_coupon_list" in _tool_names(second)
    assert second.debug.session_state_after.get("current_shop", {}).get("shop_id") == "900016"
    assert second.debug.session_state_after.get("pending_clarification") is None
    assert second.debug.semantic_frame.get("follow_up", {}).get("refine_action") == "coupon_lookup"


def test_current_shop_reference_uses_current_shop_anchor(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "这家现在还开吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "shop_status",
                "merchant_mentions": [],
                "reference_mentions": ["这家"],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": ["这家"],
                "facets": [{"name": "open_status", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.96,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    seed = _run("推荐附近性价比高的火锅", "chat-e2e-6")
    assert seed.debug.session_state_after.get("last_recommendation_list")

    text = "这家现在还开吗？"
    resp = _run(text, "chat-e2e-6")

    _assert_decision(resp, text=text, session_id="chat-e2e-6", expected_workflow="deterministic_tool")
    assert resp.debug.session_state_after.get("current_shop") is not None
    assert "营业" in resp.answer_text or "开" in resp.answer_text


def test_multi_shop_comparison_uses_previous_recommendation_list(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    first = _run("推荐附近性价比高的火锅", "chat-e2e-7")
    assert len(first.debug.session_state_after.get("last_recommendation_list") or []) >= 2

    text = "第一家和第二家哪个更适合聚餐？"
    resp = _run(text, "chat-e2e-7")

    _assert_decision(resp, text=text, session_id="chat-e2e-7", expected_workflow="discovery_decision")
    assert len(resp.debug.session_state_after.get("comparison_targets") or []) >= 2
    assert "聚餐" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)


def test_single_shop_multifacet_query_routes_to_deterministic_tool(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "海底捞西直门店现在开吗，有没有券，人均多少？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "shop_status",
                "merchant_mentions": ["海底捞西直门店"],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [
                    {"name": "open_status", "required": True},
                    {"name": "coupon", "required": False},
                    {"name": "price", "required": False},
                ],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {"price_preference": "mid"},
                "confidence": 0.97,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "海底捞西直门店现在开吗，有没有券，人均多少？"
    resp = _run(text, "chat-e2e-8")

    _assert_decision(resp, text=text, session_id="chat-e2e-8", expected_workflow="deterministic_tool")
    assert resp.debug.session_state_after.get("current_shop") is not None
    assert resp.debug.execution_plan
    assert resp.debug.evidence_pack


def test_exploration_planning_without_location_asks_for_location(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "帮我安排一个先吃饭再喝咖啡的约会路线": {
                "top_intent": "local_life",
                "task_type": "local_trip_plan",
                "primary_task": "exploration",
                "workflow_hint": "exploration_planning",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "scene": "date",
                "time": "evening",
                "exploration_stages": [
                    {"stage_id": "stage_1", "stage_type": "eat", "candidate_query": "餐厅", "order": 1, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
                    {"stage_id": "stage_2", "stage_type": "coffee", "candidate_query": "咖啡店", "order": 2, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
                ],
                "hard_constraints": {},
                "soft_preferences": {"scene": "date"},
                "ranking_signals": {"sequence": ["先吃饭再喝咖啡"]},
                "confidence": 0.9,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    text = "帮我安排一个先吃饭再喝咖啡的约会路线"
    resp = _run(text, "chat-e2e-9")

    _assert_decision(resp, text=text, session_id="chat-e2e-9", expected_workflow="exploration_planning")
    assert resp.debug.session_state_after.get("pending_clarification") is not None
    assert resp.debug.semantic_frame["workflow_hint"] == "exploration_planning"
    assert resp.debug.semantic_frame["scene"] == "date"
    assert resp.debug.semantic_frame["exploration_stages"][0]["stage_type"] == "eat"
    assert "位置" in resp.answer_text or "出发地" in resp.answer_text


def test_exploration_planning_with_location_runs_workflow(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线": {
                "top_intent": "local_life",
                "task_type": "local_trip_plan",
                "primary_task": "exploration",
                "workflow_hint": "exploration_planning",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "scene": "date",
                "time": "evening",
                "exploration_stages": [
                    {"stage_id": "stage_1", "stage_type": "eat", "candidate_query": "餐厅", "order": 1, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
                    {"stage_id": "stage_2", "stage_type": "coffee", "candidate_query": "咖啡店", "order": 2, "required": True, "evidence_requirements": ["detail", "open_status", "distance"]},
                ],
                "hard_constraints": {"location": "北京邮电大学附近"},
                "soft_preferences": {"scene": "date"},
                "ranking_signals": {"sequence": ["先吃饭再喝咖啡"]},
                "confidence": 0.94,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "帮我安排一个北京邮电大学附近先吃饭再喝咖啡的约会路线"
    resp = _run(text, "chat-e2e-10")

    _assert_decision(resp, text=text, session_id="chat-e2e-10", expected_workflow="exploration_planning")
    assert "北京邮电大学附近" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert resp.debug.semantic_frame["workflow_hint"] == "exploration_planning"
    assert resp.debug.semantic_frame["scene"] == "date"
    assert resp.debug.semantic_frame["exploration_stages"][0]["stage_type"] == "eat"
    assert resp.debug.session_state_after.get("pending_clarification") is None
    assert resp.debug.session_state_after.get("last_recommendation_list") == []
    assert resp.debug.execution_plan


def test_direct_response_and_forbidden_scope(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "你能帮我做什么？": {
                "top_intent": "chat",
                "task_type": "general_chat",
                "primary_task": "capability",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.99,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    direct_text = "你能帮我做什么？"
    direct_resp = _run(direct_text, "chat-e2e-11")
    _assert_decision(direct_resp, text=direct_text, session_id="chat-e2e-11", expected_workflow="direct_response")
    assert "本地生活" in direct_resp.answer_text
    assert direct_resp.debug.session_state_after.get("current_shop") is None

    forbidden_text = "帮我下单并支付"
    forbidden_resp = _run(forbidden_text, "chat-e2e-12")
    _assert_decision(forbidden_resp, text=forbidden_text, session_id="chat-e2e-12", expected_workflow="direct_response")
    assert "不能" in forbidden_resp.answer_text or "不支持" in forbidden_resp.answer_text
    assert forbidden_resp.debug.session_state_after.get("current_shop") is None


def test_no_result_recommendation_does_not_fake_shop(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)

    def dispatch(tool_name: str, args: dict):
        if tool_name == "search_shops" and "月球" in str(args.get("query", "")):
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        return mock_tools.search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit")) if tool_name == "search_shops" else mock_tools.get_shop_detail(str(args.get("shop_id", ""))) if tool_name == "get_shop_detail" else mock_tools.check_open_status(str(args.get("shop_id", ""))) if tool_name == "check_open_status" else mock_tools.get_coupon_list(str(args.get("shop_id", ""))) if tool_name == "get_coupon_list" else mock_tools.get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581}) if tool_name == "get_distance_eta" else mock_tools.get_shop_review_summary(list(args.get("shop_ids") or []), aspects=args.get("aspects"), scene=args.get("scene"), max_reviews=args.get("max_reviews")) if tool_name == "get_shop_review_summary" else mock_tools.get_deal_list(str(args.get("shop_id", "")), people_count=args.get("people_count"), budget_per_person=args.get("budget_per_person"), deal_type=args.get("deal_type"), only_available=args.get("only_available", True)) if tool_name == "get_deal_list" else mock_tools.resolve_shop(str(args.get("query", "")), location=args.get("location"), session_shop_ids=args.get("session_shop_ids"))

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    monkeypatch.setattr(graph_builder, "resolve_shop", lambda query, location=None, session_shop_ids=None: dispatch("resolve_shop", {"query": query, "location": location, "session_shop_ids": session_shop_ids}))

    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐月球附近的火锅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "location", "required": True}],
                "hard_constraints": {"location": "月球附近", "category": ["火锅"]},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "推荐月球附近的火锅"
    resp = _run(text, "chat-e2e-13")

    _assert_decision(resp, text=text, session_id="chat-e2e-13", expected_workflow="discovery_decision")
    assert not resp.debug.session_state_after.get("last_recommendation_list")
    assert "月球" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert resp.debug.evidence_pack.get("unknown_facets") or resp.debug.evidence_pack.get("failed_facets") or resp.debug.answer_verify_passed is False


def test_recommendation_multifacet_prefers_discovery_not_deterministic(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐北邮附近现在开门、有券、人均100左右、适合聚餐的火锅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [
                    {"name": "open_status", "required": False},
                    {"name": "coupon", "required": False},
                    {"name": "price", "required": False},
                    {"name": "scene", "required": False},
                ],
                "hard_constraints": {"location": "北邮附近", "category": ["火锅"]},
                "soft_preferences": {"scene": "聚餐", "price": "100左右"},
                "ranking_signals": {"open_now": True, "coupon": True},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "推荐北邮附近现在开门、有券、人均100左右、适合聚餐的火锅"
    resp = _run(text, "chat-e2e-14")

    _assert_decision(resp, text=text, session_id="chat-e2e-14", expected_workflow="discovery_decision")
    assert "聚餐" in json.dumps(resp.debug.semantic_frame, ensure_ascii=False)
    assert resp.debug.session_state_after.get("current_shop") is None
    assert resp.debug.execution_plan


def test_ambiguous_shop_name_does_not_fall_back_to_recommendation(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "海底捞有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": ["海底捞"],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.96,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    text = "海底捞有券吗？"
    resp = _run(text, "chat-e2e-15")

    _assert_decision(resp, text=text, session_id="chat-e2e-15", expected_workflow="clarification_fallback")
    assert resp.debug.session_state_after.get("current_shop") is None
    assert "完整店名" in resp.answer_text or "确认具体店名" in resp.answer_text


def test_unknown_shop_name_does_not_pollute_current_shop(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "不存在的神奇火锅店有券吗？": {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "coupon_query",
                "merchant_mentions": ["不存在的神奇火锅店"],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [{"name": "coupon", "required": True}],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": True,
            }
        }
    )
    set_llm_backend(backend)

    text = "不存在的神奇火锅店有券吗？"
    resp = _run(text, "chat-e2e-16")

    _assert_decision(resp, text=text, session_id="chat-e2e-16", expected_workflow="clarification_fallback")
    assert resp.debug.session_state_after.get("current_shop") is None
    assert resp.debug.session_state_after.get("pending_clarification") is not None


def test_capability_boundary_does_not_trigger_booking_or_payment(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "你能帮我订座吗？": {
                "top_intent": "capability",
                "task_type": "general_chat",
                "primary_task": "capability",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "confidence": 0.99,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    text = "你能帮我订座吗？"
    resp = _run(text, "chat-e2e-17")

    _assert_decision(resp, text=text, session_id="chat-e2e-17", expected_workflow="direct_response")
    assert "暂不支持" in resp.answer_text or "不支持" in resp.answer_text
    assert resp.debug.session_state_after.get("current_shop") is None
    assert not resp.debug.execution_plan


def test_app_and_graph_consistency(monkeypatch: pytest.MonkeyPatch):
    _install_default_dispatch(monkeypatch)
    backend = SpyRealLLMBackend(
        scenario_payloads={
            "推荐附近性价比高的火锅": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "facets": [],
                "hard_constraints": {"category": ["火锅"]},
                "soft_preferences": {"price": "性价比高"},
                "ranking_signals": {},
                "confidence": 0.95,
                "need_context": False,
            }
        }
    )
    set_llm_backend(backend)

    client = TestClient(app_module.app)
    payload = {
        "session_id": "chat-e2e-18",
        "trace_id": "trace-chat-e2e-18",
        "turn_id": "turn-chat-e2e-18",
        "page": "assistant",
        "message": "推荐附近性价比高的火锅",
        "response_mode": "stream",
    }
    with client.stream("POST", "/internal/v1/chat/stream", json=payload) as response:
        assert response.status_code == 200
        body = "\n".join(line for line in response.iter_lines() if line)

    graph_resp = _run("推荐附近性价比高的火锅", "chat-e2e-18", trace_id="trace-chat-e2e-18", turn_id="turn-chat-e2e-18")
    assert graph_resp.answer_text in body
    assert "event: final" in body
    assert state_after(graph_resp).get("last_recommendation_list")
    assert state_before(graph_resp).get("current_shop") is None
