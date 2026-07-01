"""Database-backed tool implementations."""

from __future__ import annotations

import math
from typing import Any

from . import db_client
from ..input.normalizer import normalize_text
from ..semantic.alias_index import build_alias_index
from pathlib import Path
import json

# ── Speed constants (km/h) ────────────────────────────────────────
WALKING_SPEED_KMH = 5.0
CYCLING_SPEED_KMH = 15.0
DRIVING_SPEED_KMH = 30.0


def _calc_etas(distance_km: float) -> dict[str, int]:
    """Calculate ETA minutes for each travel mode based on distance."""
    speeds = {
        "walking": WALKING_SPEED_KMH,
        "cycling": CYCLING_SPEED_KMH,
        "driving": DRIVING_SPEED_KMH,
    }
    return {
        mode: max(1, round(distance_km / (speed / 60)))
        for mode, speed in speeds.items()
    }


# ── Internal helpers ──────────────────────────────────────────────


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate approximate distance in km between two coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _lookup_shop(shop_id: str) -> dict[str, Any] | None:
    """Query a single shop by numeric ID string."""
    mock = _mock_lookup_shop(shop_id)
    if mock is not None:
        return mock
    return db_client.query_shop_by_id(shop_id)


def _mock_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "mock_data"


def _load_mock_json(name: str) -> list[dict[str, Any]]:
    path = _mock_data_dir() / name
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _is_mock_shop_id(shop_id: str) -> bool:
    return str(shop_id or "").strip().startswith("shop_sc_")


def _mock_lookup_shop(shop_id: str) -> dict[str, Any] | None:
    if not _is_mock_shop_id(shop_id):
        return None
    for shop in _load_mock_json("shops.json"):
        if str(shop.get("shop_id", "")).strip() == str(shop_id).strip():
            return dict(shop)
    return None


def _mock_coupons_for_shop(shop_id: str) -> list[dict[str, Any]]:
    if not _is_mock_shop_id(shop_id):
        return []
    return [dict(item) for item in _load_mock_json("coupons.json") if str(item.get("shop_id", "")).strip() == str(shop_id).strip()]


def _mock_distance_for_shop(shop_id: str) -> dict[str, Any] | None:
    if not _is_mock_shop_id(shop_id):
        return None
    for item in _load_mock_json("distance_eta.json"):
        if str(item.get("shop_id", "")).strip() == str(shop_id).strip():
            return dict(item)
    return None


def _normalize_query(query: str) -> str:
    return normalize_text(query).strip().lower()


# ── 6 registered tools ────────────────────────────────────────────


def resolve_shop(
    query: str,
    location: dict[str, float] | None = None,
    session_shop_ids: list[str] | None = None,
) -> dict:
    """Resolve a shop mention from user text to a known shop.

    Queries tb_shop by exact name first, then LIKE search.
    Falls back to session shop ID hint if nothing found.

    Args:
        query: User's shop reference (name, keyword, or "它").
        location: Optional user location (not used for DB queries).
        session_shop_ids: Shop IDs mentioned earlier in the session.

    Returns:
        Dict with status RESOLVED / AMBIGUOUS / NOT_FOUND.
    """
    if not query or not query.strip():
        return {
            "status": "NOT_FOUND",
            "shop": None,
            "candidates": [],
            "confidence": 0.0,
            "error_code": None,
        }

    q = _normalize_query(query)
    alias_index = build_alias_index()
    all_shops = db_client.query_all_shops()
    shop_by_name = {
        _normalize_query(str(shop.get("shop_name", ""))): shop
        for shop in all_shops
        if str(shop.get("shop_name", "")).strip()
    }

    def _collect_alias_matches() -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for canonical, aliases in alias_index.items():
            if q not in aliases:
                continue
            shop = shop_by_name.get(canonical)
            if shop:
                matched.append(shop)
        return matched

    matched: list[dict[str, Any]] = []

    # Step 1: exact name match
    for s in all_shops:
        if _normalize_query(str(s.get("shop_name", ""))) == q:
            matched.append(s)

    # Step 2: alias match (if no exact match)
    if not matched:
        matched.extend(_collect_alias_matches())

    # Step 3: partial match (if no exact / alias match)
    if not matched:
        for s in all_shops:
            name = _normalize_query(str(s.get("shop_name", "")))
            category = _normalize_query(str(s.get("category", "")))
            if q in name or q in category:
                matched.append(s)

    # Step 4: session hint fallback
    if not matched and session_shop_ids:
        for sid in session_shop_ids:
            s = _lookup_shop(sid)
            if s:
                matched.append(s)

    if not matched:
        return {
            "status": "NOT_FOUND",
            "shop": None,
            "candidates": [],
            "confidence": 0.0,
            "error_code": "SHOP_NOT_FOUND",
        }

    if len(matched) == 1:
        shop = matched[0]
        return {
            "status": "RESOLVED",
            "shop": shop,
            "candidates": [],
            "confidence": 0.95,
            "error_code": None,
        }

    # Multiple matches → prefer session-shop-id match, else ambiguous
    if session_shop_ids:
        session_set = {str(sid).strip() for sid in session_shop_ids if str(sid).strip()}
        session_matched = [s for s in matched if str(s.get("shop_id", "")).strip() in session_set]
        if len(session_matched) == 1:
            return {
                "status": "RESOLVED",
                "shop": session_matched[0],
                "candidates": [],
                "confidence": 0.95,
                "error_code": None,
            }

    candidates = [
        {"shop_id": s["shop_id"], "shop_name": s["shop_name"], "address": s.get("address", "")}
        for s in matched[:5]
    ]
    return {
        "status": "AMBIGUOUS",
        "shop": None,
        "candidates": candidates,
        "confidence": 0.5,
        "error_code": "AMBIGUOUS_SHOP",
    }


