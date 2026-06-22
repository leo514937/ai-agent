"""Focused tests for the semantic frame parser."""

from __future__ import annotations

import logging

from ..domain.enums import TaskType
from ..agent import run_agent_graph
from ..engine import graph_builder as gb
from ..llm.client import call_llm
from ..semantic.intent_parser import _validate_semantic_payload, parse_semantic_frame


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
    assert result["error_code"] == ""
    assert result["semantic_frame"].task_type == TaskType.coupon_query
    assert result["semantic_source"] == "fallback_rules"
    assert result["fallback_reason"] == "LLM_ENUM_OUT_OF_RANGE"


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
    assert (
        result["semantic_frame"].need_context is True
        or result["semantic_frame"].deictic_references
        or result["error_code"] != ""
    )


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


def test_facet_dropped_logging(caplog):
    """未知 facet 被过滤时应该产生 warning 日志；已支持的 facet 不应被过滤。"""
    payload = {
        "task_type": "single_shop_query",
        "facets": [
            {"name": "coupon", "required": True},
            {"name": "environment", "required": True},
            {"name": "rating", "required": False},
            {"name": "unknown_xxx", "required": True},
        ],
        "merchant_mentions": ["海底捞"],
    }

    with caplog.at_level(logging.WARNING, logger="local_life_agent.semantic.intent_parser"):
        result = _validate_semantic_payload(payload)

    # coupon / environment / rating — all supported → kept
    assert len(result["facets"]) == 3, (
        f"Expected 3 facets (coupon, environment, rating), "
        f"got {len(result['facets'])}: {result['facets']}"
    )
    kept_names = {f["name"] for f in result["facets"]}
    assert "coupon" in kept_names
    assert "environment" in kept_names
    assert "rating" in kept_names

    # unknown_xxx should be dropped with a warning
    assert any("unknown_xxx" in record.message for record in caplog.records), (
        "Warning log should mention dropped facet 'unknown_xxx'"
    )


def test_facet_dropped_facets_captured():
    """drop_facets 被 _validate_semantic_payload 正确捕获。"""
    from ..semantic.intent_parser import get_last_dropped_facets, _last_dropped_facets

    # Reset
    _last_dropped_facets.clear()
    payload = {
        "task_type": "single_shop_query",
        "facets": [
            {"name": "coupon", "required": True},
            {"name": "unknown_abc", "required": True},
            {"name": "unknown_def", "required": False},
        ],
        "merchant_mentions": ["海底捞"],
    }
    _validate_semantic_payload(payload)
    dropped = get_last_dropped_facets()
    assert "unknown_abc" in dropped
    assert "unknown_def" in dropped
    assert "coupon" not in dropped
    # Second call should be empty (cleared)
    assert get_last_dropped_facets() == []


def test_task_type_source_in_graph_state():
    """GraphState 包含 task_type_source 和 dropped_facets 字段。"""
    from typing import get_type_hints
    from ..domain.graph_state import GraphState

    hints = get_type_hints(GraphState)
    assert "task_type_source" in hints, (
        f"GraphState missing task_type_source. Available: {list(hints.keys())}"
    )
    assert "dropped_facets" in hints, (
        f"GraphState missing dropped_facets. Available: {list(hints.keys())}"
    )
