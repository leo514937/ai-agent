"""Metrics collection — records performance and quality metrics
for monitoring and evaluation.
"""


def record_tool_call_metric(
    tool_name: str, duration_ms: float, success: bool
) -> None:
    """Record a single tool call metric."""
    raise NotImplementedError("Metrics not yet implemented")


def record_turn_metric(trace_id: str, total_duration_ms: float) -> None:
    """Record per-turn metrics."""
    raise NotImplementedError("Metrics not yet implemented")
