"""Execution plan builder for the single-shop multi-facet flow."""

from __future__ import annotations

from typing import Any

from .. import config
from ..config import TOOL_DEFAULT_TIMEOUT_MS
from ..domain.enums import Facet, TaskType


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _facet_name(item: Any) -> str:
    if hasattr(item, "name") and getattr(item, "name") in Facet.__members__.values():
        facet = getattr(item, "name")
        return facet.value if hasattr(facet, "value") else str(facet)
    if isinstance(item, dict):
        raw = item.get("name") or item.get("facet") or item.get("facet_name") or ""
        if hasattr(raw, "value"):
            return raw.value
        return str(raw)
    if hasattr(item, "value"):
        return str(item.value)
    return str(item)


def _facet_required(item: Any) -> bool:
    if isinstance(item, dict):
        return bool(item.get("required", False))
    return bool(getattr(item, "required", False))


def _normalized_facets(facets: list[Any]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in facets or []:
        name = _facet_name(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append({"name": name, "required": _facet_required(item)})
    return ordered


def build_execution_plan(task_type: str, target: dict, facets: list[str | dict[str, Any]]) -> dict:
    """Build an execution plan dict with ordered tool calls."""
    resolved_shop: dict[str, Any] = {}
    status = ""
    if isinstance(target, dict):
        status = target.get("status", "")
        resolved_shop = target.get("resolved_shop") or target.get("shop") or {}
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()

    shop_id = resolved_shop.get("shop_id", "")
    if task_type not in (TaskType.coupon_query.value, TaskType.single_shop_query.value) or status != "RESOLVED" or not shop_id:
        return {
            "plan_id": "",
            "task_type": task_type,
            "tool_calls": [],
            "stages": [],
            "target_shop_ids": [],
        }

    normalized_facets = _normalized_facets(facets)
    tool_calls: list[dict[str, Any]] = []
    tool_names: list[str] = []

    for idx, facet in enumerate(normalized_facets, start=1):
        facet_name = facet["name"]
        required = facet["required"]
        call_id = f"call_{facet_name}_{idx}"
        if facet_name == Facet.coupon.value:
            tool_name = "get_coupon_list"
            args = {"shop_id": shop_id}
        elif facet_name == Facet.open_status.value:
            tool_name = "check_open_status"
            args = {"shop_id": shop_id}
        elif facet_name == Facet.distance.value:
            tool_name = "get_distance_eta"
            args = {"shop_id": shop_id, "from_location": config.MOCK_LOCATION}
        else:
            continue

        tool_names.append(tool_name)
        tool_calls.append(
            {
                "call_id": call_id,
                "tool_name": tool_name,
                "args": args,
                "target_shop_id": shop_id,
                "required": required,
                "facet": facet_name,
                "depends_on": [],
                "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                "retry_policy": {"max_attempts": 1 if required else 0, "backoff_ms": 0},
                "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
                "group_id": "facet_stage_1",
                "max_parallelism": max(1, min(len(normalized_facets), config.MAX_CONCURRENCY)),
            }
        )

    return {
        "plan_id": f"plan_{shop_id}",
        "task_type": task_type,
        "tool_calls": tool_calls,
        "stages": [
            {
                "stage_id": "stage_1",
                "description": "Fetch all requested facets for the resolved shop in parallel",
                "tool_names": tool_names,
                "depends_on": [],
                "max_parallelism": max(1, min(len(tool_calls), config.MAX_CONCURRENCY)),
            }
        ],
        "target_shop_ids": [shop_id],
    }
