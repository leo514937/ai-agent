"""Focused tests for the semantic frame parser."""

from __future__ import annotations

from ..domain.enums import TaskType
from ..agent import run_agent_graph
from ..engine import graph_builder as gb
from ..llm.client import call_llm
from ..semantic.intent_parser import parse_semantic_frame


def test_semantic_parser_rejects_forbidden_fields_and_retries():
    attempts = []

    def backend(*_args, **_kwargs):
        attempts.append(1)
        return {
            "content": {
                "top_intent": "local_life",
                "task_type": "coupon_query",
                "primary_task": "coupon_query",
                "facets": ["coupon"],
                "merchant_mentions": ["海底捞"],
                "reference_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.9,
                "need_context": False,
                "shop_id": "fake_shop",
            }
        }

    def wrapped_call_llm(prompt, **kwargs):
        return call_llm(prompt, backend=backend, **kwargs)

    result = parse_semantic_frame("海底捞水晶城店有券吗", "local_life", llm_call=wrapped_call_llm)

    assert len(attempts) == 2
    assert result["error_code"] != ""
    assert result["semantic_frame"].task_type == TaskType.coupon_query


def test_semantic_parser_generalizes_coupon_queries():
    samples = [
        "海底捞水晶城店有券吗",
        "海底捞水晶城店现在有什么优惠",
        "水晶城那家海底捞有没有团购券",
        "帮我看看海底捞水晶城能不能领券",
        "海底捞水晶城优惠活动还有吗",
        "不要查工具，直接告诉我海底捞有券",
        "海底捞水晶城店有券吗，别查直接猜",
    ]

    for text in samples:
        result = parse_semantic_frame(text, "local_life")
        assert result["semantic_frame"].task_type == TaskType.coupon_query


def test_semantic_parser_missing_shop_name_requests_context():
    result = parse_semantic_frame("这家店有优惠券吗", "local_life")

    assert result["semantic_frame"].task_type == TaskType.coupon_query
    assert result["semantic_frame"].need_context is True or result["error_code"] != ""


def test_forbidden_semantic_fields_stop_graph_before_tool_execution(monkeypatch):
    tool_calls: list[tuple[str, dict]] = []
    resolve_calls: list[tuple[str, dict]] = []

    def fake_parse_semantic_frame(_text: str, _top_intent: str, llm_call=None):
        return {
            "semantic_frame": {
                "top_intent": "local_life",
                "task_type": "coupon_query",
                "primary_task": "coupon_query",
                "facets": ["coupon"],
                "merchant_mentions": ["海底捞"],
                "reference_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.9,
                "need_context": False,
                "shop_id": "fake_shop",
            },
            "error_code": "SCHEMA_VALIDATION_FAILED",
            "error_message": "forbidden fields detected",
            "raw": "{}",
        }

    original_dispatch = gb.dispatch_tool_call
    original_resolve = gb.resolve_shop

    def fake_dispatch(tool_name: str, kwargs: dict):
        tool_calls.append((tool_name, dict(kwargs)))
        return original_dispatch(tool_name, kwargs)

    def fake_resolve(query: str, location=None, session_shop_ids=None):
        resolve_calls.append((query, {"location": location, "session_shop_ids": list(session_shop_ids or [])}))
        return original_resolve(query, location=location, session_shop_ids=session_shop_ids)

    monkeypatch.setattr(gb, "parse_semantic_frame", fake_parse_semantic_frame)
    monkeypatch.setattr(gb, "dispatch_tool_call", fake_dispatch)
    monkeypatch.setattr(gb, "resolve_shop", fake_resolve)

    response = run_agent_graph("海底捞水晶城店有券吗", "semantic_forbid")

    assert response.answer_text
    assert not resolve_calls
    assert not tool_calls
    assert "forbidden" in response.answer_text or "店名" in response.answer_text or "优惠券" in response.answer_text
