"""Tool call gateway - unified tool call entry point."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from .. import config
from ..observability.file_logger import get_python_service_logger, log_kv
from ..observability.metrics import record_tool_call_metric
from .circuit_breaker import get_circuit_breaker_manager
from .executor import (
    JavaToolExecutor,
    ToolExecutor,
    build_tool_executor,
)
from .normalizer import (
    normalize_circuit_open_result,
    normalize_tool_result,
    normalize_validation_error,
)
from .registry import get_registry


class ToolCallGateway:
    """Unified tool call gateway."""

    def __init__(self, executor: ToolExecutor | None = None):
        self._registry = get_registry()
        self._cb_manager = get_circuit_breaker_manager()
        if executor is not None:
            self._executor = executor
        else:
            self._executor = build_tool_executor()

    async def call(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Execute a single tool call through the full Gateway pipeline."""
        _start = time.monotonic()

        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            return normalize_validation_error(
                tool_name,
                kwargs,
                [f"Tool '{tool_name}' is not registered"],
            )

        errors = self._registry.validate_args(tool_name, kwargs)
        if errors:
            return normalize_validation_error(tool_name, kwargs, errors)

        cb_enabled = tool_def.get("circuit_breaker_enabled", False)
        if cb_enabled:
            threshold = tool_def.get("threshold", 5)
            recovery_ms = tool_def.get("recovery_timeout_ms", 30000)
            if self._cb_manager.is_open(tool_name, threshold, recovery_ms):
                return normalize_circuit_open_result(tool_name, kwargs)

        max_retries = tool_def.get("max_retries", 2)

        from .retry import retry_with_backoff as _retry

        try:
            result = await _retry(
                call_fn=self._run_tool,
                tool_name=tool_name,
                kwargs={"tool_def": tool_def, "kwargs": kwargs},
                max_attempts=max_retries + 1,
            )
        except Exception as exc:
            backend = self._executor.backend_source if hasattr(self._executor, "backend_source") else "unknown"
            result = {
                "call_id": kwargs.get("call_id", ""),
                "shop_id": kwargs.get("shop_id", ""),
                "tool_name": tool_name,
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": str(exc),
                "source": backend,
                "tool_backend": backend,
                "backend_source": backend,
                "degraded": True,
            }

        if cb_enabled:
            if result.get("success", False):
                self._cb_manager.record_success(tool_name)
            else:
                self._cb_manager.record_failure(tool_name)

        _duration = (time.monotonic() - _start) * 1000.0
        _success = bool(result.get("success", False))
        record_tool_call_metric(tool_name, _duration, _success)

        return normalize_tool_result(tool_name, result)

    async def _run_tool(self, tool_def: dict, kwargs: dict) -> dict:
        raw = await self._executor.execute(tool_def, kwargs)
        if raw.success:
            if raw.data is None:
                status = "empty"
            elif isinstance(raw.data, (list, dict)) and not raw.data:
                status = "empty"
            else:
                status = "ok"
        else:
            if raw.error_code in {"TOOL_NOT_REGISTERED", "TOOL_UNSUPPORTED", "UNSUPPORTED"}:
                status = "unsupported"
            else:
                status = "failed"
        return {
            "call_id": kwargs.get("call_id", ""),
            "shop_id": kwargs.get("shop_id", ""),
            "tool_name": tool_def["name"],
            "success": raw.success,
            "result_status": status,
            "data": raw.data,
            "error_code": raw.error_code,
            "error_message": raw.error_message,
            "source": raw.backend_source,
            "tool_backend": raw.backend_source,
            "degraded": False,
            "backend_source": raw.backend_source,
            "fallback_from": raw.fallback_from,
            "http_status": raw.http_status,
            "endpoint": raw.endpoint,
        }


@dataclass
class _BatchToolCall:
    call_id: str
    tool_name: str
    kwargs: dict[str, Any]
    required: bool
    timeout_ms: int
    max_parallelism: int


