"""Mock tools — simulated tool implementations for development and testing.

All data comes from static JSON files under mock_data/.
Supports 15 core scenarios defined in todo/07_构建Mock场景库和工具契约测试.md.

Field convention (todo/08 spec):
  - shop JSON: shop_id, shop_name, alias, category, address, lat, lng,
               avg_price, rating, tags
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

_MOCK_DATA_DIR = Path(__file__).resolve().parent.parent / "mock_data"

# ── Internal helpers ────────────────────────────────────────────


def _load_json(filename: str) -> list[dict] | dict:
    path = os.path.join(_MOCK_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _all_shops() -> list[dict]:
    data = _load_json("shops.json")
    return data if isinstance(data, list) else []


def _all_coupons() -> list[dict]:
    data = _load_json("coupons.json")
    return data if isinstance(data, list) else []


def _all_distance_eta() -> list[dict]:
    data = _load_json("distance_eta.json")
    return data if isinstance(data, list) else []


def _find_shop(shop_id: str) -> dict | None:
    for s in _all_shops():
        if s["shop_id"] == shop_id:
            return dict(s)
    return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate approximate distance in km between two coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


# ── 6 registered tools ──────────────────────────────────────────


def resolve_shop(query: str, location: dict[str, float] | None = None,
                 session_shop_ids: list[str] | None = None) -> dict:
    """Resolve a shop mention from user text to a known shop.

    Strategies tried in order:
      1. Exact shop_name match
      2. Alias match
      3. Partial name / category / tag match
      4. Session shop ID match

    Args:
        query: User's shop reference (name, alias, or "它").
        location: Optional user location for disambiguation.
        session_shop_ids: Shop IDs mentioned earlier in the session.

    Returns:
        Dict with status (RESOLVED / AMBIGUOUS / NOT_FOUND), shop info,
        candidates, and confidence.
    """
    if not query or not query.strip():
        return {
            "status": "NOT_FOUND",
            "shop": None,
            "candidates": [],
            "confidence": 0.0,
            "error_code": None,
        }

    query_lower = query.strip().lower()
    shops = _all_shops()
    matched: list[dict] = []

    # Strategy 1 & 2: exact name / alias match
    for s in shops:
        if s["shop_name"].lower() == query_lower:
            matched.append(s)
            continue
        alias = s.get("alias", "")
        if alias and alias.lower() == query_lower:
            matched.append(s)
            continue
        aliases = s.get("aliases", [])
        if any(a.lower() == query_lower for a in aliases):
            matched.append(s)
            continue

    # Strategy 3: if no exact match, try partial
    if not matched and query_lower not in ("它", "这家", "那家"):
        for s in shops:
            name_lower = s["shop_name"].lower()
            if query_lower in name_lower or query_lower in s["category"].lower():
                matched.append(s)

    # Strategy 4: session hint
    if not matched and session_shop_ids:
        for sid in session_shop_ids:
            s = _find_shop(sid)
            if s:
                matched.append(s)

    if len(matched) == 0:
        return {"status": "NOT_FOUND", "shop": None, "candidates": [], "confidence": 0.0, "error_code": "SHOP_NOT_FOUND"}

    if len(matched) == 1:
        shop = matched[0]
        return {
            "status": "RESOLVED",
            "shop": shop,
            "candidates": [],
            "confidence": 0.95,
            "error_code": None,
        }

    # Multiple matches — AMBIGUOUS
    candidates = [{"shop_id": s["shop_id"], "shop_name": s["shop_name"], "address": s.get("address", "")}
                  for s in matched[:5]]
    return {
        "status": "AMBIGUOUS",
        "shop": None,
        "candidates": candidates,
        "confidence": 0.5,
        "error_code": "AMBIGUOUS_SHOP",
    }


def search_shops(query: str, location: dict[str, float] | None = None, limit: int | None = None) -> dict:
    """Search shops by name, category, alias, or keyword.

    Supports exact name match, alias match, and partial keyword match
    across name / category / sub_category / tags.

    Args:
        query: Search keyword (shop name, alias, category, or tag).
        location: Optional user location for distance-based sorting.

    Returns:
        Search result with matched shops list.
    """
    if not query or not query.strip():
        return {"success": True, "result_status": "ok", "data": []}

    query_lower = query.strip().lower()
    shops = _all_shops()
    matched = []

    for shop in shops:
        name_lower = shop["shop_name"].lower()
        if query_lower == name_lower:
            matched.insert(0, shop)
            continue
        aliases = shop.get("aliases", [])
        if any(query_lower == a.lower() for a in aliases):
            matched.insert(0, shop)
            continue
        if (query_lower in name_lower
                or query_lower in shop["category"].lower()
                or query_lower in shop.get("sub_category", "").lower()
                or any(query_lower in tag.lower() for tag in shop.get("tags", []))):
            matched.append(shop)

    matched.sort(key=lambda s: s.get("rating", 0), reverse=True)

    if location:
        enriched: list[dict] = []
        for shop in matched:
            shop_copy = dict(shop)
            distance_meta = None
            for entry in _all_distance_eta():
                if entry["shop_id"] == shop_copy.get("shop_id"):
                    distance_meta = entry
                    break
            if distance_meta is not None:
                shop_copy["distance_km"] = distance_meta.get("distance_km")
                shop_copy["eta_minutes"] = distance_meta.get("eta_minutes")
                shop_copy["traffic_level"] = distance_meta.get("traffic_level", "low")
            enriched.append(shop_copy)
        matched = enriched

    if limit is not None:
        try:
            matched = matched[: max(0, int(limit))]
        except Exception:
            pass

    return {
        "success": True,
        "result_status": "ok",
        "data": matched,
        "total": len(matched),
    }


def get_shop_detail(shop_id: str) -> dict:
    """Get detailed information for a shop by ID.

    Args:
        shop_id: Unique shop identifier.

    Returns:
        Shop detail with standardized field set.
    """
    shop = _find_shop(shop_id)
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

    Special case — shop_sc_06 raises TimeoutError to simulate a
    coupon query timeout.

    Args:
        shop_id: Unique shop identifier.

    Returns:
        Coupon list result. Empty list for shops with no coupons.

    Raises:
        TimeoutError: When shop_sc_06 is queried.
    """
    if shop_id == "shop_sc_06":
        raise TimeoutError("Coupon query timed out for shop_sc_06 (simulated)")

    coupons = [c for c in _all_coupons() if c["shop_id"] == shop_id]

    return {
        "success": True,
        "result_status": "ok" if coupons else "empty",
        "data": coupons,
        "total": len(coupons),
    }


