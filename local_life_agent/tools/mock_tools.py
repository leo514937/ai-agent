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


# ── 9 registered tools ──────────────────────────────────────────


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

    if session_shop_ids:
        session_set = {str(sid).strip() for sid in session_shop_ids if str(sid).strip()}
        session_matched = [s for s in matched if str(s.get("shop_id", "")).strip() in session_set]
        if len(session_matched) == 1:
            shop = session_matched[0]
            return {
                "status": "RESOLVED",
                "shop": shop,
                "candidates": [],
                "confidence": 0.95,
                "error_code": None,
            }
        if len(session_matched) > 1:
            matched = session_matched

    # Multiple matches – AMBIGUOUS
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


def _all_deals() -> list[dict]:
    data = _load_json("deals.json")
    return data if isinstance(data, list) else []


def _all_review_summaries() -> list[dict]:
    data = _load_json("review_summaries.json")
    return data if isinstance(data, list) else []


def _shop_aliases(shop: dict) -> list[str]:
    aliases: list[str] = []
    alias = str(shop.get("alias", "") or "").strip()
    if alias:
        aliases.append(alias)
    for item in shop.get("aliases", []) or []:
        item_str = str(item or "").strip()
        if item_str and item_str not in aliases:
            aliases.append(item_str)
    return aliases


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


def _distance_meta(shop_id: str) -> dict | None:
    for entry in _all_distance_eta():
        if entry.get("shop_id") == shop_id:
            return dict(entry)
    return None


def _build_scene_tags(shop: dict, *, rating: float | None, avg_price: float | None, open_status: str | None) -> list[str]:
    tags = [str(item) for item in shop.get("tags", []) or [] if str(item).strip()]
    scene_tags: list[str] = []
    if any(token in tags for token in ["安静", "环境好", "咖啡", "甜品"]):
        scene_tags.append("约会")
    if any(token in tags for token in ["家庭", "聚餐", "长辈"]):
        scene_tags.append("家庭聚餐")
        scene_tags.append("带长辈")
    if any(token in tags for token in ["学生", "实惠"]) or (avg_price is not None and avg_price <= 30):
        scene_tags.append("学生党")
    if rating is not None and rating >= 4.4 and (open_status or "open") == "open":
        scene_tags.append("朋友聚餐")
    if avg_price is not None and avg_price >= 60:
        scene_tags.append("聚餐")
    return list(dict.fromkeys(scene_tags))


def _scene_fit(scene: str | None, *, rating: float | None, avg_price: float | None, tags: list[str], positive_tags: list[str], negative_tags: list[str]) -> dict:
    if not scene:
        return {"scene": None, "score": None, "label": None, "reasons": []}

    score = 0.5
    reasons: list[str] = []
    scene_lower = scene.lower()
    if scene_lower in {"date", "约会"}:
        if "约会" in tags or any(t in positive_tags for t in ["安静", "环境好"]):
            score += 0.25
            reasons.append("环境/标签更适合约会")
        if avg_price is not None and avg_price > 80:
            score -= 0.15
            reasons.append("价格偏高，约会预算压力更大")
    elif scene_lower in {"family", "elderly", "带长辈"}:
        if "带长辈" in tags or "家庭聚餐" in tags:
            score += 0.2
            reasons.append("场景标签匹配带长辈")
        if avg_price is not None and avg_price <= 60:
            score += 0.1
            reasons.append("人均更平稳")
        if any(t in negative_tags for t in ["排队久", "吵"]):
            score -= 0.15
            reasons.append("排队/噪音风险偏高")
    elif scene_lower in {"friends", "朋友聚餐"}:
        if "朋友聚餐" in tags:
            score += 0.2
            reasons.append("适合朋友聚餐的标签存在")
    elif scene_lower in {"student", "学生党"}:
        if "学生党" in tags or (avg_price is not None and avg_price <= 30):
            score += 0.25
            reasons.append("价格和标签都偏学生党友好")
    elif scene_lower in {"business", "商务"}:
        if any(t in positive_tags for t in ["环境好", "服务好"]) or rating is not None and rating >= 4.3:
            score += 0.2
            reasons.append("环境/服务更稳")

    score = max(0.0, min(1.0, round(score, 2)))
    if score >= 0.75:
        label = "high"
    elif score >= 0.55:
        label = "medium"
    else:
        label = "low"
    return {"scene": scene, "score": score, "label": label, "reasons": reasons or ["基于当前评分、标签和价格信息推断"]}


