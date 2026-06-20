"""Facet planner for the single-shop multi-facet flow."""

from __future__ import annotations

from typing import Any

from ..domain.enums import Facet


def _facet_name(item: Any) -> str:
    if isinstance(item, dict):
        raw = item.get("name") or item.get("facet") or item.get("facet_name") or ""
        if hasattr(raw, "value"):
            return str(raw.value)
        return str(raw)
    if hasattr(item, "name"):
        raw = getattr(item, "name")
        if hasattr(raw, "value"):
            return str(raw.value)
        return str(raw)
    if hasattr(item, "value"):
        return str(item.value)
    return str(item)


def _facet_required(item: Any) -> bool:
    if isinstance(item, dict):
        return bool(item.get("required", False))
    return bool(getattr(item, "required", False))


def plan_facets(task_type: str, semantic_frame: dict) -> list[dict[str, Any]]:
    """Decide which facets to query based on task type and user request."""
    facets = semantic_frame.get("facets") or []
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in facets:
        name = _facet_name(item).strip()
        if not name or name in seen:
            continue
        if name not in {facet.value for facet in Facet}:
            continue
        seen.add(name)
        ordered.append({"name": name, "required": _facet_required(item)})

    return ordered
