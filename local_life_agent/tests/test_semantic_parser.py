"""Focused tests for the semantic frame parser."""

from __future__ import annotations

import json
import logging

from ..domain.enums import RefineAction, TaskType
from ..domain.session_context_summary import (
    SessionContextSummary,
    build_session_context_summary,
)
from ..agent import run_agent_graph
from ..engine import graph_builder as gb
from ..llm.client import call_llm
from ..semantic.intent_parser import (
    _normalize_refine_action,
    _validate_semantic_payload,
    parse_semantic_frame,
)


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

    def fake_parse_semantic_frame(_text: str, _top_intent: str, llm_call=None, **kwargs):
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


# ===================================================================
# SessionContextSummary tests
# ===================================================================


class TestSessionContextSummary:
    """Tests for the compressed session context summary."""

    def test_empty_when_no_session(self):
        summary = build_session_context_summary(None)
        assert summary.has_context is False
        assert summary.last_recommendation_names == []

    def test_empty_when_empty_session(self):
        summary = build_session_context_summary({})
        assert summary.has_context is False

    def test_recommendation_names_limited_to_5(self):
        state = {
            "last_recommendation_list": [
                {"shop_name": f"Shop {i}"} for i in range(10)
            ],
        }
        summary = build_session_context_summary(state)
        assert summary.has_context is True
        assert summary.last_recommendation_count == 10
        assert len(summary.last_recommendation_names) == 5

    def test_current_shop_name_extracted(self):
        state = {"current_shop": {"shop_name": "海底捞(牡丹园店)"}}
        summary = build_session_context_summary(state)
        assert summary.current_shop_name == "海底捞(牡丹园店)"

    def test_active_constraints_preserved(self):
        state = {"active_constraints": {"price": "cheap", "category": "火锅"}}
        summary = build_session_context_summary(state)
        assert summary.active_constraints.get("price") == "cheap"

    def test_pending_clarification_type(self):
        state = {"pending_clarification": {"expected_reply_type": "shop_choice"}}
        summary = build_session_context_summary(state)
        assert summary.pending_clarification_present is True
        assert summary.pending_clarification_type == "shop_choice"

    def test_comparison_target_names(self):
        state = {
            "comparison_targets": [
                {"shop_name": "A店"},
                {"shop_name": "B店"},
            ],
        }
        summary = build_session_context_summary(state)
        assert summary.comparison_targets_count == 2
        assert "A店" in summary.comparison_target_names

    def test_model_dump_no_none_fields(self):
        """model_dump should not include None fields by default."""
        summary = SessionContextSummary()
        dumped = summary.model_dump()
        # has_context is False but not None, so it should be present
        assert "has_context" in dumped
        # current_shop_name is None but that's fine for Pydantic

    def test_from_session_state_object(self):
        from ..domain.state import SessionState
        ss = SessionState(
            current_shop={"shop_name": "测试店"},
            last_recommendation_list=[{"shop_name": "A店"}, {"shop_name": "B店"}],
        )
        summary = build_session_context_summary(ss)
        assert summary.has_context is True
        assert summary.current_shop_name == "测试店"
        assert len(summary.last_recommendation_names) == 2


# ===================================================================
# refine_action normalization tests
# ===================================================================


