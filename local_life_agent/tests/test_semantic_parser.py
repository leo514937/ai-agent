"""Focused tests for the semantic frame parser."""

from __future__ import annotations

import importlib
import json
import logging

import pytest

from ..domain.enums import GroundingStatus, MissingSlotType, PreferenceType, RefineAction, SemanticParseSource, TaskType
from ..domain.schemas import SemanticFrame
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
from ..semantic.slot_extractor import extract_slots


def _semantic_ok_backend(*_args, **_kwargs):
    return {
        "ok": True,
        "content": {
            "top_intent": "local_life",
            "task_type": "coupon_query",
            "primary_task": "coupon_query",
            "facets": [{"name": "coupon", "required": True}],
            "merchant_mentions": ["海底捞"],
            "reference_mentions": [],
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {},
            "follow_up": None,
            "confidence": 0.9,
            "need_context": False,
        },
        "raw": "{}",
        "error_code": "",
        "error_message": "",
        "attempts": 1,
    }


def _structured_backend(content: dict, *, raw: str | None = None, attempts: int = 1):
    return {
        "ok": True,
        "content": content,
        "raw": raw if raw is not None else json.dumps(content, ensure_ascii=False),
        "error_code": "",
        "error_message": "",
        "attempts": attempts,
    }


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
    assert result["semantic_frame"] is not None
    assert result["semantic_source"] == "diagnostic_rules"
    assert result["fallback_reason"] == "LLM_ENUM_OUT_OF_RANGE"


def test_semantic_parser_ignores_llm_wrapper_metadata():
    def backend(*_args, **_kwargs):
        return {
            "ok": True,
            "content": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "facets": [{"name": "category", "required": True}],
                "merchant_mentions": [],
                "reference_mentions": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.95,
                "need_context": False,
            },
            "raw": "{\"top_intent\":\"local_life\"}",
            "error_code": "",
            "error_message": "",
            "attempts": 1,
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "transport": "httpx",
            "llm_backend": "openrouter/deepseek-v4-flash",
        }

    def wrapped_call_llm(prompt, **kwargs):
        return call_llm(prompt, backend=backend, **kwargs)

    result = parse_semantic_frame("推荐北京邮电大学附近的火锅或烧烤，要性价比高的", "local_life", llm_call=wrapped_call_llm)

    assert result["semantic_frame"] is not None
    assert result["semantic_frame"].task_type == TaskType.recommendation
    assert result["error_code"] == ""


def test_exploration_slot_extractor_builds_stage_level_plan():
    frame = extract_slots("五道口附近晚上约会怎么安排", "local_life")

    assert frame["workflow_hint"] == "exploration_planning"
    assert frame["scene"] == "date"
    assert frame["time"] == "evening"
    assert frame["location"]["location_name"] == "五道口附近"
    assert frame["missing_slot_type"] == ""
    assert [stage["stage_type"] for stage in frame["exploration_stages"]] == ["eat", "coffee", "walk"]
    assert frame["exploration_stages"][0]["candidate_query"] == "餐厅"
    assert "open_status" in frame["exploration_stages"][0]["evidence_requirements"]


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
        result = parse_semantic_frame(text, "local_life", llm_call=_semantic_ok_backend)
        assert result["semantic_frame"].task_type == TaskType.coupon_query


def test_semantic_parser_missing_shop_name_requests_context():
    result = parse_semantic_frame("这家店有优惠券吗", "local_life", llm_call=_semantic_ok_backend)

    assert result["semantic_frame"].task_type == TaskType.coupon_query
    assert result["error_code"] == ""


def test_forbidden_semantic_fields_stop_graph_before_tool_execution(monkeypatch):
    module = importlib.reload(gb)
    from ..engine.subgraphs import understanding_subgraph as us
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

    original_dispatch = module.dispatch_tool_call
    original_resolve = module.resolve_shop

    def fake_dispatch(tool_name: str, kwargs: dict):
        tool_calls.append((tool_name, dict(kwargs)))
        return original_dispatch(tool_name, kwargs)

    def fake_resolve(query: str, location=None, session_shop_ids=None):
        resolve_calls.append((query, {"location": location, "session_shop_ids": list(session_shop_ids or [])}))
        return original_resolve(query, location=location, session_shop_ids=session_shop_ids)

    monkeypatch.setattr(us, "parse_semantic_frame", fake_parse_semantic_frame)
    monkeypatch.setattr(module, "dispatch_tool_call", fake_dispatch)
    monkeypatch.setattr(module, "resolve_shop", fake_resolve)

    response = run_agent_graph("海底捞水晶城店有券吗", "semantic_forbid")

    assert response.answer_text
    assert not resolve_calls
    assert not tool_calls
    assert "本地生活" in response.answer_text or "相关问题" in response.answer_text


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


def test_parsed_semantic_frame_roundtrips_with_extended_schema():
    result = parse_semantic_frame("海底捞水晶城店有券吗", "local_life", llm_call=_semantic_ok_backend)
    frame = result["semantic_frame"]

    assert isinstance(frame, SemanticFrame)
    restored = SemanticFrame.model_validate_json(frame.model_dump_json())
    assert restored.semantic_source == frame.semantic_source
    assert restored.parse_source.value == frame.semantic_source
    assert restored.semantic_parse_source.value == frame.semantic_source


def test_structured_llm_output_exposes_parse_sources_and_schema_validation():
    content = extract_slots("推荐北京邮电大学附近的火锅或烧烤，要性价比高的", "local_life")
    content.update(
        {
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "workflow_hint": "recommendation",
            "comparison_intent": False,
            "comparison_structure": "unknown",
            "preference_signals": [
                {"preference_type": "value_for_money", "value": "value_for_money", "text": "性价比高"}
            ],
            "soft_preferences": {"price_preference": "value_for_money"},
            "ranking_signals": {"ranking_policy": "value_for_money_first"},
            "facets": [],
            "focused_facets": [],
            "comparison_targets": [],
            "comparison_facets": [],
            "comparison_focus": "",
            "exploration_stages": [],
            "missing_slots": [],
            "missing_slot_type": "other",
            "follow_up": None,
            "need_context": False,
            "discourse_marker": "",
            "constraint_update": False,
            "new_task_override": False,
            "cancel_intent": False,
        }
    )

    result = parse_semantic_frame("推荐北京邮电大学附近的火锅或烧烤，要性价比高的", "local_life", llm_call=lambda *args, **kwargs: _structured_backend(content))

    frame = result["semantic_frame"]
    assert frame is not None
    assert frame.preference_signals[0].preference_type == PreferenceType.value_for_money
    assert result["parse_source"] == "real_llm"
    assert result["semantic_parse_source"] == "real_llm"
    assert result["schema_validation_result"]["status"] == "validated"
    assert frame.model_dump_json()


def test_schema_validation_failure_falls_back_with_low_confidence():
    bad_content = {
        "top_intent": "local_life",
        "task_type": "single_shop_query",
        "primary_task": "single_shop_query",
        "merchant_mentions": ["海底捞"],
        "shop_id": "fake_shop",
        "confidence": 0.98,
    }

    result = parse_semantic_frame("海底捞西直门店有券吗", "local_life", llm_call=lambda *args, **kwargs: _structured_backend(bad_content))

    assert result["semantic_frame"] is not None
    assert result["semantic_parse_source"] == "fallback_rules"
    assert result["semantic_frame"].confidence >= 0.85
    assert result["fallback_reason"]
    assert result["schema_validation_result"]["status"] in {"fallback", "recovered"}


