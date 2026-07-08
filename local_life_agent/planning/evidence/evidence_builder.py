"""Evidence builder for the single-shop multi-facet flow."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from ... import config
from ...domain.enums import ToolResultStatus
from .evidence_cache import EvidenceCache, get_default_evidence_cache
from ..policies.ranking_policy import derive_comparison_winner, rank_candidates


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


def _coerce_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _identity_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _candidate_identity_key(candidate: Any) -> tuple[Any, ...]:
    data = _candidate_from_shop(candidate)
    shop_name = _identity_text(data.get("shop_name") or data.get("name"))
    address = _identity_text(data.get("address") or data.get("shop_address"))
    branch = _identity_text(data.get("branch_name") or data.get("branch") or data.get("branch_name_full"))
    lat = data.get("lat")
    lng = data.get("lng")
    try:
        lat_text = f"{float(lat):.5f}" if lat is not None else ""
        lng_text = f"{float(lng):.5f}" if lng is not None else ""
    except Exception:
        lat_text = ""
        lng_text = ""

    if shop_name and address:
        return ("name_address", shop_name, address)
    if shop_name and branch:
        return ("name_branch", shop_name, branch)
    if shop_name and lat_text and lng_text:
        return ("name_coords", shop_name, lat_text, lng_text)
    if shop_name:
        return ("name", shop_name)

    shop_id = _identity_text(data.get("shop_id"))
    if shop_id:
        return ("shop_id", shop_id)
    return ("raw", tuple(sorted((str(key), str(value)) for key, value in data.items())))


def _status_value(value: Any) -> str:
    if isinstance(value, ToolResultStatus):
        return value.value
    if isinstance(value, str):
        return value
    return str(value or "unknown")


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw_value = getattr(value, "value", None)
    if raw_value is not None:
        return str(raw_value)
    return str(value)


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
        "calculate_distance_km": "distance",
        "get_shop_cards": "shop_cards",
        "get_shop_review_summary": "review_summary",
        "get_deal_list": "deal",
    }.get(tool_name, "unknown")


def _facet_claims_for_status(facet: str, status: str) -> list[str]:
    if facet == "coupon":
        if status in {"unknown", "failed", "circuit_open", "error", "backend_unavailable"}:
            return ["有券", "有可用券", "当前暂无可用券", "暂无可用券", "没有券"]
    elif facet == "open_status":
        if status in {"unknown", "failed", "circuit_open", "error", "backend_unavailable"}:
            return ["营业中", "正在营业", "已打烊", "已关门", "不营业"]
    elif facet == "distance":
        if status in {"unknown", "failed", "circuit_open", "error", "backend_unavailable"}:
            return ["很近", "不远", "很远", "x公里", "km"]
    return []


def _facet_status_summary(result_status: str, data: Any) -> str:
    if result_status in {"failed", "error", "circuit_open", "unknown", "backend_unavailable"}:
        return result_status
    if result_status == "empty":
        return "empty"
    if result_status in {"ok", "partial"}:
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
            open_status = data.get("open_status")
            if open_status is None:
                if data.get("is_open") is True:
                    open_status = "open"
                elif data.get("is_open") is False:
                    open_status = "closed"
                else:
                    open_status = data.get("open_status_text", "unknown")
            payload["value"] = open_status
    elif facet == "distance":
        if result_status == "ok" and isinstance(data, dict):
            payload["value"] = {
                "distance_km": data.get("distance_km"),
                "eta_minutes": data.get("eta_minutes"),
                "method": data.get("method", "haversine"),
                "blocked_reason": data.get("blocked_reason"),
            }
    elif facet == "shop_cards":
        if result_status in {"ok", "partial"} and isinstance(data, dict):
            payload["value"] = [item.get("name", "") for item in data.get("items", []) if isinstance(item, dict) and item.get("name")]
    elif facet == "review_summary":
        if result_status in {"ok", "partial"} and isinstance(data, dict):
            payload["value"] = [item.get("summary", "") for item in data.get("items", []) if isinstance(item, dict) and item.get("summary")]
    elif facet == "deal":
        if result_status in {"ok", "partial"} and isinstance(data, dict):
            payload["value"] = [item.get("title", "") for item in data.get("items", []) if isinstance(item, dict) and item.get("title")]
    return payload


def _items_from_tool_data(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("items", [])
        return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _candidate_items_from_tool_data(data: Any) -> list[dict[str, Any]]:
    items = _items_from_tool_data(data)
    if items:
        return items
    if isinstance(data, dict):
        for key in ("data", "items", "shops", "results"):
            nested = data.get(key)
            nested_items = _candidate_items_from_tool_data(nested)
            if nested_items:
                return nested_items
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and str(item.get("shop_id", "")).strip()]
    return []


def _candidate_from_shop(shop: Any) -> dict[str, Any]:
    candidate = _to_dict(shop)
    if not candidate:
        return {}
    candidate.setdefault("shop_id", "")
    candidate.setdefault("shop_name", candidate.get("name", ""))
    candidate.setdefault("category", "")
    candidate.setdefault("tags", candidate.get("scene_tags") or candidate.get("top_tags") or [])
    candidate.setdefault("rating", 0)
    if candidate.get("distance_km") is None and candidate.get("distance_m") is not None:
        try:
            candidate["distance_km"] = float(candidate.get("distance_m")) / 1000.0
        except Exception:
            candidate["distance_km"] = None
    candidate.setdefault("distance_km", None)
    candidate.setdefault("eta_minutes", None)
    candidate.setdefault("open_status", candidate.get("open_status", "unknown"))
    candidate.setdefault("coupon_count", candidate.get("coupon_count"))
    return candidate


def _normalize_open_status_value(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    open_status = data.get("open_status")
    if open_status is not None and str(open_status).strip():
        return str(open_status).strip().lower()
    if data.get("is_open") is True:
        return "open"
    if data.get("is_open") is False:
        return "closed"
    return str(data.get("open_status_text", "unknown") or "unknown").strip().lower()


def _search_result_candidates(tool_results: dict, plan_calls: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for call_id, tool_result in (tool_results or {}).items():
        result = _to_dict(tool_result)
        tool_name = str(result.get("tool_name", ""))
        data = result.get("data")
        if tool_name == "search_shops":
            limit = config.RECOMMENDATION_CANDIDATE_TOP_K
            call_plan = plan_calls.get(str(call_id), {})
            try:
                limit = min(limit, int(call_plan.get("args", {}).get("limit", config.SEARCH_LIMIT)))
            except Exception:
                limit = config.RECOMMENDATION_CANDIDATE_TOP_K
            for item in _candidate_items_from_tool_data(data)[:limit]:
                candidate = _candidate_from_shop(item)
                if candidate.get("shop_id"):
                    candidates.append(candidate)
        elif tool_name == "get_shop_cards":
            for item in _candidate_items_from_tool_data(data):
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


def _evidence_backend_source(tool_results: dict, call_id: Any) -> str:
    result = _to_dict((tool_results or {}).get(str(call_id), {}))
    return (
        str(result.get("backend_source", "") or "")
        or str(result.get("tool_backend", "") or "")
        or str(result.get("source", "") or "")
        or "unknown"
    )


def _attach_backend_source(items: list[dict[str, Any]], tool_results: dict) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        if not str(row.get("backend_source", "") or "").strip():
            row["backend_source"] = _evidence_backend_source(tool_results, row.get("call_id", ""))
        enriched.append(row)
    return enriched


def _facet_protocol_metadata(execution_plan: Any, resolved_target: dict[str, Any]) -> dict[str, Any]:
    plan_dict = _to_dict(execution_plan)
    if "plan" in plan_dict and isinstance(plan_dict.get("plan"), (dict, object)):
        nested_plan = _to_dict(plan_dict.get("plan"))
        if nested_plan:
            plan_dict = nested_plan
    facet_set = _to_dict(plan_dict.get("facet_set"))
    facets = plan_dict.get("facets") or facet_set.get("facets") or []
    conflicting_facets = plan_dict.get("conflicting_facets") or facet_set.get("conflicting_facets") or []
    ranking_policy = plan_dict.get("ranking_policy") or facet_set.get("ranking_policy")
    target_resolution = plan_dict.get("target_resolution") or facet_set.get("target_resolution")
    if not target_resolution:
        resolved_dict = _to_dict(resolved_target)
        if str(resolved_dict.get("resolved", "")).lower() == "true" or str(resolved_dict.get("status", "")).upper() == "RESOLVED":
            target_shop = resolved_dict.get("target_shop") or resolved_dict.get("resolved_shop") or resolved_dict.get("shop")
            target_resolution = {
                "resolved": True,
                "target_shop": _to_dict(target_shop),
                "source": resolved_dict.get("source") or resolved_dict.get("reference_resolution_source") or "resolved_target",
                "confidence": float(resolved_dict.get("confidence", 1.0) or 1.0),
                "owner": resolved_dict.get("owner") or "execution_review_subgraph",
                "resolution_reason": resolved_dict.get("resolution_reason") or resolved_dict.get("reason") or "resolved_target",
                "reference_type": resolved_dict.get("reference_type") or resolved_dict.get("reference"),
                "unresolved_reason": resolved_dict.get("unresolved_reason"),
            }
        elif resolved_dict:
            target_resolution = {
                "resolved": bool(resolved_dict.get("resolved", False)),
                "target_shop": _to_dict(resolved_dict.get("target_shop")),
                "source": resolved_dict.get("source"),
                "confidence": float(resolved_dict.get("confidence", 0.0) or 0.0),
                "owner": resolved_dict.get("owner") or "execution_review_subgraph",
                "resolution_reason": resolved_dict.get("resolution_reason") or resolved_dict.get("reason") or "",
                "reference_type": resolved_dict.get("reference_type"),
                "unresolved_reason": resolved_dict.get("unresolved_reason"),
            }
    return {
        "facets": [dict(item) if isinstance(item, dict) else _to_dict(item) for item in facets or []],
        "target_resolution": _to_dict(target_resolution) if target_resolution else None,
        "conflicting_facets": [dict(item) if isinstance(item, dict) else _to_dict(item) for item in conflicting_facets or []],
        "ranking_policy": _to_dict(ranking_policy) if ranking_policy else None,
    }


def _facet_triage_from_results(facet_results: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    answerable: list[str] = []
    unknown: list[str] = []
    failed: list[str] = []
    for item in facet_results or []:
        facet = str((item or {}).get("facet", "") or "").strip()
        if not facet:
            continue
        status = str((item or {}).get("status", (item or {}).get("result_status", "unknown")) or "unknown").lower()
        if status in {"ok", "partial"}:
            if facet not in answerable:
                answerable.append(facet)
        elif status in {"failed", "error", "circuit_open", "backend_unavailable"}:
            if facet not in failed:
                failed.append(facet)
        else:
            if facet not in unknown:
                unknown.append(facet)
    return {
        "answerable_facets": answerable,
        "unknown_facets": unknown,
        "failed_facets": failed,
    }


def _facet_status_label(raw_status: Any) -> str:
    status = str(raw_status or "unknown").strip().lower()
    if status in {"ok", "grounded", "supported"}:
        return "grounded"
    if status == "empty":
        return "empty"
    if status == "partial":
        return "partial"
    if status in {"failed", "error", "timeout", "circuit_open", "backend_unavailable"}:
        return "failed"
    if status == "unsupported":
        return "unsupported"
    return "unknown"


def _distance_blocked_reason(location: dict[str, Any] | None) -> str:
    location_dict = _to_dict(location)
    if location_dict.get("lat") is None or location_dict.get("lng") is None:
        return "distance_tool_missing_or_location_unresolved"
    return "distance_tool_missing_or_unavailable"


def _facet_contract_from_target(
    target: dict[str, Any] | None,
    *,
    location: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    item = _to_dict(target)
    facet_statuses: dict[str, str] = {}
    grounded_facts: dict[str, Any] = {}
    facet_reasons: dict[str, str] = {}

    open_status = str(item.get("open_status", "unknown") or "unknown").lower()
    if open_status in {"open", "closed"}:
        facet_statuses["open_status"] = "grounded"
        grounded_facts["open_status"] = open_status
    elif open_status == "empty":
        facet_statuses["open_status"] = "empty"
    elif open_status in {"failed", "circuit_open", "error", "backend_unavailable", "timeout"}:
        facet_statuses["open_status"] = "failed"
        facet_reasons["open_status"] = str(item.get("open_reason") or item.get("open_status_reason") or "open_status_tool_failed")
    elif open_status in {"partial"}:
        facet_statuses["open_status"] = "partial"
    else:
        facet_statuses["open_status"] = "unknown"
        grounded_facts["open_status"] = open_status
        facet_reasons["open_status"] = str(item.get("open_status_reason") or "open_status_unknown")

    coupon_status = str(item.get("coupon_status", "unknown") or "unknown").lower()
    coupon_titles = [str(title) for title in _coerce_list_value(item.get("coupon_titles")) if str(title).strip()]
    coupon_count = item.get("coupon_count")
    if coupon_status == "has_coupon" or coupon_titles:
        facet_statuses["coupon"] = "grounded"
        grounded_facts["coupon_count"] = int(coupon_count if coupon_count is not None else len(coupon_titles))
        grounded_facts["coupon_titles"] = coupon_titles
    elif coupon_status == "empty":
        facet_statuses["coupon"] = "empty"
        grounded_facts["coupon_count"] = 0
        grounded_facts["coupon_titles"] = []
    elif coupon_status in {"failed", "circuit_open", "error", "backend_unavailable", "timeout"}:
        facet_statuses["coupon"] = "failed"
        facet_reasons["coupon"] = str(item.get("coupon_reason") or item.get("coupon_status_reason") or "coupon_tool_failed")
    elif coupon_status == "partial":
        facet_statuses["coupon"] = "partial"
        facet_reasons["coupon"] = str(item.get("coupon_reason") or item.get("coupon_status_reason") or "coupon_partial")
    else:
        facet_statuses["coupon"] = "unknown"
        facet_reasons["coupon"] = str(item.get("coupon_reason") or item.get("coupon_status_reason") or "coupon_unknown")

    distance_km = item.get("distance_km")
    eta_minutes = item.get("eta_minutes")
    if distance_km is not None:
        facet_statuses["distance"] = "grounded"
        grounded_facts["distance_km"] = distance_km
        if eta_minutes is not None:
            grounded_facts["eta_minutes"] = eta_minutes
    else:
        distance_status = str(item.get("distance_status", "") or "").lower()
        blocked_reason = (
            item.get("distance_reason")
            or item.get("distance_blocked_reason")
            or _to_dict(item.get("distance")).get("blocked_reason")
        )
        if distance_status in {"failed", "circuit_open", "error", "backend_unavailable", "timeout"}:
            facet_statuses["distance"] = "failed"
            facet_reasons["distance"] = str(blocked_reason or _distance_blocked_reason(location))
        elif distance_status == "empty":
            facet_statuses["distance"] = "empty"
            facet_reasons["distance"] = str(blocked_reason or _distance_blocked_reason(location))
        elif distance_status == "partial":
            facet_statuses["distance"] = "partial"
            facet_reasons["distance"] = str(blocked_reason or _distance_blocked_reason(location))
        else:
            facet_statuses["distance"] = "unknown"
            facet_reasons["distance"] = str(blocked_reason or _distance_blocked_reason(location))

    rating = item.get("rating")
    if rating is not None:
        facet_statuses["rating"] = "grounded"
        grounded_facts["rating"] = rating
    elif "rating" not in facet_statuses:
        facet_statuses["rating"] = "unknown"

    avg_price = item.get("avg_price")
    if avg_price is not None:
        facet_statuses["avg_price"] = "grounded"
        grounded_facts["avg_price"] = avg_price
    elif "avg_price" not in facet_statuses:
        facet_statuses["avg_price"] = "unknown"

    return facet_statuses, grounded_facts, facet_reasons


def _merge_facet_contract_with_results(
    facet_statuses: dict[str, str],
    grounded_facts: dict[str, Any],
    facet_reasons: dict[str, str],
    facet_results: list[dict[str, Any]],
    *,
    location: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    merged_statuses = dict(facet_statuses)
    merged_grounded = dict(grounded_facts)
    merged_reasons = dict(facet_reasons)

    for result in facet_results or []:
        if not isinstance(result, dict):
            continue
        facet = str(result.get("facet") or "").strip()
        if not facet:
            continue
        status = _facet_status_label(result.get("status") or result.get("result_status"))
        if status in {"failed", "unknown", "partial", "empty"}:
            merged_statuses[facet] = status
        if status == "failed":
            merged_reasons.setdefault(facet, str(result.get("error_message") or result.get("error_code") or result.get("blocked_reason") or _distance_blocked_reason(location)))
        elif status in {"unknown", "partial", "empty"}:
            merged_reasons.setdefault(facet, str(result.get("error_message") or result.get("error_code") or result.get("blocked_reason") or _distance_blocked_reason(location)))

    return merged_statuses, merged_grounded, merged_reasons


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
        if tool_name in {"get_shop_cards", "get_shop_review_summary"}:
            for item in _items_from_tool_data(data):
                item_shop_id = str(item.get("shop_id", "")).strip()
                if not item_shop_id:
                    continue
                row = rows_by_shop_id.setdefault(
                    item_shop_id,
                    {
                        "shop_id": item_shop_id,
                        "shop_name": str(item.get("name", "") or item.get("shop_name", "")).strip(),
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
                if tool_name == "get_shop_cards":
                    row["shop_name"] = str(item.get("name", "") or row.get("shop_name", "")).strip()
                    row["rating"] = item.get("rating", row.get("rating"))
                    row["avg_price"] = item.get("avg_price", row.get("avg_price"))
                    row["tags"] = item.get("top_tags") or item.get("scene_tags") or row.get("tags", [])
                    row["address"] = item.get("address", row.get("address", ""))
                    row["open_status"] = str(item.get("open_status_text", item.get("open_status", "unknown")) or "unknown")
                    row["coupon_status"] = "has_coupon" if item.get("has_coupon") else "empty" if item.get("has_coupon") is False else row.get("coupon_status", "unknown")
                    row["coupon_titles"] = [item.get("top_coupon_title")] if item.get("top_coupon_title") else row.get("coupon_titles", [])
                    raw_km = item.get("distance_km")
                    if raw_km is not None:
                        try:
                            row["distance_km"] = float(raw_km)
                        except Exception:
                            pass
                    elif item.get("distance_m") is not None:
                        try:
                            row["distance_km"] = float(item["distance_m"]) / 1000.0
                        except Exception:
                            pass
                    if item.get("eta_minutes") is not None:
                        row["eta_minutes"] = item.get("eta_minutes")
                else:
                    row["shop_name"] = str(item.get("name", "") or row.get("shop_name", "")).strip()
                    row["rating"] = item.get("rating", row.get("rating"))
                    row["tags"] = item.get("scene_tags") or item.get("positive_tags") or row.get("tags", [])
                    scene_fit = item.get("scene_fit") if isinstance(item.get("scene_fit"), dict) else {}
                    if scene_fit:
                        row["scene_fit"] = scene_fit
            continue
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
        elif tool_name in {"get_distance_eta", "calculate_distance_km"}:
            if result_status == "ok" and isinstance(data, dict):
                row["distance_km"] = data.get("distance_km", row.get("distance_km"))
                row["eta_minutes"] = data.get("eta_minutes", row.get("eta_minutes"))
                row["distance_method"] = data.get("method", row.get("distance_method", "haversine" if tool_name == "calculate_distance_km" else ""))
                if data.get("blocked_reason") is not None:
                    row["distance_blocked_reason"] = data.get("blocked_reason")

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
        if s_lower in {"failed", "circuit_open", "error", "backend_unavailable"}:
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
            elif cell["status"] in {"failed", "circuit_open", "error", "backend_unavailable"}:
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

    winner_payload = derive_comparison_winner(rows)

    from ...domain.schemas import ComparisonMatrix
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
        "statistical_winner": winner_payload.get("statistical_winner"),
        "winner_provenance": winner_payload.get("winner_provenance", {}),
        "winner_uncertainty_note": winner_payload.get("winner_uncertainty_note", ""),
    }
    # Perform strict schemas validation
    ComparisonMatrix.model_validate(matrix_dict)

    # Build facet_results from the cells collection, which already
    # contains per-shop per-facet status/value data. Without this the
    # evidence_review sees required facets as UNKNOWN.
    facet_results = [
        {
            "facet": cell["facet"],
            "result_status": cell.get("result_status", cell.get("status", "unknown")),
            "shop_id": cell.get("shop_id", ""),
            "shop_name": cell.get("shop_name", ""),
            "value": cell.get("value"),
        }
        for cell in cells
        if isinstance(cell, dict) and cell.get("facet")
    ]
    if facet_results and rows:
        # Copy open_status and coupon_status into value for verifier compat
        for fr in facet_results:
            if fr["facet"] == "open_status" and fr.get("value") is None:
                for r in rows:
                    if r.get("shop_id") == fr.get("shop_id"):
                        fr["value"] = r.get("open_status")
                        fr["open_status"] = r.get("open_status", "")
                        break
    return {
        "target_shop_ids": target_ids,
        "requested_facets": ["detail", "open_status", "coupon", "distance"],
        "facet_results": facet_results,
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
    *,
    semantic_frame: dict[str, Any] | None = None,
    semantic_parse_source: str = "",
    grounding_status: str = "",
    missing_slot_type: str = "",
    router_policy_decision: dict[str, Any] | None = None,
    router_policy_conflicts: list[str] | None = None,
    conversation_continuity: dict[str, Any] | None = None,
    exploration_stages: list[dict[str, Any]] | None = None,
    stage_queries: list[str] | None = None,
    stage_evidence_requirements: list[list[str]] | None = None,
    stage_statuses: list[str] | None = None,
    scene: str = "",
    time: str = "",
    location: dict[str, Any] | None = None,
    cache: EvidenceCache | None = None,
    cache_scope: dict[str, Any] | str | None = None,
) -> dict:
    """Build an evidence pack from tool results."""
    cache_store = cache or get_default_evidence_cache()
    resolved_target = _to_dict(resolved_target)
    shop_id, shop_name = _first_shop_name(resolved_target)
    plan_dict = _to_dict(execution_plan)
    cache_payload = {
        "tool_results": tool_results or {},
        "resolved_target": resolved_target,
        "execution_plan": plan_dict,
        "recommendation_candidates": recommendation_candidates or [],
        "comparison_targets": comparison_targets or [],
        "semantic_frame": semantic_frame or {},
        "semantic_parse_source": semantic_parse_source,
        "grounding_status": grounding_status,
        "missing_slot_type": missing_slot_type,
        "router_policy_decision": router_policy_decision or {},
        "router_policy_conflicts": router_policy_conflicts or [],
        "conversation_continuity": conversation_continuity or {},
        "exploration_stages": exploration_stages or [],
        "stage_queries": stage_queries or [],
        "stage_evidence_requirements": stage_evidence_requirements or [],
        "stage_statuses": stage_statuses or [],
        "scene": scene,
        "time": time,
        "location": location or {},
    }

    def _build() -> dict[str, Any]:
        return _build_evidence_uncached(
            tool_results=tool_results,
            resolved_target=resolved_target,
            execution_plan=execution_plan,
            recommendation_candidates=recommendation_candidates,
            comparison_targets=comparison_targets,
            plan_dict=plan_dict,
            shop_id=shop_id,
            shop_name=shop_name,
            semantic_frame=semantic_frame,
            semantic_parse_source=semantic_parse_source,
            grounding_status=grounding_status,
            missing_slot_type=missing_slot_type,
            router_policy_decision=router_policy_decision,
            router_policy_conflicts=router_policy_conflicts,
            conversation_continuity=conversation_continuity,
            exploration_stages=exploration_stages,
            stage_queries=stage_queries,
            stage_evidence_requirements=stage_evidence_requirements,
            stage_statuses=stage_statuses,
            scene=scene,
            time=time,
            location=location,
        )

    if cache_store is not None and cache_scope is not None:
        evidence_dict, cache_meta = cache_store.get_or_build(cache_scope, cache_payload, _build)
        if isinstance(evidence_dict, dict):
            evidence_dict["evidence_cache_key"] = cache_meta.get("cache_key", "")
            evidence_dict["evidence_cache_scope"] = cache_meta.get("cache_scope", "")
            evidence_dict["evidence_cache_hit"] = bool(cache_meta.get("cache_hit", False))
        return evidence_dict

    return _build()


def _build_evidence_uncached(
    *,
    tool_results: dict,
    resolved_target: dict,
    execution_plan: Any | None,
    recommendation_candidates: list[Any] | None,
    comparison_targets: list[Any] | None,
    plan_dict: dict[str, Any],
    shop_id: str,
    shop_name: str,
    semantic_frame: dict[str, Any] | None = None,
    semantic_parse_source: str = "",
    grounding_status: str = "",
    missing_slot_type: str = "",
    router_policy_decision: dict[str, Any] | None = None,
    router_policy_conflicts: list[str] | None = None,
    conversation_continuity: dict[str, Any] | None = None,
    exploration_stages: list[dict[str, Any]] | None = None,
    stage_queries: list[str] | None = None,
    stage_evidence_requirements: list[list[str]] | None = None,
    stage_statuses: list[str] | None = None,
    scene: str = "",
    time: str = "",
    location: dict[str, Any] | None = None,
) -> dict:
    plan_calls = {}
    if execution_plan is not None:
        for call in plan_dict.get("tool_calls", []) or []:
            call_dict = _to_dict(call)
            call_id = str(call_dict.get("call_id", "")).strip()
            if call_id:
                plan_calls[call_id] = call_dict

    task_type = _enum_value(plan_dict.get("task_type", ""))
    if task_type == "comparison":
        comparison_payload = _build_comparison_evidence(
            tool_results or {},
            plan_calls,
            plan_dict,
            comparison_targets or [],
        )
        comparison_payload.setdefault("evidence_cache_key", "")
        comparison_payload.setdefault("evidence_cache_scope", "")
        comparison_payload.setdefault("evidence_cache_hit", False)
        comparison_payload.setdefault("evidence_enrichment_top_k", config.RECOMMENDATION_CANDIDATE_TOP_K)
        return comparison_payload

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
        call_plan = plan_calls.get(str(call_id), {})
        facet = str(call_plan.get("facet") or _facet_name_from_tool(tool_name))
        result_status = _status_value(result.get("result_status", "unknown"))
        data = result.get("data")
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
                open_status = _normalize_open_status_value(data)
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
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "result_status": "ok",
                        "field_path": "data.distance_km",
                        "value": {
                            "distance_km": distance_km,
                            "eta_minutes": eta_minutes,
                            "method": data.get("method", "haversine"),
                            "blocked_reason": data.get("blocked_reason"),
                        },
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
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "result_status": result_status,
                        "field_path": "",
                        "value": {
                            "distance_km": None,
                            "eta_minutes": None,
                            "method": data.get("method", "haversine") if isinstance(data, dict) else "haversine",
                            "blocked_reason": data.get("blocked_reason") if isinstance(data, dict) else None,
                        },
                        "confidence": 0.0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_type": "tool",
                    }
                )
        elif facet in {"shop_cards", "review_summary", "scene_fit", "environment", "taste", "service", "price"}:
            if result_status in {"ok", "partial"} and isinstance(data, dict):
                items = _items_from_tool_data(data)
                first_item = items[0] if items else {}
                if facet == "shop_cards":
                    value = [item.get("name", "") for item in items if item.get("name")]
                elif facet == "review_summary":
                    value = [item.get("summary", "") for item in items if item.get("summary")]
                elif facet == "scene_fit":
                    value = first_item.get("scene_fit", {})
                elif facet == "environment":
                    value = first_item.get("environment_score")
                elif facet == "taste":
                    value = first_item.get("taste_score")
                elif facet == "service":
                    value = first_item.get("service_score")
                else:
                    value = first_item.get("price_score")
                facet_results[-1]["value"] = value

    required_statuses = [item["status"] for item in facet_results if item["required"]]
    if any(status == "circuit_open" for status in required_statuses):
        overall_status = "circuit_open"
    elif any(status in {"failed", "error", "backend_unavailable"} for status in required_statuses):
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
        if status in {"unknown", "failed", "circuit_open", "error", "backend_unavailable"}:
            forbidden_claims.extend(_facet_claims_for_status(facet, status))

    comparison_matrix = {
        "status": overall_status,
        "error_code": error_code,
        "error_message": error_message,
        "facet_statuses": facet_statuses,
    }

    if _enum_value(plan_dict.get("task_type", "")) == "recommendation":
        return _build_recommendation_evidence(
            recommendation_candidates or [],
            tool_results or {},
            plan_calls,
            plan_dict,
            semantic_frame=semantic_frame,
            semantic_parse_source=semantic_parse_source,
            grounding_status=grounding_status,
            missing_slot_type=missing_slot_type,
            router_policy_decision=router_policy_decision,
            router_policy_conflicts=router_policy_conflicts,
            conversation_continuity=conversation_continuity,
            exploration_stages=exploration_stages,
            stage_queries=stage_queries,
            stage_evidence_requirements=stage_evidence_requirements,
            stage_statuses=stage_statuses,
            scene=scene,
            time=time,
            location=location,
        )

    facet_status_contract, grounded_facts_contract, facet_reason_contract = _facet_contract_from_target(
        ranking_snapshot,
        location=location,
    )
    facet_status_contract, grounded_facts_contract, facet_reason_contract = _merge_facet_contract_with_results(
        facet_status_contract,
        grounded_facts_contract,
        facet_reason_contract,
        facet_results,
        location=location,
    )
    evidence_payload = {
        **_facet_protocol_metadata(execution_plan, resolved_target),
        **_facet_triage_from_results(facet_results),
        "target_shop_ids": [shop_id] if shop_id else [],
        "requested_facets": requested_facets,
        "facet_results": facet_results,
        "evidence_items": _attach_backend_source(evidence_items, tool_results or {}),
        "unknown_items": _attach_backend_source(unknown_items, tool_results or {}),
        "forbidden_claims": forbidden_claims,
        "ranking_snapshot": ranking_snapshot,
        "comparison_matrix": comparison_matrix,
        "tool_results": tool_results or {},
        "semantic_frame": semantic_frame or {},
        "semantic_parse_source": semantic_parse_source,
        "grounding_status": grounding_status,
        "missing_slot_type": missing_slot_type,
        "router_policy_decision": router_policy_decision or {},
        "router_policy_conflicts": list(router_policy_conflicts or []),
        "conversation_continuity": conversation_continuity or {},
        "exploration_stages": list(exploration_stages or []),
        "stage_queries": list(stage_queries or []),
        "stage_evidence_requirements": list(stage_evidence_requirements or []),
        "stage_statuses": list(stage_statuses or []),
        "scene": scene,
        "time": time,
        "location": location or {},
        "facet_statuses": facet_status_contract,
        "grounded_facts": grounded_facts_contract,
        "facet_reasons": facet_reason_contract,
        "evidence_status": "grounded" if facet_results and not comparison_matrix.get("status") in {"unknown", "failed"} else "unknown",
        "comparison_support_status": "grounded" if comparison_matrix.get("status") == "ok" else str(comparison_matrix.get("status", "") or ""),
        "ranking_preserved": True,
        "unsupported_reasons": [],
        "unknown_fields": _facet_triage_from_results(facet_results)["unknown_facets"],
        "failed_tools": [],
        "partial_fields": [],
        "evidence_review_result": {},
        "answer_verify_result": {},
        "evidence_cache_key": "",
        "evidence_cache_scope": "",
        "evidence_cache_hit": False,
        "evidence_enrichment_top_k": config.RECOMMENDATION_CANDIDATE_TOP_K,
    }
    return evidence_payload


def _build_recommendation_evidence(
    recommendation_candidates: list[Any],
    tool_results: dict,
    plan_calls: dict[str, dict[str, Any]],
    plan_dict: dict[str, Any],
    *,
    semantic_frame: dict[str, Any] | None = None,
    semantic_parse_source: str = "",
    grounding_status: str = "",
    missing_slot_type: str = "",
    router_policy_decision: dict[str, Any] | None = None,
    router_policy_conflicts: list[str] | None = None,
    conversation_continuity: dict[str, Any] | None = None,
    exploration_stages: list[dict[str, Any]] | None = None,
    stage_queries: list[str] | None = None,
    stage_evidence_requirements: list[list[str]] | None = None,
    stage_statuses: list[str] | None = None,
    scene: str = "",
    time: str = "",
    location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    search_result_candidates = _search_result_candidates(tool_results, plan_calls)
    merged_candidates: list[Any] = []
    seen_candidate_keys: set[tuple[Any, ...]] = set()
    for candidate in (search_result_candidates or []) + (recommendation_candidates or []):
        candidate_dict = _candidate_from_shop(candidate)
        identity_key = _candidate_identity_key(candidate_dict)
        if identity_key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(identity_key)
        merged_candidates.append(candidate)
    recommendation_candidates = merged_candidates
    candidates_by_shop_id: dict[str, dict[str, Any]] = {}
    seen_candidate_identities: set[tuple[Any, ...]] = set()
    for raw_candidate in recommendation_candidates:
        candidate = _candidate_from_shop(raw_candidate)
        identity_key = _candidate_identity_key(candidate)
        if identity_key in seen_candidate_identities:
            continue
        seen_candidate_identities.add(identity_key)
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
        if tool_name in {"get_shop_cards", "get_shop_review_summary"}:
            for item in _items_from_tool_data(data):
                item_shop_id = str(item.get("shop_id", "")).strip()
                if not item_shop_id:
                    continue
                candidate = candidates_by_shop_id.setdefault(item_shop_id, {"shop_id": item_shop_id, "shop_name": ""})
                candidate["shop_name"] = str(item.get("name", "") or item.get("shop_name", "") or candidate.get("shop_name", "")).strip()
                if tool_name == "get_shop_cards":
                    # Prefer direct distance_km (now returned by the tool); fall back to distance_m/1000
                    raw_km = item.get("distance_km")
                    raw_m = item.get("distance_m")
                    if raw_km is not None:
                        resolved_km = float(raw_km)
                    elif raw_m is not None:
                        resolved_km = float(raw_m) / 1000.0
                    else:
                        resolved_km = candidate.get("distance_km")
                    candidate.update(
                        {
                            "category": item.get("category", candidate.get("category")),
                            "rating": item.get("rating", candidate.get("rating")),
                            "avg_price": item.get("avg_price", candidate.get("avg_price")),
                            "distance_km": resolved_km,
                            "eta_minutes": item.get("eta_minutes", candidate.get("eta_minutes")),
                            "open_status": str(item.get("open_status_text", item.get("open_status", "unknown")) or "unknown"),
                            "coupon_count": item.get("coupon_count", candidate.get("coupon_count")),
                            "tags": item.get("top_tags") or item.get("scene_tags") or candidate.get("tags", []),
                        }
                    )
                    evidence_items.append(
                        {
                            "evidence_id": f"evi_shop_card_{item_shop_id}",
                            "shop_id": item_shop_id,
                            "shop_name": candidate.get("shop_name", ""),
                            "facet": "shop_cards",
                            "tool_name": "get_shop_cards",
                            "call_id": call_id,
                            "result_status": result_status,
                            "field_path": "data.items",
                            "value": {
                                "rating": item.get("rating"),
                                "avg_price": item.get("avg_price"),
                                "distance_m": item.get("distance_m"),
                                "distance_km": item.get("distance_km"),
                                "eta_minutes": item.get("eta_minutes"),
                                "etas": item.get("etas"),
                                "traffic_level": item.get("traffic_level"),
                                "open_status_text": item.get("open_status_text"),
                                "coupon_count": item.get("coupon_count"),
                            },
                            "confidence": 1.0,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "source_type": "tool",
                        }
                    )
                else:
                    candidate["review_summary"] = str(item.get("summary", "") or "")
                    candidate["scene_fit"] = item.get("scene_fit", candidate.get("scene_fit"))
                    candidate["positive_tags"] = item.get("positive_tags", candidate.get("positive_tags", []))
                    candidate["negative_tags"] = item.get("negative_tags", candidate.get("negative_tags", []))
                    evidence_items.append(
                        {
                            "evidence_id": f"evi_review_{item_shop_id}",
                            "shop_id": item_shop_id,
                            "shop_name": candidate.get("shop_name", ""),
                            "facet": "review_summary",
                            "tool_name": "get_shop_review_summary",
                            "call_id": call_id,
                            "result_status": result_status,
                            "field_path": "data.items",
                            "value": candidate.get("review_summary", ""),
                            "confidence": 1.0,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "source_type": "tool",
                        }
                    )
            continue
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
                open_status = _normalize_open_status_value(data)
                current_open_status = str(candidate.get("open_status", "unknown") or "unknown").lower()
                if current_open_status not in {"open", "closed"}:
                    candidate["open_status"] = open_status
                elif current_open_status == "open" and open_status == "closed":
                    candidate["open_status_check"] = open_status
                else:
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
        if str(candidate.get("open_status", "")).lower() == "closed" and str(candidate.get("open_status_check", "")).lower() != "open":
            continue
        candidate["open_status"] = open_status_by_shop_id.get(shop_id, candidate.get("open_status", "unknown"))
        if "coupon_count" not in candidate:
            candidate["coupon_count"] = coupon_count_by_shop_id.get(shop_id)
        surviving_candidates.append(candidate)

    if not surviving_candidates:
        fallback_candidates = []
        seen_fallback_identities: set[tuple[Any, ...]] = set()
        for candidate in search_result_candidates:
            candidate_dict = _candidate_from_shop(candidate)
            identity_key = _candidate_identity_key(candidate_dict)
            if identity_key not in seen_fallback_identities:
                seen_fallback_identities.add(identity_key)
                fallback_candidates.append(candidate_dict)
        if fallback_candidates:
            surviving_candidates = fallback_candidates

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
                "category": item.get("category", ""),
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
        "status": "ok" if ranked_snapshot else ("empty" if (recommendation_candidates or search_result_candidates) else "unknown"),
        "strategy": "category_match*30 + open_status_score*25 + distance_score*20 + rating_score*15 + coupon_score*10 + tag_match_score*10 - risk_penalty",
        "ranked": ranked_snapshot,
        "ranked_shops": ranked_snapshot,
        "query_terms": plan_dict.get("query_terms", []),
        "scene_terms": plan_dict.get("scene_terms", []),
        "candidate_count": len(surviving_candidates or recommendation_candidates or search_result_candidates),
    }

    forbidden_claims = []
    for candidate in recommendation_candidates:
        candidate_dict = _candidate_from_shop(candidate)
        if candidate_dict.get("detail_failed"):
            forbidden_claims.append(str(candidate_dict.get("shop_name", "")))

    # Build facet_results from evidence_items and ranking data.
    # Without this the evidence_review sees required facets as UNKNOWN
    # and routes to fallback_answer instead of answer_generate.
    facet_results: list[dict[str, Any]] = []
    seen_facets: set[str] = set()
    for ei in evidence_items:
        facet = str(ei.get("facet", "") or "").strip()
        if facet and facet not in seen_facets:
            seen_facets.add(facet)
            result = {
                "facet": facet,
                "result_status": str(ei.get("result_status", "ok")),
                "shop_id": str(ei.get("shop_id", "") or ""),
                "shop_name": str(ei.get("shop_name", "") or ""),
            }
            # Include value field so the verifier can check answer content
            val = ei.get("value")
            if val is not None:
                result["value"] = val
                # For open_status, propagate value as open_status for verifier compatibility
                if facet == "open_status":
                    result["open_status"] = str(val).strip().lower()
            facet_results.append(result)
    # Add distance facet from ranking snapshot (distance is rarely a separate tool call)
    for item in ranked_snapshot:
        d_km = item.get("distance_km")
        facet_results.append({
            "facet": "distance",
            "result_status": "ok" if d_km is not None else "empty",
            "shop_id": str(item.get("shop_id", "") or ""),
            "shop_name": str(item.get("shop_name", "") or ""),
            "distance_km": d_km,
            "value": d_km,
        })
        seen_facets.add("distance")
    # Add rating facet from ranking snapshot
    if "rating" not in seen_facets:
        for item in ranked_snapshot:
            r = item.get("rating")
            facet_results.append({
                "facet": "rating",
                "result_status": "ok" if r is not None else "empty",
                "shop_id": str(item.get("shop_id", "") or ""),
                "shop_name": str(item.get("shop_name", "") or ""),
                "value": r,
            })
            seen_facets.add("rating")
    # Add coupon/open_status facets from ranking snapshot if evidence_items didn't cover them
    if "coupon" not in seen_facets:
        for item in ranked_snapshot:
            c = item.get("coupon_count")
            facet_results.append({
                "facet": "coupon",
                "result_status": "ok" if (c or 0) > 0 else "empty",
                "shop_id": str(item.get("shop_id", "") or ""),
                "shop_name": str(item.get("shop_name", "") or ""),
                "value": c,
            })
            seen_facets.add("coupon")
    if "open_status" not in seen_facets:
        for item in ranked_snapshot:
            os_val = str(item.get("open_status", "unknown"))
            facet_results.append({
                "facet": "open_status",
                "result_status": "ok" if os_val in ("open", "closed") else "unknown",
                "shop_id": str(item.get("shop_id", "") or ""),
                "shop_name": str(item.get("shop_name", "") or ""),
                "open_status": os_val,
                "value": os_val,
            })
            seen_facets.add("open_status")

    facet_contract_source = ranked_snapshot[0] if ranked_snapshot else {}
    facet_status_contract, grounded_facts_contract, facet_reason_contract = _facet_contract_from_target(
        facet_contract_source,
        location=location,
    )
    facet_status_contract, grounded_facts_contract, facet_reason_contract = _merge_facet_contract_with_results(
        facet_status_contract,
        grounded_facts_contract,
        facet_reason_contract,
        facet_results,
        location=location,
    )

    return {
        **_facet_protocol_metadata(plan_dict, {"target_resolution": plan_dict.get("target_resolution")}),
        **_facet_triage_from_results(facet_results),
        "target_shop_ids": [item["shop_id"] for item in ranked_snapshot],
        "requested_facets": ["rating", "distance", "open_status", "coupon"],
        "facet_results": facet_results,
        "evidence_items": _attach_backend_source(evidence_items, tool_results or {}),
        "unknown_items": _attach_backend_source(unknown_items, tool_results or {}),
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
        "semantic_frame": semantic_frame or {},
        "semantic_parse_source": semantic_parse_source,
        "grounding_status": grounding_status,
        "missing_slot_type": missing_slot_type,
        "router_policy_decision": router_policy_decision or {},
        "router_policy_conflicts": list(router_policy_conflicts or []),
        "conversation_continuity": conversation_continuity or {},
        "exploration_stages": list(exploration_stages or []),
        "stage_queries": list(stage_queries or []),
        "stage_evidence_requirements": list(stage_evidence_requirements or []),
        "stage_statuses": list(stage_statuses or []),
        "scene": scene,
        "time": time,
        "location": location or {},
        "facet_statuses": facet_status_contract,
        "grounded_facts": grounded_facts_contract,
        "facet_reasons": facet_reason_contract,
        "evidence_status": "grounded" if ranking_snapshot.get("status") == "ok" else ranking_snapshot.get("status", "unknown"),
        "comparison_support_status": "grounded" if ranking_snapshot.get("status") == "ok" else ranking_snapshot.get("status", "unknown"),
        "ranking_preserved": True,
        "unsupported_reasons": [],
        "unknown_fields": _facet_triage_from_results(facet_results)["unknown_facets"],
        "failed_tools": [],
        "partial_fields": [],
        "evidence_review_result": {},
        "answer_verify_result": {},
    }
