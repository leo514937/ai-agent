"""Tool registry — central lookup and registration layer."""

from __future__ import annotations

from typing import Any

from .definitions import TOOL_DEFINITIONS
from .validators import validate_tool_args


class ToolRegistry:
    """Central registry for all available tools with metadata."""

    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}
        self._load_definitions()

    def _load_definitions(self) -> None:
        for tdef in TOOL_DEFINITIONS:
            self._tools[tdef["name"]] = dict(tdef)

    def register(self, name: str, metadata: dict[str, Any]) -> None:
        """Register or override a tool definition."""
        self._tools[name] = dict(metadata)

    def get(self, name: str) -> dict[str, Any] | None:
        """Look up a tool definition by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def validate_args(self, tool_name: str, args: dict[str, Any]) -> list[str]:
        """Validate tool arguments against the input schema."""
        tdef = self._tools.get(tool_name)
        if tdef is None:
            return [f"Tool '{tool_name}' not registered"]
        return validate_tool_args(tool_name, tdef, args)


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry

