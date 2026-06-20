"""Tool retry logic — configurable retry with exponential backoff
for transient tool failures (TIMEOUT, NETWORK_ERROR).

RetryManager applies jittered exponential backoff and only retries
on transient error codes. Permanent errors (SHOP_NOT_FOUND,
INVALID_ARGUMENT, TOOL_NOT_REGISTERED) are returned immediately.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

_TRANSIENT_CODES = {"TOOL_TIMEOUT", "NETWORK_ERROR", "CIRCUIT_OPEN"}
_PERMANENT_CODES = {
    "SHOP_NOT_FOUND", "INVALID_ARGUMENT", "TOOL_NOT_REGISTERED",
    "AMBIGUOUS_SHOP", "LOW_CONFIDENCE", "SCHEMA_VALIDATION_FAILED",
}


def _default_backoff(attempt: int, base_ms: int = 200, max_ms: int = 5000) -> float:
    """Jittered exponential backoff in seconds."""
    delay = min(base_ms * (2 ** attempt), max_ms)
    jitter = random.uniform(0, delay * 0.1)
    return (delay + jitter) / 1000.0


async def retry_with_backoff(
    call_fn: Any,
    tool_name: str,
    kwargs: dict[str, Any],
    max_attempts: int = 3,
    base_backoff_ms: int = 200,
    max_backoff_ms: int = 5000,
    transient_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Call *call_fn* with retry for transient failures.

    Args: see docstring.
    Returns: Tool result dict.
    """
    if transient_codes is None:
        transient_codes = _TRANSIENT_CODES

    last_result: dict[str, Any] | None = None
    is_async = asyncio.iscoroutinefunction(call_fn)

    for attempt in range(max_attempts):
        try:
            if is_async:
                raw = await call_fn(**kwargs)
            else:
                raw = call_fn(**kwargs)
            result: dict[str, Any] = raw if isinstance(raw, dict) else {"success": True, "data": raw}
        except TimeoutError as exc:
            result = {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "TOOL_TIMEOUT",
                "error_message": str(exc),
                "source": "mock",
                "degraded": False,
            }
        except Exception as exc:
            result = {
                "success": False,
                "result_status": "unknown",
                "data": None,
                "error_code": "NETWORK_ERROR",
                "error_message": str(exc),
                "source": "mock",
                "degraded": False,
            }

        if result.get("success", False):
            return result

        error_code = result.get("error_code", "")
        if error_code in _PERMANENT_CODES:
            return result

        if error_code in transient_codes and attempt < max_attempts - 1:
            delay = _default_backoff(attempt, base_backoff_ms, max_backoff_ms)
            await asyncio.sleep(delay)
            last_result = result
            continue

        return result

    if last_result is None:
        last_result = {
            "success": False,
            "result_status": "unknown",
            "data": None,
            "error_code": "UNKNOWN",
            "error_message": f"Tool '{tool_name}' failed after {max_attempts} attempt(s)",
            "source": "mock",
            "degraded": False,
        }
    return last_result

