"""Tool executor — abstract interface and concrete implementations.

Defines the ``ToolExecutor`` abstract base class that all executor
implementations (HTTP / DB) must follow, ensuring the upper layers
(Planner, Gateway) remain source-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .. import config
from ..streaming.runtime import raise_if_turn_cancelled


class RawToolResult:
    """Raw output from a tool executor before normalisation.

    Carries the bare tool output plus execution metadata.
    Now includes ``backend_source``, ``http_status``, and
    ``endpoint`` so the Gateway can propagate them into ToolResult.
    """

    def __init__(
        self,
        data: Any,
        success: bool = True,
        error_code: str | None = None,
        error_message: str = "",
        *,
        backend_source: str = "unknown",
        http_status: int | None = None,
        endpoint: str | None = None,
        fallback_from: str | None = None,
    ):
        self.data = data
        self.success = success
        self.error_code = error_code
        self.error_message = error_message
        self.backend_source = backend_source
        self.http_status = http_status
        self.endpoint = endpoint
        self.fallback_from = fallback_from


class ToolExecutor(ABC):
    """Abstract interface for tool execution.

        All executor implementations must implement ``execute()``.  The
        Gateway calls this method without knowing whether the source is a
        remote HTTP API or a DB.
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

    @property
    def backend_source(self) -> str:
        """Return the source identifier.

        Test executors may keep the default ``unknown`` value.
        """
        return "unknown"


class DbToolExecutor(ToolExecutor):
    """Executes tools by querying MySQL directly via ``db_tools``.

    Reads data from ``tb_shop``, ``tb_shop_type``, and ``tb_voucher``
    tables using the ``db_client`` module.  This is the default executor
    when ``TOOL_BACKEND=db`` (production mode).
    """

    def __init__(self):
        import importlib
        self._mod = importlib.import_module(".db_tools", package="local_life_agent.tools")

    @property
    def backend_source(self) -> str:
        return "db"

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        raise_if_turn_cancelled()
        tool_name = tool_def["name"]
        fn = getattr(self._mod, tool_name, None)
        if fn is None:
            return RawToolResult(
                data=None,
                success=False,
                error_code="TOOL_NOT_REGISTERED",
                error_message=f"DB implementation for '{tool_name}' not found",
                backend_source=self.backend_source,
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
                backend_source=self.backend_source,
            )

        if isinstance(result, dict):
            if "success" in result and "data" in result:
                return RawToolResult(
                    data=result.get("data"),
                    success=result.get("success", False),
                    error_code=result.get("error_code"),
                    error_message=result.get("error_message", ""),
                    backend_source=self.backend_source,
                )
            return RawToolResult(
                data=result,
                success=True,
                error_code=result.get("error_code"),
                error_message=result.get("error_message", ""),
                backend_source=self.backend_source,
            )
        return RawToolResult(data=result, success=True, backend_source=self.backend_source)


class JavaToolExecutor(ToolExecutor):
    """Executes tools by forwarding calls to the Java backend via HTTP.

    Uses ``JavaToolClient`` under the hood.  Every result carries
    ``backend_source="java_api"``.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
    ):
        from .java_client import JavaToolClient as _JavaToolClient

        self._client = client or _JavaToolClient()

    @property
    def backend_source(self) -> str:
        return "java_api"

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        """Forward a tool call to the Java backend.

        Args:
            tool_def: Tool definition dict from the registry.
            args: Arguments validated by ToolCallGateway.

        Returns:
            ``RawToolResult`` with ``backend_source="java_api"``.

        Raises:
            TimeoutError: Propagated from JavaToolClient when the
                         HTTP request times out.
        """
        raise_if_turn_cancelled()
        tool_name = tool_def["name"]
        data, meta = await self._client.call(tool_name, args)

        success = data.get("success", False)
        result_status = data.get("result_status", "unknown" if not success else "ok")
        error_code = data.get("error_code")
        error_message = data.get("error_message", "")

        payload = data["data"] if "data" in data else data
        return RawToolResult(
            data=payload,
            success=success,
            error_code=error_code,
            error_message=error_message,
            backend_source=self.backend_source,
            http_status=meta.get("http_status"),
            endpoint=meta.get("endpoint"),
        )


# ═══════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════


def build_tool_executor() -> ToolExecutor:
    """Create a ToolExecutor based on ``config.TOOL_BACKEND``.

    Returns:
        ``DbToolExecutor``    when TOOL_BACKEND == "db".
        ``JavaToolExecutor``  when TOOL_BACKEND == "java_api".

    Raises:
        ValueError: When TOOL_BACKEND has an unexpected value.
    """
    backend = config.TOOL_BACKEND
    if backend == "db":
        return DbToolExecutor()
    if backend == "java_api":
        return JavaToolExecutor()
    raise ValueError(f"Unknown TOOL_BACKEND: {backend!r}")


def build_db_executor() -> ToolExecutor:
    """Return a DbToolExecutor for direct DB access."""
    return DbToolExecutor()