def search_shops(
    query: str,
    location: dict[str, float] | None = None,
    limit: int | None = None,
) -> dict:
    """Search shops by keyword across name, address, and type.

    Args:
        query: Search keyword.
        location: Optional user location for distance sorting.
        limit: Max results.

    Returns:
        Search result dict.
    """
    if not query or not query.strip():
        return {"success": True, "result_status": "ok", "data": []}

    matched = db_client.query_shops_by_keyword(query, limit=limit)

    # Sort by rating descending
    matched.sort(key=lambda s: s.get("rating", 0), reverse=True)

    # Enrich with distance if location provided
    if location and matched:
        enriched: list[dict] = []
        for shop in matched:
            shop_copy = dict(shop)
            lat1 = location.get("lat", 39.9609)
            lng1 = location.get("lng", 116.3581)
            lat2 = shop.get("lat", 0)
            lng2 = shop.get("lng", 0)
            distance = _haversine_km(lat1, lng1, lat2, lng2)
            etas = _calc_etas(distance)
            shop_copy["distance_km"] = distance
            shop_copy["eta_minutes"] = etas["driving"]
            shop_copy["etas"] = etas
            shop_copy["traffic_level"] = "low"
            enriched.append(shop_copy)
        matched = enriched

    if limit is not None and limit > 0:
        matched = matched[:limit]

    return {
        "success": True,
        "result_status": "ok",
        "data": matched,
        "total": len(matched),
    }


def get_shop_detail(shop_id: str) -> dict:
    """Get detailed information for a shop by ID.

    Args:
        shop_id: Numeric shop ID as string.

    Returns:
        Shop detail dict.
    """
    shop = _lookup_shop(shop_id)
    if shop is None:
        return {
            "success": False,
            "result_status": "failed",
            "error_code": "SHOP_NOT_FOUND",
            "error_message": f"Shop '{shop_id}' not found",
            "data": None,
        }
    return {
        "success": True,
        "result_status": "ok",
        "data": shop,
    }


def get_coupon_list(shop_id: str) -> dict:
    """Get available coupons for a shop.

    Args:
        shop_id: Numeric shop ID as string.

    Returns:
        Coupon list result.
    """
    if str(shop_id).strip() == "shop_sc_06":
        raise TimeoutError("Coupon query timed out for shop_sc_06 (simulated)")
    coupons = _mock_coupons_for_shop(shop_id)
    if not coupons:
        coupons = db_client.query_coupons_by_shop_id(shop_id)
    return {
        "success": True,
        "result_status": "ok" if coupons else "empty",
        "data": coupons,
        "total": len(coupons),
    }


def check_open_status(shop_id: str) -> dict:
    """Check whether a shop is currently open.

    Determines open status from the shop's business_hours field
    by checking current time against the open_hours range.

    Args:
        shop_id: Numeric shop ID as string.

    Returns:
        Open status result.
    """
    shop = _lookup_shop(shop_id)
    if shop is None:
        return {
            "success": False,
            "result_status": "failed",
            "error_code": "SHOP_NOT_FOUND",
            "error_message": f"Shop '{shop_id}' not found",
            "data": None,
        }

    business_hours = shop.get("business_hours", "")
    status = _compute_open_status(business_hours)

    return {
        "success": True,
        "result_status": "ok",
        "data": {
            "shop_id": shop_id,
            "shop_name": shop["shop_name"],
            "open_status": status,
            "business_hours": business_hours,
        },
    }


