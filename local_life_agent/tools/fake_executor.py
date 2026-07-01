"""FakeToolExecutor — test-only executor that returns empty/fake results without a real DB.

Used by tests that do not need real shop data. Registered via
``build_tool_executor()`` when ``TOOL_BACKEND="fake"``.
"""

from __future__ import annotations

from typing import Any

from .executor import ToolExecutor, RawToolResult


class FakeToolExecutor(ToolExecutor):
    """Returns empty success results for every tool call.

    All tools report success with empty data so the graph flow
    still proceeds (no exceptions, no timeouts).
    """

    @property
    def backend_source(self) -> str:
        return "fake"

    async def execute(self, tool_def: dict, args: dict[str, Any]) -> RawToolResult:
        return RawToolResult(
            data={},
            success=True,
            backend_source=self.backend_source,
        )
