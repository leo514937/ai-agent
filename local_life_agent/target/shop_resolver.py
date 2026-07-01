"""Thin shop resolution wrapper around the tool gateway."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..tools.gateway import dispatch_tool_call


class ShopResolver:
    """Resolve a shop mention through the unified tool gateway."""

    def resolve(
        self,
        query: str,
        *,
        location: dict[str, float] | None = None,
        session_shop_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from ..engine import graph_builder as gb

        graph_builder_resolve: Callable[..., dict[str, Any]] | None = getattr(gb, "resolve_shop", None)
        payload = {
            "query": query,
            "location": location,
            "session_shop_ids": session_shop_ids or [],
        }
        if callable(graph_builder_resolve) and graph_builder_resolve is not resolve_shop:
            return graph_builder_resolve(query, location=location, session_shop_ids=session_shop_ids)
        return dispatch_tool_call("resolve_shop", payload)


_SHOP_RESOLVER = ShopResolver()


def resolve_shop(
    query: str,
    *,
    location: dict[str, float] | None = None,
    session_shop_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Backward-compatible helper for callers that expect a function."""
    return _SHOP_RESOLVER.resolve(query, location=location, session_shop_ids=session_shop_ids)
