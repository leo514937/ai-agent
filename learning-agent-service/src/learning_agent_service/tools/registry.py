from __future__ import annotations

from typing import List

from .models import RegisteredTool, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {}

    def register(self, registered_tool: RegisteredTool) -> None:
        if registered_tool.spec.name in self._tools:
            raise ValueError("Tool already registered: {name}".format(name=registered_tool.spec.name))
        self._tools[registered_tool.spec.name] = registered_tool

    def get(self, name: str) -> RegisteredTool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def list_specs(self) -> List[ToolSpec]:
        return [registered.spec for registered in self._tools.values()]
