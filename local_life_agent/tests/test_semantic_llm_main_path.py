"""Regression tests for the LLM-first semantic main path."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pytest

from ..agent import run_agent_graph
from ..domain.state import SessionState
from ..engine import graph_builder
from ..llm.client import call_llm
from ..semantic.intent_parser import parse_semantic_frame
from ..session.store import get_session_store, reset_session_store


SHOP_A = {"shop_id": "shop_sc_05", "shop_name": "\u5ddd\u5473\u8f69(\u77e5\u6625\u8def\u5e97)"}
SHOP_B = {"shop_id": "shop_007", "shop_name": "\u6d77\u5e95\u635e(\u7261\u4e39\u56ed\u5e97)"}
SHOP_C = {"shop_id": "shop_sc_01", "shop_name": "\u6d77\u5e95\u635e\u706b\u9505(\u6c34\u6676\u57ce\u8d2d\u7269\u4e2d\u5fc3\u5e97)"}
SHOP_D = {"shop_id": "shop_sc_04", "shop_name": "\u5f20\u8bb0\u5bb6\u5e38\u83dc(\u5317\u90ae\u5e97)"}


@pytest.fixture(autouse=True)
def _reset_store() -> Generator[None, None, None]:
    reset_session_store()
    yield
    reset_session_store()


def _llm_ok(payload: dict) -> Callable[..., dict]:
    def _call(*_args, **_kwargs) -> dict:
        return {
            "ok": True,
            "content": payload,
            "confidence": float(payload.get("confidence", 0.95)),
            "raw": "{}",
            "error_code": "",
            "error_message": "",
        }

    return _call


def _llm_fail(error_code: str = "LLM_TIMEOUT") -> Callable[..., dict]:
    def _call(*_args, **_kwargs) -> dict:
        return {
            "ok": False,
            "content": None,
            "confidence": 0.0,
            "raw": "",
            "error_code": error_code,
            "error_message": error_code.lower(),
        }

    return _call


def _recommendation_payload(*, coupon: bool, open_now: bool, nearby: bool = True) -> dict:
    return {
        "top_intent": "local_life",
        "task_type": "recommendation",
        "primary_task": "recommendation",
        "facets": [],
        "merchant_mentions": [],
        "reference_mentions": [],
        "comparison_targets": [],
        "ordinal_references": [],
        "deictic_references": [],
        "focused_facets": [],
        "comparison_focus": "",
        "hard_constraints": {},
        "soft_preferences": {
            "scene_terms": ["\u7ea6\u4f1a"],
            "coupon_preferred": coupon,
            "open_now_preferred": open_now,
            "nearby_preferred": nearby,
        },
        "ranking_signals": {
            "query_terms": ["\u706b\u9505"],
            "category": "\u706b\u9505",
            "coupon_preferred": coupon,
            "open_now_preferred": open_now,
            "nearby_preferred": nearby,
        },
        "follow_up": None,
        "confidence": 0.95,
        "need_context": False,
    }


def _comparison_payload(*, focused_facets: list[str], deictic_refs: list[str] | None = None) -> dict:
    return {
        "top_intent": "local_life",
        "task_type": "comparison",
        "primary_task": "comparison",
        "facets": [],
        "merchant_mentions": [SHOP_B["shop_name"]],
        "reference_mentions": ["\u7b2c\u4e00\u5bb6"],
        "comparison_targets": [
            {"shop_name": "\u7b2c\u4e00\u5bb6", "reference": "ordinal", "source_text": "\u7b2c\u4e00\u5bb6"},
            {"shop_name": SHOP_B["shop_name"], "reference": "explicit", "source_text": SHOP_B["shop_name"]},
        ],
        "ordinal_references": ["\u7b2c\u4e00\u5bb6"],
        "deictic_references": deictic_refs or [],
        "focused_facets": focused_facets,
        "comparison_focus": focused_facets[0] if focused_facets else "",
        "hard_constraints": {},
        "soft_preferences": {},
        "ranking_signals": {},
        "follow_up": None,
        "confidence": 0.96,
        "need_context": False,
    }


def test_graph_semantic_parse_calls_default_llm_backend(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[tuple, dict]] = []

    def fake_call_llm(*args, **kwargs) -> dict:
        calls.append((args, kwargs))
        return _llm_ok(_recommendation_payload(coupon=False, open_now=False))(*args, **kwargs)

    monkeypatch.setattr(graph_builder, "call_llm", fake_call_llm)
    response = run_agent_graph("\u9644\u8fd1\u63a8\u8350\u706b\u9505", "llm_default_backend")

    assert calls
    assert response.debug is not None
    assert response.debug.semantic_frame.get("semantic_source") == "real_llm"
    assert response.debug.semantic_frame.get("llm_called") is True


def test_graph_semantic_parse_uses_injected_fake_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "call_llm", _llm_ok(_recommendation_payload(coupon=True, open_now=True)))

    response = run_agent_graph("\u9644\u8fd1\u63a8\u8350\u706b\u9505", "llm_injected_backend")

    assert response.debug is not None
    assert response.debug.semantic_frame.get("semantic_source") == "real_llm"
    assert response.debug.turn_trace.get("task_type") == "recommendation"
    assert response.debug.turn_trace.get("semantic_source") == "real_llm"


def test_semantic_parse_fallback_only_when_llm_fails():
    success = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=_llm_ok(_recommendation_payload(coupon=False, open_now=False)),
    )
    failure = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=_llm_fail("LLM_TIMEOUT"),
    )

    assert success["semantic_source"] == "real_llm"
    assert success["fallback_reason"] == ""
    assert failure["semantic_frame"] is not None
    assert failure["semantic_source"] == "diagnostic_rules"
    assert failure["fallback_reason"] == "LLM_TIMEOUT"
    assert failure["semantic_repair_hints"]
    assert failure["llm_called"] is True


def _fail_semantic_only(error_code: str = "LLM_TIMEOUT"):
    """Return a backend that succeeds for intent routing but fails for semantic parsing.

    ``_h_top_intent_router`` and ``_h_semantic_parse`` both receive the same
    injected ``call_llm``.  We distinguish them by checking the prompt content.
    """
    def _call(*_args: Any, **_kwargs: Any) -> dict:
        prompt = _args[0] if _args else _kwargs.get("prompt", "")
        if "Local Life Semantic Parser" in prompt or "本地生活语义解析器" in prompt:
            return {
                "ok": False,
                "content": None,
                "confidence": 0.0,
                "raw": "",
                "error_code": error_code,
                "error_message": error_code.lower(),
                "llm_backend": "real_llm",
            }
        # Intent routing — succeed so the graph can reach semantic_parse
        return {
            "ok": True,
            "content": {"top_intent": "local_life", "confidence": 0.95},
            "confidence": 0.95,
            "raw": "{}",
            "error_code": "",
            "error_message": "",
            "llm_backend": "real_llm",
        }
    return _call


def test_semantic_debug_marks_llm_or_fallback_source(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "call_llm", _llm_ok(_recommendation_payload(coupon=False, open_now=False)))
    llm_response = run_agent_graph("\u9644\u8fd1\u63a8\u8350\u706b\u9505", "llm_debug_source")

    monkeypatch.setattr(graph_builder, "call_llm", _fail_semantic_only("LLM_TIMEOUT"))
    fallback_response = run_agent_graph("\u9644\u8fd1\u63a8\u8350\u706b\u9505", "fallback_debug_source")

    assert llm_response.debug is not None
    assert fallback_response.debug is not None
    assert llm_response.debug.semantic_frame.get("semantic_source") == "real_llm"
    assert fallback_response.debug.turn_trace.get("semantic_source") == "diagnostic_rules"
    assert fallback_response.debug.turn_trace.get("fallback_reason")


def test_recommendation_uses_fake_llm_constraints(monkeypatch: pytest.MonkeyPatch):
    result = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=_llm_ok(_recommendation_payload(coupon=True, open_now=True)),
    )

    frame = result["semantic_frame"]
    assert frame.task_type == "recommendation"
    assert frame.ranking_signals.get("query_terms") == ["\u706b\u9505"]
    assert frame.soft_preferences.get("scene_terms") == ["\u7ea6\u4f1a"]
    assert frame.soft_preferences.get("coupon_preferred") is True
    assert frame.soft_preferences.get("open_now_preferred") is True


def test_recommendation_llm_keyword_conflict_prefers_llm(monkeypatch: pytest.MonkeyPatch):
    result = parse_semantic_frame(
        "\u9644\u8fd1\u6709\u5238\u7684\u706b\u9505",
        "local_life",
        llm_call=_llm_ok(_recommendation_payload(coupon=False, open_now=False)),
    )

    frame = result["semantic_frame"]
    assert frame.task_type == "recommendation"
    assert frame.soft_preferences.get("coupon_preferred") is False
    assert frame.soft_preferences.get("open_now_preferred") is False


def test_recommendation_parser_rejects_tool_name_and_shop_id():
    def backend(*_args, **_kwargs):
        return {
            "content": {
                **_recommendation_payload(coupon=True, open_now=True),
                "tool_name": "search_shops",
                "shop_id": "fake_shop",
            }
        }

    def wrapped_call_llm(prompt, **kwargs):
        return call_llm(prompt, backend=backend, **kwargs)

    result = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=wrapped_call_llm,
    )

    assert result["semantic_frame"] is not None
    assert result["semantic_source"] == "diagnostic_rules"
    assert result["fallback_reason"] == "LLM_ENUM_OUT_OF_RANGE"


def test_comparison_uses_fake_llm_targets(monkeypatch: pytest.MonkeyPatch):
    get_session_store().save(
        "cmp_llm_targets",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
    )
    monkeypatch.setattr(graph_builder, "call_llm", _llm_ok(_comparison_payload(focused_facets=["distance"])))
    monkeypatch.setattr(graph_builder, "verify_answer", lambda *_args, **_kwargs: {"passed": True})

    response = run_agent_graph("海底捞和山城一锅哪个好？", "cmp_llm_targets")

    assert response.debug is not None
    assert response.debug.turn_trace.get("task_type") == "comparison"
    assert response.debug.turn_trace.get("semantic_source") == "real_llm"


def test_comparison_focused_facets_from_llm(monkeypatch: pytest.MonkeyPatch):
    get_session_store().save(
        "cmp_llm_focus",
        SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C, SHOP_D]),
    )
    payload = _comparison_payload(focused_facets=["distance"], deictic_refs=["\u8fd9\u51e0\u5bb6"])
    payload["merchant_mentions"] = []
    payload["reference_mentions"] = []
    payload["comparison_targets"] = [{"shop_name": "\u8fd9\u51e0\u5bb6", "reference": "deictic", "source_text": "\u8fd9\u51e0\u5bb6"}]
    payload["ordinal_references"] = []
    monkeypatch.setattr(graph_builder, "call_llm", _llm_ok(payload))
    monkeypatch.setattr(graph_builder, "verify_answer", lambda *_args, **_kwargs: {"passed": True})

    response = run_agent_graph("\u9644\u8fd1\u5e2e\u6211\u5904\u7406\u8fd9\u4e2a", "cmp_llm_focus")

    assert response.debug is not None
    plan = response.debug.execution_plan
    assert plan.get("task_type") == "comparison"
    assert {call.get("facet") for call in plan.get("tool_calls", [])} == {"distance"}


def test_semantic_source_fails_closed_when_using_default_backend():
    """Default backend without injection must fail closed, not fabricate a semantic frame."""
    result = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=call_llm,
    )

    assert result["semantic_frame"] is not None
    assert result["semantic_source"] == "diagnostic_rules"
    assert result["llm_backend"] != ""


def test_semantic_source_marks_real_llm_when_real_backend_injected():
    result = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=_llm_ok(_recommendation_payload(coupon=False, open_now=False)),
    )

    assert result["semantic_source"] == "real_llm"
    assert result["llm_backend"] == "real_llm"


def test_semantic_source_returns_repair_hints_on_llm_failure():
    result = parse_semantic_frame(
        "\u9644\u8fd1\u63a8\u8350\u706b\u9505",
        "local_life",
        llm_call=_llm_fail("LLM_TIMEOUT"),
    )

    assert result["semantic_frame"] is not None
    assert result["semantic_source"] == "diagnostic_rules"
    assert result["fallback_reason"] == "LLM_TIMEOUT"
    assert result["semantic_repair_hints"]