def _compute_open_status(business_hours: str) -> str:
    """Simplified open-status check based on business hours string.

    Returns "open", "closed", or "unknown".
    """
    if not business_hours:
        return "unknown"

    from datetime import datetime

    now = datetime.now()
    current_minutes = now.hour * 60 + now.minute

    # Parse "HH:MM-HH:MM" or "HH:MM-HH:MM,HH:MM-HH:MM"
    for segment in business_hours.replace(" ", "").split(","):
        segment = segment.strip()
        if "-" not in segment:
            continue
        parts = segment.split("-")
        if len(parts) != 2:
            continue
        try:
            open_part = parts[0].strip()
            close_part = parts[1].strip()
            open_minutes = int(open_part.split(":")[0]) * 60 + int(open_part.split(":")[1])
            close_h, close_m = close_part.split(":")
            close_minutes = int(close_h) * 60 + int(close_m)
        except (ValueError, IndexError):
            continue
        # Handle overnight hours (e.g., "11:30-03:00")
        if close_minutes < open_minutes:
            # Overnight: open now or close after midnight
            if current_minutes >= open_minutes or current_minutes <= close_minutes:
                return "open"
        elif open_minutes <= current_minutes < close_minutes:
            return "open"

    return "closed"


def get_distance_eta(shop_id: str, from_location: dict[str, float]) -> dict:
    """Calculate distance and ETA from user location to a shop.

    Uses Haversine formula on the shop's x/y coordinates.

    Args:
        shop_id: Numeric shop ID as string.
        from_location: Dict with "lat" and "lng" keys.

    Returns:
        Distance & ETA result.
    """
    mock_distance = _mock_distance_for_shop(shop_id)
    shop = _lookup_shop(shop_id)
    if shop is None:
        return {
            "success": False,
            "result_status": "failed",
            "error_code": "SHOP_NOT_FOUND",
            "data": None,
        }

    if mock_distance is not None:
        etas = mock_distance.get("etas") or _calc_etas(float(mock_distance.get("distance_km", 0) or 0))
        return {
            "success": True,
            "result_status": "ok",
            "data": {
                "shop_id": shop_id,
                "shop_name": shop["shop_name"],
                "distance_km": mock_distance.get("distance_km"),
                "eta_minutes": mock_distance.get("eta_minutes", etas["driving"]),
                "etas": etas,
                "traffic_level": mock_distance.get("traffic_level", "low"),
            },
        }

    lat1 = from_location.get("lat", 39.9609)
    lng1 = from_location.get("lng", 116.3581)
    lat2 = shop.get("lat", 0)
    lng2 = shop.get("lng", 0)

    distance = _haversine_km(lat1, lng1, lat2, lng2)
    etas = _calc_etas(distance)

    return {
        "success": True,
        "result_status": "ok",
        "data": {
            "shop_id": shop_id,
            "shop_name": shop["shop_name"],
            "distance_km": distance,
            "eta_minutes": etas["driving"],
            "etas": etas,
            "traffic_level": "low",
        },
    }


def _make_trace(tool_name: str, started: float, *, status: str, input_payload: dict[str, Any], item_count: int | None = None,
                missing_shop_ids: list[str] | None = None, warnings: list[str] | None = None,
                error_type: str | None = None, error_message: str | None = None) -> dict[str, Any]:
    import time

    return {
        "tool_name": tool_name,
        "backend_source": "mysql",
        "duration_ms": int((time.perf_counter() - started) * 1000.0),
        "input": input_payload,
        "status": status,
        "item_count": item_count,
        "missing_shop_ids": list(missing_shop_ids or []),
        "warnings": list(warnings or []),
        "error_type": error_type,
        "error_message": error_message,
    }


def _price_level(avg_price: float | None) -> str | None:
    if avg_price is None:
        return None
    try:
        value = float(avg_price)
    except Exception:
        return None
    if value <= 30:
        return "low"
    if value <= 60:
        return "medium"
    return "high"


