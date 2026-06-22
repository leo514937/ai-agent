from __future__ import annotations

import os
import pytest

from local_life_agent import config
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import call_llm, set_llm_backend, clear_llm_backend
from local_life_agent.semantic.intent_parser import parse_semantic_frame

# Check if real API key is configured (config file or env var)
has_api_key = bool(config.load_llm_api_key())

pytestmark = pytest.mark.skipif(
    True,
    reason="Real LLM integration tests require manual enable: set LLM_API_KEY and flip to False"
)


def test_openai_backend_direct_call():
    # Instantiate backend with config or overrides
    backend = OpenAICompatibleBackend(timeout_seconds=45)
    
    # Simple direct invocation check
    prompt = "Reply with exactly the word: 'Hello'"
    response = backend(prompt=prompt, system_prompt="You are a helpful assistant.", temperature=0.0, timeout_ms=45000)
    
    assert response is not None
    assert "hello" in response.get("content", "").lower()


def test_openai_backend_integration_via_call_llm(monkeypatch):
    monkeypatch.setattr(config, "REAL_LLM_TIMEOUT_SECONDS", 45)
    monkeypatch.setattr(config, "LLM_TIMEOUT_MS", 45000)

    backend = OpenAICompatibleBackend(timeout_seconds=45)
    set_llm_backend(backend)
    
    try:
        # Prompt designed to look like intent parser payload
        prompt = (
            "Determine the user's intent. Input text: '附近推荐火锅'.\n"
            "Return a JSON object with: 'top_intent': 'local_life'."
        )
        
        result = call_llm(
            prompt=prompt,
            system_prompt="You must output only valid JSON.",
            temperature=0.0,
            timeout_ms=45000
        )
        
        assert result.get("ok") is True
        assert result.get("llm_backend") == backend.llm_backend
        
        # Verify parse_semantic_frame output metadata
        frame = parse_semantic_frame("附近推荐火锅", "local_life", llm_call=call_llm)
        
        assert frame["semantic_source"] == "real_llm"
        assert frame["llm_backend"] == backend.llm_backend
        assert frame["llm_called"] is True
        assert not frame["fallback_reason"]
        
    finally:
        clear_llm_backend()
