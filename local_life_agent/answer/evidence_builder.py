"""Evidence builder for the single-shop multi-facet flow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..domain.enums import ToolResultStatus


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


def build_evidence(tool_results: dict, resolved_target: dict, execution_plan: Any | None = None) -> dict:
    """Build an evidence pack from tool results."""
    resolved_target = _to_dict(resolved_target)
    shop_id, shop_name = _first_shop_name(resolved_target)
    plan_calls = {}
    if execution_plan is not None:
        plan_dict = _to_dict(execution_plan)
        for call in plan_dict.get("tool_calls", []) or []:
            call_dict = _to_dict(call)
            call_id = str(call_dict.get("call_id", "")).strip()
            if call_id:
                plan_calls[call_id] = call_dict

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

    return {
        "target_shop_ids": [shop_id] if shop_id else [],
        "requested_facets": requested_facets,
        "evidence_items": evidence_items,
        "unknown_items": unknown_items,
        "forbidden_claims": forbidden_claims,
        "ranking_snapshot": ranking_snapshot,
        "comparison_matrix": comparison_matrix,
    }