def _build_trace(tool_name: str, started: float, *, backend_source: str, status: str, input_payload: dict[str, Any], item_count: int | None = None,
                 missing_shop_ids: list[str] | None = None, warnings: list[str] | None = None,
                 error_type: str | None = None, error_message: str | None = None) -> dict:
    import time

    duration_ms = int((time.perf_counter() - started) * 1000.0)
    return {
        "tool_name": tool_name,
        "backend_source": backend_source,
        "duration_ms": duration_ms,
        "input": input_payload,
        "status": status,
        "item_count": item_count,
        "missing_shop_ids": list(missing_shop_ids or []),
        "warnings": list(warnings or []),
        "error_type": error_type,
        "error_message": error_message,
    }


def get_shop_cards(
    shop_ids: list[str],
    user_location: dict[str, float] | None = None,
    need_coupon_brief: bool = True,
    need_open_status: bool = True,
    need_distance_eta: bool = True,
    max_items: int | None = None,
) -> dict:
    """Batch fetch lightweight shop facts for recommendation / comparison."""
    import time

    started = time.perf_counter()
    warnings: list[str] = []
    missing: list[str] = []
    items: list[dict[str, Any]] = []
    location = user_location if isinstance(user_location, dict) else None
    if need_distance_eta and location is None:
        warnings.append("未提供用户位置，距离和 ETA 返回 null")

    limit = len(shop_ids) if max_items is None else max(0, int(max_items))
    for sid in [str(item).strip() for item in shop_ids or [] if str(item).strip()][:limit]:
        shop = _find_shop(sid)
        if shop is None:
            missing.append(sid)
            continue

        rating = shop.get("rating")
        avg_price = shop.get("avg_price")
        open_status = shop.get("open_status", "unknown")
        distance_m: int | None = None
        eta_minutes: int | None = None
        if need_distance_eta and location is not None:
            meta = _distance_meta(sid)
            if meta is not None:
                distance_m = int(round(float(meta.get("distance_km", 0.0)) * 1000))
                eta_minutes = int(meta.get("eta_minutes", 0))
            elif shop.get("lat") is not None and shop.get("lng") is not None:
                lat1 = float(location.get("lat", 39.9609))
                lng1 = float(location.get("lng", 116.3581))
                distance_km = _haversine_km(lat1, lng1, float(shop.get("lat", 0.0)), float(shop.get("lng", 0.0)))
                distance_m = int(round(distance_km * 1000))
                eta_minutes = max(1, round(distance_km / 0.5))

        coupons = [c for c in _all_coupons() if c.get("shop_id") == sid] if need_coupon_brief else []
        top_coupon_title = coupons[0].get("title") if coupons else None
        item = {
            "shop_id": sid,
            "name": shop.get("shop_name", ""),
            "alias": _shop_aliases(shop),
            "category": shop.get("category"),
            "address": shop.get("address"),
            "rating": rating,
            "avg_price": avg_price,
            "price_level": _price_level(avg_price),
            "distance_m": distance_m,
            "eta_minutes": eta_minutes,
            "is_open": True if open_status == "open" else False if open_status == "closed" else None,
            "open_status_text": open_status,
            "coupon_count": len(coupons) if need_coupon_brief else None,
            "has_coupon": bool(coupons) if need_coupon_brief else None,
            "top_coupon_title": top_coupon_title,
            "top_tags": [str(tag) for tag in shop.get("tags", []) or [] if str(tag).strip()],
            "scene_tags": _build_scene_tags(shop, rating=rating, avg_price=avg_price, open_status=open_status),
            "source_fields": ["detail"],
        }
        if need_coupon_brief:
            item["source_fields"].append("coupon")
        if need_open_status:
            item["source_fields"].append("open_status")
        if need_distance_eta:
            item["source_fields"].append("distance_eta")
        items.append(item)

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
            "trace": _build_trace(
                "get_shop_cards",
                started,
                backend_source="mock",
                status=status,
                input_payload={
                    "shop_ids": shop_ids,
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
    """Structured shop review summary with scene-fit inference."""
    import time

    started = time.perf_counter()
    warnings: list[str] = []
    missing: list[str] = []
    items: list[dict[str, Any]] = []
    review_by_shop = {str(item.get("shop_id", "")).strip(): dict(item) for item in _all_review_summaries()}
    requested_aspects = [str(item).strip() for item in (aspects or []) if str(item).strip()]

    if scene and scene not in {"date", "family", "friends", "elderly", "student", "business", "约会", "带长辈", "朋友聚餐", "学生党", "商务"}:
        warnings.append(f"scene={scene} 未命中明确场景词，仍会给出基于现有事实的推断")

    for sid in [str(item).strip() for item in shop_ids or [] if str(item).strip()][: max(0, int(max_reviews)) if isinstance(max_reviews, int) and max_reviews > 0 else len(shop_ids or [])]:
        shop = _find_shop(sid)
        if shop is None:
            missing.append(sid)
            continue

        review = review_by_shop.get(sid, {})
        rating = review.get("rating", shop.get("rating"))
        review_count = review.get("review_count", shop.get("comments"))
        shop_tags = [str(tag) for tag in shop.get("tags", []) or [] if str(tag).strip()]
        positive_tags = list(review.get("positive_tags") or [])
        negative_tags = list(review.get("negative_tags") or [])
        scene_tags = list(review.get("scene_tags") or [])
        if not positive_tags:
            positive_tags = [tag for tag in shop_tags if tag in {"安静", "有WiFi", "环境好", "服务好", "实惠", "学生", "咖啡", "甜品"}]
        if not negative_tags and review.get("risks"):
            negative_tags = [str(item) for item in review.get("risks", []) if str(item).strip()]
        if not scene_tags:
            scene_tags = _build_scene_tags(shop, rating=rating, avg_price=shop.get("avg_price"), open_status=shop.get("open_status"))

        taste_score = review.get("taste_score", rating)
        environment_score = review.get("environment_score", rating)
        service_score = review.get("service_score", rating)
        price_score = review.get("price_score")
        if price_score is None and shop.get("avg_price") is not None:
            price_score = max(1.0, 5.0 - float(shop["avg_price"]) / 30.0)

        highlights = list(review.get("highlights") or [])
        risks = list(review.get("risks") or [])
        summary = review.get("summary")
        source_fields = list(review.get("source_fields") or [])
        if "rating" not in source_fields:
            source_fields.append("rating")
        if shop_tags and "shop_tags" not in source_fields:
            source_fields.append("shop_tags")
        if review.get("blog_summary") and "blog_summary" not in source_fields:
            source_fields.append("blog_summary")
        if review.get("facade_review_summary") and "facade_review_summary" not in source_fields:
            source_fields.append("facade_review_summary")

        if not summary:
            summary_parts = [f"评分{rating:.1f}" if isinstance(rating, (int, float)) else "评分暂无"]
            if scene_tags:
                summary_parts.append(f"适合场景：{'、'.join(scene_tags[:3])}")
            if highlights:
                summary_parts.append(f"优点：{'、'.join(highlights[:2])}")
            if risks:
                summary_parts.append(f"风险：{'、'.join(risks[:2])}")
            summary = "；".join(summary_parts)

        scene_fit = review.get("scene_fit")
        if not isinstance(scene_fit, dict):
            scene_fit = _scene_fit(scene, rating=rating, avg_price=shop.get("avg_price"), tags=scene_tags, positive_tags=positive_tags, negative_tags=negative_tags)
        else:
            scene_fit = {
                "scene": scene_fit.get("scene", scene),
                "score": scene_fit.get("score"),
                "label": scene_fit.get("label"),
                "reasons": list(scene_fit.get("reasons") or []),
            }

        items.append(
            {
                "shop_id": sid,
                "name": shop.get("shop_name", ""),
                "rating": rating,
                "review_count": review_count,
                "taste_score": taste_score,
                "environment_score": environment_score,
                "service_score": service_score,
                "price_score": price_score,
                "positive_tags": positive_tags,
                "negative_tags": negative_tags,
                "scene_tags": scene_tags,
                "scene_fit": scene_fit,
                "highlights": highlights,
                "risks": risks,
                "summary": summary,
                "source_fields": source_fields,
            }
        )

    status = "empty" if not items and not missing else "partial" if missing or warnings else "ok"
    if not items and missing:
        status = "empty"
    if requested_aspects:
        for item in items:
            item["source_fields"].append("aspects")
    return {
        "success": True,
        "result_status": status,
        "data": {
            "status": status,
            "items": items,
            "missing_shop_ids": missing,
            "warnings": warnings,
            "trace": _build_trace(
                "get_shop_review_summary",
                started,
                backend_source="mock",
                status=status,
                input_payload={
                    "shop_ids": shop_ids,
                    "aspects": aspects or [],
                    "scene": scene,
                    "max_reviews": max_reviews,
                },
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
    """Return deal / group-buy facts for a shop."""
    import time

    started = time.perf_counter()
    warnings: list[str] = []
    shop = _find_shop(shop_id)
    if shop is None:
        warnings.append(f"shop_id={shop_id} 未找到，返回空套餐结果")
        return {
            "success": True,
            "result_status": "empty",
            "data": {
                "status": "empty",
                "shop_id": str(shop_id),
                "shop_name": None,
                "items": [],
                "warnings": warnings,
                "trace": _build_trace(
                    "get_deal_list",
                    started,
                    backend_source="mock",
                    status="empty",
                    input_payload={
                        "shop_id": shop_id,
                        "people_count": people_count,
                        "budget_per_person": budget_per_person,
                        "deal_type": deal_type,
                        "only_available": only_available,
                    },
                    item_count=0,
                    warnings=warnings,
                ),
            },
        }

    deals = [dict(item) for item in _all_deals() if str(item.get("shop_id", "")).strip() == str(shop_id).strip()]
    if not deals:
        warnings.append("当前没有查到套餐数据，仅有 coupon 数据时不回退拼接")

    filtered: list[dict[str, Any]] = []
    for deal in deals:
        if only_available and not bool(deal.get("available", True)):
            continue
        if deal_type and str(deal.get("deal_type", "")).strip() and str(deal.get("deal_type")).strip() != str(deal_type).strip():
            continue
        price = deal.get("price")
        original_price = deal.get("original_price")
        discount_rate = None
        if isinstance(price, (int, float)) and isinstance(original_price, (int, float)) and original_price:
            discount_rate = round(float(price) / float(original_price), 4)
        avg_price_per_person = None
        if people_count and people_count > 0 and isinstance(price, (int, float)):
            avg_price_per_person = round(float(price) / float(people_count), 2)
        elif isinstance(price, (int, float)):
            min_people = deal.get("people_count_min") or 1
            max_people = deal.get("people_count_max") or min_people
            estimated_people = max(1, int(round((float(min_people) + float(max_people)) / 2.0)))
            avg_price_per_person = round(float(price) / estimated_people, 2)
        if budget_per_person is not None and avg_price_per_person is not None and avg_price_per_person > float(budget_per_person):
            continue
        filtered.append(
            {
                "deal_id": str(deal.get("deal_id", "")),
                "title": str(deal.get("title", "")),
                "deal_type": deal.get("deal_type"),
                "price": price,
                "original_price": original_price,
                "discount_rate": discount_rate,
                "people_count_min": deal.get("people_count_min"),
                "people_count_max": deal.get("people_count_max"),
                "avg_price_per_person": avg_price_per_person,
                "available": deal.get("available"),
                "valid_time_text": deal.get("valid_time_text"),
                "use_time_rules": list(deal.get("use_time_rules") or []),
                "limitations": list(deal.get("limitations") or []),
                "included_items": list(deal.get("included_items") or []),
                "recommend_tags": list(deal.get("recommend_tags") or []),
                "source_fields": ["deal_catalog"],
            }
        )

    status = "empty" if not filtered else "partial" if warnings else "ok"
    return {
        "success": True,
        "result_status": status,
        "data": {
            "status": status,
            "shop_id": str(shop_id),
            "shop_name": shop.get("shop_name"),
            "items": filtered,
            "warnings": warnings,
            "trace": _build_trace(
                "get_deal_list",
                started,
                backend_source="mock",
                status=status,
                input_payload={
                    "shop_id": shop_id,
                    "people_count": people_count,
                    "budget_per_person": budget_per_person,
                    "deal_type": deal_type,
                    "only_available": only_available,
                },
                item_count=len(filtered),
                warnings=warnings,
            ),
        },
    }


# ── Backward compatibility alias ────────────────────────────────

calculate_distance = get_distance_eta
