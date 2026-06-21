"""Shared test fixtures for LLM main path verification."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

LLM_SENTINEL_PREFIX = "LLM_SENTINEL_"


class SpyRealLLMBackend:
    """Spy that records LLM calls and returns sentinel-marked responses.

    Proves the real LLM path was taken (not fallback) by embedding a
    unique sentinel ID in the response content.  Compatible with both
    ``set_llm_backend()`` and ``monkeypatch.setattr(graph_builder, "call_llm", ...)``.
    """

    def __init__(self, default_payload: dict[str, Any] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.sentinel_id = f"{LLM_SENTINEL_PREFIX}{uuid.uuid4().hex[:8].upper()}"
        self._default_payload = dict(default_payload or {
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
        })

    def __call__(self, prompt: str = "", system_prompt: str = "", timeout_ms: int = 3000, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "timeout_ms": timeout_ms,
            "kwargs": kwargs,
        })
        sentinel_content = self.sentinel_id
        raw_payload = json.dumps(
            {**self._default_payload, "_sentinel": sentinel_content},
            ensure_ascii=False,
        )
        return {
            "ok": True,
            "content": dict(self._default_payload),
            "confidence": 0.95,
            "raw": raw_payload,
            "error_code": "",
            "error_message": "",
            "llm_backend": "real_llm",
            "attempts": 1,
            "temperature": kwargs.get("temperature", 0.0),
            "timeout_ms": timeout_ms,
        }

    @property
    def called(self) -> bool:
        return len(self.calls) > 0

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def reset(self) -> None:
        self.calls.clear()


# ---- Fixtures ----

@pytest.fixture
def spy_backend() -> SpyRealLLMBackend:
    """Create a fresh SpyRealLLMBackend for each test."""
    return SpyRealLLMBackend()


@pytest.fixture
def poison_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every known fallback path with a function that raises.

    Use alongside ``spy_backend`` / ``monkeypatch.setattr(graph_builder, "call_llm", spy)``.
    If the LLM call fails and fallback is triggered, the test crashes instead
    of silently passing.
    """
    def _poison(*_args: Any, **_kwargs: Any) -> Any:
        msg = "FALLBACK_ACTIVATED - test would pass falsely through fallback"
        raise RuntimeError(msg)

    # intent_parser fallbacks
    monkeypatch.setattr(
        "local_life_agent.semantic.intent_parser._fallback_semantic_frame",
        _poison,
    )
    monkeypatch.setattr(
        "local_life_agent.semantic.intent_parser._fallback_intent",
        _poison,
    )

    # slot_extractor fallbacks
    monkeypatch.setattr(
        "local_life_agent.semantic.slot_extractor.extract_slots",
        _poison,
    )
    monkeypatch.setattr(
        "local_life_agent.semantic.slot_extractor._extract_deictic",
        _poison,
    )
