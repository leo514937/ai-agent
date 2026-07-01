from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ...input.normalizer import normalize_text


_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "mock_data"


def _load_json(name: str) -> list[dict[str, Any]]:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _all_shops() -> list[dict[str, Any]]:
    return _load_json("shops.json")


def _all_coupons() -> list[dict[str, Any]]:
    return _load_json("coupons.json")


def _all_distance_eta() -> list[dict[str, Any]]:
    return _load_json("distance_eta.json")


def _all_review_summaries() -> list[dict[str, Any]]:
    return _load_json("review_summaries.json")


def _all_deals() -> list[dict[str, Any]]:
    return _load_json("deals.json")


def _find_shop(shop_id: str) -> dict[str, Any] | None:
    for shop in _all_shops():
        if shop.get("shop_id") == shop_id:
            return dict(shop)
    return None


def _normalize_query(text: str) -> str:
    return normalize_text(text).strip().lower()


def _build_alias_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for shop in _all_shops():
        canonical = _normalize_query(str(shop.get("shop_name", "")))
        if not canonical:
            continue
        aliases = [canonical]
        alias_field = _normalize_query(str(shop.get("alias", "") or ""))
        if alias_field:
            aliases.append(alias_field)
        for alias_item in shop.get("aliases", []) or []:
            alias_norm = _normalize_query(str(alias_item))
            if alias_norm:
                aliases.append(alias_norm)
        index[canonical] = list(dict.fromkeys(aliases))
    return index


