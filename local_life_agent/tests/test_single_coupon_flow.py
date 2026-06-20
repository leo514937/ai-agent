"""Stage-10 single-shop coupon flow tests.

These tests keep the scope narrow:
  - exact shop name can reach ``get_coupon_list``
  - empty / timeout tool results degrade gracefully
  - fuzzy shop mentions do not jump directly into coupon lookup
"""

from __future__ import annotations

from ..agent import AgentResponse, DebugInfo
from ..engine import graph_builder as gb


def _run_with_spy(text: str, monkeypatch):
    calls: list[tuple[str, dict]] = []
    resolve_calls: list[tuple[str, dict]] = []
    original = gb.dispatch_tool_call
    original_resolve = gb.resolve_shop

    def fake_dispatch(tool_name: str, kwargs: dict):
        calls.append((tool_name, dict(kwargs)))
        return original(tool_name, kwargs)

    def fake_resolve(query: str, location=None, session_shop_ids=None):
        resolve_calls.append((
            query,
            {
                "location": location,
                "session_shop_ids": list(session_shop_ids or []),
            },
        ))
        return original_resolve(query, location=location, session_shop_ids=session_shop_ids)

    monkeypatch.setattr(gb, "dispatch_tool_call", fake_dispatch)
    monkeypatch.setattr(gb, "resolve_shop", fake_resolve)
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
    return response, calls, resolve_calls


def test_exact_shop_name_reaches_coupon_tool_and_returns_coupon(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("海底捞(牡丹园店)有券吗", monkeypatch)

    assert resolve_calls
    assert any(tool_name == "get_coupon_list" for tool_name, _ in calls)
    assert "海底捞(牡丹园店)" in response.answer_text
    assert "海底捞午市88折券" in response.answer_text
    assert "有券" in response.answer_text
    assert response.debug is not None
    assert response.debug.semantic_frame
    assert response.debug.execution_plan
    assert response.debug.tool_results


def test_empty_coupon_shop_returns_no_coupon_notice(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("海底捞火锅(水晶城购物中心店)有券吗", monkeypatch)

    assert resolve_calls
    assert any(tool_name == "get_coupon_list" for tool_name, _ in calls)
    assert "暂无可用券" in response.answer_text or "没有券" in response.answer_text


def test_timeout_coupon_shop_degrades_controlled(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("远方烧烤(清河店)有券吗", monkeypatch)

    assert resolve_calls
    assert any(tool_name == "get_coupon_list" for tool_name, _ in calls)
    assert (
        "暂时无法确认优惠券情况" in response.answer_text
        or "获取优惠券信息失败" in response.answer_text
        or "稍后再试" in response.answer_text
    )


def test_fuzzy_shop_does_not_call_coupon_tool(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("海底捞有券吗", monkeypatch)

    assert resolve_calls
    assert all(tool_name != "get_coupon_list" for tool_name, _ in calls)
    assert "店名有点模糊" in response.answer_text or "请提供完整店名" in response.answer_text


def test_missing_shop_name_returns_non_empty_clarification(monkeypatch):
    response, calls, resolve_calls = _run_with_spy("这家店有优惠券吗", monkeypatch)

    assert not resolve_calls
    assert all(tool_name != "get_coupon_list" for tool_name, _ in calls)
    assert response.answer_text.strip()
    assert "店名" in response.answer_text or "优惠券" in response.answer_text


def test_verifier_failure_falls_back_to_unknown_message(monkeypatch):
    original_generate = gb.generate_answer

    def bad_generate(*_args, **_kwargs):
        return "没有券"

    monkeypatch.setattr(gb, "generate_answer", bad_generate)
    response, calls, resolve_calls = _run_with_spy("远方烧烤(清河店)有券吗", monkeypatch)
    monkeypatch.setattr(gb, "generate_answer", original_generate)

    assert resolve_calls
    assert any(tool_name == "get_coupon_list" for tool_name, _ in calls)
    assert "暂时无法确认优惠券情况" in response.answer_text
    assert "没有券" not in response.answer_text
    assert "暂无券" not in response.answer_text
    assert "无优惠" not in response.answer_text
