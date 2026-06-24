"""Comparison planner for multi-shop comparison flows.

P1: EvidencePlanner-compatible shell.
When a CandidateSet is available in the graph state, delegates to
``evidence_planner.plan_evidence()``. Otherwise falls back to the
legacy ``plan_comparison()`` behaviour.
"""

from __future__ import annotations

from typing import Any

from .. import config
from ..config import TOOL_DEFAULT_TIMEOUT_MS
from ..domain.candidate import CandidateSet, LocalLifeGoalDraft
from ..domain.schemas import ExecutionPlan
from .evidence_planner import plan_evidence


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


def _normalize_shop(item: Any) -> dict[str, Any]:
    shop = _to_dict(item)
    resolved_shop = shop.get("resolved_shop") or shop.get("shop") or shop
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()
    if isinstance(resolved_shop, dict):
        shop = dict(resolved_shop)
    shop.setdefault("shop_id", "")
    shop.setdefault("shop_name", "")
    return shop


def _focus_facets(shops: list[dict[str, Any]], max_detail: int) -> tuple[str, list[str]]:
    count = len(shops)
    if count <= max_detail:
        return "full", ["detail", "open_status", "coupon", "distance"]

    if count <= config.COMPARISON_FOCUSED_SHOP_LIMIT:
        return "focused", ["detail", "open_status", "coupon", "distance"]

    return "intercept", []


def plan_comparison(
    shops: list,
    max_detail: int = config.COMPARISON_FULL_DETAIL_SHOP_LIMIT,
    *,
    focus_facets: list[str] | None = None,
    location: dict[str, float] | None = None,
) -> dict:
    """Plan a deterministic multi-shop comparison."""
    normalized = []
    seen: set[str] = set()
    for item in shops or []:
        shop = _normalize_shop(item)
        shop_id = str(shop.get("shop_id", "")).strip()
        shop_name = str(shop.get("shop_name", "")).strip()
        if not shop_id and not shop_name:
            continue
        key = shop_id or shop_name
        if key in seen:
            continue
        seen.add(key)
        normalized.append(shop)

    if len(normalized) > config.COMPARISON_MAX_SHOP_LIMIT:
        target_shop_ids = [str(item.get("shop_id", "")).strip() for item in normalized if str(item.get("shop_id", "")).strip()]
        return {
            "plan_id": "comparison_plan_intercept",
            "task_type": "comparison",
            "tool_calls": [],
            "stages": [
                {
                    "stage_id": "stage_1",
                    "description": "Too many comparison targets; please narrow the scope",
                    "tool_names": [],
                    "depends_on": [],
                    "max_parallelism": 1,
                }
            ],
            "target_shop_ids": target_shop_ids,
        }

    selected = normalized
    mode, default_facets = _focus_facets(selected, max_detail)
    target_shop_ids = [str(item.get("shop_id", "")).strip() for item in selected if str(item.get("shop_id", "")).strip()]
    selected_focus_facets = [facet for facet in (focus_facets or default_facets) if facet in {"detail", "open_status", "coupon", "distance"}]

    if len(selected) < 2:
        return {
            "plan_id": "comparison_plan_empty",
            "task_type": "comparison",
            "tool_calls": [],
            "stages": [],
            "target_shop_ids": target_shop_ids,
        }

    tool_calls: list[dict[str, Any]] = []
    stage_tool_names: list[str] = []

    for idx, shop in enumerate(selected, start=1):
        shop_id = str(shop.get("shop_id", "")).strip()
        if not shop_id:
            continue
        call_group = f"comparison_stage_{idx}"
        if mode == "full":
            facet_specs = ["detail", "open_status", "coupon", "distance"]
        elif mode == "focused":
            facet_specs = selected_focus_facets or ["detail"]
        else:
            facet_specs = []

        for facet in facet_specs:
            if facet == "detail":
                tool_name = "get_shop_detail"
                args = {"shop_id": shop_id}
            elif facet == "open_status":
                tool_name = "check_open_status"
                args = {"shop_id": shop_id}
            elif facet == "coupon":
                tool_name = "get_coupon_list"
                args = {"shop_id": shop_id}
            elif facet == "distance":
                tool_name = "get_distance_eta"
                args = {"shop_id": shop_id, "from_location": location or config.MOCK_LOCATION}
            else:
                continue

            stage_tool_names.append(tool_name)
            tool_calls.append(
                {
                    "call_id": f"call_{facet}_{idx}",
                    "tool_name": tool_name,
                    "args": args,
                    "target_shop_id": shop_id,
                    "required": False,
                    "facet": facet,
                    "depends_on": [],
                    "timeout_ms": TOOL_DEFAULT_TIMEOUT_MS,
                    "retry_policy": {"max_attempts": 0, "backoff_ms": 0},
                    "fallback_policy": {"fallback_tool": "", "fallback_args": {}},
                    "group_id": call_group,
                    "max_parallelism": max(1, min(len(facet_specs), config.MAX_CONCURRENCY)),
                }
            )

    description = {
        "full": "Fetch full detail for up to 3 shops and compare all common facets",
        "focused": "Fetch focused comparison facets for up to 5 shops",
        "intercept": "Too many comparison targets; please narrow the scope",
    }.get(mode, "Compare multiple shops")

    return {
        "plan_id": f"comparison_plan_{'_'.join(target_shop_ids) or 'empty'}",
        "task_type": "comparison",
        "tool_calls": tool_calls,
        "stages": [
            {
                "stage_id": "stage_1",
                "description": description,
                "tool_names": sorted(set(stage_tool_names)),
                "depends_on": [],
                "max_parallelism": max(1, min(len(tool_calls), config.MAX_CONCURRENCY)),
            }
        ],
        "target_shop_ids": target_shop_ids,
    }


def plan_comparison_with_candidate_set(
    goal: LocalLifeGoalDraft,
    candidate_set: CandidateSet,
    semantic_frame: dict[str, Any] | None = None,
    comparison_targets: list[dict[str, Any]] | None = None,
    location: dict[str, Any] | None = None,
) -> ExecutionPlan:
    """Shell that delegates to EvidencePlanner when a CandidateSet is available.

    This is the P1-compatible entry point called by the graph builder when
    a CandidateSet is present for comparison flows.
    """
    return plan_evidence(
        goal=goal,
        candidate_set=candidate_set,
        semantic_frame=semantic_frame,
        comparison_targets=comparison_targets,
        location=location,
    )