def check_open_status(shop_id: str) -> dict:
    """Check whether a shop is currently open.

    Returns the shop's ``open_status`` field: ``"open"``, ``"closed"``,
    or ``"unknown"``.

    Args:
        shop_id: Unique shop identifier.

    Returns:
        Open status result.
    """
    shop = _find_shop(shop_id)
    if shop is None:
        return {
            "success": False,
            "result_status": "failed",
            "error_code": "SHOP_NOT_FOUND",
            "error_message": f"Shop '{shop_id}' not found",
            "data": None,
        }

    status = shop.get("open_status", "unknown")
    return {
        "success": True,
        "result_status": "ok",
        "data": {
            "shop_id": shop_id,
            "shop_name": shop["shop_name"],
            "open_status": status,
            "business_hours": shop.get("business_hours", ""),
        },
    }


def get_distance_eta(shop_id: str, from_location: dict[str, float]) -> dict:
    """Calculate distance and ETA from user location to a shop.

    Uses pre-computed distance_eta.json when available, otherwise
    falls back to Haversine approximate calculation.

    Args:
        shop_id: Unique shop identifier.
        from_location: Dict with "lat" and "lng" keys.

    Returns:
        Distance & ETA result.
    """
    # Try pre-computed data first
    for entry in _all_distance_eta():
        if entry["shop_id"] == shop_id:
            shop = _find_shop(shop_id)
            return {
                "success": True,
                "result_status": "ok",
                "data": {
                    "shop_id": shop_id,
                    "shop_name": shop["shop_name"] if shop else "",
                    "distance_km": entry["distance_km"],
                    "eta_minutes": entry["eta_minutes"],
                    "traffic_level": entry.get("traffic_level", "low"),
                },
            }

    # Fallback: Haversine + rough ETA estimate
    shop = _find_shop(shop_id)
    if shop is None:
        return {
            "success": False,
            "result_status": "failed",
            "error_code": "SHOP_NOT_FOUND",
            "data": None,
        }

    lat1 = from_location.get("lat", 39.9609)
    lng1 = from_location.get("lng", 116.3581)
    lat2 = shop.get("lat", 0)
    lng2 = shop.get("lng", 0)

    distance = _haversine_km(lat1, lng1, lat2, lng2)
    eta = max(1, round(distance / 0.5))  # Rough: 0.5 km/min

    return {
        "success": True,
        "result_status": "ok",
        "data": {
            "shop_id": shop_id,
            "shop_name": shop["shop_name"],
            "distance_km": distance,
            "eta_minutes": eta,
            "traffic_level": "low",
        },
    }


# ── Backward compatibility alias ────────────────────────────────

calculate_distance = get_distance_eta