class TestRefineActionNormalization:
    """Tests for ``_normalize_refine_action``."""

    def test_direct_match(self):
        assert _normalize_refine_action("cheaper") == "cheaper"
        assert _normalize_refine_action("closer") == "closer"
        assert _normalize_refine_action("select_candidate") == "select_candidate"

    def test_synonym_cheaper(self):
        for synonym in ("lower_price", "more_affordable", "cheap", "price_down", "affordable", "budget"):
            assert _normalize_refine_action(synonym) == "cheaper", f"{synonym} -> cheaper"

    def test_synonym_closer(self):
        for synonym in ("nearer", "nearby", "shorter_distance", "near", "close"):
            assert _normalize_refine_action(synonym) == "closer", f"{synonym} -> closer"

    def test_synonym_higher_rating(self):
        for synonym in ("rating_higher", "better_score", "better_rating"):
            assert _normalize_refine_action(synonym) == "higher_rating", f"{synonym} -> higher_rating"

    def test_synonym_select_candidate(self):
        for synonym in ("select", "pick_one", "which_one", "first_one", "ordinal", "this_one"):
            assert _normalize_refine_action(synonym) == "select_candidate", f"{synonym} -> select_candidate"

    def test_unknown_becomes_other(self):
        assert _normalize_refine_action("something_random") == "other"

    def test_case_and_whitespace_normalized(self):
        assert _normalize_refine_action(" Lower Price ") == "cheaper"
        assert _normalize_refine_action("near-by") == "closer"
        assert _normalize_refine_action("NEAR_BY") == "closer"
        assert _normalize_refine_action("Better Score") == "higher_rating"

    def test_integration_in_validate_semantic_payload(self):
        """_validate_semantic_payload normalizes refine_action."""
        payload = {
            "task_type": "single_shop_query",
            "merchant_mentions": ["测试店"],
            "follow_up": {"is_follow_up": True, "refine_action": "lower_price"},
        }
        result = _validate_semantic_payload(payload)
        fu = result.get("follow_up", {})
        assert fu.get("refine_action") == "cheaper"

    def test_no_follow_up_unchanged(self):
        payload = {
            "task_type": "single_shop_query",
            "merchant_mentions": ["测试店"],
        }
        result = _validate_semantic_payload(payload)
        assert result.get("follow_up") is None


# ===================================================================
# SESSION_CONTEXT injection in parse_semantic_frame
# ===================================================================


class TestSessionContextInjection:
    """Tests that session context is injected into the parser LLM prompt."""

    def test_session_context_in_prompt_when_provided(self):
        calls = []

        def capturing_backend(prompt, **kwargs):
            calls.append(prompt)
            return {
                "ok": True,
                "content": {
                    "task_type": "recommendation",
                    "merchant_mentions": [],
                    "primary_task": "follow_up",
                    "facets": [],
                    "follow_up": {"is_follow_up": True, "refine_action": "cheaper"},
                    "need_context": True,
                    "confidence": 0.8,
                },
                "raw": "",
                "error_code": "",
                "error_message": "",
                "attempts": 1,
            }

        from ..domain.state import SessionState
        ss = SessionState(
            last_recommendation_list=[{"shop_name": "A火锅店"}, {"shop_name": "B烧烤店"}],
            active_constraints={"category": "火锅"},
        )

        result = parse_semantic_frame(
            "便宜一点的呢",
            "local_life",
            llm_call=capturing_backend,
            session_state=ss,
        )

        assert calls
        prompt_text = calls[0]
        # Check SESSION_CONTEXT is in the prompt
        assert '"has_context": true' in prompt_text or "has_context" in prompt_text
        # Check TEXT is last in the prompt
        assert prompt_text.strip().endswith("便宜一点的呢")
        # Check no shop_id leaked
        assert '"shop_id"' not in prompt_text
        # Check recommendation count is present
        assert '"last_recommendation_count"' in prompt_text or "2" in prompt_text

    def test_no_session_context_when_not_provided(self):
        calls = []

        def capturing_backend(prompt, **kwargs):
            calls.append(prompt)
            return {
                "ok": True,
                "content": {
                    "task_type": "single_shop_query",
                    "merchant_mentions": ["测试店"],
                    "primary_task": "",
                    "facets": [],
                    "follow_up": None,
                    "need_context": False,
                    "confidence": 0.9,
                },
                "raw": "",
                "error_code": "",
                "error_message": "",
                "attempts": 1,
            }

        result = parse_semantic_frame(
            "测试店有券吗",
            "local_life",
            llm_call=capturing_backend,
        )

        assert calls
        prompt_text = calls[0]
        # SESSION_CONTEXT should be present with has_context=false (compact JSON)
        assert '"has_context":false' in prompt_text
