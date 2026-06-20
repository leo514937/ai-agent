"""Tool executor — abstract interface and concrete implementations.

Defines the ``ToolExecutor`` abstract base class that all executor
implementations (Mock / HTTP / DB) must follow, ensuring the upper
layers (Planner, Gateway) remain source-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RawToolResult:
    """Raw output from a tool executor before normalisation.

    Carries the bare tool output plus execution metadata.
    """

    def __init__(self, data: Any, success: bool = True,
                 error_code: str | None = None,
                 error_message: str = ""):
        self.data = data
        self.success = success
        self.error_code = error_code
        self.error_message = error_message


class ToolExecutor(ABC):
    """Abstract interface for tool execution.

    All executor implementations (MockToolExecutor, RealToolExecutor)
    must implement ``execute()``.  The Gateway calls this method without
    knowing whether the source is local JSON, a remote HTTP API, or a DB.
    """

    @abstractmethod
    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        """Execute a tool call.

        Args:
            tool_def: Tool definition dict from the registry (includes
                      name, input_schema, output_schema, timeout_ms, ...).
            args: Resolved arguments for this call.

        Returns:
            ``RawToolResult`` with the execution output.
        """
        ...


class MockToolExecutor(ToolExecutor):
    """Mock executor that delegates to ``mock_tools`` module functions.

    Reads static JSON files from ``mock_data/``.  This is the default
    executor for development and testing.  Replacing it with
    ``RealToolExecutor`` (HTTP / DB) requires zero changes to the
    Gateway or Planner.
    """

    def __init__(self):
        import importlib
        self._mod = importlib.import_module(".mock_tools", package="local_life_agent.tools")

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        """Execute a tool via mock_tools.

        The tool function is looked up by ``tool_def["name"]`` on the
        mock_tools module.  If the function raises ``TimeoutError`` it
        is propagated to the Gateway for retry / normalisation.

        Args:
            tool_def: Tool definition from the registry.
            args: Arguments for this call.

        Returns:
            ``RawToolResult`` wrapping the mock function output.

        Raises:
            TimeoutError: For tools that simulate a timeout.
        """
        tool_name = tool_def["name"]
        fn = getattr(self._mod, tool_name, None)
        if fn is None:
            return RawToolResult(
                data=None,
                success=False,
                error_code="TOOL_NOT_REGISTERED",
                error_message=f"Mock implementation for '{tool_name}' not found",
            )
        try:
            result = fn(**args)
        except TimeoutError:
            raise
        except Exception as exc:
            return RawToolResult(
                data=None,
                success=False,
                error_code="NETWORK_ERROR",
                error_message=str(exc),
            )

        if isinstance(result, dict):
            # Tool functions may return either the standard envelope
            #   {"success": True, "data": ..., "result_status": "ok", ...}
            # or a bare result dict (e.g. resolve_shop returns
            #   {"status": "RESOLVED", "shop": {...}}).
            if "success" in result and "data" in result:
                return RawToolResult(
                    data=result.get("data"),
                    success=result.get("success", False),
                    error_code=result.get("error_code"),
                    error_message=result.get("error_message", ""),
                )
            # Non-standard envelope: wrap the whole dict as data.
            return RawToolResult(
                data=result,
                success=True,
                error_code=result.get("error_code"),
                error_message=result.get("error_message", ""),
            )
        return RawToolResult(data=result, success=True)
