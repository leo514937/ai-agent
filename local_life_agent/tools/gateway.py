"""Tool call gateway — unified tool call entry point.

The Gateway is the **sole** entry point for executing any tool call.
It enforces the following pipeline for every invocation:

  1. Schema validation  — validates args against ToolRegistry input_schema
  2. Circuit breaker    — checks CircuitBreakerManager (OPEN → early return)
  3. Execution          — delegates to ToolExecutor (Mock / HTTP / DB)
  4. Timeout catch      — catches TimeoutError from executor
  5. Retry              — RetryManager with exponential backoff
  6. Normalisation      — normalizer.py converts everything to ToolResult

The caller always receives a normalised ``ToolResult`` dict — no bare
exceptions escape.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .circuit_breaker import get_circuit_breaker_manager
from .executor import MockToolExecutor, ToolExecutor
from .normalizer import (
    normalize_circuit_open_result,
    normalize_tool_result,
    normalize_validation_error,
)
from .registry import get_registry


class ToolCallGateway:
    """Unified tool call gateway.

    Usage::

        gateway = ToolCallGateway()
        result = await gateway.call("search_shops", {"query": "火锅"})
    """

    def __init__(self, executor: ToolExecutor | None = None):
        self._registry = get_registry()
        self._cb_manager = get_circuit_breaker_manager()
        self._executor = executor or MockToolExecutor()

    async def call(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Execute a single tool call through the full Gateway pipeline.

        Args:
            tool_name: Registered tool name.
            kwargs: Tool arguments.

        Returns:
            Normalised ``ToolResult`` dict.  Never raises.
        """
        # ── Step 1: Lookup ──────────────────────────────────────
        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            return normalize_validation_error(
                tool_name, kwargs,
                [f"Tool '{tool_name}' is not registered"],
            )

        # ── Step 2: Schema validation ───────────────────────────
        errors = self._registry.validate_args(tool_name, kwargs)
        if errors:
            return normalize_validation_error(tool_name, kwargs, errors)

        # ── Step 3: Circuit breaker check ───────────────────────
        cb_enabled = tool_def.get("circuit_breaker_enabled", False)
        if cb_enabled:
            threshold = tool_def.get("threshold", 5)
            recovery_ms = tool_def.get("recovery_timeout_ms", 30000)
            if self._cb_manager.is_open(tool_name, threshold, recovery_ms):
                return normalize_circuit_open_result(tool_name, kwargs)

        # ── Step 4: Execute with retry ──────────────────────────
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
            result = {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": str(exc),
                "source": "mock",
                "degraded": True,
            }

        # ── Step 5: Circuit breaker feedback ────────────────────
        if cb_enabled:
            if result.get("success", False):
                self._cb_manager.record_success(tool_name)
            else:
                self._cb_manager.record_failure(tool_name)

        # ── Step 6: Normalise ───────────────────────────────────
        return normalize_tool_result(tool_name, result)

    # ── Internal: single-shot tool execution ────────────────────

    async def _run_tool(self, tool_def: dict, kwargs: dict) -> dict:
        """Execute one tool call (used as the retry callable).

        Args:
            tool_def: Tool definition from the registry.
            kwargs: Arguments dict.

        Returns:
            Raw result dict from the executor.
        """
        raw = await self._executor.execute(tool_def, kwargs)
        # Derive result_status from the raw output: if the tool returned
        # success but produced no meaningful data (None, empty list, empty
        # dict) mark it as "empty" rather than "ok".
        if raw.success:
            if raw.data is None:
                status = "empty"
            elif isinstance(raw.data, (list, dict)) and not raw.data:
                status = "empty"
            else:
                status = "ok"
        else:
            status = "unknown"
        return {
            "call_id": kwargs.get("call_id", ""),
            "shop_id": kwargs.get("shop_id", ""),
            "tool_name": tool_def["name"],
            "success": raw.success,
            "result_status": status,
            "data": raw.data,
            "error_code": raw.error_code,
            "error_message": raw.error_message,
            "source": "mock",
            "degraded": False,
        }


# ── Module-level convenience function ───────────────────────────

_gateway_instance: ToolCallGateway | None = None


def get_gateway() -> ToolCallGateway:
    """Return a module-level singleton Gateway instance."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = ToolCallGateway()
    return _gateway_instance


def dispatch_tool_call(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible synchronous convenience wrapper.

    Delegates to ``ToolCallGateway.call()`` via the module-level
    singleton.  This preserves the synchronous API from the previous
    gateway version so that existing tests continue to work.
    """
    return asyncio.run(get_gateway().call(tool_name, kwargs))
