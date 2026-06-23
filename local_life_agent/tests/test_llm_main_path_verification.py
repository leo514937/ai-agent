"""LLM main path authenticity verification.

Ensures the real LLM path is exercised, not fallback rules,
by using a SpyRealLLMBackend + Poison Fallback combination.
"""

from __future__ import annotations

from typing import Any

import pytest

from local_life_agent.agent import run_agent_graph
from local_life_agent.domain.state import SessionState
from local_life_agent.engine import graph_builder
from local_life_agent.session.store import get_session_store, reset_session_store

from .conftest import SpyRealLLMBackend


# ---- Shared helpers ----

SHOP_A = {"shop_id": "shop_sc_05", "shop_name": "川味轩(知春路店)"}
SHOP_B = {"shop_id": "shop_007", "shop_name": "海底捞(牡丹园店)"}
SHOP_C = {"shop_id": "shop_sc_01", "shop_name": "海底捞火锅(水晶城购物中心店)"}
SHOP_D = {"shop_id": "shop_sc_04", "shop_name": "张记家常菜(北邮店)"}


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    reset_session_store()
    yield
    reset_session_store()


def _assert_llm_path_taken(response: Any, spy: SpyRealLLMBackend) -> None:
    """Assert that the LLM path was taken, not fallback."""
    assert spy.called, "SpyRealLLMBackend was never called — LLM path not exercised"
    assert response.debug is not None
    semantic_source = response.debug.semantic_frame.get("semantic_source", "")
    assert semantic_source in ("real_llm", "fake_llm", "spy_real_llm"), (
        f"Expected real_llm/fake_llm/spy_real_llm semantic_source, got {semantic_source!r}"
    )
    assert response.debug.semantic_frame.get("llm_called") is True


# ===================================================================
# Test 1: 推荐 (Recommendation)
# ===================================================================


class TestRecommendationLLMPath:
    """Scenario: '附近推荐火锅' — should use LLM for semantic parsing."""

    def test_recommendation_uses_llm_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recommendation query must go through the LLM path, not fallback."""
        spy = SpyRealLLMBackend()
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        response = run_agent_graph("附近推荐火锅", "verify_reco_llm")

        assert spy.called, "SpyRealLLMBackend was never called"
        assert response.debug is not None
        sf = response.debug.semantic_frame
        assert sf.get("semantic_source") in ("real_llm", "fake_llm", "spy_real_llm"), sf.get("semantic_source")
        assert sf.get("llm_called") is True

    def test_recommendation_with_poison_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With fallback poisoned, recommendation must still work via LLM."""
        spy = SpyRealLLMBackend()
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        # Poison fallback manually for this test
        def _raise(*_a, **_kw):
            raise RuntimeError("FALLBACK_ACTIVATED")

        monkeypatch.setattr(
            "local_life_agent.semantic.intent_parser._fallback_semantic_frame",
            _raise,
        )

        # Should NOT raise because LLM path succeeds
        response = run_agent_graph("附近推荐火锅", "verify_reco_poison")

        assert spy.called
        assert response.debug is not None
        assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "fake_llm", "spy_real_llm")


# ===================================================================
# Test 2: 对比 (Comparison)
# ===================================================================


