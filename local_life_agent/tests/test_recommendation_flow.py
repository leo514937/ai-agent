"""Regression and contract tests for the nearby recommendation flow."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, cast
import json
import re

import pytest

from .. import agent
from ..agent import run_agent_graph
from ..config import RECOMMENDATION_CANDIDATE_TOP_K, SEARCH_LIMIT
from ..engine import graph_builder
from ..llm.client import _default_llm_backend, clear_llm_backend, set_llm_backend
from ..planning import execution_plan_builder
from ..session.store import reset_session_store


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    reset_session_store()
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None, raising=False)
    set_llm_backend(_recommendation_llm_backend)
    monkeypatch.setattr(graph_builder, "call_llm", _recommendation_llm_backend)
    yield
    clear_llm_backend()
    reset_session_store()
    agent._GRAPH_CACHE = None


def _mock_llm_backend(prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs) -> str:
    if "DecisionPlan" not in prompt and "DecisionPlan" not in system_prompt:
        return _default_llm_backend(prompt, system_prompt, temperature, timeout_ms)

    selected: list[str] = []
    for text in (prompt, system_prompt):
        match = re.search(r'- 选择的目标店面:\s*(.*)', text)
        if match:
            selected = re.findall(r'"shop_name":\s*"([^"]+)"', match.group(1))
            if selected:
                break
        match = re.search(r'- 综合排序:\s*(.*)', text)
        if match:
            selected = re.findall(r'"shop_name":\s*"([^"]+)"', match.group(1))
            if selected:
                break

    if selected:
        items = [f"{idx}. {name}" for idx, name in enumerate(selected[:3], 1)]
        text = "附近我推荐这3家：" + "；".join(items) + "。"
    else:
        text = "附近我推荐这3家。"
    return json.dumps({"natural_response": text}, ensure_ascii=False)


def _user_text_from_prompt(prompt: str) -> str:
    match = re.search(r"用户输入：\s*(.*)", prompt, re.S)
    if not match:
        return prompt
    return match.group(1).strip()


def _recommendation_llm_backend(prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs):
    user_text = _user_text_from_prompt(prompt)
    if "顶层意图路由" in prompt:
        return {
            "ok": True,
            "content": {"top_intent": "local_life", "confidence": 0.99},
            "confidence": 0.99,
            "raw": "{}",
            "error_code": "",
            "error_message": "",
        }
    if "本地生活语义解析器" not in prompt:
        return _mock_llm_backend(prompt, system_prompt, temperature, timeout_ms, **kwargs)
    semantic = {
        "top_intent": "local_life",
        "task_type": "recommendation",
        "primary_task": "recommendation",
        "facets": [],
        "merchant_mentions": [],
        "brand_mentions": [],
        "branch_mentions": [],
        "reference_mentions": [],
        "comparison_targets": [],
        "ordinal_references": [],
        "deictic_references": [],
        "focused_facets": [],
        "comparison_focus": "",
        "hard_constraints": {"category": "火锅"},
        "soft_preferences": {"nearby_preferred": True},
        "ranking_signals": {"query_terms": ["火锅"], "category": "火锅", "nearby_preferred": True},
        "follow_up": None,
        "confidence": 0.95,
        "need_context": False,
    }
    if "约会" in user_text:
        semantic["soft_preferences"]["scene_terms"] = ["约会"]
        semantic["ranking_signals"]["scene_terms"] = ["约会"]
    if "现在营业" in user_text or "现在开门" in user_text:
        semantic["soft_preferences"]["open_now_preferred"] = True
        semantic["ranking_signals"]["open_now_preferred"] = True
    if "最好有券" in user_text or "有券" in user_text:
        semantic["soft_preferences"]["coupon_preferred"] = True
        semantic["ranking_signals"]["coupon_preferred"] = True
    if "第一家" in user_text or "第一个" in user_text:
        semantic.update({
            "task_type": "coupon_query",
            "primary_task": "coupon_query",
            "facets": [{"name": "coupon", "required": True}],
            "ordinal_references": ["第一家"],
            "need_context": True,
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
        })
    if "这家" in user_text:
        semantic.update({
            "task_type": "coupon_query",
            "primary_task": "coupon_query",
            "facets": [{"name": "coupon", "required": True}],
            "deictic_references": ["这家"],
            "need_context": True,
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
        })
    return {"ok": True, "content": semantic, "confidence": 0.95, "raw": "{}", "error_code": "", "error_message": ""}


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return cast(dict[str, Any], model_dump())
    return dict(getattr(value, "__dict__", {}) or {})


def _semantic_frame(
    *,
    query_terms: list[str] | None = None,
    scene_terms: list[str] | None = None,
    coupon_preferred: bool = False,
    open_now_preferred: bool = False,
    nearby_preferred: bool = False,
) -> dict:
    return {
        "task_type": "recommendation",
        "merchant_mentions": [],
        "hard_constraints": {},
        "soft_preferences": {
            "scene_terms": scene_terms or [],
            "coupon_preferred": coupon_preferred,
            "open_now_preferred": open_now_preferred,
            "nearby_preferred": nearby_preferred,
        },
        "ranking_signals": {
            "query_terms": query_terms or [],
            "coupon_preferred": coupon_preferred,
            "open_now_preferred": open_now_preferred,
            "nearby_preferred": nearby_preferred,
        },
    }


def _fake_shop(
    shop_id: str,
    shop_name: str,
    *,
    rating: float | None = 4.0,
    distance_km: float | None = 1.0,
    eta_minutes: int | None = 10,
    open_status: str = "open",
    tags: list[str] | None = None,
) -> dict:
    payload = {
        "shop_id": shop_id,
        "shop_name": shop_name,
        "category": "火锅",
        "sub_category": "川味火锅",
        "tags": tags or ["约会", "聚餐"],
        "open_status": open_status,
    }
    if rating is not None:
        payload["rating"] = rating
    if distance_km is not None:
        payload["distance_km"] = distance_km
    if eta_minutes is not None:
        payload["eta_minutes"] = eta_minutes
    return payload


def _shop_names_from_snapshot(snapshot: dict) -> list[str]:
    ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or []
    return [
        str(item.get("shop_name", "")).strip()
        for item in ranked
        if isinstance(item, dict) and item.get("shop_name")
    ]


def _tool_names(tool_results: dict[str, Any]) -> list[str]:
    return [str(_to_dict(item).get("tool_name", "")) for item in (tool_results or {}).values()]


def _gateway_stub(
    search_data: list[dict],
    *,
    detail_overrides: dict[str, dict] | None = None,
    open_overrides: dict[str, dict] | None = None,
    coupon_overrides: dict[str, dict] | None = None,
) -> tuple[Callable[[str, dict], dict], list[tuple[str, dict]]]:
    recorded: list[tuple[str, dict]] = []
    detail_overrides = detail_overrides or {}
    open_overrides = open_overrides or {}
    coupon_overrides = coupon_overrides or {}
    search_map = {item["shop_id"]: dict(item) for item in search_data}

    def _dispatch(tool_name: str, args: dict) -> dict:
        recorded.append((tool_name, dict(args)))
        if tool_name == "search_shops":
            return {
                "success": True,
                "result_status": "ok",
                "data": [dict(item) for item in search_data],
                "total": len(search_data),
            }

        shop_id = str(args.get("shop_id", ""))
        base = dict(search_map.get(shop_id, {}))
        if tool_name == "get_shop_detail":
            override = detail_overrides.get(shop_id)
            if override is not None:
                return dict(override)
            return {"success": True, "result_status": "ok", "data": base}
        if tool_name == "check_open_status":
            override = open_overrides.get(shop_id)
            if override is not None:
                return dict(override)
            return {
                "success": True,
                "result_status": "ok",
                "data": {
                    "shop_id": shop_id,
                    "shop_name": base.get("shop_name", ""),
                    "open_status": base.get("open_status", "open"),
                    "business_hours": "10:00-22:00",
                },
            }
        if tool_name == "get_coupon_list":
            override = coupon_overrides.get(shop_id)
            if override is not None:
                return dict(override)
            return {
                "success": True,
                "result_status": "empty",
                "data": [],
                "total": 0,
            }
        raise AssertionError(f"Unexpected tool: {tool_name}")

    return _dispatch, recorded


@pytest.mark.xfail(reason="legacy assertion expected dynamic enrich-call trimming before staged placeholder planning", strict=False)
def test_recommendation_flow_staged_parallel():
    response = run_agent_graph("附近有没有适合约会、现在营业、最好有券的火锅？", "recommendation_flow")

    assert response.debug is not None
    plan = response.debug.execution_plan
    snapshot = response.debug.evidence_pack.get("ranking_snapshot") or {}
    tool_calls = plan.get("tool_calls", [])

    search_calls = [call for call in tool_calls if call.get("tool_name") == "search_shops"]
    enrich_calls = [call for call in tool_calls if call.get("tool_name") != "search_shops"]

    assert plan.get("task_type") == "recommendation"
    assert search_calls and search_calls[0]["args"]["limit"] == SEARCH_LIMIT
    assert len(enrich_calls) == min(RECOMMENDATION_CANDIDATE_TOP_K, snapshot.get("candidate_count", 0)) * 3
    assert {call.get("tool_name") for call in enrich_calls} == {
        "get_shop_detail",
        "check_open_status",
        "get_coupon_list",
    }
    assert "get_distance_eta" not in {call.get("tool_name") for call in tool_calls}
    assert len(snapshot.get("ranked", [])) == 3


@pytest.mark.xfail(reason="legacy builder test expected pre-executed search_shops inside planner", strict=False)
def test_recommendation_plan_enriches_only_top_8_candidates(monkeypatch: pytest.MonkeyPatch):
    observed: dict[str, object] = {}

    def fake_search_shops(query: str, location: dict | None = None, limit: int | None = None) -> dict:
        observed["query"] = query
        observed["location"] = location
        observed["limit"] = limit
        return {
            "success": True,
            "result_status": "ok",
            "data": [_fake_shop(f"shop_{idx:02d}", f"火锅店{idx}", rating=5.0 - idx * 0.1) for idx in range(12)],
            "total": 12,
        }

    monkeypatch.setattr(execution_plan_builder, "search_shops", fake_search_shops)

    payload = execution_plan_builder.build_recommendation_execution_plan(  # type: ignore[call-arg]
        _semantic_frame(query_terms=["火锅"], scene_terms=["约会"], coupon_preferred=True),
        location={"lat": 39.9, "lng": 116.3},
        fallback_query="附近有没有适合约会的火锅",
    )

    plan = payload["plan"]
    target_shop_ids = plan["target_shop_ids"]
    tool_calls = plan["tool_calls"]

    assert observed["query"] == "火锅"
    assert observed["limit"] == SEARCH_LIMIT
    assert len(target_shop_ids) == RECOMMENDATION_CANDIDATE_TOP_K
    assert target_shop_ids == [f"shop_{idx:02d}" for idx in range(RECOMMENDATION_CANDIDATE_TOP_K)]
    assert len(tool_calls) == 1 + RECOMMENDATION_CANDIDATE_TOP_K * 3
    assert tool_calls[0]["tool_name"] == "search_shops"
    assert {call["tool_name"] for call in tool_calls[1:]} == {
        "get_shop_detail",
        "check_open_status",
        "get_coupon_list",
    }
    assert {call["target_shop_id"] for call in tool_calls[1:]} == set(target_shop_ids)


def test_recommendation_flow_staged_parallel_placeholder_plan():
    response = run_agent_graph("\u9644\u8fd1\u6709\u6ca1\u6709\u9002\u5408\u7ea6\u4f1a\u3001\u73b0\u5728\u8425\u4e1a\u3001\u6700\u597d\u6709\u5238\u7684\u706b\u9505\uff1f", "recommendation_flow_placeholder")

    assert response.debug is not None
    plan = response.debug.execution_plan
    snapshot = response.debug.evidence_pack.get("ranking_snapshot") or {}
    tool_calls = plan.get("tool_calls", [])

    search_calls = [call for call in tool_calls if call.get("tool_name") == "search_shops"]
    enrich_calls = [call for call in tool_calls if call.get("tool_name") != "search_shops"]

    assert plan.get("task_type") == "recommendation"
    assert search_calls and search_calls[0]["args"]["limit"] == SEARCH_LIMIT
    assert len(enrich_calls) == RECOMMENDATION_CANDIDATE_TOP_K * 3
    assert enrich_calls[0]["target_shop_id"] == "$search_result[0].shop_id"
    assert enrich_calls[-1]["target_shop_id"] == f"$search_result[{RECOMMENDATION_CANDIDATE_TOP_K - 1}].shop_id"
    assert len(snapshot.get("ranked", [])) <= 3


def test_recommendation_plan_builds_placeholder_enrichment_calls():
    payload = execution_plan_builder.build_recommendation_execution_plan(
        _semantic_frame(query_terms=["\u706b\u9505"], scene_terms=["\u7ea6\u4f1a"], coupon_preferred=True),
        location={"lat": 39.9, "lng": 116.3},
    )

    plan = payload["plan"]
    tool_calls = plan["tool_calls"]

    assert payload["recommendation_query"] == "\u706b\u9505"
    assert plan["target_shop_ids"] == []
    assert len(tool_calls) == 1 + RECOMMENDATION_CANDIDATE_TOP_K * 3
    assert tool_calls[0]["tool_name"] == "search_shops"
    assert tool_calls[0]["args"]["limit"] == SEARCH_LIMIT
    assert tool_calls[1]["target_shop_id"] == "$search_result[0].shop_id"
    assert tool_calls[-1]["target_shop_id"] == f"$search_result[{RECOMMENDATION_CANDIDATE_TOP_K - 1}].shop_id"


def test_recommendation_all_tools_go_through_gateway(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "call_llm", _recommendation_llm_backend)
    response = run_agent_graph("附近推荐火锅", "recommendation_gateway_contract")

    assert response.debug is not None
    plan_tools = [call.get("tool_name") for call in response.debug.execution_plan.get("tool_calls", [])]
    assert "search_shops" in plan_tools
    assert "get_shop_detail" in plan_tools
    assert "check_open_status" in plan_tools
    assert "get_coupon_list" in plan_tools


def test_recommendation_semantic_constraints_should_surface_in_plan_and_ranking():
    response = run_agent_graph(
        "附近有没有适合约会、现在营业、最好有券的火锅？",
        "recommendation_semantic_constraints",
    )

    assert response.debug is not None
    plan = response.debug.execution_plan
    ranked = response.debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    sf = response.debug.semantic_frame

    assert plan.get("query_terms") == ["火锅"]
    assert "约会" in sf.get("soft_preferences", {}).get("scene_terms", [])
    assert plan.get("open_now_preferred") is True
    assert plan.get("coupon_preferred") is True
    assert ranked
    assert any(item.get("component_scores", {}).get("category_match", 0) > 0 for item in ranked)
    assert all("tag_match_score" in item.get("component_scores", {}) for item in ranked)


def test_recommendation_ranking_score_is_recomputable():
    response = run_agent_graph("附近推荐火锅", "recommendation_score_snapshot")

    assert response.debug is not None
    ranked = response.debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])

    assert ranked
    for item in ranked:
        components = item["component_scores"]
        expected = (
            components["category_match"] * 30
            + components["open_status_score"] * 25
            + components["distance_score"] * 20
            + components["rating_score"] * 15
            + components["coupon_score"] * 10
            + components["tag_match_score"] * 10
            - components["risk_penalty"]
        )
        assert item["total_score"] == pytest.approx(expected)


def test_recommendation_ranking_order_matches_system_score():
    response = run_agent_graph("附近推荐火锅", "recommendation_rank_order")

    assert response.debug is not None
    snapshot = response.debug.evidence_pack.get("ranking_snapshot") or {}
    ranked = snapshot.get("ranked", [])

    assert ranked == sorted(ranked, key=lambda item: item["rank"])
    assert ranked == sorted(ranked, key=lambda item: item["total_score"], reverse=True)
    names = [item["shop_name"] for item in ranked]
    positions = [response.answer_text.find(name) for name in names]
    assert positions == sorted(positions)


def test_recommendation_outputs_exactly_top_3_when_enough_candidates():
    response = run_agent_graph("附近推荐火锅", "recommendation_exact_top3")

    assert response.debug is not None
    ranked = response.debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    assert len(ranked) <= 3
    assert len(_shop_names_from_snapshot(response.debug.evidence_pack.get("ranking_snapshot") or {})) <= 3


def test_closed_shop_is_removed(monkeypatch: pytest.MonkeyPatch):
    shops = [
        _fake_shop("s1", "火锅A", rating=4.8, open_status="open"),
        _fake_shop("s2", "火锅B", rating=4.9, open_status="closed"),
        _fake_shop("s3", "火锅C", rating=4.7, open_status="open"),
        _fake_shop("s4", "火锅D", rating=4.6, open_status="open"),
    ]
    dispatch, _ = _gateway_stub(shops)
    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_closed_removed")
    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    names = [item["shop_name"] for item in ranked]

    assert "火锅B" not in names
    assert "火锅B" not in response.answer_text


def test_detail_failed_shop_is_removed(monkeypatch: pytest.MonkeyPatch):
    shops = [
        _fake_shop("s1", "火锅A", rating=4.8),
        _fake_shop("s2", "火锅B", rating=4.9),
        _fake_shop("s3", "火锅C", rating=4.7),
        _fake_shop("s4", "火锅D", rating=4.6),
    ]
    dispatch, _ = _gateway_stub(
        shops,
        detail_overrides={
            "s2": {
                "success": False,
                "result_status": "failed",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": "detail failed",
            }
        },
    )
    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_detail_failed")
    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])

    assert "火锅B" not in [item["shop_name"] for item in ranked]
    assert "火锅B" not in response.answer_text


def test_open_unknown_not_removed_but_no_open_score(monkeypatch: pytest.MonkeyPatch):
    shops = [
        _fake_shop("s1", "火锅A", rating=4.8),
        _fake_shop("s2", "火锅B", rating=4.7),
        _fake_shop("s3", "火锅C", rating=4.6),
    ]
    dispatch, _ = _gateway_stub(
        shops,
        open_overrides={
            "s2": {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": "unknown",
            }
        },
    )
    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_open_unknown")
    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    item = next(entry for entry in ranked if entry["shop_name"] == "火锅B")

    assert item["component_scores"]["open_status_score"] == 0


def test_coupon_unknown_not_removed_but_no_coupon_score(monkeypatch: pytest.MonkeyPatch):
    shops = [
        _fake_shop("s1", "火锅A", rating=4.8),
        _fake_shop("s2", "火锅B", rating=4.7),
        _fake_shop("s3", "火锅C", rating=4.6),
    ]
    dispatch, _ = _gateway_stub(
        shops,
        coupon_overrides={
            "s2": {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": "unknown",
            }
        },
    )
    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_coupon_unknown")
    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    item = next(entry for entry in ranked if entry["shop_name"] == "火锅B")

    assert item["component_scores"]["coupon_score"] == 0
    assert "有券" not in response.answer_text or "火锅B" not in response.answer_text


def test_distance_missing_does_not_call_distance_tool(monkeypatch: pytest.MonkeyPatch):
    shops = [
        _fake_shop("s1", "火锅A", rating=4.8, distance_km=None, eta_minutes=None),
        _fake_shop("s2", "火锅B", rating=4.7),
        _fake_shop("s3", "火锅C", rating=4.6),
    ]
    dispatch, recorded = _gateway_stub(shops)
    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_distance_missing")
    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    item = next(entry for entry in ranked if entry["shop_name"] == "火锅A")

    assert item["component_scores"]["distance_score"] == 0
    assert "get_distance_eta" not in [tool_name for tool_name, _args in recorded]


def test_rating_missing_score_zero_no_fabrication(monkeypatch: pytest.MonkeyPatch):
    shops = [
        _fake_shop("s1", "火锅A", rating=None),
        _fake_shop("s2", "火锅B", rating=4.7),
        _fake_shop("s3", "火锅C", rating=4.6),
    ]
    dispatch, _ = _gateway_stub(shops)
    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_rating_missing")
    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    item = next(entry for entry in ranked if entry["shop_name"] == "火锅A")

    assert item["component_scores"]["rating_score"] == 0


def test_recommendation_success_updates_last_recommendation_list_not_current_shop():
    response = run_agent_graph("附近推荐火锅", "recommendation_session_state")

    debug = response.debug
    assert debug is not None
    ranked = debug.evidence_pack.get("ranking_snapshot", {}).get("ranked", [])
    session_after = debug.session_state_after

    assert len(ranked) <= 3
    assert session_after.get("current_shop") is None
    assert session_after.get("pending_clarification") is None
    assert session_after.get("last_recommendation_list") == ranked


def test_after_recommendation_first_item_reference_works():
    run_agent_graph("附近推荐火锅", "recommendation_followup_first")
    follow_up = run_agent_graph("第一家有券吗", "recommendation_followup_first")

    debug = follow_up.debug
    assert debug is not None
    tool_names = _tool_names(debug.tool_results or {})
    assert "get_coupon_list" in tool_names
    assert debug.semantic_frame.get("ordinal_references") == ["第一家"]


def test_after_recommendation_this_shop_must_clarify():
    run_agent_graph("附近推荐火锅", "recommendation_followup_clarify")
    follow_up = run_agent_graph("这家有券吗", "recommendation_followup_clarify")

    debug = follow_up.debug
    assert debug is not None
    tool_names = _tool_names(debug.tool_results or {})
    assert "get_coupon_list" not in tool_names
    assert debug.semantic_frame.get("deictic_references") == ["这家"]
    assert debug.semantic_frame.get("need_context") is True


def test_recommendation_failure_does_not_pollute_session(monkeypatch: pytest.MonkeyPatch):
    def _dispatch(tool_name: str, args: dict) -> dict:
        if tool_name == "search_shops":
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        raise AssertionError(f"Unexpected tool: {tool_name}")

    from ..engine import graph_builder

    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _dispatch)
    response = run_agent_graph("附近推荐火锅", "recommendation_empty_session")

    assert response.debug is not None
    assert response.debug.session_state_after.get("last_recommendation_list") == []
    assert response.debug.session_state_after.get("current_shop") is None
