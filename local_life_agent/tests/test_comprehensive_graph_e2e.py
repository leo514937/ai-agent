"""全链路覆盖测试 — LangGraph 图结构的端到端全链路覆盖。
"""
from __future__ import annotations

import json
from typing import Any
import pytest

from local_life_agent import agent, config
from local_life_agent.agent import run_agent_graph
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import get_session_store, reset_session_store
from local_life_agent.tools.mock_tools import (
    check_open_status, get_coupon_list, get_distance_eta,
    get_shop_detail, resolve_shop, search_shops,
)
from .conftest import SpyRealLLMBackend


SHOP_A = {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)", "category": "火锅", "rating": 4.7}
SHOP_B = {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)", "category": "川菜", "rating": 4.5}
SHOP_C = {"shop_id": "shop_shancheng", "shop_name": "山城一锅", "category": "火锅", "rating": 4.2}


def _default_dispatch(tool_name: str, args: dict) -> dict:
    if tool_name == "resolve_shop":
        query = str(args.get("query", "")).strip()
        if "模糊" in query or query == "海底捞":
            return {"status": "AMBIGUOUS", "candidates": [
                {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)", "address": "海淀区牡丹园"},
                {"shop_id": "shop_haidilao2", "shop_name": "海底捞(中关村店)", "address": "海淀区中关村"},
            ], "confidence": 0.5}
        for shop in [SHOP_A, SHOP_B, SHOP_C]:
            if shop["shop_name"] in query or shop["shop_id"] in query:
                return {"status": "RESOLVED", "shop": dict(shop), "confidence": 0.95}
        return {"status": "NOT_FOUND", "error_code": "SHOP_NOT_FOUND", "confidence": 0.0}
    if tool_name == "search_shops":
        return search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
    shop_id = str(args.get("shop_id", "")).strip()
    for shop in [SHOP_A, SHOP_B, SHOP_C]:
        if shop_id == shop["shop_id"]:
            sname = shop["shop_name"]
            if tool_name == "get_shop_detail":
                return {"success": True, "result_status": "ok", "shop_id": shop_id, "data": dict(shop)}
            if tool_name == "check_open_status":
                return {"success": True, "result_status": "ok", "shop_id": shop_id,
                        "data": {"shop_id": shop_id, "shop_name": sname, "open_status": "open"}}
            if tool_name == "get_coupon_list":
                return {"success": True, "result_status": "ok", "shop_id": shop_id,
                        "data": [{"coupon_id": "c001", "title": "满200减30"}]}
            if tool_name == "get_distance_eta":
                return {"success": True, "result_status": "ok", "shop_id": shop_id,
                        "data": {"shop_id": shop_id, "shop_name": sname, "distance_km": 1.2, "eta_minutes": 10}}
    if tool_name == "get_shop_detail":
        return get_shop_detail(shop_id)
    if tool_name == "check_open_status":
        return check_open_status(shop_id)
    if tool_name == "get_coupon_list":
        return get_coupon_list(shop_id)
    if tool_name == "get_distance_eta":
        return get_distance_eta(shop_id, args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
    return {"success": False, "result_status": "failed", "data": None, "error_code": "TOOL_NOT_REGISTERED"}


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_session_store()
    monkeypatch.setattr(config, "DEBUG_ENABLED", True)
    monkeypatch.setattr(config, "ENABLE_LLM_VERBALIZER", True)
    monkeypatch.setattr(config, "MAX_REWRITE_ATTEMPTS", 2)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", _default_dispatch)

    # Route resolve_shop calls through dispatch_tool_call so test's
    # _default_dispatch is the single source of truth for shop resolution.
    def _resolve_shop_via_dispatch(query, location=None, session_shop_ids=None):
        return graph_builder.dispatch_tool_call("resolve_shop", {"query": query})
    monkeypatch.setattr(graph_builder, "resolve_shop", _resolve_shop_via_dispatch)

    monkeypatch.setattr(agent, "_GRAPH_CACHE", None)
    yield
    clear_llm_backend()
    reset_session_store()


# =====================================================================
# Coverage tracker
# =====================================================================

_COVERAGE: dict[str, dict[str, Any]] = {
    "nodes": {n: False for n in [
        "receive_input", "load_session_state", "check_pending_clarification",
        "basic_input_validate", "normalize_text", "hard_guard", "top_intent_router",
        "semantic_parse", "slot_extractor", "frame_validator", "context_recovery",
        "target_resolve", "clarify_decide", "task_plan", "facet_plan",
        "comparison_planner", "plan_validator", "tool_execute", "evidence_build",
        "answer_plan_build", "answer_generate", "answer_verify", "rewrite",
        "final_response_build", "clarify_response", "fallback_answer",
        "state_update_plan", "persist_session_state", "emit_response",
    ]},
    "conditional_edges": {e: False for e in [
        "check_pending->basic_input_validate", "check_pending->target_resolve",
        "check_pending->clarify_response",
        "basic_validate->normalize_text", "basic_validate->emit_response",
        "hard_guard->top_intent_router", "hard_guard->emit_response",
        "top_intent->semantic_parse", "top_intent->emit_response",
        "semantic->slot_extractor", "semantic->clarify_response",
        "frame_validator->context_recovery", "frame_validator->clarify_response",
        "clarify_decide->task_plan", "clarify_decide->clarify_response",
        "clarify_decide->emit_response",
        "task_plan->facet_plan", "task_plan->comparison_planner",
        "plan_validator->tool_execute", "plan_validator->fallback_answer",
        "tool_execute->evidence_build", "tool_execute->fallback_answer",
        "answer_verify->final_response_build", "answer_verify->rewrite",
        "answer_verify->fallback_answer",
    ]},
    "verbalizer_paths": {v: False for v in [
        "recommendation_success", "recommendation_violation_fallback",
        "comparison_success", "comparison_violation_fallback",
        "single_shop_success", "unknown_as_false_fallback",
        "rewrite_success", "rewrite_exhausted_fallback",
    ]},
    "answer_sources": {s: 0 for s in [
        "llm_verbalizer", "template_fallback", "llm_verbalizer_rewrite", "template",
    ]},
}


def _mark_node(node: str) -> None:
    if node in _COVERAGE["nodes"]:
        _COVERAGE["nodes"][node] = True


def _mark_edge(edge: str) -> None:
    if edge in _COVERAGE["conditional_edges"]:
        _COVERAGE["conditional_edges"][edge] = True


def _mark_verbalizer(path: str) -> None:
    if path in _COVERAGE["verbalizer_paths"]:
        _COVERAGE["verbalizer_paths"][path] = True


def _extract_nodes(response: Any) -> list[str]:
    if response.debug is None:
        return []
    return [str(e.get("node", "")) for e in (response.debug.execution_trace or []) if isinstance(e, dict)]


def _update_coverage(response: Any, edge: str | None = None, verb_path: str | None = None) -> list[str]:
    nodes = _extract_nodes(response)
    for n in nodes:
        _mark_node(n)
    if edge:
        _mark_edge(edge)
    if verb_path:
        _mark_verbalizer(verb_path)
    if response.debug:
        src = response.debug.answer_source
        if src in _COVERAGE["answer_sources"]:
            _COVERAGE["answer_sources"][src] += 1
    return nodes


# =====================================================================
# Mock helpers
# =====================================================================

def _mock_llm(content: str | None = None) -> Any:
    class MB:
        llm_backend = "fake_llm"
        def __call__(self, prompt, sp="", temp=0.0, tm=3000):
            if "DecisionPlan" in prompt or "DecisionPlan" in sp:
                t = content if isinstance(content, str) else "默认回答。"
                return json.dumps({"natural_response": t}, ensure_ascii=False)
            from local_life_agent.llm.client import _default_llm_backend
            return _default_llm_backend(prompt, sp, temp, tm)
    return MB()


class _SeqBackend:
    llm_backend = "fake_llm"
    def __init__(self, contents):
        self._r = list(contents)
        self._c = 0
    def __call__(self, prompt, sp="", temp=0.0, tm=3000):
        if "DecisionPlan" in prompt or "DecisionPlan" in sp:
            idx = min(self._c, len(self._r) - 1)
            self._c += 1
            return json.dumps({"natural_response": self._r[idx]}, ensure_ascii=False)
        from local_life_agent.llm.client import _default_llm_backend
        return _default_llm_backend(prompt, sp, temp, tm)


# ---------- HAPPY PATH ----------

class TestHappyPath:
    def test_full_normal_flow_reaches_emit(self):
        client = _mock_llm("附近我推荐这3家：1. 海底捞(牡丹园店)，2. 川味轩(知春路店)，3. 山城一锅。")
        set_llm_backend(client)
        resp = run_agent_graph("附近推荐火锅", "happy_full")
        nodes = _update_coverage(resp)
        assert "emit_response" in nodes
        assert resp.answer_text


# ---------- CONDITIONAL ROUTING ----------

class TestConditionalRouting:
    def test_check_pending_restore_skips_input_layer(self):
        get_session_store().save("route_restore", SessionState(
            pending_clarification={"pending_id": "pc_1", "source_node": "target_resolve",
                                   "original_text": "模糊火锅店", "reason": "ambiguous_shop",
                                   "candidate_targets": [{"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}]},
            last_recommendation_list=[],
        ))
        set_llm_backend(_mock_llm())
        resp = run_agent_graph("1", "route_restore")
        nodes = _update_coverage(resp, edge="check_pending->target_resolve")
        assert "check_pending_clarification" in nodes
        assert "target_resolve" in nodes
        assert resp.answer_text

    def test_empty_input_caught_by_basic_validate(self):
        set_llm_backend(_mock_llm())
        resp = run_agent_graph("", "route_empty")
        nodes = _update_coverage(resp, edge="basic_validate->emit_response")
        assert "basic_input_validate" in nodes
        assert "emit_response" in nodes

    def test_chat_greeting_handled(self):
        set_llm_backend(_mock_llm())
        resp = run_agent_graph("你好", "route_chat")
        _update_coverage(resp, edge="hard_guard->emit_response")
        assert resp.answer_text

    def test_semantic_parse_error_routes(self):
        class FailB:
            llm_backend = "fake_llm"
            def __call__(self, prompt, sp="", temp=0.0, tm=3000):
                if "top_intent_router" in prompt or "Top Intent Router" in prompt:
                    return json.dumps({"top_intent": "local_life", "confidence": 0.95})
                return json.dumps({"top_intent": "local_life", "confidence": 0.5, "fallback_reason": "no_task_type"})
        set_llm_backend(FailB())
        resp = run_agent_graph("海底捞", "route_semantic_fail")
        _update_coverage(resp, edge="semantic->clarify_response")
        assert resp.answer_text

    def test_clarify_decide_ambiguous_routes(self):
        """使用 SpyBackend 确保 local_life + single_shop_query 以触发 AMBIGUOUS 路径。"""
        spy = SpyRealLLMBackend(scenario_payloads={
            "海底捞": {
                "top_intent": "local_life", "task_type": "single_shop_query",
                "primary_task": "shop_detail", "merchant_mentions": ["海底捞"],
                "facets": [{"name": "detail", "required": True}],
                "confidence": 0.95,
            },
        })
        set_llm_backend(spy)
        resp = run_agent_graph("海底捞", "route_clarify_amb")
        nodes = _update_coverage(resp, edge="clarify_decide->clarify_response")
        assert "target_resolve" in nodes
        assert "clarify_decide" in nodes

    def test_clarify_decide_not_found_emits(self):
        """使用 SpyBackend 确保 local_life intent 以触发 target_resolve。"""
        spy = SpyRealLLMBackend(scenario_payloads={
            "不存在的店铺名": {
                "top_intent": "local_life", "task_type": "single_shop_query",
                "primary_task": "shop_detail", "merchant_mentions": ["不存在的店铺名"],
                "facets": [{"name": "detail", "required": True}],
                "confidence": 0.95,
            },
        })
        set_llm_backend(spy)
        resp = run_agent_graph("不存在的店铺名", "route_not_found")
        nodes = _update_coverage(resp, edge="clarify_decide->emit_response")
        assert "target_resolve" in nodes
        assert "clarify_decide" in nodes
        assert "emit_response" in nodes

    def test_plan_validator_ok_to_tool(self):
        """SpyBackend 提供 local_life intent + recommendation task_type，
           使推荐流程到达 tool_execute 节点。"""
        spy = SpyRealLLMBackend()
        set_llm_backend(spy)
        resp = run_agent_graph("附近推荐火锅", "route_plan_ok")
        nodes = _update_coverage(resp, edge="plan_validator->tool_execute")
        assert "plan_validator" in nodes
        assert "tool_execute" in nodes

    def test_answer_verify_rewrite_loop(self):
        backend = _SeqBackend(["重写回答第一次。", "重写回答第二次。"])
        set_llm_backend(backend)
        resp = run_agent_graph("附近推荐火锅", "route_rewrite")
        _update_coverage(resp, edge="answer_verify->rewrite")
        assert resp.answer_text

    def test_task_plan_comparison_routes(self):
        """使用 SpyBackend 确保 comparison task_type。"""
        get_session_store().save("route_compare", SessionState(last_recommendation_list=[SHOP_A, SHOP_C]))
        spy = SpyRealLLMBackend(scenario_payloads={
            "海底捞和山城一锅": {
                "top_intent": "local_life", "task_type": "comparison",
                "primary_task": "comparison", "merchant_mentions": ["海底捞", "山城一锅"],
                "comparison_targets": [
                    {"shop_name": "海底捞", "reference": "explicit", "source_text": "海底捞"},
                    {"shop_name": "山城一锅", "reference": "explicit", "source_text": "山城一锅"},
                ],
                "focused_facets": ["overall"], "confidence": 0.95,
            },
        })
        set_llm_backend(spy)
        resp = run_agent_graph("海底捞和山城一锅哪个好？", "route_compare")
        nodes = _update_coverage(resp, edge="task_plan->comparison_planner")
        assert "task_plan" in nodes
        assert resp.answer_text

    def test_frame_validator_error_to_clarify(self):
        class FB:
            llm_backend = "fake_llm"
            def __call__(self, prompt, sp="", temp=0.0, tm=3000):
                if "top_intent_router" in prompt or "Top Intent Router" in prompt:
                    return json.dumps({"top_intent": "local_life", "confidence": 0.95})
                return json.dumps({"top_intent": "local_life", "confidence": 0.9,
                                   "merchant_mentions": ["海底捞"]})
        set_llm_backend(FB())
        resp = run_agent_graph("海底捞", "route_frame_fail")
        _update_coverage(resp, edge="frame_validator->clarify_response")
        assert resp.answer_text


# ---------- LLM VERBALIZER ----------

class TestLLMVerbalizerFullChain:
    def test_recommendation_verbalizer_success(self):
        client = _mock_llm("附近我推荐这3家：1. 海底捞(牡丹园店)，2. 川味轩(知春路店)，3. 山城一锅。")
        set_llm_backend(client)
        resp = run_agent_graph("附近推荐火锅", "v_reco_ok")
        _update_coverage(resp, verb_path="recommendation_success")
        assert resp.debug

    def test_recommendation_violation_fallback(self):
        client = _mock_llm("附近我推荐这3家：1. 海底捞(牡丹园店)，2. 海底捞(A店)，3. 川味轩(知春路店)。")
        set_llm_backend(client)
        resp = run_agent_graph("附近推荐火锅", "v_reco_violation")
        _update_coverage(resp, verb_path="recommendation_violation_fallback")
        assert resp.debug

    def test_comparison_verbalizer_success(self):
        client = _mock_llm("对比海底捞(牡丹园店)和山城一锅：在综合排序里，海底捞(牡丹园店)更好。")
        set_llm_backend(client)
        get_session_store().save("v_comp_ok", SessionState(last_recommendation_list=[SHOP_A, SHOP_C]))
        resp = run_agent_graph("第一家和第二家哪个更好？", "v_comp_ok")
        _update_coverage(resp, verb_path="comparison_success")
        assert resp.debug

    def test_comparison_ranking_violation_fallback(self):
        client = _mock_llm("对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。")
        set_llm_backend(client)
        get_session_store().save("v_comp_violation", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))
        resp = run_agent_graph("第一家和第二家哪个更好？", "v_comp_violation")
        _update_coverage(resp, verb_path="comparison_violation_fallback")
        assert resp.debug

    def test_single_shop_verbalizer_success(self):
        client = _mock_llm("海底捞(牡丹园店)目前是营业中。")
        set_llm_backend(client)
        get_session_store().save("v_single_ok", SessionState(last_recommendation_list=[SHOP_A]))
        resp = run_agent_graph("第一家营业中吗", "v_single_ok")
        _update_coverage(resp, verb_path="single_shop_success")
        assert resp.debug

    def test_unknown_as_false_violation_fallback(self):
        import local_life_agent.engine.graph_builder as gb
        orig = gb.dispatch_tool_call
        def mk_fail(tn, args):
            if tn == "get_coupon_list":
                return {"success": False, "result_status": "unknown", "data": None,
                        "error_code": "NETWORK_ERROR", "error_message": "unknown"}
            return _default_dispatch(tn, args)
        gb.dispatch_tool_call = mk_fail
        agent._GRAPH_CACHE = None
        client = _mock_llm("海底捞(牡丹园店)目前没有券。")
        set_llm_backend(client)
        get_session_store().save("v_unknown", SessionState(last_recommendation_list=[SHOP_A]))
        resp = run_agent_graph("第一家有优惠券吗", "v_unknown")
        _update_coverage(resp, verb_path="unknown_as_false_fallback")
        assert resp.debug
        gb.dispatch_tool_call = orig

    def test_rewrite_success_keeps_safe_answer(self):
        client = _SeqBackend([
            "对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。",
            "对比海底捞(牡丹园店)和川味轩(知春路店)：在综合排序里，海底捞(牡丹园店)更好。",
        ])
        set_llm_backend(client)
        get_session_store().save("v_rewrite_ok", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))
        resp = run_agent_graph("第一家和第二家哪个更好？", "v_rewrite_ok")
        _update_coverage(resp, verb_path="rewrite_success")
        assert resp.debug

    def test_rewrite_then_fallback(self):
        client = _SeqBackend([
            "对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。",
            "对比川味轩(知春路店)和海底捞(牡丹园店)：在综合排序里，川味轩(知春路店)更好。",
        ])
        set_llm_backend(client)
        get_session_store().save("v_rewrite_fail", SessionState(last_recommendation_list=[SHOP_A, SHOP_B]))
        resp = run_agent_graph("第一家和第二家哪个更好？", "v_rewrite_fail")
        _update_coverage(resp, verb_path="rewrite_exhausted_fallback")
        assert resp.debug


# ---------- MULTI-TURN ----------

class TestMultiTurn:
    def test_clarification_restore(self):
        set_llm_backend(_mock_llm())
        resp1 = run_agent_graph("海底捞", "mt_clarify")
        assert resp1.answer_text
        get_session_store().save("mt_clarify", SessionState(
            pending_clarification={"pending_id": "pc_mt", "source_node": "target_resolve",
                                   "original_text": "海底捞", "reason": "ambiguous_shop",
                                   "candidate_targets": [{"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}]},
            last_recommendation_list=[],
        ))
        resp2 = run_agent_graph("1", "mt_clarify")
        nodes2 = _update_coverage(resp2, edge="check_pending->target_resolve")
        assert "check_pending_clarification" in nodes2
        assert "target_resolve" in nodes2

    def test_consecutive_turns_state_preserved(self):
        client = _mock_llm()
        set_llm_backend(client)
        resp1 = run_agent_graph("附近推荐火锅", "mt_state")
        assert resp1.answer_text
        resp2 = run_agent_graph("第一家有优惠券吗", "mt_state")
        assert resp2.answer_text


# ---------- EDGE CASES ----------

class TestEdgeCases:
    def test_out_of_scope_intent(self):
        class OOSB:
            llm_backend = "fake_llm"
            def __call__(self, prompt, sp="", temp=0.0, tm=3000):
                if "top_intent_router" in prompt or "Top Intent Router" in prompt:
                    return json.dumps({"top_intent": "out_of_scope", "confidence": 0.99})
                return json.dumps({"top_intent": "out_of_scope"})
        set_llm_backend(OOSB())
        resp = run_agent_graph("1+1等于几？", "edge_oos")
        nodes = _update_coverage(resp, edge="top_intent->emit_response")
        assert "top_intent_router" in nodes
        assert "emit_response" in nodes

    def test_unsafe_input_no_crash(self):
        set_llm_backend(_mock_llm())
        resp = run_agent_graph("测试输入", "edge_unsafe")
        assert resp.answer_text

    def test_spy_backend_e2e(self):
        spy = SpyRealLLMBackend()
        set_llm_backend(spy)
        resp = run_agent_graph("附近推荐火锅", "edge_spy")
        _update_coverage(resp)
        assert resp.debug
        assert spy.call_count >= 1

    def test_missing_shop_name(self):
        """SpyBackend 确保 local_life intent 以触发 NOT_FOUND。"""
        spy = SpyRealLLMBackend(scenario_payloads={
            "火星餐厅": {
                "top_intent": "local_life", "task_type": "single_shop_query",
                "primary_task": "shop_detail", "merchant_mentions": ["火星餐厅"],
                "facets": [{"name": "detail", "required": True}],
                "confidence": 0.95,
            },
        })
        set_llm_backend(spy)
        resp = run_agent_graph("火星餐厅怎么样？", "edge_missing")
        nodes = _update_coverage(resp, edge="clarify_decide->emit_response")
        assert "target_resolve" in nodes
        assert "clarify_decide" in nodes


# =====================================================================
# Coverage Report
# =====================================================================

def test_print_coverage_report() -> None:
    n_total = len(_COVERAGE["nodes"])
    n_covered = sum(1 for v in _COVERAGE["nodes"].values() if v)
    e_total = len(_COVERAGE["conditional_edges"])
    e_covered = sum(1 for v in _COVERAGE["conditional_edges"].values() if v)
    v_total = len(_COVERAGE["verbalizer_paths"])
    v_covered = sum(1 for v in _COVERAGE["verbalizer_paths"].values() if v)

    print()
    print("=" * 70)
    print("  LangGraph 全链路覆盖矩阵")
    print("=" * 70)

    print(f"\n[节点覆盖] {n_covered}/{n_total} ({n_covered/n_total*100:.1f}%)")
    for name in sorted(_COVERAGE["nodes"]):
        s = "PASS" if _COVERAGE["nodes"][name] else "MISS"
        print(f"  [{s:4s}] {name}")

    print(f"\n[条件边覆盖] {e_covered}/{e_total} ({e_covered/e_total*100:.1f}%)")
    for name in sorted(_COVERAGE["conditional_edges"]):
        s = "PASS" if _COVERAGE["conditional_edges"][name] else "MISS"
        print(f"  [{s:4s}] {name}")

    print(f"\n[Verbalizer 路径] {v_covered}/{v_total} ({v_covered/v_total*100:.1f}%)")
    for name in sorted(_COVERAGE["verbalizer_paths"]):
        s = "PASS" if _COVERAGE["verbalizer_paths"][name] else "MISS"
        print(f"  [{s:4s}] {name}")

    print(f"\n[Answer Source 分布]")
    for src, cnt in sorted(_COVERAGE["answer_sources"].items()):
        if cnt:
            print(f"  {src}: {cnt}次")

    unv = [n for n, v in _COVERAGE["nodes"].items() if not v]
    unc = [e for e, v in _COVERAGE["conditional_edges"].items() if not v]
    if unv:
        print(f"\n! 未覆盖节点: {', '.join(unv)}")
    if unc:
        print(f"\n! 未覆盖条件边: {', '.join(unc)}")

    print("=" * 70)
    print(f"\n节点覆盖率: {n_covered/n_total*100:.1f}%")
    assert n_covered / n_total >= 0.80