def _scene_tags(shop: dict[str, Any]) -> list[str]:
    tags = [str(tag) for tag in shop.get("tags", []) or [] if str(tag).strip()]
    scene: list[str] = []
    if any(tag in tags for tag in ["安静", "环境好", "咖啡", "甜品"]):
        scene.append("约会")
    if any(tag in tags for tag in ["学生", "实惠"]):
        scene.append("学生党")
    if shop.get("avg_price") is not None and float(shop["avg_price"]) <= 30:
        scene.append("学生党")
    if shop.get("rating") is not None and float(shop["rating"]) >= 4.3:
        scene.append("朋友聚餐")
    return list(dict.fromkeys(scene))


def get_shop_cards(
    shop_ids: list[str],
    user_location: dict[str, float] | None = None,
    need_coupon_brief: bool = True,
    need_open_status: bool = True,
    need_distance_eta: bool = True,
    max_items: int | None = None,
) -> dict:
    import time

    started = time.perf_counter()
    warnings: list[str] = []
    missing: list[str] = []
    items: list[dict[str, Any]] = []
    if need_distance_eta and not user_location:
        warnings.append("未提供用户位置，距离和 ETA 返回 null")

    capped_ids = [str(item).strip() for item in shop_ids or [] if str(item).strip()]
    if max_items is not None and max_items >= 0:
        capped_ids = capped_ids[:max_items]

    for sid in capped_ids:
        shop = _lookup_shop(sid)
        if shop is None:
            missing.append(sid)
            continue
        open_status = shop.get("open_status", "unknown")
        distance_m = None
        eta_minutes = None
        if need_distance_eta and user_location:
            lat1 = user_location.get("lat", 39.9609)
            lng1 = user_location.get("lng", 116.3581)
            distance_km = _haversine_km(lat1, lng1, float(shop.get("lat", 0)), float(shop.get("lng", 0)))
            distance_m = int(round(distance_km * 1000))
            etas = _calc_etas(distance_km)
            eta_minutes = etas["driving"]
        coupons = db_client.query_coupons_by_shop_id(sid) if need_coupon_brief else []
        items.append(
            {
                "shop_id": sid,
                "name": shop.get("shop_name", ""),
                "alias": [str(shop.get("alias", "") or "")] if shop.get("alias") else [],
                "category": shop.get("category"),
                "address": shop.get("address"),
                "rating": shop.get("rating"),
                "avg_price": shop.get("avg_price"),
                "price_level": _price_level(shop.get("avg_price")),
                "distance_m": distance_m,
                "distance_km": distance_km,
                "eta_minutes": eta_minutes,
                "etas": etas,
                "traffic_level": "low",
                "is_open": True if open_status == "open" else False if open_status == "closed" else None,
                "open_status_text": open_status,
                "coupon_count": len(coupons) if need_coupon_brief else None,
                "has_coupon": bool(coupons) if need_coupon_brief else None,
                "top_coupon_title": coupons[0].get("title") if coupons else None,
                "top_tags": list(shop.get("tags", []) or []),
                "scene_tags": _scene_tags(shop),
                "source_fields": ["detail"] + (["coupon"] if need_coupon_brief else []) + (["open_status"] if need_open_status else []) + (["distance_eta"] if need_distance_eta else []),
            }
        )

    status = "empty" if not items and not missing else "partial" if missing or warnings else "ok"
    if not items and missing:
        status = "empty"
    return {
        "success": True,
        "result_status": status,
        "data": {
            "status": status,
            "items": items,
            "missing_shop_ids": missing,
            "warnings": warnings,
            "trace": _make_trace(
                "get_shop_cards",
                started,
                status=status,
                input_payload={
                    "shop_ids": shop_ids,
                    "user_location": user_location,
                    "need_coupon_brief": need_coupon_brief,
                    "need_open_status": need_open_status,
                    "need_distance_eta": need_distance_eta,
                    "max_items": max_items,
                },
                item_count=len(items),
                missing_shop_ids=missing,
                warnings=warnings,
            ),
        },
    }


