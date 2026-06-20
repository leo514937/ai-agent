"""Distributed tracing — generates and manages trace IDs, records
per-turn execution spans for debugging and monitoring.
"""


def new_trace_id() -> str:
    """Generate a unique trace ID for a request."""
    raise NotImplementedError("Tracing not yet implemented")


def record_span(trace_id: str, span_name: str, metadata: dict | None = None) -> None:
    """Record a span in the current trace."""
    raise NotImplementedError("Tracing not yet implemented")
