"""Bootstrap-friendly OpenAI client factory for Responses API usage."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from learning_agent_service.config.settings_impl import OpenAISettings

from .errors import InfrastructureConfigurationError, require_dependency

try:
    from openai import APIStatusError, AuthenticationError, OpenAI, PermissionDeniedError
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    OpenAI = None
    APIStatusError = None
    AuthenticationError = None
    PermissionDeniedError = None


@dataclass(frozen=True)
class OpenAIRuntime:
    """Holds the shared OpenAI client and the default Responses model name."""

    client: Any
    default_model: str


class _FailoverResourceProxy:
    def __init__(self, parent: FailoverOpenAIClient, resource_name: str) -> None:
        self._parent = parent
        self._resource_name = resource_name

    def __getattr__(self, method_name: str):
        def _wrapped(*args, **kwargs):
            return self._parent._invoke(self._resource_name, method_name, *args, **kwargs)

        return _wrapped


class _FailoverStreamManager:
    def __init__(self, parent: FailoverOpenAIClient, resource_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._parent = parent
        self._resource_name = resource_name
        self._args = args
        self._kwargs = kwargs
        self._active_manager = None

    def __enter__(self):
        last_error: Exception | None = None
        for index, client in self._parent.iter_clients():
            try:
                resource = getattr(client, self._resource_name)
                manager = resource.stream(*self._args, **self._kwargs)
                stream = manager.__enter__()
            except Exception as exc:
                if self._parent._is_fallback_error(exc):
                    last_error = exc
                    continue
                raise
            self._parent._set_active_index(index)
            self._active_manager = manager
            return stream

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI runtime does not expose a usable stream manager")

    def __exit__(self, exc_type, exc, tb):
        if self._active_manager is None:
            return False
        return self._active_manager.__exit__(exc_type, exc, tb)


class FailoverOpenAIClient:
    def __init__(self, clients: list[Any]) -> None:
        self._clients = list(clients)
        self._active_index = 0

    def iter_clients(self):
        if not self._clients:
            return
        start = min(self._active_index, len(self._clients) - 1)
        for offset in range(len(self._clients)):
            index = (start + offset) % len(self._clients)
            yield index, self._clients[index]

    def _set_active_index(self, index: int) -> None:
        self._active_index = max(0, min(index, len(self._clients) - 1))

    def _is_fallback_error(self, exc: Exception) -> bool:
        if AuthenticationError is not None and isinstance(exc, AuthenticationError):
            return True
        if PermissionDeniedError is not None and isinstance(exc, PermissionDeniedError):
            return True
        if APIStatusError is not None and isinstance(exc, APIStatusError):
            status_code = getattr(exc, "status_code", None)
            return status_code in {401, 403}
        return False

    def _invoke(self, resource_name: str, method_name: str, *args, **kwargs):
        last_error: Exception | None = None
        for index, client in self.iter_clients():
            resource = getattr(client, resource_name, None)
            method = getattr(resource, method_name, None) if resource is not None else None
            if method is None:
                continue
            try:
                if resource_name == "responses" and method_name == "stream":
                    return _FailoverStreamManager(self, resource_name, args, kwargs)
                result = method(*args, **kwargs)
            except Exception as exc:
                if self._is_fallback_error(exc):
                    last_error = exc
                    continue
                raise
            self._set_active_index(index)
            return result
        if last_error is not None:
            raise last_error
        if resource_name == "responses" and method_name == "create":
            return SimpleNamespace(output_text="{}")
        raise RuntimeError(f"OpenAI runtime does not expose {resource_name}.{method_name}")

    @property
    def responses(self):
        return _FailoverResourceProxy(self, "responses")

    @property
    def embeddings(self):
        return _FailoverResourceProxy(self, "embeddings")

    def __getattr__(self, name: str):
        if not self._clients:
            raise AttributeError(name)
        return getattr(self._clients[self._active_index], name)

import httpx


class OpenRouterFilterTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            # We wrap the response stream to filter out "response.keep_alive" events
            original_stream = response.stream
            
            def filtered_stream():
                buffer = b""
                for chunk in original_stream:
                    buffer += chunk
                    # SSE events are separated by double newlines: \n\n or \r\n\r\n
                    while b"\n\n" in buffer or b"\r\n\r\n" in buffer:
                        # Find the boundary
                        boundary = b"\r\n\r\n" if b"\r\n\r\n" in buffer else b"\n\n"
                        parts = buffer.split(boundary, 1)
                        event_block = parts[0]
                        buffer = parts[1]
                        
                        # Check if this event block contains "response.keep_alive"
                        if b"response.keep_alive" in event_block:
                            # Skip this event block
                            continue
                        
                        # Yield the original block with boundary
                        yield event_block + boundary
                if buffer:
                    if b"response.keep_alive" not in buffer:
                        yield buffer
                        
            class FilteredByteStream(httpx.SyncByteStream):
                def __iter__(self):
                    return filtered_stream()
                def close(self):
                    original_stream.close()

            response.stream = FilteredByteStream()
        return response


def build_openai_runtime(settings: OpenAISettings) -> OpenAIRuntime:
    """Create the OpenAI client used by higher-level orchestration layers."""

    if OpenAI is None:
        require_dependency("openai", "model access")
    api_keys = list(getattr(settings, "api_key_candidates", None) or [])
    if not api_keys and settings.api_key:
        api_keys = [settings.api_key]
    if not api_keys:
        raise InfrastructureConfigurationError(
            "OPENAI_API_KEY or LEARNING_AGENT_OPENAI_API_KEY must be configured before enabling model access"
        )
    clients = [
        OpenAI(
            api_key=api_key,
            base_url=settings.base_url,
            organization=settings.organization,
            project=settings.project,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            http_client=httpx.Client(transport=OpenRouterFilterTransport()),
        )
        for api_key in api_keys
    ]
    return OpenAIRuntime(client=FailoverOpenAIClient(clients), default_model=settings.responses_model)