def _calc_etas(distance_km: float) -> dict[str, int]:
    """Calculate ETA minutes for walking/cycling/driving."""
    speeds = {"walking": 5.0, "cycling": 15.0, "driving": 30.0}
    return {mode: max(1, round(distance_km / (speed / 60))) for mode, speed in speeds.items()}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return round(radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def resolve_shop(query: str, location: dict[str, float] | None = None, session_shop_ids: list[str] | None = None) -> dict[str, Any]:
    if not query or not query.strip():
        return {"status": "NOT_FOUND", "shop": None, "candidates": [], "confidence": 0.0, "error_code": None}
    query_lower = _normalize_query(query)
    alias_index = _build_alias_index()
    shops_by_name = {
        _normalize_query(str(shop.get("shop_name", ""))): dict(shop)
        for shop in _all_shops()
        if str(shop.get("shop_name", "")).strip()
    }
    matched: list[dict[str, Any]] = []
    for shop in _all_shops():
        if _normalize_query(str(shop.get("shop_name", ""))) == query_lower:
            matched.append(dict(shop))
            continue
    if not matched:
        for canonical, aliases in alias_index.items():
            if query_lower in aliases and canonical in shops_by_name:
                matched.append(dict(shops_by_name[canonical]))
    if not matched:
        for shop in _all_shops():
            name_lower = _normalize_query(str(shop.get("shop_name", "")))
            category_lower = _normalize_query(str(shop.get("category", "")))
            if query_lower in name_lower or query_lower in category_lower:
                matched.append(dict(shop))
    if not matched and query_lower not in {"它", "这家", "那家"}:
        for shop in _all_shops():
            if query_lower in _normalize_query(str(shop.get("shop_name", ""))) or query_lower in _normalize_query(str(shop.get("category", ""))):
                matched.append(dict(shop))
    if not matched and session_shop_ids:
        for shop_id in session_shop_ids:
            shop = _find_shop(str(shop_id))
            if shop is not None:
                matched.append(shop)
    if not matched:
        return {"status": "NOT_FOUND", "shop": None, "candidates": [], "confidence": 0.0, "error_code": "SHOP_NOT_FOUND"}
    if len(matched) == 1:
        return {"status": "RESOLVED", "shop": matched[0], "candidates": [], "confidence": 0.95, "error_code": None}
    candidates = [{"shop_id": s.get("shop_id", ""), "shop_name": s.get("shop_name", ""), "address": s.get("address", "")} for s in matched[:5]]
    return {"status": "AMBIGUOUS", "shop": None, "candidates": candidates, "confidence": 0.5, "error_code": "AMBIGUOUS_SHOP"}


def search_shops(query: str, location: dict[str, float] | None = None, limit: int | None = None) -> dict[str, Any]:
    if not query or not query.strip():
        return {"success": True, "result_status": "ok", "data": []}
    query_lower = query.strip().lower()
    matched: list[dict[str, Any]] = []
    for shop in _all_shops():
        name_lower = str(shop.get("shop_name", "")).lower()
        aliases = [str(item).lower() for item in (shop.get("aliases") or [])]
        if query_lower == name_lower or query_lower in aliases:
            matched.insert(0, dict(shop))
            continue
        if query_lower in name_lower or query_lower in str(shop.get("category", "")).lower() or query_lower in str(shop.get("sub_category", "")).lower() or any(query_lower in str(tag).lower() for tag in shop.get("tags", [])):
            matched.append(dict(shop))
    matched.sort(key=lambda item: item.get("rating", 0), reverse=True)
    if location:
        distances = {str(item.get("shop_id", "")): item for item in _all_distance_eta()}
        enriched: list[dict[str, Any]] = []
        for shop in matched:
            entry = distances.get(str(shop.get("shop_id", "")))
            if entry:
                shop["distance_km"] = entry.get("distance_km")
                shop["eta_minutes"] = entry.get("eta_minutes")
                shop["etas"] = entry.get("etas") or _calc_etas(entry.get("distance_km", 0))
                shop["traffic_level"] = entry.get("traffic_level", "low")
            enriched.append(shop)
        matched = enriched
    if limit is not None:
        matched = matched[: max(0, int(limit))]
    return {"success": True, "result_status": "ok", "data": matched, "total": len(matched)}


def get_shop_detail(shop_id: str) -> dict[str, Any]:
    shop = _find_shop(shop_id)
    if shop is None:
        return {"success": False, "result_status": "failed", "error_code": "SHOP_NOT_FOUND", "error_message": f"Shop '{shop_id}' not found", "data": None}
    return {"success": True, "result_status": "ok", "data": shop}


def get_coupon_list(shop_id: str) -> dict[str, Any]:
    if shop_id == "shop_sc_06":
        raise TimeoutError("Coupon query timed out for shop_sc_06 (simulated)")
    coupons = [coupon for coupon in _all_coupons() if coupon.get("shop_id") == shop_id]
    return {"success": True, "result_status": "ok" if coupons else "empty", "data": coupons, "total": len(coupons)}


def check_open_status(shop_id: str) -> dict[str, Any]:
    shop = _find_shop(shop_id)
    if shop is None:
        return {"success": False, "result_status": "failed", "error_code": "SHOP_NOT_FOUND", "error_message": f"Shop '{shop_id}' not found", "data": None}
    return {"success": True, "result_status": "ok", "data": {"shop_id": shop_id, "shop_name": shop.get("shop_name", ""), "open_status": shop.get("open_status", "unknown"), "business_hours": shop.get("business_hours", "")}}


def get_distance_eta(shop_id: str, from_location: dict[str, float]) -> dict[str, Any]:
    for entry in _all_distance_eta():
        if entry.get("shop_id") == shop_id:
            shop = _find_shop(shop_id)
            etas = entry.get("etas") or _calc_etas(entry.get("distance_km", 0))
            return {"success": True, "result_status": "ok", "data": {"shop_id": shop_id, "shop_name": shop.get("shop_name", "") if shop else "", "distance_km": entry.get("distance_km"), "eta_minutes": etas.get("driving", entry.get("eta_minutes")), "etas": etas, "traffic_level": entry.get("traffic_level", "low")}}
    shop = _find_shop(shop_id)
    if shop is None:
        return {"success": False, "result_status": "failed", "error_code": "SHOP_NOT_FOUND", "data": None}
    distance = _haversine_km(float(from_location.get("lat", 39.9609)), float(from_location.get("lng", 116.3581)), float(shop.get("lat", 0)), float(shop.get("lng", 0)))
    etas = _calc_etas(distance)
    return {"success": True, "result_status": "ok", "data": {"shop_id": shop_id, "shop_name": shop.get("shop_name", ""), "distance_km": distance, "eta_minutes": etas["driving"], "etas": etas, "traffic_level": "low"}}


def get_shop_cards(shop_ids: list[str], user_location: dict[str, float] | None = None, need_coupon_brief: bool = True, need_open_status: bool = True, need_distance_eta: bool = True, max_items: int | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    limit = len(shop_ids) if max_items is None else max(0, int(max_items))
    for shop_id in [str(item).strip() for item in shop_ids or [] if str(item).strip()][:limit]:
        shop = _find_shop(shop_id)
        if shop is None:
            missing.append(shop_id)
            continue
        distance_meta = next((item for item in _all_distance_eta() if item.get("shop_id") == shop_id), None)
        coupons = [coupon for coupon in _all_coupons() if coupon.get("shop_id") == shop_id] if need_coupon_brief else []
        items.append({
            "shop_id": shop_id,
            "name": shop.get("shop_name", ""),
            "alias": [shop.get("alias")] if shop.get("alias") else [],
            "category": shop.get("category"),
            "address": shop.get("address"),
            "rating": shop.get("rating"),
            "avg_price": shop.get("avg_price"),
            "price_level": "low" if float(shop.get("avg_price", 0) or 0) <= 30 else "medium" if float(shop.get("avg_price", 0) or 0) <= 60 else "high",
            "distance_m": int(round(float(distance_meta.get("distance_km", 0)) * 1000)) if distance_meta and need_distance_eta else None,
            "distance_km": float(distance_meta.get("distance_km", 0)) if distance_meta and need_distance_eta else None,
            "eta_minutes": int(distance_meta.get("eta_minutes", 0)) if distance_meta and need_distance_eta else None,
            "etas": (distance_meta.get("etas") or _calc_etas(distance_meta.get("distance_km", 0))) if distance_meta and need_distance_eta else None,
            "traffic_level": distance_meta.get("traffic_level", "low") if distance_meta and need_distance_eta else None,
            "is_open": True if shop.get("open_status") == "open" else False if shop.get("open_status") == "closed" else None,
            "open_status_text": shop.get("open_status", "unknown"),
            "coupon_count": len(coupons) if need_coupon_brief else None,
            "has_coupon": bool(coupons) if need_coupon_brief else None,
            "top_coupon_title": coupons[0].get("title") if coupons else None,
            "top_tags": [str(tag) for tag in shop.get("tags", []) or [] if str(tag).strip()],
            "scene_tags": [],
            "source_fields": ["detail"],
        })
    status = "empty" if not items and not missing else "partial" if missing else "ok"
    return {"success": True, "result_status": status, "data": {"status": status, "items": items, "missing_shop_ids": missing, "warnings": [], "trace": {"tool_name": "get_shop_cards", "backend_source": "tests_fake", "status": status}}}


def get_shop_review_summary(shop_ids: list[str], aspects: list[str] | None = None, scene: str | None = None, max_reviews: int | None = None) -> dict[str, Any]:
    summaries = {str(item.get("shop_id", "")): item for item in _all_review_summaries()}
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for shop_id in [str(item).strip() for item in shop_ids or [] if str(item).strip()][: max_reviews if isinstance(max_reviews, int) and max_reviews > 0 else len(shop_ids or [])]:
        shop = _find_shop(shop_id)
        if shop is None:
            missing.append(shop_id)
            continue
        summary = dict(summaries.get(shop_id, {}))
        items.append({
            "shop_id": shop_id,
            "name": shop.get("shop_name", ""),
            "rating": summary.get("rating", shop.get("rating")),
            "review_count": summary.get("review_count", 0),
            "taste_score": summary.get("taste_score", shop.get("rating")),
            "environment_score": summary.get("environment_score", shop.get("rating")),
            "service_score": summary.get("service_score", shop.get("rating")),
            "price_score": summary.get("price_score"),
            "positive_tags": list(summary.get("positive_tags") or []),
            "negative_tags": list(summary.get("negative_tags") or []),
            "scene_tags": list(summary.get("scene_tags") or []),
            "scene_fit": dict(summary.get("scene_fit") or {"scene": scene, "score": None, "label": None, "reasons": []}),
            "highlights": list(summary.get("highlights") or []),
            "risks": list(summary.get("risks") or []),
            "summary": summary.get("summary"),
            "source_fields": list(summary.get("source_fields") or []),
        })
    status = "empty" if not items and not missing else "partial" if missing else "ok"
    return {"success": True, "result_status": status, "data": {"status": status, "items": items, "missing_shop_ids": missing, "warnings": [], "trace": {"tool_name": "get_shop_review_summary", "backend_source": "tests_fake", "status": status}}}


def get_deal_list(shop_id: str, people_count: int | None = None, budget_per_person: float | None = None, deal_type: str | None = None, only_available: bool = True) -> dict[str, Any]:
    shop = _find_shop(shop_id)
    if shop is None:
        return {"success": True, "result_status": "empty", "data": {"status": "empty", "shop_id": str(shop_id), "shop_name": None, "items": [], "warnings": [f"shop_id={shop_id} 未找到"], "trace": {"tool_name": "get_deal_list", "backend_source": "tests_fake", "status": "empty"}}}
    deals = [dict(item) for item in _all_deals() if str(item.get("shop_id", "")).strip() == str(shop_id).strip()]
    filtered = []
    for deal in deals:
        if only_available and not bool(deal.get("available", True)):
            continue
        if deal_type and str(deal.get("deal_type", "")).strip() and str(deal.get("deal_type")).strip() != str(deal_type).strip():
            continue
        filtered.append({**deal, "source_fields": ["deal_catalog"]})
    status = "empty" if not filtered else "ok"
    return {"success": True, "result_status": status, "data": {"status": status, "shop_id": str(shop_id), "shop_name": shop.get("shop_name"), "items": filtered, "warnings": [], "trace": {"tool_name": "get_deal_list", "backend_source": "tests_fake", "status": status}}}


calculate_distance = get_distance_eta
