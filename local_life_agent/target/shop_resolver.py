"""Thin shop resolution wrapper around the tool gateway."""

from __future__ import annotations

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
        payload = {
            "query": query,
            "location": location,
            "session_shop_ids": session_shop_ids or [],
        }
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
