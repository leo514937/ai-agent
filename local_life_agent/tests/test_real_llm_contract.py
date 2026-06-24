"""Contract tests for real LLM backend integration.

These tests validate that the LLM client respects the configuration
contract — they do NOT call an actual LLM.  They verify wiring,
error handling, and metadata propagation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from ..config import LLM_BACKEND, LLM_ENABLED
from ..domain.enums import TopIntent
from ..domain.schemas import SemanticFrame
from ..llm.client import call_llm, clear_llm_backend, has_llm_backend, set_llm_backend
from ..semantic.intent_parser import parse_semantic_frame
from ..semantic.slot_extractor import extract_slots


# ====================================================================
# Helpers
# ====================================================================

def _llm_ok(payload: dict) -> Any:
    """Return a callable that simulates a successful LLM response."""
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


def _llm_fail(error_code: str = "LLM_TIMEOUT") -> Any:
    """Return a callable that simulates an LLM failure."""
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


# ====================================================================
# B2-1: Backend kind propagation
# ====================================================================

class TestBackendKindDetection:
    """call_llm must report the correct backend_kind in its result."""

    def test_default_backend_is_rule_based(self):
        """No injection, no explicit backend → backend_kind = rule_based."""
        clear_llm_backend()
        result = call_llm("附近推荐火锅", "test prompt")
        assert result.get("llm_backend") == "rule_based"

    def test_injected_fake_backend(self):
        """set_llm_backend(fake_fn) → backend_kind falls through to real_llm
        (the injected function has no llm_backend attribute)."""
        def fake_backend(*_args, **_kwargs) -> dict:
            return {"ok": True, "content": {"top_intent": "local_life"}, "raw": "{}"}
        set_llm_backend(fake_backend)
        try:
            result = call_llm("附近推荐火锅", "test prompt")
            # fake_backend has no llm_backend attr → defaults to real_llm
            assert result.get("llm_backend") == "real_llm"
        finally:
            clear_llm_backend()

    def test_explicit_backend_param(self):
        """Passing backend= explicitly should be preferred."""

        def custom_backend(*_args, **_kwargs) -> dict:
            return {"content": {"top_intent": "local_life", "confidence": 0.9}}

        result = call_llm("附近推荐火锅", "test prompt", backend=custom_backend)
        # custom_backend has no llm_backend attr → defaults to real_llm
        assert result.get("llm_backend") == "real_llm"


# ====================================================================
# B2-1: semantic_source propagation from parse_semantic_frame
# ====================================================================

class TestSemanticSourcePropagation:
    """The semantic_source field must reflect the actual backend used."""

    def test_rule_based_source_when_no_backend(self):
        """No injection → semantic_source = rule_based."""
        clear_llm_backend()
        result = parse_semantic_frame(
            "附近推荐火锅",
            "local_life",
            llm_call=call_llm,
        )
        assert result["semantic_source"] == "rule_based"
        assert result["llm_backend"] == "rule_based"
        # llm_called is True because the call_llm pipeline was invoked
        # (even though the underlying backend is rule-based).
        assert result["llm_called"] is True

    def test_fake_llm_source_when_injected(self):
        """Injected fake with llm_backend='fake' → semantic_source = fake_llm."""

        def fake_with_attr(*_args, **_kwargs) -> dict:
            return {
                "ok": True,
                "content": _recommendation_payload(),
                "confidence": 0.95,
                "raw": "{}",
                "error_code": "",
                "error_message": "",
                "llm_backend": "fake",
            }

        result = parse_semantic_frame(
            "附近推荐火锅",
            "local_life",
            llm_call=fake_with_attr,
        )
        assert result["semantic_source"] == "fake_llm"
        assert result["llm_backend"] == "fake"

    def test_real_llm_source_when_external_backend(self):
        """External backend (no llm_backend attr) → semantic_source = real_llm."""
        result = parse_semantic_frame(
            "附近推荐火锅",
            "local_life",
            llm_call=_llm_ok(_recommendation_payload()),
        )
        assert result["semantic_source"] == "real_llm"
        assert result["llm_backend"] == "real_llm"
        assert result["llm_called"] is True

    def test_fallback_rules_on_failure(self):
        """LLM failure → semantic_source = fallback_rules."""
        result = parse_semantic_frame(
            "附近推荐火锅",
            "local_life",
            llm_call=_llm_fail("LLM_TIMEOUT"),
        )
        assert result["semantic_source"] == "fallback_rules"
        assert result["fallback_reason"] == "LLM_TIMEOUT"
        assert result["llm_called"] is True


# ====================================================================
# B2-2: Contract — config shape
# ====================================================================

class TestConfigContract:
    """LLM_BACKEND and related config must exist with defaults."""

    def test_backend_config_default(self):
        """Default value reflects current config (already initialized to real_llm)."""
        assert LLM_BACKEND in ("rule_based", "real_llm")

    def test_llm_enabled_default(self):
        """LLM_ENABLED must default based on LLM_BACKEND."""
        assert LLM_ENABLED is (LLM_BACKEND != "rule_based")


# ====================================================================
# B2-3: Verbalizer contract — metadata tracking
# ====================================================================

class TestAnswerMetadataContract:
    """generate_answer must produce answer_source metadata."""

    def test_template_source_when_verbalizer_disabled(self):
        """When ENABLE_LLM_VERBALIZER=False, answer_source = template."""
        from ..answer.generator import generate_answer

        with patch("local_life_agent.config.ENABLE_LLM_VERBALIZER", False):
            metadata: dict[str, Any] = {}
            res = generate_answer(
                {"answer_type": "single_shop"},
                {"ranking_snapshot": {"status": "ok", "shop_name": "川味轩"}},
                metadata_out=metadata,
            )
            assert res == "川味轩信息已确认。"
            assert metadata.get("answer_source") == "template"
            assert metadata.get("llm_verbalizer_enabled") is False
            assert metadata.get("llm_used") is False

    def test_verbalizer_source_when_llm_succeeds(self):
        """Verbalizer ON + LLM success → answer_source = llm_verbalizer."""

        def mock_llm(*_args, **_kwargs) -> dict:
            return {
                "ok": True,
                "content": {"natural_response": "川味轩的详细情况已查明！"},
                "confidence": 0.95,
                "raw": "{}",
                "error_code": "",
                "error_message": "",
            }

        from ..answer.generator import generate_answer

        with patch("local_life_agent.config.ENABLE_LLM_VERBALIZER", True):
            metadata: dict[str, Any] = {}
            res = generate_answer(
                {"answer_type": "single_shop"},
                {"ranking_snapshot": {"status": "ok", "shop_name": "川味轩"}},
                llm_client=mock_llm,
                metadata_out=metadata,
            )
            assert metadata.get("answer_source") == "llm_verbalizer"
            assert metadata.get("llm_used") is True

    def test_template_when_verbalizer_returns_template(self):
        """Verbalizer ON but output == template → answer_source 保持 template。"""
        from ..answer.generator import generate_answer

        with patch("local_life_agent.config.ENABLE_LLM_VERBALIZER", True):
            metadata: dict[str, Any] = {}
            _ = generate_answer(
                {"answer_type": "single_shop"},
                {"ranking_snapshot": {"status": "ok", "shop_name": "川味轩"}},
                llm_client=None,  # falls through to default backend
                metadata_out=metadata,
            )
            assert metadata.get("answer_source") == "template"


# ====================================================================
# B2-4: Reference resolver — raw-text dedup contract
# ====================================================================

class TestReferenceResolverContract:
    """resolve_references must avoid raw-text duplication when
    the semantic frame has explicit reference fields."""

    def test_semantic_frame_prevents_raw_text_fallback(self):
        """Frame with ordinal_refs → no raw-text re-parsing even when
        resolution fails."""
        from ..target.reference_resolver import resolve_references

        frame = SemanticFrame(
            top_intent=TopIntent.local_life,
            ordinal_references=["第一家"],  # semantic frame has refs
            deictic_references=[],
        )
        result = resolve_references(
            "第一家",  # would parse successfully from raw text
            None,
            semantic_frame=frame,
        )
        # Without session state the ordinal "第一家" overflows
        # (out_of_range), but the point is the resolution_source must
        # be semantic_frame — no raw-text re-parsing occurred.
        assert result.get("resolution_source") == "semantic_frame"
        assert result.get("status") in ("unresolved", "out_of_range")

    def test_raw_text_fallback_when_no_frame_refs(self):
        """Frame without reference fields → raw-text fallback active."""
        from ..target.reference_resolver import resolve_references

        frame = SemanticFrame(
            top_intent=TopIntent.local_life,
            ordinal_references=[],
            deictic_references=[],
        )
        result = resolve_references(
            "第一家",
            None,
            semantic_frame=frame,
        )
        assert result.get("resolution_source") == "raw_text"

    def test_semantic_frame_refs_are_consumed_first(self):
        """Frame ordinal_refs take priority over raw text."""
        from ..target.reference_resolver import resolve_references
        from ..domain.state import SessionState

        frame = SemanticFrame(
            top_intent=TopIntent.local_life,
            ordinal_references=["第一家"],
            deictic_references=[],
        )
        session = SessionState(last_recommendation_list=[
            {"shop_id": "s1", "shop_name": "ShopA"},
            {"shop_id": "s2", "shop_name": "ShopB"},
        ])
        result = resolve_references(
            "第一家",
            session,
            semantic_frame=frame,
        )
        assert result.get("resolution_source") == "semantic_frame"
        assert result.get("status") == "resolved"
        assert result.get("target", {}).get("shop_id") == "s1"


# ====================================================================
# Shared payload builder
# ====================================================================

def _recommendation_payload(**overrides: Any) -> dict:
    payload = {
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
        "soft_preferences": {},
        "ranking_signals": {"query_terms": ["火锅"]},
        "follow_up": None,
        "confidence": 0.95,
        "need_context": False,
    }
    payload.update(overrides)
    return payload