class TestComparisonLLMPath:
    """Scenario: '对比一下海底捞和川味轩' — comparison via LLM."""

    def test_comparison_uses_llm_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload: dict[str, Any] = {
            "top_intent": "local_life",
            "task_type": "comparison",
            "primary_task": "comparison",
            "facets": [],
            "merchant_mentions": ["海底捞(牡丹园店)", "川味轩(知春路店)"],
            "reference_mentions": [],
            "comparison_targets": [
                {"shop_name": "海底捞(牡丹园店)", "reference": "explicit", "source_text": "海底捞"},
                {"shop_name": "川味轩(知春路店)", "reference": "explicit", "source_text": "川味轩"},
            ],
            "ordinal_references": [],
            "deictic_references": [],
            "focused_facets": [],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {"query_terms": ["海底捞", "川味轩"]},
            "follow_up": None,
            "confidence": 0.96,
            "need_context": False,
        }
        spy = SpyRealLLMBackend(default_payload=payload)
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        response = run_agent_graph("对比一下海底捞和川味轩", "verify_cmp_llm")

        assert spy.called, "LLM path not exercised for comparison"
        assert response.debug is not None
        assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "fake_llm", "spy_real_llm")
        assert response.debug.semantic_frame.get("llm_called") is True

    def test_comparison_with_poison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Poison fallback should not trigger for comparison via LLM."""
        payload: dict[str, Any] = {
            "top_intent": "local_life",
            "task_type": "comparison",
            "primary_task": "comparison",
            "facets": [],
            "merchant_mentions": ["海底捞(牡丹园店)", "川味轩(知春路店)"],
            "reference_mentions": [],
            "comparison_targets": [
                {"shop_name": "海底捞(牡丹园店)", "reference": "explicit", "source_text": "海底捞"},
                {"shop_name": "川味轩(知春路店)", "reference": "explicit", "source_text": "川味轩"},
            ],
            "ordinal_references": [],
            "deictic_references": [],
            "focused_facets": [],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {"query_terms": ["海底捞", "川味轩"]},
            "follow_up": None,
            "confidence": 0.96,
            "need_context": False,
        }
        spy = SpyRealLLMBackend(default_payload=payload)
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        # Poison fallback
        def _raise(*_a, **_kw):
            raise RuntimeError("FALLBACK_ACTIVATED")
        monkeypatch.setattr(
            "local_life_agent.semantic.intent_parser._fallback_semantic_frame",
            _raise,
        )

        response = run_agent_graph("对比一下海底捞和川味轩", "verify_cmp_poison")
        assert spy.called


# ===================================================================
# Test 3: 多轮对话 (Multi-turn with context)
# ===================================================================


class TestMultiTurnLLMPath:
    """Scenario: session has last_recommendation_list, user says '有什么优惠'."""

    def test_multiturn_uses_llm_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_session_store().save(
            "verify_mt_llm",
            SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
        )

        spy = SpyRealLLMBackend()
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        response = run_agent_graph("有什么优惠", "verify_mt_llm")

        assert spy.called
        assert response.debug is not None
        assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "fake_llm", "spy_real_llm")

    def test_multiturn_with_poison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_session_store().save(
            "verify_mt_poison",
            SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
        )

        spy = SpyRealLLMBackend()
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        def _raise(*_a, **_kw):
            raise RuntimeError("FALLBACK_ACTIVATED")
        monkeypatch.setattr(
            "local_life_agent.semantic.intent_parser._fallback_semantic_frame",
            _raise,
        )

        response = run_agent_graph("有什么优惠", "verify_mt_poison")
        assert spy.called


# ===================================================================
# Test 4: 推荐筛选 (Refinement query)
# ===================================================================


class TestRefinementLLMPath:
    """Scenario: '有便宜的推荐吗' as a refinement query."""

    def test_refinement_uses_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = SpyRealLLMBackend()
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        response = run_agent_graph("有便宜的推荐吗", "verify_ref_llm")

        assert spy.called
        assert response.debug is not None
        assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "fake_llm", "spy_real_llm")

    def test_refinement_with_poison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = SpyRealLLMBackend()
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        def _raise(*_a, **_kw):
            raise RuntimeError("FALLBACK_ACTIVATED")
        monkeypatch.setattr(
            "local_life_agent.semantic.intent_parser._fallback_semantic_frame",
            _raise,
        )

        response = run_agent_graph("有便宜的推荐吗", "verify_ref_poison")
        assert spy.called


# ===================================================================
# Test 5: 这家和海底捞比呢 (Deictic + Explicit Comparison)
# ===================================================================


class TestDeicticComparisonLLMPath:
    """Scenario: '这家和海底捞比呢' — deictic reference + explicit comparison."""

    def test_deictic_comparison_uses_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_session_store().save(
            "verify_deictic_llm",
            SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
        )

        payload: dict[str, Any] = {
            "top_intent": "local_life",
            "task_type": "comparison",
            "primary_task": "comparison",
            "facets": [],
            "merchant_mentions": ["海底捞(牡丹园店)"],
            "reference_mentions": ["这家"],
            "comparison_targets": [
                {"shop_name": "这家", "reference": "deictic", "source_text": "这家"},
                {"shop_name": "海底捞(牡丹园店)", "reference": "explicit", "source_text": "海底捞"},
            ],
            "ordinal_references": [],
            "deictic_references": ["这家"],
            "focused_facets": [],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {"query_terms": ["海底捞"]},
            "follow_up": None,
            "confidence": 0.95,
            "need_context": False,
        }
        spy = SpyRealLLMBackend(default_payload=payload)
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        response = run_agent_graph("这家和海底捞比呢", "verify_deictic_llm")

        assert spy.called
        assert response.debug is not None
        assert response.debug.semantic_frame.get("semantic_source") in ("real_llm", "fake_llm", "spy_real_llm")

    def test_deictic_comparison_with_poison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_session_store().save(
            "verify_deictic_poison",
            SessionState(last_recommendation_list=[SHOP_A, SHOP_B, SHOP_C]),
        )

        payload: dict[str, Any] = {
            "top_intent": "local_life",
            "task_type": "comparison",
            "primary_task": "comparison",
            "facets": [],
            "merchant_mentions": ["海底捞(牡丹园店)"],
            "reference_mentions": ["这家"],
            "comparison_targets": [
                {"shop_name": "这家", "reference": "deictic", "source_text": "这家"},
                {"shop_name": "海底捞(牡丹园店)", "reference": "explicit", "source_text": "海底捞"},
            ],
            "ordinal_references": [],
            "deictic_references": ["这家"],
            "focused_facets": [],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {"query_terms": ["海底捞"]},
            "follow_up": None,
            "confidence": 0.95,
            "need_context": False,
        }
        spy = SpyRealLLMBackend(default_payload=payload)
        monkeypatch.setattr(graph_builder, "call_llm", spy)

        def _raise(*_a, **_kw):
            raise RuntimeError("FALLBACK_ACTIVATED")
        monkeypatch.setattr(
            "local_life_agent.semantic.intent_parser._fallback_semantic_frame",
            _raise,
        )

        response = run_agent_graph("这家和海底捞比呢", "verify_deictic_poison")
        assert spy.called


# ===================================================================
# LLM Failure → Fallback verification (negative test)
# ===================================================================


def _fail_semantic_only(error_code: str = "LLM_TIMEOUT"):
    """Return a backend that succeeds for intent routing but fails for semantic parsing.

    ``_h_top_intent_router`` and ``_h_semantic_parse`` both receive the same
    injected ``call_llm``.  We distinguish them by checking the prompt content.
    """
    def _call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
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


class TestLLMFailureFallback:
    """When LLM truly fails, the fallback path should produce correct metadata."""

    def test_llm_failure_triggers_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM failure → semantic_source = fallback_rules, fallback_reason set."""
        monkeypatch.setattr(graph_builder, "call_llm", _fail_semantic_only("LLM_TIMEOUT"))

        response = run_agent_graph("附近推荐火锅", "verify_llm_fail")

        assert response.debug is not None
        sf = response.debug.semantic_frame
        assert sf.get("semantic_source") == "fallback_rules", (
            f"Expected fallback_rules, got {sf.get('semantic_source')!r}"
        )
        assert sf.get("fallback_reason") == "LLM_TIMEOUT"
        assert sf.get("llm_called") is True


# ===================================================================
# Real provider integration test (reinforcement)
# ===================================================================


class TestRealLLMProviderContract:
    """Contract check: if a real LLM provider is configured, verify
    the client wiring works end-to-end."""

    def test_call_llm_with_explicit_backend(self) -> None:
        """Explicit backend param must route through the client correctly."""
        from local_life_agent.llm.client import call_llm

        def explicit_backend(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"content": {"top_intent": "local_life", "confidence": 0.9}}

        result = call_llm(
            "附近推荐火锅",
            "test prompt",
            backend=explicit_backend,
        )
        assert result.get("ok") is True
        assert result.get("llm_backend") == "real_llm"

    def test_real_llm_backend_wiring(self) -> None:
        """Verify that set_llm_backend + call_llm propagates backend_kind."""
        from local_life_agent.llm.client import call_llm, set_llm_backend, clear_llm_backend

        def fake_backend(*_a: Any, **_kw: Any) -> dict[str, Any]:
            return {"ok": True, "content": {"top_intent": "local_life"}, "raw": "{}"}

        set_llm_backend(fake_backend)
        try:
            result = call_llm("附近推荐火锅", "test prompt")
            assert result.get("ok") is True
        finally:
            clear_llm_backend()
