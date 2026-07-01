"""OpenAI compatible backend for call_llm."""

from __future__ import annotations

import json
import os
from typing import Any
import httpx
import requests

from .. import config
from ..streaming.runtime import raise_if_turn_cancelled


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
        stream_handler: Any | None = None,
    ) -> dict[str, Any]:
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
            "HTTP-Referer": "http://localhost",
            "X-OpenRouter-Title": "local-life-agent-dev",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 1024,
        }
        if stream_handler is not None:
            payload["stream"] = True

        # Convert timeout_ms to seconds, fallback to config.REAL_LLM_TIMEOUT_SECONDS
        timeout_sec = (timeout_ms / 1000.0) if timeout_ms else float(self.timeout_seconds)

        try:
            with httpx.Client(timeout=timeout_sec) as client:
                if stream_handler is None:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    res_data = response.json()
                    transport = "httpx"
                else:
                    raw_chunks: list[str] = []
                    with client.stream("POST", url, headers=headers, json=payload) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            raise_if_turn_cancelled()
                            if not line:
                                continue
                            if isinstance(line, bytes):
                                line = line.decode("utf-8", errors="ignore")
                            if not str(line).startswith("data:"):
                                continue
                            data = str(line)[5:].strip()
                            if not data or data == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(data)
                            except Exception:
                                continue
                            choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
                            content_delta = delta.get("content", "")
                            if not content_delta:
                                continue
                            raw_chunks.append(str(content_delta))
                            stream_handler(str(content_delta))
                            raise_if_turn_cancelled()
                    res_data = {"choices": [{"message": {"content": "".join(raw_chunks)}}]}
                    transport = "httpx_stream"
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            if not self._should_fallback_to_requests(exc):
                raise
            response = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
            response.raise_for_status()
            res_data = response.json()
            transport = "requests_fallback"

        choices = res_data.get("choices", [])
        if not choices:
            raise RuntimeError(f"OpenAI compatible response missing 'choices': {res_data}")
        content = choices[0].get("message", {}).get("content", "")
        parsed_content = self._maybe_parse_json_content(content)
        return {
            "ok": True,
            "content": parsed_content if parsed_content is not None else content,
            "raw": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str),
            "provider": self.provider,
            "model": self.model,
            "transport": transport,
            "llm_backend": self.llm_backend,
        }

    def _maybe_parse_json_content(self, content: Any) -> dict[str, Any] | None:
        if not isinstance(content, str):
            return None
        try:
            parsed = json.loads(content)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        return self._sanitize_payload(parsed)

    def _should_fallback_to_requests(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "eof occurred in violation of protocol" in message
            or "connecterror" in type(exc).__name__.lower()
            or "remotprotocolerror" in type(exc).__name__.lower()
            or "ssl" in message
        )

    def _sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(payload)
        for key in ("comparison_focus", "primary_task"):
            if key in sanitized and sanitized.get(key) is None:
                sanitized[key] = ""
        return sanitized
