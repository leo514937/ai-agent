"""Evidence builder for the single-shop multi-facet flow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import config
from ..domain.enums import ToolResultStatus
from ..planning.ranking_policy import rank_candidates


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


def _status_value(value: Any) -> str:
    if isinstance(value, ToolResultStatus):
        return value.value
    if isinstance(value, str):
        return value
    return str(value or "unknown")


def _first_shop_name(resolved_target: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(resolved_target, dict):
        return "", ""
    resolved_shop = resolved_target.get("resolved_shop") or resolved_target.get("shop") or {}
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()
    if isinstance(resolved_shop, dict):
        return resolved_shop.get("shop_id", ""), resolved_shop.get("shop_name", "")
    return "", ""


def _facet_name_from_tool(tool_name: str) -> str:
    return {
        "get_coupon_list": "coupon",
        "check_open_status": "open_status",
        "get_distance_eta": "distance",
    }.get(tool_name, "unknown")


def _facet_claims_for_status(facet: str, status: str) -> list[str]:
    if facet == "coupon":
        if status in {"unknown", "failed", "circuit_open"}:
            return ["有券", "有可用券", "当前暂无可用券", "暂无可用券", "没有券"]
    elif facet == "open_status":
        if status in {"unknown", "failed", "circuit_open"}:
            return ["营业中", "正在营业", "已打烊", "已关门", "不营业"]
    elif facet == "distance":
        if status in {"unknown", "failed", "circuit_open"}:
            return ["很近", "不远", "很远", "x公里", "km"]
    return []


def _facet_status_summary(result_status: str, data: Any) -> str:
    if result_status in {"failed", "circuit_open", "unknown"}:
        return result_status
    if result_status == "empty":
        return "empty"
    if result_status == "ok":
        return "ok"
    return "unknown"


def _facet_result_payload(facet: str, result_status: str, data: Any) -> dict[str, Any]:
    payload = {
        "facet": facet,
        "status": _facet_status_summary(result_status, data),
        "result_status": result_status,
        "value": None,
    }
    if facet == "coupon":
        if result_status == "ok" and isinstance(data, list):
            payload["value"] = [coupon.get("title", "") for coupon in data if isinstance(coupon, dict) and coupon.get("title")]
        elif result_status == "empty":
            payload["value"] = "empty"
    elif facet == "open_status":
        if result_status == "ok" and isinstance(data, dict):
            payload["value"] = data.get("open_status", "unknown")
    elif facet == "distance":
        if result_status == "ok" and isinstance(data, dict):
            payload["value"] = {
                "distance_km": data.get("distance_km"),
                "eta_minutes": data.get("eta_minutes"),
            }
    return payload


def _candidate_from_shop(shop: Any) -> dict[str, Any]:
    candidate = _to_dict(shop)
    if not candidate:
        return {}
    candidate.setdefault("shop_id", "")
    candidate.setdefault("shop_name", "")
    candidate.setdefault("category", "")
    candidate.setdefault("tags", [])
    candidate.setdefault("rating", 0)
    candidate.setdefault("distance_km", None)
    candidate.setdefault("eta_minutes", None)
    candidate.setdefault("open_status", candidate.get("open_status", "unknown"))
    candidate.setdefault("coupon_count", candidate.get("coupon_count"))
    return candidate


def _search_result_candidates(tool_results: dict, plan_calls: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for call_id, tool_result in (tool_results or {}).items():
        result = _to_dict(tool_result)
        tool_name = str(result.get("tool_name", ""))
        if tool_name != "search_shops":
            continue
        data = result.get("data")
        if not isinstance(data, list):
            continue
        limit = config.RECOMMENDATION_CANDIDATE_TOP_K
        call_plan = plan_calls.get(str(call_id), {})
        try:
            limit = min(limit, int(call_plan.get("args", {}).get("limit", config.SEARCH_LIMIT)))
        except Exception:
            limit = config.RECOMMENDATION_CANDIDATE_TOP_K
        for item in data[:limit]:
            candidate = _candidate_from_shop(item)
            if candidate.get("shop_id"):
                candidates.append(candidate)
    return candidates


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _comparison_target_shop(item: Any) -> dict[str, Any]:
    data = _to_dict(item)
    resolved_shop = data.get("resolved_shop") or data.get("shop") or data
    if hasattr(resolved_shop, "model_dump"):
        resolved_shop = resolved_shop.model_dump()
    if not isinstance(resolved_shop, dict):
        resolved_shop = {}
    return {
        "shop_id": str(resolved_shop.get("shop_id", "") or data.get("shop_id", "")).strip(),
        "shop_name": str(resolved_shop.get("shop_name", "") or data.get("shop_name", "")).strip(),
    }


def _comparison_dimension_score(row: dict[str, Any]) -> tuple[float, int]:
    known = 0
    score = 0.0

    rating = row.get("rating")
    if rating is not None:
        known += 1
        try:
            score += float(rating) / 5.0
        except Exception:
            pass

    distance_km = row.get("distance_km")
    if distance_km is not None:
        known += 1
        try:
            distance = float(distance_km)
            score += max(0.0, 1.0 - min(distance, 10.0) / 10.0)
        except Exception:
            pass

    open_status = str(row.get("open_status", "") or "").lower()
    if open_status:
        known += 1
        if open_status == "open":
            score += 1.0
        elif open_status == "closed":
            score += 0.0

    coupon_count = row.get("coupon_count")
    if coupon_count is not None:
        known += 1
        try:
            score += 1.0 if int(coupon_count) > 0 else 0.0
        except Exception:
            pass

    if known:
        return score / known, known
    return 0.0, 0


def _comparison_open_rank(status: str) -> int:
    status = str(status or "").lower()
    if status == "open":
        return 2
    if status == "unknown":
        return 1
    if status == "closed":
        return 0
    return 0


def _build_comparison_evidence(
    tool_results: dict,
    plan_calls: dict[str, dict[str, Any]],
    plan_dict: dict[str, Any],
    comparison_targets: list[Any],
) -> dict[str, Any]:
    targets = [_comparison_target_shop(item) for item in comparison_targets if _comparison_target_shop(item).get("shop_id") or _comparison_target_shop(item).get("shop_name")]
    target_ids = [item["shop_id"] for item in targets if item["shop_id"]]
    if not target_ids:
        target_ids = [str(shop_id).strip() for shop_id in plan_dict.get("target_shop_ids", []) or [] if str(shop_id).strip()]

    rows_by_shop_id: dict[str, dict[str, Any]] = {}
    for target in targets:
        sid = target["shop_id"]
        rows_by_shop_id[sid] = {
            "shop_id": sid,
            "shop_name": target["shop_name"],
            "detail_status": "unknown",
            "open_status": "unknown",
            "coupon_status": "unknown",
            "rating": None,
            "distance_km": None,
            "eta_minutes": None,
            "coupon_titles": [],
            "avg_price": None,
            "tags": [],
            "address": "",
        }

    if not rows_by_shop_id:
        for call_id, result in (tool_results or {}).items():
            row_id = str(_to_dict(result).get("shop_id", "")).strip()
            if row_id and row_id not in rows_by_shop_id:
                rows_by_shop_id[row_id] = {
                    "shop_id": row_id,
                    "shop_name": "",
                    "detail_status": "unknown",
                    "open_status": "unknown",
                    "coupon_status": "unknown",
                    "rating": None,
                    "distance_km": None,
                    "eta_minutes": None,
                    "coupon_titles": [],
                    "avg_price": None,
                    "tags": [],
                    "address": "",
                }

    for call_id, tool_result in (tool_results or {}).items():
        result = _to_dict(tool_result)
        tool_name = str(result.get("tool_name", ""))
        result_status = _status_value(result.get("result_status", "unknown"))
        data = result.get("data")
        call_plan = plan_calls.get(str(call_id), {})
        shop_id = str(result.get("shop_id", "") or call_plan.get("target_shop_id", "")).strip()
        if not shop_id:
            continue
        row = rows_by_shop_id.setdefault(
            shop_id,
            {
                "shop_id": shop_id,
                "shop_name": "",
                "detail_status": "unknown",
                "open_status": "unknown",
                "coupon_status": "unknown",
                "rating": None,
                "distance_km": None,
                "eta_minutes": None,
                "coupon_titles": [],
                "avg_price": None,
                "tags": [],
                "address": "",
            },
        )

        if tool_name == "get_shop_detail":
            row["detail_status"] = result_status
            if result_status == "ok" and isinstance(data, dict):
                row["shop_name"] = data.get("shop_name", row.get("shop_name", ""))
                row["rating"] = data.get("rating", row.get("rating"))
                row["avg_price"] = data.get("avg_price", row.get("avg_price"))
                row["tags"] = data.get("tags", row.get("tags", []))
                row["address"] = data.get("address", row.get("address", ""))
        elif tool_name == "check_open_status":
            if result_status == "ok" and isinstance(data, dict):
                row["open_status"] = str(data.get("open_status", "unknown"))
        elif tool_name == "get_coupon_list":
            if result_status == "ok" and isinstance(data, list):
                titles = [item.get("title", "") for item in data if isinstance(item, dict) and item.get("title")]
                row["coupon_titles"] = titles
                row["coupon_status"] = "has_coupon" if titles else "empty"
            elif result_status == "empty":
                row["coupon_titles"] = []
                row["coupon_status"] = "empty"
            else:
                row["coupon_status"] = "unknown"
        elif tool_name == "get_distance_eta":
            if result_status == "ok" and isinstance(data, dict):
                row["distance_km"] = data.get("distance_km", row.get("distance_km"))
                row["eta_minutes"] = data.get("eta_minutes", row.get("eta_minutes"))

    rows: list[dict[str, Any]] = []
    for idx, shop_id in enumerate(target_ids or list(rows_by_shop_id.keys()), start=1):
        row = dict(rows_by_shop_id.get(shop_id, {"shop_id": shop_id, "shop_name": ""}))
        row.setdefault("shop_id", shop_id)
        row.setdefault("shop_name", "")
        row.setdefault("detail_status", "unknown")
        row.setdefault("open_status", "unknown")
        row.setdefault("coupon_status", "unknown")
        row.setdefault("rating", None)
        row.setdefault("distance_km", None)
        row.setdefault("eta_minutes", None)
        row.setdefault("coupon_titles", [])
        row["rank"] = idx
        row["overall_score"], row["known_dimensions"] = _comparison_dimension_score(row)
        rows.append(row)

    overall_ranked = sorted(
        rows,
        key=lambda item: (
            -float(item.get("overall_score", 0.0) or 0.0),
            -int(item.get("known_dimensions", 0) or 0),
            -float(item.get("rating", 0.0) or 0.0),
            float(item.get("distance_km", 9999.0) or 9999.0),
            str(item.get("shop_id", "")),
        ),
    )

    cells: list[dict[str, Any]] = []
    unknown_cells: list[dict[str, Any]] = []
    failed_cells: list[dict[str, Any]] = []

    def _map_to_ok_status(s: str) -> str:
        s_lower = str(s or "").lower()
        if s_lower in {"ok", "has_coupon", "empty", "open", "closed"}:
            return "ok"
        if s_lower in {"failed", "circuit_open"}:
            return s_lower
        return "unknown"

    for row in rows:
        row_cells = []
        
        # Rating cell
        rating_val = row.get("rating")
        rating_status = "ok" if rating_val is not None else _map_to_ok_status(row.get("detail_status", "unknown"))
        row_cells.append(
            {
                "shop_id": row["shop_id"],
                "shop_name": row["shop_name"],
                "facet": "rating",
                "dimension": "rating",
                "status": rating_status,
                "result_status": rating_status,
                "value": rating_val,
                "evidence_ref": "",
                "eligible_for_comparison": (rating_status == "ok"),
            }
        )

        # Distance cell
        distance_val = row.get("distance_km")
        distance_status = "ok" if distance_val is not None else "unknown"
        row_cells.append(
            {
                "shop_id": row["shop_id"],
                "shop_name": row["shop_name"],
                "facet": "distance",
                "dimension": "distance",
                "status": distance_status,
                "result_status": distance_status,
                "value": distance_val,
                "evidence_ref": "",
                "eligible_for_comparison": (distance_status == "ok"),
            }
        )

        # Open status cell
        open_val = row.get("open_status")
        open_status_str = str(open_val or "unknown").lower()
        open_status_status = "ok" if open_status_str in {"open", "closed"} else _map_to_ok_status(open_val)
        row_cells.append(
            {
                "shop_id": row["shop_id"],
                "shop_name": row["shop_name"],
                "facet": "open_status",
                "dimension": "open_status",
                "status": open_status_status,
                "result_status": open_status_status,
                "value": open_val,
                "eligible_for_comparison": (open_status_status == "ok"),
            }
        )

        # Coupon cell
        coupon_val = row.get("coupon_status")
        coupon_status_status = "ok" if coupon_val in {"has_coupon", "empty"} else _map_to_ok_status(coupon_val)
        coupon_cell_value = len(row.get("coupon_titles", [])) if coupon_val == "has_coupon" else coupon_val
        row_cells.append(
            {
                "shop_id": row["shop_id"],
                "shop_name": row["shop_name"],
                "facet": "coupon",
                "dimension": "coupon",
                "status": coupon_status_status,
                "result_status": coupon_status_status,
                "value": coupon_cell_value,
                "evidence_ref": "",
                "eligible_for_comparison": (coupon_status_status == "ok"),
            }
        )

        for cell in row_cells:
            cells.append(cell)
            if cell["status"] == "unknown":
                unknown_cells.append(cell)
            elif cell["status"] in {"failed", "circuit_open"}:
                failed_cells.append(cell)

    dimension_winners: dict[str, list[dict[str, Any]]] = {}
    known_ratings = [row for row in rows if row.get("rating") is not None]
    if len(known_ratings) >= 2:
        best_rating = max(float(row.get("rating", 0.0) or 0.0) for row in known_ratings)
        dimension_winners["rating"] = [
            {"shop_id": row["shop_id"], "shop_name": row["shop_name"], "value": row.get("rating")}
            for row in known_ratings
            if float(row.get("rating", 0.0) or 0.0) == best_rating
        ]

    known_distances = [row for row in rows if row.get("distance_km") is not None]
    if len(known_distances) >= 2:
        best_distance = min(float(row.get("distance_km", 9999.0) or 9999.0) for row in known_distances)
        dimension_winners["distance"] = [
            {"shop_id": row["shop_id"], "shop_name": row["shop_name"], "value": row.get("distance_km")}
            for row in known_distances
            if float(row.get("distance_km", 9999.0) or 9999.0) == best_distance
        ]

    open_rows = [row for row in rows if str(row.get("open_status", "")).lower() == "open"]
    if len([row for row in rows if str(row.get("open_status", "")).lower() in {"open", "closed"}]) >= 2 and open_rows:
        dimension_winners["open_status"] = [
            {"shop_id": row["shop_id"], "shop_name": row["shop_name"], "value": "open"}
            for row in open_rows
        ]

    coupon_rows = [row for row in rows if row.get("coupon_status") == "has_coupon"]
    if len([row for row in rows if row.get("coupon_status") in {"has_coupon", "empty"}]) >= 2 and coupon_rows:
        dimension_winners["coupon"] = [
            {"shop_id": row["shop_id"], "shop_name": row["shop_name"], "value": len(row.get("coupon_titles", []))}
            for row in coupon_rows
        ]

    uncertainty_notes: list[str] = []
    for row in rows:
        if row.get("open_status") == "unknown":
            uncertainty_notes.append(f"{row.get('shop_name') or row.get('shop_id')}营业状态暂无法确认")
        if row.get("coupon_status") == "unknown":
            uncertainty_notes.append(f"{row.get('shop_name') or row.get('shop_id')}优惠暂无法确认")
        if row.get("distance_km") is None:
            uncertainty_notes.append(f"{row.get('shop_name') or row.get('shop_id')}距离暂无法确认")

    from ..domain.schemas import ComparisonMatrix
    matrix_dict = {
        "matrix_id": f"cmp_{plan_dict.get('plan_id', '') or 'matrix'}",
        "status": "ok" if rows else "unknown",
        "rows": rows,
        "cells": cells,
        "unknown_cells": unknown_cells,
        "failed_cells": failed_cells,
        "dimension_winners": dimension_winners,
        "uncertainty_notes": uncertainty_notes,
        "overall_ranked": overall_ranked,
        "overall_ranking": overall_ranked,
    }
    # Perform strict schemas validation
    ComparisonMatrix.model_validate(matrix_dict)

    return {
        "target_shop_ids": target_ids,
        "requested_facets": ["detail", "open_status", "coupon", "distance"],
        "facet_results": [],
        "evidence_items": [],
        "unknown_items": [],
        "forbidden_claims": [],
        "ranking_snapshot": {
            "snapshot_id": f"comparison_{plan_dict.get('plan_id', '') or 'snapshot'}",
            "status": "ok" if rows else "unknown",
            "ranked": overall_ranked,
            "ranked_shops": overall_ranked,
            "candidate_count": len(rows),
        },
        "comparison_matrix": matrix_dict,
        "tool_results": tool_results or {},
    }


def build_evidence(
    tool_results: dict,
    resolved_target: dict,
    execution_plan: Any | None = None,
    recommendation_candidates: list[Any] | None = None,
    comparison_targets: list[Any] | None = None,
) -> dict:
    """Build an evidence pack from tool results."""
    resolved_target = _to_dict(resolved_target)
    shop_id, shop_name = _first_shop_name(resolved_target)
    plan_dict = _to_dict(execution_plan)
    plan_calls = {}
    if execution_plan is not None:
        for call in plan_dict.get("tool_calls", []) or []:
            call_dict = _to_dict(call)
            call_id = str(call_dict.get("call_id", "")).strip()
            if call_id:
                plan_calls[call_id] = call_dict

    task_type = str(plan_dict.get("task_type", ""))
    if task_type == "comparison":
        return _build_comparison_evidence(
            tool_results or {},
            plan_calls,
            plan_dict,
            comparison_targets or [],
        )

    evidence_items: list[dict[str, Any]] = []
    unknown_items: list[dict[str, Any]] = []
    facet_results: list[dict[str, Any]] = []
    requested_facets: list[str] = []
    facet_statuses: dict[str, str] = {}
    coupon_titles: list[str] = []
    coupon_count = 0
    open_status = "unknown"
    distance_km: float | None = None
    eta_minutes: int | None = None
    overall_status = "unknown"
    error_code = ""
    error_message = ""

    for call_id, tool_result in (tool_results or {}).items():
        result = _to_dict(tool_result)
        tool_name = result.get("tool_name", "")
        facet = _facet_name_from_tool(tool_name)
        result_status = _status_value(result.get("result_status", "unknown"))
        data = result.get("data")
        call_plan = plan_calls.get(str(call_id), {})
        requested_facets.append(facet)
        facet_statuses[facet] = _facet_status_summary(result_status, data)
        facet_results.append(
            {
                "facet": facet,
                "required": bool(call_plan.get("required", result.get("required", True))),
                "status": facet_statuses[facet],
                "tool_name": tool_name,
                "call_id": call_id,
                "error_code": result.get("error_code", ""),
                "error_message": result.get("error_message", ""),
                **_facet_result_payload(facet, result_status, data),
            }
        )
        error_code = result.get("error_code") or error_code
        error_message = result.get("error_message", "") or error_message

        if facet == "coupon":
            if result_status == "ok" and isinstance(data, list):
                coupon_count = len(data)
                for idx, coupon in enumerate(data):
                    coupon = coupon if isinstance(coupon, dict) else {}
                    title = coupon.get("title", "")
                    if title:
                        coupon_titles.append(title)
                    evidence_items.append(
                        {
                            "evidence_id": f"evi_coupon_{idx + 1}",
                            "shop_id": coupon.get("shop_id", shop_id),
                            "shop_name": shop_name,
                            "facet": "coupon",
                            "tool_name": "get_coupon_list",
                            "call_id": call_id,
                            "result_status": "ok",
                            "field_path": f"data[{idx}].title",
                            "value": title or coupon.get("description", ""),
                            "confidence": 1.0,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "source_type": "tool",
                        }
                    )
            elif result_status == "empty":
                coupon_count = 0
                evidence_items.append(
                    {
                        "evidence_id": "evi_coupon_empty",
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "facet": "coupon",
                        "tool_name": "get_coupon_list",
                        "call_id": call_id,
                        "result_status": "empty",
                        "field_path": "data",
                        "value": "empty",
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            else:
                unknown_items.append(
                    {
                        "evidence_id": f"evi_unknown_{len(unknown_items) + 1}",
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "facet": "coupon",
                        "tool_name": "get_coupon_list",
                        "call_id": call_id,
                        "result_status": result_status,
                        "field_path": "",
                        "value": None,
                        "confidence": 0.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
        elif facet == "open_status":
            if result_status == "ok" and isinstance(data, dict):
                open_status = str(data.get("open_status", "unknown"))
                evidence_items.append(
                    {
                        "evidence_id": "evi_open_status",
                        "shop_id": data.get("shop_id", shop_id),
                        "shop_name": data.get("shop_name", shop_name),
                        "facet": "open_status",
                        "tool_name": "check_open_status",
                        "call_id": call_id,
                        "result_status": "ok",
                        "field_path": "data.open_status",
                        "value": open_status,
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            elif result_status != "empty":
                unknown_items.append(
                    {
                        "evidence_id": f"evi_unknown_{len(unknown_items) + 1}",
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "facet": "open_status",
                        "tool_name": "check_open_status",
                        "call_id": call_id,
                        "result_status": result_status,
                        "field_path": "",
                        "value": None,
                        "confidence": 0.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
        elif facet == "distance":
            if result_status == "ok" and isinstance(data, dict):
                distance_km = data.get("distance_km", distance_km)
                eta_minutes = data.get("eta_minutes", eta_minutes)
                evidence_items.append(
                    {
                        "evidence_id": "evi_distance",
                        "shop_id": data.get("shop_id", shop_id),
                        "shop_name": data.get("shop_name", shop_name),
                        "facet": "distance",
                        "tool_name": "get_distance_eta",
                        "call_id": call_id,
                        "result_status": "ok",
                        "field_path": "data.distance_km",
                        "value": distance_km,
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            elif result_status != "empty":
                unknown_items.append(
                    {
                        "evidence_id": f"evi_unknown_{len(unknown_items) + 1}",
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "facet": "distance",
                        "tool_name": "get_distance_eta",
                        "call_id": call_id,
                        "result_status": result_status,
                        "field_path": "",
                        "value": None,
                        "confidence": 0.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )

    required_statuses = [item["status"] for item in facet_results if item["required"]]
    if any(status == "circuit_open" for status in required_statuses):
        overall_status = "circuit_open"
    elif any(status == "failed" for status in required_statuses):
        overall_status = "failed"
    elif any(status == "unknown" for status in required_statuses):
        overall_status = "unknown"
    elif required_statuses and all(status == "empty" for status in required_statuses):
        overall_status = "empty"
    elif facet_results and all(item["status"] == "empty" for item in facet_results):
        overall_status = "empty"
    elif facet_results and any(item["status"] == "ok" for item in facet_results):
        overall_status = "ok"

    if overall_status == "unknown" and not facet_results:
        overall_status = "unknown"

    ranking_snapshot = {
        "status": overall_status,
        "shop_id": shop_id,
        "shop_name": shop_name,
        "coupon_count": coupon_count,
        "coupon_titles": coupon_titles,
        "open_status": open_status,
        "distance_km": distance_km,
        "eta_minutes": eta_minutes,
        "requested_facets": requested_facets,
        "facet_statuses": facet_statuses,
        "facet_results": facet_results,
        "resolved": bool(shop_id),
    }

    forbidden_claims: list[str] = []
    for facet, status in facet_statuses.items():
        if status in {"unknown", "failed", "circuit_open"}:
            forbidden_claims.extend(_facet_claims_for_status(facet, status))

    comparison_matrix = {
        "status": overall_status,
        "error_code": error_code,
        "error_message": error_message,
        "facet_statuses": facet_statuses,
    }

    if str(plan_dict.get("task_type", "")) == "recommendation":
        return _build_recommendation_evidence(
            recommendation_candidates or [],
            tool_results or {},
            plan_calls,
            plan_dict,
        )

    return {
        "target_shop_ids": [shop_id] if shop_id else [],
        "requested_facets": requested_facets,
        "facet_results": facet_results,
        "evidence_items": evidence_items,
        "unknown_items": unknown_items,
        "forbidden_claims": forbidden_claims,
        "ranking_snapshot": ranking_snapshot,
        "comparison_matrix": comparison_matrix,
        "tool_results": tool_results or {},
    }


def _build_recommendation_evidence(
    recommendation_candidates: list[Any],
    tool_results: dict,
    plan_calls: dict[str, dict[str, Any]],
    plan_dict: dict[str, Any],
) -> dict[str, Any]:
    if not recommendation_candidates:
        recommendation_candidates = _search_result_candidates(tool_results, plan_calls)
    candidates_by_shop_id: dict[str, dict[str, Any]] = {}
    for raw_candidate in recommendation_candidates:
        candidate = _candidate_from_shop(raw_candidate)
        shop_id = str(candidate.get("shop_id", "")).strip()
        if shop_id:
            candidates_by_shop_id[shop_id] = candidate

    detail_failed_shop_ids: set[str] = set()
    open_status_by_shop_id: dict[str, str] = {}
    coupon_count_by_shop_id: dict[str, int | None] = {}
    evidence_items: list[dict[str, Any]] = []
    unknown_items: list[dict[str, Any]] = []

    for call_id, tool_result in (tool_results or {}).items():
        result = _to_dict(tool_result)
        tool_name = str(result.get("tool_name", ""))
        result_status = _status_value(result.get("result_status", "unknown"))
        data = result.get("data")
        call_plan = plan_calls.get(str(call_id), {})
        shop_id = str(result.get("shop_id", "") or call_plan.get("target_shop_id", "")).strip()
        if not shop_id:
            continue

        candidate = candidates_by_shop_id.setdefault(shop_id, {"shop_id": shop_id, "shop_name": ""})

        if tool_name == "get_shop_detail":
            if result_status == "ok" and isinstance(data, dict):
                candidate.update(data)
                candidate["detail_failed"] = False
                evidence_items.append(
                    {
                        "evidence_id": f"evi_detail_{shop_id}",
                        "shop_id": shop_id,
                        "shop_name": candidate.get("shop_name", ""),
                        "facet": "detail",
                        "tool_name": "get_shop_detail",
                        "call_id": call_id,
                        "result_status": "ok",
                        "field_path": "data",
                        "value": {
                            "rating": data.get("rating"),
                            "avg_price": data.get("avg_price"),
                            "address": data.get("address"),
                            "tags": data.get("tags", []),
                        },
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            elif result_status != "empty":
                candidate["detail_failed"] = True
                detail_failed_shop_ids.add(shop_id)
        elif tool_name == "check_open_status":
            if result_status == "ok" and isinstance(data, dict):
                open_status = str(data.get("open_status", "unknown"))
                candidate["open_status"] = open_status
                open_status_by_shop_id[shop_id] = open_status
                evidence_items.append(
                    {
                        "evidence_id": f"evi_open_{shop_id}",
                        "shop_id": shop_id,
                        "shop_name": candidate.get("shop_name", ""),
                        "facet": "open_status",
                        "tool_name": "check_open_status",
                        "call_id": call_id,
                        "result_status": "ok",
                        "field_path": "data.open_status",
                        "value": open_status,
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            elif result_status != "empty":
                candidate["open_status"] = "unknown"
                open_status_by_shop_id.setdefault(shop_id, "unknown")
        elif tool_name == "get_coupon_list":
            if result_status == "ok" and isinstance(data, list):
                coupon_count_by_shop_id[shop_id] = len(data)
                candidate["coupon_count"] = len(data)
                evidence_items.append(
                    {
                        "evidence_id": f"evi_coupon_{shop_id}",
                        "shop_id": shop_id,
                        "shop_name": candidate.get("shop_name", ""),
                        "facet": "coupon",
                        "tool_name": "get_coupon_list",
                        "call_id": call_id,
                        "result_status": "ok",
                        "field_path": "data",
                        "value": [item.get("title", "") for item in data if isinstance(item, dict) and item.get("title")],
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            elif result_status == "empty":
                coupon_count_by_shop_id[shop_id] = 0
                candidate["coupon_count"] = 0
                evidence_items.append(
                    {
                        "evidence_id": f"evi_coupon_empty_{shop_id}",
                        "shop_id": shop_id,
                        "shop_name": candidate.get("shop_name", ""),
                        "facet": "coupon",
                        "tool_name": "get_coupon_list",
                        "call_id": call_id,
                        "result_status": "empty",
                        "field_path": "data",
                        "value": "empty",
                        "confidence": 1.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
            else:
                unknown_items.append(
                    {
                        "evidence_id": f"evi_unknown_coupon_{shop_id}",
                        "shop_id": shop_id,
                        "shop_name": candidate.get("shop_name", ""),
                        "facet": "coupon",
                        "tool_name": "get_coupon_list",
                        "call_id": call_id,
                        "result_status": result_status,
                        "field_path": "",
                        "value": None,
                        "confidence": 0.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )

    surviving_candidates: list[dict[str, Any]] = []
    for candidate in candidates_by_shop_id.values():
        shop_id = str(candidate.get("shop_id", "")).strip()
        if not shop_id:
            continue
        if candidate.get("detail_failed") or shop_id in detail_failed_shop_ids:
            continue
        if str(candidate.get("open_status", "")).lower() == "closed":
            continue
        candidate["open_status"] = open_status_by_shop_id.get(shop_id, candidate.get("open_status", "unknown"))
        if "coupon_count" not in candidate:
            candidate["coupon_count"] = coupon_count_by_shop_id.get(shop_id)
        surviving_candidates.append(candidate)

    preferences = {
        "query_terms": _as_list(plan_dict.get("query_terms")),
        "scene_terms": _as_list(plan_dict.get("scene_terms")),
    }
    ranked = rank_candidates(surviving_candidates, preferences)
    top_ranked = ranked[: config.RECOMMENDATION_FINAL_TOP_K]
    ranked_snapshot = []
    for idx, item in enumerate(top_ranked, start=1):
        ranked_snapshot.append(
            {
                "rank": idx,
                "shop_id": item.get("shop_id", ""),
                "shop_name": item.get("shop_name", ""),
                "rating": item.get("rating"),
                "distance_km": item.get("distance_km"),
                "eta_minutes": item.get("eta_minutes"),
                "open_status": item.get("open_status", "unknown"),
                "coupon_count": item.get("coupon_count"),
                "score": item.get("score", 0.0),
                "total_score": item.get("total_score", item.get("score", 0.0)),
                "component_scores": item.get("component_scores", {}),
                "reason_codes": item.get("reason_codes", []),
                "degradation_notes": item.get("degradation_notes", []),
                "evidence_refs": item.get("evidence_refs", []),
                "score_breakdown": item.get("score_breakdown", {}),
            }
        )

    ranking_snapshot = {
        "snapshot_id": f"recommendation_{plan_dict.get('plan_id', '') or 'snapshot'}",
        "status": "ok" if ranked_snapshot else ("empty" if recommendation_candidates else "unknown"),
        "strategy": "category_match*30 + open_status_score*25 + distance_score*20 + rating_score*15 + coupon_score*10 + tag_match_score*10 - risk_penalty",
        "ranked": ranked_snapshot,
        "ranked_shops": ranked_snapshot,
        "query_terms": plan_dict.get("query_terms", []),
        "scene_terms": plan_dict.get("scene_terms", []),
        "candidate_count": len(recommendation_candidates),
    }

    forbidden_claims = []
    for candidate in recommendation_candidates:
        candidate_dict = _candidate_from_shop(candidate)
        if candidate_dict.get("detail_failed"):
            forbidden_claims.append(str(candidate_dict.get("shop_name", "")))

    return {
        "target_shop_ids": [item["shop_id"] for item in ranked_snapshot],
        "requested_facets": ["rating", "distance", "open_status", "coupon"],
        "facet_results": [],
        "evidence_items": evidence_items,
        "unknown_items": unknown_items,
        "forbidden_claims": forbidden_claims,
        "ranking_snapshot": ranking_snapshot,
        "comparison_matrix": {
            "status": ranking_snapshot["status"],
            "error_code": "",
            "error_message": "",
            "facet_statuses": {},
        },
        "last_recommendation_list": ranked_snapshot,
        "tool_results": tool_results or {},
    }
