"""Circuit breaker — prevents cascading failures by stopping calls
to a failing tool after a threshold of consecutive failures.

Supports per-tool configuration via CircuitBreakerManager.
"""

from __future__ import annotations

import time
from typing import Any


class CircuitBreaker:
    """Per-tool circuit breaker with failure counting and auto-recovery."""

    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing — calls rejected immediately
    HALF_OPEN = "half_open"  # Testing the waters after recovery_timeout

    def __init__(self, threshold: int = 5, recovery_timeout_ms: int = 30000):
        self.threshold = threshold
        self.recovery_timeout_ms = recovery_timeout_ms
        self._state: str = self.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> str:
        """Return the current state label."""
        if self._state == self.OPEN:
            elapsed_ms = (time.time() - self._last_failure_time) * 1000
            if elapsed_ms >= self.recovery_timeout_ms:
                self._state = self.HALF_OPEN
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if the circuit is currently open (blocking calls)."""
        return self.state == self.OPEN

    def record_failure(self) -> None:
        """Record a failure and open the circuit if threshold exceeded."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.threshold:
            self._state = self.OPEN

    def record_success(self) -> None:
        """Reset on success when half-open; otherwise just decrement count."""
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            self._failure_count = 0
        elif self._failure_count > 0:
            self._failure_count = max(0, self._failure_count - 1)

    def reset(self) -> None:
        """Forcefully reset the breaker to closed state."""
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0


class CircuitBreakerManager:
    """Manages circuit breakers for multiple tools."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def _get_or_create(self, tool_name: str, threshold: int = 5, recovery_timeout_ms: int = 30000) -> CircuitBreaker:
        if tool_name not in self._breakers:
            self._breakers[tool_name] = CircuitBreaker(
                threshold=threshold,
                recovery_timeout_ms=recovery_timeout_ms,
            )
        return self._breakers[tool_name]

    def is_open(self, tool_name: str, threshold: int = 5, recovery_timeout_ms: int = 30000) -> bool:
        """Check if the circuit is open for a given tool."""
        return self._get_or_create(tool_name, threshold, recovery_timeout_ms).is_open

    def record_failure(self, tool_name: str, threshold: int = 5, recovery_timeout_ms: int = 30000) -> None:
        """Record a tool failure (may open the circuit)."""
        self._get_or_create(tool_name, threshold, recovery_timeout_ms).record_failure()

    def record_success(self, tool_name: str, threshold: int = 5, recovery_timeout_ms: int = 30000) -> None:
        """Record a tool success (may close the circuit if half-open)."""
        self._get_or_create(tool_name, threshold, recovery_timeout_ms).record_success()

    def get_state(self, tool_name: str) -> str:
        """Return the circuit state for a tool."""
        cb = self._breakers.get(tool_name)
        return cb.state if cb is not None else CircuitBreaker.CLOSED

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for cb in self._breakers.values():
            cb.reset()


# Module-level singleton
_manager: CircuitBreakerManager | None = None


def get_circuit_breaker_manager() -> CircuitBreakerManager:
    global _manager
    if _manager is None:
        _manager = CircuitBreakerManager()
    return _manager