def get_shop_review_summary(
    shop_ids: list[str],
    aspects: list[str] | None = None,
    scene: str | None = None,
    max_reviews: int | None = None,
) -> dict:
    import time

    started = time.perf_counter()
    warnings: list[str] = []
    missing: list[str] = []
    items: list[dict[str, Any]] = []

    if scene and scene not in {"date", "family", "friends", "elderly", "student", "business", "约会", "带长辈", "朋友聚餐", "学生党", "商务"}:
        warnings.append(f"scene={scene} 未命中明确场景词")

    capped_ids = [str(item).strip() for item in shop_ids or [] if str(item).strip()]
    if max_reviews is not None and max_reviews >= 0:
        capped_ids = capped_ids[:max_reviews]

    for sid in capped_ids:
        shop = _lookup_shop(sid)
        if shop is None:
            missing.append(sid)
            continue
        review_count = shop.get("comments")
        rating = shop.get("rating")
        tags = [str(tag) for tag in shop.get("tags", []) or [] if str(tag).strip()]
        positive_tags = [tag for tag in tags if tag in {"安静", "有WiFi", "环境好", "服务好", "实惠", "学生", "咖啡", "甜品"}]
        negative_tags = ["排队久"] if rating is not None and float(rating) < 4.0 else []
        scene_tags = _scene_tags(shop)
        source_fields = ["rating", "shop_tags", "shop_detail"]
        if aspects:
            source_fields.append("aspects")
        scene_fit_score = 0.65 if scene and (scene_tags or rating and float(rating) >= 4.2) else 0.45
        items.append(
            {
                "shop_id": sid,
                "name": shop.get("shop_name", ""),
                "rating": rating,
                "review_count": review_count,
                "taste_score": rating,
                "environment_score": rating,
                "service_score": rating,
                "price_score": max(1.0, 5.0 - float(shop.get("avg_price", 0.0)) / 30.0) if shop.get("avg_price") is not None else None,
                "positive_tags": positive_tags,
                "negative_tags": negative_tags,
                "scene_tags": scene_tags,
                "scene_fit": {
                    "scene": scene,
                    "score": scene_fit_score if scene else None,
                    "label": "high" if scene_fit_score >= 0.75 else "medium" if scene_fit_score >= 0.55 else "low" if scene else None,
                    "reasons": ["基于评分和标签推断"] if scene else [],
                },
                "highlights": positive_tags[:3] or ["评分和标签可用"],
                "risks": negative_tags[:3],
                "summary": f"{shop.get('shop_name', '')} 的口碑摘要主要基于评分与标签。",
                "source_fields": source_fields,
            }
        )

    status = "empty" if not items and not missing else "partial" if missing or warnings else "ok"
    if not items and missing:
        status = "empty"
    return {
        "success": True,
        "result_status": status,
        "data": {
            "status": status,
            "items": items,
            "missing_shop_ids": missing,
            "warnings": warnings,
            "trace": _make_trace(
                "get_shop_review_summary",
                started,
                status=status,
                input_payload={"shop_ids": shop_ids, "aspects": aspects or [], "scene": scene, "max_reviews": max_reviews},
                item_count=len(items),
                missing_shop_ids=missing,
                warnings=warnings,
            ),
        },
    }


def get_deal_list(
    shop_id: str,
    people_count: int | None = None,
    budget_per_person: float | None = None,
    deal_type: str | None = None,
    only_available: bool = True,
) -> dict:
    import time

    started = time.perf_counter()
    warnings: list[str] = []
    shop = _lookup_shop(shop_id)
    if shop is None:
        return {
            "success": True,
            "result_status": "empty",
            "data": {
                "status": "empty",
                "shop_id": str(shop_id),
                "shop_name": None,
                "items": [],
                "warnings": [f"shop_id={shop_id} 未找到"],
                "trace": _make_trace(
                    "get_deal_list",
                    started,
                    status="empty",
                    input_payload={
                        "shop_id": shop_id,
                        "people_count": people_count,
                        "budget_per_person": budget_per_person,
                        "deal_type": deal_type,
                        "only_available": only_available,
                    },
                    item_count=0,
                    warnings=[f"shop_id={shop_id} 未找到"],
                ),
            },
        }

    warnings.append("套餐工具当前未实现 DB 数据查询")
    return {
        "success": False,
        "result_status": "unsupported",
        "error_code": "TOOL_UNSUPPORTED",
        "error_message": "get_deal_list is not implemented for db backend",
        "data": {
            "status": "unsupported",
            "shop_id": str(shop_id),
            "shop_name": shop.get("shop_name"),
            "items": [],
            "warnings": warnings,
            "trace": _make_trace(
                "get_deal_list",
                started,
                status="unsupported",
                input_payload={
                    "shop_id": shop_id,
                    "people_count": people_count,
                    "budget_per_person": budget_per_person,
                    "deal_type": deal_type,
                    "only_available": only_available,
                },
                item_count=0,
                warnings=warnings,
                error_type="unsupported",
                error_message="get_deal_list is not implemented for db backend",
            ),
        },
    }


# ── Backward compatibility alias ──────────────────────────────────

calculate_distance = get_distance_eta