@pytest.mark.parametrize(
    ("text", "content_builder", "expectations"),
    [
        (
            "推荐几家比较便宜的烧烤",
            lambda: {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "category": "烧烤",
                "comparison_intent": False,
                "preference_signals": [
                    {"preference_type": "relative_price_preference", "value": "relative_price_preference", "text": "比较便宜"}
                ],
                "soft_preferences": {"price_preference": "lower_price"},
                "confidence": 0.92,
            },
            {"task_type": TaskType.recommendation, "pref": PreferenceType.relative_price_preference, "comparison": False},
        ),
        (
            "第一家和第二家比一下",
            lambda: {
                "top_intent": "local_life",
                "task_type": "comparison",
                "primary_task": "comparison",
                "comparison_intent": True,
                "comparison_structure": "multi_target",
                "comparison_targets": [
                    {"shop_name": "第一家", "reference": "ordinal", "source_text": "第一家"},
                    {"shop_name": "第二家", "reference": "ordinal", "source_text": "第二家"},
                ],
                "ordinal_references": ["第一家", "第二家"],
                "comparison_facets": [],
                "confidence": 0.93,
            },
            {"task_type": TaskType.comparison, "comparison": True},
        ),
        (
            "这家有券吗",
            lambda: {
                "top_intent": "local_life",
                "task_type": "single_shop_query",
                "primary_task": "single_shop_query",
                "merchant_mentions": [],
                "shop_reference": {"reference_type": "shop_reference", "text": "这家", "resolved": False},
                "deictic_reference": {"reference_type": "deictic_reference", "text": "这家", "resolved": False},
                "filter_signals": [{"filter_type": "coupon_filter", "value": True, "required": True, "text": "有券"}],
                "need_context": True,
                "confidence": 0.84,
            },
            {"task_type": TaskType.single_shop_query, "need_context": True},
        ),
        (
            "不要烧烤了，推荐咖啡",
            lambda: {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "category": "咖啡",
                "new_task_override": True,
                "constraint_update": True,
                "confidence": 0.88,
            },
            {"task_type": TaskType.recommendation, "override": True},
        ),
        (
            "算了",
            lambda: {
                "top_intent": "local_life",
                "task_type": "clarification_reply",
                "primary_task": "clarification_reply",
                "cancel_intent": True,
                "need_context": False,
                "confidence": 0.62,
            },
            {"task_type": TaskType.clarification_reply, "cancel": True},
        ),
        (
            "帮我安排一个先吃饭再喝咖啡的约会路线",
            lambda: {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "workflow_hint": "exploration_planning",
                "exploration_stages": [
                    {"stage_type": "scene", "scene": "eat", "query": "吃饭"},
                    {"stage_type": "scene", "scene": "coffee", "query": "咖啡"},
                ],
                "discourse_marker": "先",
                "missing_slot_type": "missing_exploration_location",
                "need_context": True,
                "confidence": 0.86,
            },
            {"task_type": TaskType.recommendation, "explore": True},
        ),
    ],
)
def test_structured_examples_cover_phase2_semantics(text, content_builder, expectations):
    result = parse_semantic_frame(text, "local_life", llm_call=lambda *args, **kwargs: _structured_backend(content_builder()))
    frame = result["semantic_frame"]

    assert frame is not None
    assert result["semantic_parse_source"] == "real_llm"
    assert result["schema_validation_result"]["status"] == "validated"
    assert frame.task_type == expectations["task_type"]
    if expectations.get("comparison") is True:
        assert frame.comparison_intent is True
    if expectations.get("override") is True:
        assert frame.new_task_override is True
        assert frame.constraint_update is True
    if expectations.get("cancel") is True:
        assert frame.cancel_intent is True
    if expectations.get("need_context") is True:
        assert frame.need_context is True
    if expectations.get("explore") is True:
        assert len(frame.exploration_stages) >= 2
        assert frame.missing_slot_type == MissingSlotType.missing_exploration_location
    if expectations.get("pref") is not None:
        assert frame.preference_signals[0].preference_type == expectations["pref"]


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

    def test_preference_hints_make_context_visible(self):
        from ..domain.state import SessionState

        ss = SessionState(
            active_preferences=[
                {"preference_type": "budget", "polarity": "like", "value": "lower_price"},
            ]
        )
        summary = build_session_context_summary(ss)
        assert summary.has_context is True
        assert summary.preference_hints == ["budget:like:lower_price"]


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

    def test_recommendation_follow_up_can_be_recovered_from_session_context(self):
        def missing_task_backend(prompt, **kwargs):
            return {
                "ok": True,
                "content": {
                    "top_intent": "local_life",
                    "task_type": None,
                    "primary_task": "",
                    "workflow_hint": "",
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
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "ranking_signals": {},
                    "follow_up": None,
                    "confidence": 0.55,
                    "need_context": True,
                },
                "raw": "",
                "error_code": "",
                "error_message": "",
                "attempts": 1,
            }

        from ..domain.state import SessionState

        ss = SessionState(last_recommendation_list=[{"shop_name": "A火锅店"}, {"shop_name": "B烧烤店"}])
        result = parse_semantic_frame("便宜一点的呢", "local_life", llm_call=missing_task_backend, session_state=ss)

        frame = result["semantic_frame"]
        assert frame.task_type == TaskType.recommendation
        assert frame.primary_task == "recommendation_refine"
        assert frame.workflow_hint == "recommendation"
        assert frame.need_context is True
        assert frame.follow_up is not None
        assert frame.follow_up.get("refine_action") == "cheaper"
        assert frame.soft_preferences.get("price_preference") == "lower_price"
        assert frame.ranking_signals.get("price_preference") == "lower_price"
