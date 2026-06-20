"""LLM client abstraction layer.

Provides a uniform interface for LLM calls with timeout, retry,
and confidence threshold enforcement.
"""


def call_llm(prompt: str, system_prompt: str = "", timeout_ms: int = 3000) -> dict:
    """Send a prompt to the LLM and return the parsed response.

    Args:
        prompt: User-facing prompt content.
        system_prompt: Optional system-level instructions.
        timeout_ms: Max wait time in milliseconds.

    Returns:
        Dict with keys: content (str), confidence (float), raw (str).
    """
    raise NotImplementedError("LLM client not yet implemented")
