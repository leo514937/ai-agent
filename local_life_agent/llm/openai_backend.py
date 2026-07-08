"""OpenAI compatible backend for call_llm."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from uuid import uuid4
from typing import Any
import httpx
import requests

from .. import config
from ..observability.file_logger import current_log_context, get_python_service_logger, log_kv
from ..observability.trace import record_span, sanitize_payload
from ..streaming.runtime import raise_if_turn_cancelled

_LOGGER = get_python_service_logger()


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
        self._client: httpx.Client | None = None

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

    def _get_client(self) -> httpx.Client:
        """Reuse one HTTP client so connection pooling can work across calls."""
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def close(self) -> None:
        """Release the underlying HTTP client explicitly when the backend is discarded."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __call__(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
        timeout_ms: int = 3000,
        stream_handler: Any | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        context = current_log_context()
        llm_call_id = str(metadata.get("llm_call_id") or context.get("llm_call_id") or f"llm_{uuid4().hex[:12]}")
        node_name = str(metadata.get("node_name") or context.get("node") or context.get("node_name") or "")
        workflow_name = str(metadata.get("workflow_name") or context.get("workflow_name") or "")
        semantic_task_type = str(metadata.get("semantic_task_type") or context.get("semantic_task_type") or context.get("task_type") or "")
        retry_count = int(metadata.get("retry_count", 0) or 0)
        attempt_index = int(metadata.get("attempt_index", 1) or 1)
        prompt_version = str(metadata.get("prompt_version") or context.get("prompt_version") or "")
        prompt_hash = str(metadata.get("user_prompt_hash") or _hash_text(prompt))
        system_prompt_hash = str(metadata.get("system_prompt_hash") or _hash_text(system_prompt))
        temperature_source = str(
            metadata.get("temperature_source")
            or ("default_config" if temperature is None else "call_override")
        )
        effective_temperature = 0.0 if temperature is None else float(temperature)
        streaming = bool(stream_handler is not None)
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
            "temperature": effective_temperature,
            "max_tokens": 1024,
        }
        if stream_handler is not None:
            payload["stream"] = True

        # Convert timeout_ms to seconds, fallback to config.REAL_LLM_TIMEOUT_SECONDS
        timeout_sec = (timeout_ms / 1000.0) if timeout_ms else float(self.timeout_seconds)
        call_metadata = {
            "llm_call_id": llm_call_id,
            "session_id": context.get("session_id", ""),
            "turn_id": context.get("turn_id", ""),
            "node_name": node_name,
            "workflow_name": workflow_name,
            "semantic_task_type": semantic_task_type,
            "provider": self.provider,
            "model": self.model,
            "backend_name": self.llm_backend,
            "temperature": effective_temperature if temperature is not None else None,
            "temperature_source": temperature_source,
            "top_p": metadata.get("top_p"),
            "max_tokens": payload.get("max_tokens"),
            "presence_penalty": metadata.get("presence_penalty"),
            "frequency_penalty": metadata.get("frequency_penalty"),
            "seed": metadata.get("seed"),
            "timeout_ms": timeout_ms,
            "retry_count": retry_count,
            "streaming": streaming,
            "prompt_version": prompt_version,
            "system_prompt_hash": system_prompt_hash,
            "user_prompt_hash": prompt_hash,
            "status": "started",
            "error_code": "",
            "fallback_reason": "",
        }
        log_kv(
            _LOGGER,
            logging.INFO,
            "[LLM_CALL]",
            tone="llm",
            **call_metadata,
        )

        client = self._get_client()
        try:
            if stream_handler is None:
                response = client.post(url, headers=headers, json=payload, timeout=timeout_sec)
                response.raise_for_status()
                res_data = response.json()
                transport = "httpx"
            else:
                raw_chunks: list[str] = []
                with client.stream("POST", url, headers=headers, json=payload, timeout=timeout_sec) as response:
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
                _emit_llm_error(
                    call_metadata,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    latency_ms=int((time.monotonic() - started_at) * 1000),
                )
                raise
            response = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
            response.raise_for_status()
            res_data = response.json()
            transport = "requests_fallback"

        choices = res_data.get("choices", [])
        if not choices:
            error_message = f"OpenAI compatible response missing 'choices': {res_data}"
            _emit_llm_error(
                call_metadata,
                error_code="LLM_RESPONSE_INVALID",
                error_message=error_message,
                latency_ms=int((time.monotonic() - started_at) * 1000),
            )
            raise RuntimeError(error_message)
        content = choices[0].get("message", {}).get("content", "")
        parsed_content = self._maybe_parse_json_content(content)
        call_metadata["status"] = "success"
        call_metadata["transport"] = transport
        call_metadata["error_code"] = ""
        call_metadata["fallback_reason"] = ""
        call_metadata["latency_ms"] = int((time.monotonic() - started_at) * 1000)
        _emit_llm_span(call_metadata)
        log_kv(
            _LOGGER,
            logging.INFO,
            "[LLM_RESULT]",
            tone="llm",
            **call_metadata,
        )
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


def _hash_text(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _emit_llm_error(call_metadata: dict[str, Any], *, error_code: str, error_message: str, latency_ms: int | None) -> None:
    payload = dict(call_metadata)
    payload.update(
        {
            "status": "failed",
            "error_code": error_code,
            "error_message": error_message,
            "fallback_reason": error_code,
        }
    )
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    _emit_llm_span(payload)
    log_kv(
        _LOGGER,
        logging.WARNING,
        "[LLM_ERROR]",
        tone="warn",
        **payload,
    )


def _emit_llm_span(call_metadata: dict[str, Any]) -> None:
    trace_id = str(current_log_context().get("trace_id", "") or "")
    if not trace_id:
        return
    record_span(
        trace_id,
        "llm_call",
        sanitize_payload(call_metadata),
    )