class BatchToolExecutor:
    """Execute a batch of tool calls concurrently with a shared deadline."""

    def __init__(
        self,
        *,
        deadline_ms: int | None = None,
        max_concurrency: int | None = None,
        call_fn: Any | None = None,
        backend_source: str | None = None,
    ) -> None:
        self._deadline_ms = deadline_ms or config.DEADLINE_MS
        self._max_concurrency = max_concurrency or config.MAX_CONCURRENCY
        self._call_fn = call_fn or dispatch_tool_call
        self._backend_source = backend_source or config.TOOL_BACKEND

    def _normalize_call(self, call: Any) -> _BatchToolCall:
        if hasattr(call, "model_dump"):
            call = call.model_dump()
        if not isinstance(call, dict):
            call = {}
        return _BatchToolCall(
            call_id=str(call.get("call_id", "") or call.get("tool_name", "")),
            tool_name=str(call.get("tool_name", "")),
            kwargs=dict(call.get("args", {}) or {}),
            required=bool(call.get("required", True)),
            timeout_ms=int(call.get("timeout_ms", config.TOOL_DEFAULT_TIMEOUT_MS)),
            max_parallelism=max(1, int(call.get("max_parallelism", 1) or 1)),
        )

    def _timeout_payload(self, call: _BatchToolCall, message: str) -> dict[str, Any]:
        status = "failed" if call.required else "unknown"
        return {
            "call_id": call.call_id,
            "shop_id": str(call.kwargs.get("shop_id", "")),
            "tool_name": call.tool_name,
            "success": False,
            "result_status": status,
            "data": None,
            "error_code": "TOOL_TIMEOUT",
            "error_message": message,
            "source": self._backend_source,
            "tool_backend": self._backend_source,
            "backend_source": self._backend_source,
            "degraded": not call.required,
            "fallback_from": None,
            "http_status": None,
            "endpoint": None,
        }

    async def _run_one(self, call: _BatchToolCall, semaphore: asyncio.Semaphore, deadline: float) -> tuple[str, dict[str, Any]]:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return call.call_id, self._timeout_payload(call, f"Tool '{call.tool_name}' exceeded batch deadline")

        per_call_timeout = min(remaining, max(0.05, call.timeout_ms / 1000.0))

        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._call_fn, call.tool_name, call.kwargs),
                    timeout=per_call_timeout,
                )
                return call.call_id, result
            except asyncio.TimeoutError:
                return call.call_id, self._timeout_payload(
                    call,
                    f"Tool '{call.tool_name}' timed out after {call.timeout_ms} ms",
                )
            except Exception as exc:  # pragma: no cover - safety net
                status = "failed" if call.required else "unknown"
                return call.call_id, {
                    "call_id": call.call_id,
                    "shop_id": str(call.kwargs.get("shop_id", "")),
                    "tool_name": call.tool_name,
                    "success": False,
                    "result_status": status,
                    "data": None,
                    "error_code": "NETWORK_ERROR",
                    "error_message": str(exc),
                    "source": self._backend_source,
                    "tool_backend": self._backend_source,
                    "backend_source": self._backend_source,
                    "degraded": not call.required,
                    "fallback_from": None,
                    "http_status": None,
                    "endpoint": None,
                }

    async def execute(self, tool_calls: list[Any]) -> dict[str, dict[str, Any]]:
        if not tool_calls:
            return {}

        batch_calls = [self._normalize_call(call) for call in tool_calls]
        semaphore = asyncio.Semaphore(max(1, min(self._max_concurrency, max(c.max_parallelism for c in batch_calls))))
        deadline = time.monotonic() + (self._deadline_ms / 1000.0)

        tasks = [self._run_one(call, semaphore, deadline) for call in batch_calls]
        results: dict[str, dict[str, Any]] = {}

        for call_id, payload in await asyncio.gather(*tasks):
            results[call_id] = payload

        return results

    def execute_sync(self, tool_calls: list[Any]) -> dict[str, dict[str, Any]]:
        return _run_coroutine_sync(self.execute(tool_calls))


_gateway_instance: ToolCallGateway | None = None


def get_gateway() -> ToolCallGateway:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = ToolCallGateway()
    return _gateway_instance


def dispatch_tool_call(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    _tool_logger = get_python_service_logger()
    from ..observability.trace import sanitize_payload as _sanitize
    started_at = time.monotonic()
    call_id = str(kwargs.get("call_id", "") or "")[:40]
    # Log tool entry with key args (sanitized, truncated)
    safe_args = _sanitize(kwargs)
    safe_args = {k: v for k, v in safe_args.items() if k not in ("call_id",)}
    log_kv(
        _tool_logger,
        logging.INFO,
        "[TOOL_CALL]",
        tone="tool",
        tool_name=tool_name,
        call_id=call_id,
        args=safe_args,
    )
    result = _run_coroutine_sync(get_gateway().call(tool_name, kwargs))
    success = bool(result.get("success", False))
    status = str(result.get("result_status", "") or "")
    elapsed_ms = int((time.monotonic() - started_at) * 1000.0)
    data = result.get("data")
    if isinstance(data, dict):
        data_size = len(data)
    elif isinstance(data, list):
        data_size = len(data)
    elif data is None:
        data_size = 0
    else:
        data_size = 1
    log_kv(
        _tool_logger,
        logging.INFO if success else logging.WARNING,
        "[TOOL_RESULT]",
        tone="tool" if success else "warn",
        tool_name=tool_name,
        call_id=call_id,
        success=success,
        status=status,
        elapsed_ms=elapsed_ms,
        backend=result.get("backend_source", "") or result.get("tool_backend", ""),
        data_size=data_size,
        error_code=result.get("error_code", ""),
        error_message=result.get("error_message", ""),
        data_preview=data,
    )
    return result


def _run_coroutine_sync(coro: Any) -> Any:
    """Run a coroutine in a synchronous context, reusing a running event loop if present."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply(loop)
        return loop.run_until_complete(coro)
    else:
        return asyncio.run(coro)

