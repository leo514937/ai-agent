"""OpenAI compatible backend for call_llm."""

from __future__ import annotations

import os
from typing import Any
import httpx

from .. import config


class OpenAICompatibleBackend:
    """Backend client utilizing an OpenAI-compatible endpoint."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.provider = provider or config.LLM_PROVIDER
        self.model = model or config.LLM_MODEL
        self.endpoint = endpoint or config.LLM_ENDPOINT
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds or config.LLM_TIMEOUT_SECONDS

        # Construct the llm_backend kind identifier
        p = self.provider or "real"
        m = self.model or "model"
        self.llm_backend = f"{p}/{m}"

    def _get_api_key(self) -> str:
        """Resolve API key: constructor arg > config file > env var."""
        if self._api_key:
            return self._api_key
        key = config.load_llm_api_key()
        if key:
            return key
        raise ValueError(
            "LLM API key not found. Set it in config/llm.json (api_key field) "
            "or via the LLM_API_KEY environment variable."
        )

    def __call__(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.0,
        timeout_ms: int = 3000,
    ) -> str:
        api_key = self._get_api_key()

        url = self.endpoint
        if not url:
            # Fallback/default endpoint if empty
            url = "https://api.openai.com/v1/chat/completions"
        elif not (url.endswith("/chat/completions") or url.endswith("/completions")):
            url = url.rstrip("/") + "/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": messages,
            "temperature": temperature,
        }

        # Convert timeout_ms to seconds, fallback to config.REAL_LLM_TIMEOUT_SECONDS
        timeout_sec = (timeout_ms / 1000.0) if timeout_ms else float(self.timeout_seconds)

        with httpx.Client(timeout=timeout_sec) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            res_data = response.json()
            choices = res_data.get("choices", [])
            if not choices:
                raise RuntimeError(f"OpenAI compatible response missing 'choices': {res_data}")
            content = choices[0].get("message", {}).get("content", "")
            return content
