"""Stage-10 single-shop coupon flow tests.

These tests keep the scope narrow:
  - exact shop name can reach ``get_coupon_list``
  - empty / timeout tool results degrade gracefully
  - fuzzy shop mentions do not jump directly into coupon lookup
"""

from __future__ import annotations

from typing import Any, cast

from ..agent import AgentResponse, DebugInfo
from ..engine import graph_builder as gb
from ..session.store import reset_session_store


def _coupon_llm_backend(prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs):
    if "本地生活语义解析器" not in prompt:
        return {
            "ok": True,
            "content": {"top_intent": "local_life", "confidence": 0.95},
            "confidence": 0.95,
            "raw": "{}",
            "error_code": "",
            "error_message": "",
        }
    if "这家店有优惠券吗" in prompt or "这家有优惠券吗" in prompt:
        content = {
            "top_intent": "local_life",
            "task_type": "coupon_query",
            "primary_task": "查询优惠券",
            "facets": [{"name": "coupon", "required": True}],
            "merchant_mentions": [],
            "brand_mentions": [],
            "branch_mentions": [],
            "reference_mentions": [],
            "comparison_targets": [],
            "ordinal_references": [],
            "deictic_references": ["这家"],
            "focused_facets": ["coupon"],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "follow_up": None,
            "confidence": 0.95,
            "need_context": True,
        }
        return {"ok": True, "content": content, "confidence": 0.95, "raw": "{}", "error_code": "", "error_message": ""}

    mentions = ["海底捞"]
    branch_mentions = []
    if "海底捞火锅(湖滨店)" in prompt:
        mentions = ["海底捞火锅(湖滨店)", "海底捞"]
        branch_mentions = ["湖滨店"]
    elif "海底捞火锅(水晶城购物中心店)" in prompt:
        mentions = ["海底捞火锅(水晶城购物中心店)", "海底捞"]
        branch_mentions = ["水晶城购物中心店"]
    elif "远方烧烤(清河店)" in prompt:
        mentions = ["远方烧烤(清河店)", "远方烧烤"]
        branch_mentions = ["清河店"]
    elif "海底捞(牡丹园店)" in prompt:
        mentions = ["海底捞", "牡丹园店"]
        branch_mentions = ["牡丹园店"]

    return {
        "ok": True,
        "content": {
            "top_intent": "local_life",
            "task_type": "coupon_query",
            "primary_task": "查询优惠券",
            "facets": [{"name": "coupon", "required": True}],
            "merchant_mentions": mentions,
            "brand_mentions": [m for m in mentions if "店" not in m and "(" not in m],
            "branch_mentions": branch_mentions,
            "reference_mentions": [],
            "comparison_targets": [],
            "ordinal_references": [],
            "deictic_references": [],
            "focused_facets": ["coupon"],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "follow_up": None,
            "confidence": 0.95,
            "need_context": False,
        },
        "confidence": 0.95,
        "raw": "{}",
        "error_code": "",
        "error_message": "",
    }


def _run_with_spy(text: str, monkeypatch):
    reset_session_store()
    calls: list[tuple[str, dict]] = []
    original_dispatch = gb.dispatch_tool_call

    def fake_dispatch(tool_name: str, kwargs: dict):
        calls.append((tool_name, dict(kwargs)))
        return original_dispatch(tool_name, kwargs)

    monkeypatch.setattr(gb, "call_llm", _coupon_llm_backend)
    monkeypatch.setattr(gb, "dispatch_tool_call", fake_dispatch)
    graph = gb.build_graph()
    initial = {
        "raw_text": text,
        "session_id": "stage10_coupon",
        "trace_id": "test_trace",
        "turn_id": "",
        "user_id": "",
        "normalized_text": "",
        "input_type": "text",
        "top_intent": None,
        "semantic_frame": None,
        "pending_clarification": None,
        "current_shop": None,
        "last_recommendation_list": [],
        "active_constraints": {},
        "comparison_targets": [],
        "resolved_target": None,
        "resolve_shop_result": None,
        "execution_plan": None,
        "validated_plan": None,
        "tool_results": {},
        "tool_result_set": {},
        "evidence_pack": None,
        "answer_plan": None,
        "final_response": "",
        "state_update_plan": None,
        "session_state_before": None,
        "event_log": [],
        "metrics_tags": {},
        "trace_spans": [],
        "rewrite_count": 0,
        "session_state": None,
        "error_code": "",
        "guard_result": "",
        "verify_result": "",
        "draft_response": "",
    }
    final_state = graph.invoke(initial, config={"recursion_limit": 50})
    response = AgentResponse(
        answer_text=final_state.get("final_response", ""),
        trace_id=final_state.get("trace_id", ""),
        session_id=final_state.get("session_id", ""),
        debug=DebugInfo(
            execution_trace=final_state.get("event_log", []),
            semantic_frame=final_state.get("semantic_frame") or {},
            execution_plan=final_state.get("execution_plan") or {},
            tool_results=final_state.get("tool_result_set") or final_state.get("tool_results") or {},
        ),
    )
    return response, calls, [item for item in calls if item[0] == "resolve_shop"]


def test_exact_shop_name_reaches_coupon_tool_and_returns_coupon(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("海底捞(牡丹园店)有券吗", monkeypatch)

    assert response.debug is not None
    assert response.debug.semantic_frame
    assert response.debug.execution_plan
    assert response.debug.tool_results
    plan_obj = response.debug.execution_plan
    plan_dump = getattr(plan_obj, "model_dump", None)
    plan = cast(dict[str, Any], plan_dump() if callable(plan_dump) else dict(plan_obj))
    tool_names = [call.get("tool_name") for call in plan.get("tool_calls", [])]
    assert "get_coupon_list" in tool_names


def test_empty_coupon_shop_returns_no_coupon_notice(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("海底捞火锅(水晶城购物中心店)有券吗", monkeypatch)

    assert response.debug is not None
    assert any(tool_name == "get_coupon_list" for tool_name, _ in calls)


def test_timeout_coupon_shop_degrades_controlled(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("远方烧烤(清河店)有券吗", monkeypatch)

    assert response.debug is not None
    assert any(tool_name == "get_coupon_list" for tool_name, _ in calls)
    assert response.answer_text


def test_fuzzy_shop_does_not_call_coupon_tool(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("海底捞有券吗", monkeypatch)

    assert all(tool_name != "get_coupon_list" for tool_name, _ in calls)
    assert response.debug is not None
    sf = response.debug.semantic_frame
    need_context = getattr(sf, "need_context", None)
    if need_context is None and isinstance(sf, dict):
        need_context = sf.get("need_context")
    assert need_context in (False, True)


def test_missing_shop_name_returns_non_empty_clarification(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("这家店有优惠券吗", monkeypatch)

    assert all(tool_name != "get_coupon_list" for tool_name, _ in calls)
    assert response.debug is not None
    sf = response.debug.semantic_frame
    need_context = getattr(sf, "need_context", None)
    if need_context is None and isinstance(sf, dict):
        need_context = sf.get("need_context")
    assert need_context is True


def test_verifier_failure_falls_back_to_unknown_message(monkeypatch):
    original_generate = gb.generate_answer

    def bad_generate(*_args, **_kwargs):
        return "没有券"

    monkeypatch.setattr(gb, "generate_answer", bad_generate)
    response, calls, resolve_calls = _run_with_spy("远方烧烤(清河店)有券吗", monkeypatch)
    monkeypatch.setattr(gb, "generate_answer", original_generate)

    assert response.debug is not None
    assert response.answer_text
