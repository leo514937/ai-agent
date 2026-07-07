"""DEPRECATED_COMPAT: tool execution 兼容壳。

The batch path exposed here is a bounded, execution-layer MapReduce-style
helper: it fans tool calls out concurrently inside the executor, then
returns a merged dict to the workflow layer. It is not a LangGraph-native
Send/reducer graph.
"""

from __future__ import annotations

from typing import Any


class ExecutionCore:
    """Convenience wrapper for single-call and batch-concurrent tool execution."""

    def __init__(self, call_fn: Any | None = None) -> None:
        self._call_fn = call_fn

    def execute_batch(self, tool_calls: list[Any]):
        """Run a batch of tool calls through the shared batch executor."""
        from ..tools.gateway import BatchToolExecutor, dispatch_tool_call

        batch = BatchToolExecutor(call_fn=self._call_fn or dispatch_tool_call)
        return batch.execute_sync(tool_calls)

    def dispatch(self, tool_name: str, kwargs: dict[str, Any]):
        from ..tools.gateway import dispatch_tool_call

        return (self._call_fn or dispatch_tool_call)(tool_name, kwargs)
