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
    not has_api_key,
    reason="Real LLM integration tests require an API key in config/llm.json or LLM_API_KEY env var"
)


def test_openai_backend_direct_call():
    # Instantiate backend with config or overrides
    backend = OpenAICompatibleBackend()
    
    # Simple direct invocation check
    prompt = "Reply with exactly the word: 'Hello'"
    response = backend(prompt=prompt, system_prompt="You are a helpful assistant.", temperature=0.0)
    
    assert response is not None
    assert "hello" in response.lower()


def test_openai_backend_integration_via_call_llm():
    backend = OpenAICompatibleBackend()
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
            temperature=0.0
        )
        
        assert result.get("ok") is True
        assert result.get("llm_backend") == backend.llm_backend
        
        # Verify parse_semantic_frame output metadata
        frame = parse_semantic_frame("附近推荐火锅", "local_life")
        
        assert frame["semantic_source"] == "real_llm"
        assert frame["llm_backend"] == backend.llm_backend
        assert frame["llm_called"] is True
        assert frame["fallback_reason"] is None
        
    finally:
        clear_llm_backend()
