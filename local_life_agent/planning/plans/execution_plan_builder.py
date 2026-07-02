"""Execution plan builder for local-life flows."""

from __future__ import annotations

import logging
from typing import Any

from ... import config
from ...config import TOOL_DEFAULT_TIMEOUT_MS
from ...domain.enums import Facet, TaskType
from ...domain.facets import build_target_resolution_result, normalize_query_facets
from ..policies.ranking_policy import infer_recommendation_query

_logger = logging.getLogger(__name__)


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
    if hasattr(item, "name"):
        raw_name = getattr(item, "name")
        if isinstance(raw_name, str) and raw_name.strip():
            return raw_name.strip()
        if hasattr(raw_name, "value"):
            return str(raw_name.value)
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


def _recommendation_preferences(frame: dict[str, Any]) -> dict[str, Any]:
    ranking_signals = _to_dict(frame.get("ranking_signals"))
    soft_preferences = _to_dict(frame.get("soft_preferences"))
    query_terms = [str(item) for item in ranking_signals.get("query_terms", []) or [] if str(item).strip()]
    scene_terms = [str(item) for item in soft_preferences.get("scene_terms", []) or [] if str(item).strip()]
    return {
        "query_terms": query_terms,
        "scene_terms": scene_terms,
        "open_now_preferred": bool(
            ranking_signals.get("open_now_preferred") or soft_preferences.get("open_now_preferred")
        ),
        "coupon_preferred": bool(
            ranking_signals.get("coupon_preferred") or soft_preferences.get("coupon_preferred")
        ),
        "nearby_preferred": bool(
            ranking_signals.get("nearby_preferred") or soft_preferences.get("nearby_preferred")
        ),
    }


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
    if task_type != TaskType.single_shop_query.value or status != "RESOLVED" or not shop_id:
        _logger.warning(
            "build_execution_plan: unknown task_type=%r or unresolvable target "
            "(status=%r shop_id=%r) => returning empty plan",
            task_type, status, shop_id,
        )
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
            args = {"shop_id": shop_id}
        elif facet_name in (Facet.environment.value, Facet.taste.value, Facet.service.value,
                            Facet.review_summary.value, Facet.scene_fit.value):
            tool_name = "get_shop_detail"
            args = {"shop_id": shop_id}
        else:
            # price / rating / category — get_shop_detail 包含这些基础信息
            tool_name = "get_shop_detail"
            args = {"shop_id": shop_id}

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
        "facets": normalized_facets,
        "target_resolution": build_target_resolution_result(
            {
                "current_shop": resolved_shop,
                "comparison_targets": [],
                "reference_mentions": [],
                "deictic_references": [],
                "ordinal_references": [],
            },
            raw_text=str(target.get("source_text", "") or ""),
        ),
        "conflicting_facets": [],
        "ranking_policy": None,
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


def build_recommendation_execution_plan(
    semantic_frame: dict[str, Any],
    *,
    location: dict[str, float] | None = None,
    fallback_query: str = "",
) -> dict[str, Any]:
    """Build a deterministic recommendation plan."""
    frame = _to_dict(semantic_frame)
    query = infer_recommendation_query(frame) or str(fallback_query or "").strip()
    preferences = _recommendation_preferences(frame)
    facet_set = normalize_query_facets(frame, raw_text=fallback_query or query)
    location = location or {}
    tool_calls: list[dict[str, Any]] = [
        {
            "call_id": "call_search_shops",
            "tool_name": "search_shops",
            "args": {
                "query": query,
                "location": location,
                "limit": config.SEARCH_LIMIT,
            },
            "target_shop_id": "",
            "required": True,
            "facet": "recall",
            "depends_on": [],
            "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
            "retry_policy": {"max_attempts": 1, "backoff_ms": 0},
            "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
            "group_id": "recommendation_stage_0",
            "max_parallelism": 1,
        }
    ]

    task_type = str(_to_dict(frame).get("task_type", TaskType.recommendation.value))

    for idx in range(1, config.RECOMMENDATION_CANDIDATE_TOP_K + 1):
        tool_calls.extend(
            [
                {
                    "call_id": f"call_detail_{idx}",
                    "tool_name": "get_shop_detail",
                    "args": {"shop_id": f"$search_result[{idx - 1}].shop_id"},
                    "target_shop_id": f"$search_result[{idx - 1}].shop_id",
                    "required": False,
                    "facet": "detail",
                    "depends_on": ["call_search_shops"],
                    "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                    "retry_policy": {"max_attempts": 1, "backoff_ms": 0},
                    "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
                    "group_id": "recommendation_stage_1",
                    "max_parallelism": config.MAX_CONCURRENCY,
                },
                {
                    "call_id": f"call_open_{idx}",
                    "tool_name": "check_open_status",
                    "args": {"shop_id": f"$search_result[{idx - 1}].shop_id"},
                    "target_shop_id": f"$search_result[{idx - 1}].shop_id",
                    "required": False,
                    "facet": "open_status",
                    "depends_on": ["call_search_shops"],
                    "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                    "retry_policy": {"max_attempts": 0, "backoff_ms": 0},
                    "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
                    "group_id": "recommendation_stage_1",
                    "max_parallelism": config.MAX_CONCURRENCY,
                },
                {
                    "call_id": f"call_coupon_{idx}",
                    "tool_name": "get_coupon_list",
                    "args": {"shop_id": f"$search_result[{idx - 1}].shop_id"},
                    "target_shop_id": f"$search_result[{idx - 1}].shop_id",
                    "required": False,
                    "facet": "coupon",
                    "depends_on": ["call_search_shops"],
                    "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                    "retry_policy": {"max_attempts": 0, "backoff_ms": 0},
                    "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
                    "group_id": "recommendation_stage_1",
                    "max_parallelism": config.MAX_CONCURRENCY,
                },
            ]
        )

    return {
        "plan": {
            "plan_id": f"recommendation_plan_{task_type}",
            "task_type": TaskType.recommendation.value,
            "facets": [facet.model_dump() if hasattr(facet, "model_dump") else facet for facet in (facet_set.facets or [])],
            "target_resolution": facet_set.target_resolution.model_dump() if facet_set.target_resolution else None,
            "conflicting_facets": [item.model_dump() if hasattr(item, "model_dump") else item for item in (facet_set.conflicting_facets or [])],
            "ranking_policy": facet_set.ranking_policy.model_dump() if facet_set.ranking_policy else None,
            "tool_calls": tool_calls,
            "stages": [
                {
                    "stage_id": "stage_0",
                    "description": "Recall recommendation candidates with search_shops",
                    "tool_names": ["search_shops"],
                    "depends_on": [],
                    "max_parallelism": 1,
                },
                {
                    "stage_id": "stage_1",
                    "description": "Enrich the top candidates in parallel",
                    "tool_names": ["get_shop_detail", "check_open_status", "get_coupon_list"],
                    "depends_on": ["stage_0"],
                    "max_parallelism": config.MAX_CONCURRENCY,
                },
            ],
            "target_shop_ids": [],
            "query_terms": preferences["query_terms"],
            "scene_terms": preferences["scene_terms"],
            "open_now_preferred": preferences["open_now_preferred"],
            "coupon_preferred": preferences["coupon_preferred"],
            "nearby_preferred": preferences["nearby_preferred"],
        },
        "recommendation_query": query,
        "query_terms": preferences["query_terms"],
        "scene_terms": preferences["scene_terms"],
    }
