from __future__ import annotations

from datetime import datetime, time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from ..local_life.catalog import LocalLifeCatalog, get_default_catalog
from ..local_life.schemas import (
    BlogRecord,
    LocalLifeIntentType,
    LocalLifeSlots,
    LocationNorm,
    PriceNorm,
    ShopRecord,
    ShopTypeRecord,
    VoucherRecord,
)
from .transaction_store import InMemoryTransactionStore
from .models import RegisteredTool, SideEffectLevel, ToolSpec
from .registry import ToolRegistry




class SearchRestaurantsToolInput(BaseModel):
    query: str = Field(default="")
    city: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: float = Field(default=3.0)
    category: Optional[str] = None
    shop_query: Optional[str] = None
    shop_ids: list[int] = Field(default_factory=list)
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    target_price: Optional[float] = None
    scene: Optional[str] = None
    scene_tags: list[str] = Field(default_factory=list)
    companions: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    need_open_now: bool = False
    need_parking: bool = False
    need_quiet: bool = False
    need_family_friendly: bool = False
    need_elder_friendly: bool = False
    limit: int = Field(default=5)
    page: Optional[str] = None


class ShopDetailToolInput(BaseModel):
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    query: str = Field(default="")
    lat: Optional[float] = None
    lng: Optional[float] = None
    current: int = Field(default=1)


class ShopTypeListToolInput(BaseModel):
    limit: int = Field(default=20)


class CouponListToolInput(BaseModel):
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    limit: int = Field(default=10)


class BlogListToolInput(BaseModel):
    shop_id: Optional[int] = None
    user_id: Optional[int] = None
    shop_name: Optional[str] = None
    current: int = Field(default=1)
    limit: int = Field(default=5)


class DistanceEtaToolInput(BaseModel):
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    shop_lat: Optional[float] = None
    shop_lng: Optional[float] = None
    mode: str = Field(default="drive")
    speed_kmh: Optional[float] = None


class OpenStatusToolInput(BaseModel):
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    open_hours: Optional[str] = None


class BookingToolInput(BaseModel):
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    booking_time: Optional[str] = None
    party_size: Optional[int] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    note: Optional[str] = None
    idempotency_key: Optional[str] = None
    current: int = Field(default=1)


class OrderToolInput(BaseModel):
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    amount: Optional[float] = None
    note: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    idempotency_key: Optional[str] = None
    current: int = Field(default=1)


class CancelOrderToolInput(BaseModel):
    order_id: Optional[str] = None
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None


class RefundOrderToolInput(BaseModel):
    order_id: Optional[str] = None
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None


class OrderStatusToolInput(BaseModel):
    order_id: Optional[str] = None


class GenericToolOutput(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


def _tool_output(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"data": data}


def _dump_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump_model(item) for item in value]
    if isinstance(value, dict):
        return dict(value)
    return value


def _transaction_payload(record: Any, transaction_type: str) -> Dict[str, Any]:
    if hasattr(record, "to_payload"):
        payload = record.to_payload()
    elif isinstance(record, Mapping):
        payload = dict(record)
    else:
        return {}

    payload = dict(payload)
    transaction_key = "booking_id" if transaction_type == "booking" else "order_id"
    transaction_id = payload.get(transaction_key) or payload.get("transaction_id")
    if transaction_id is not None:
        payload.setdefault(transaction_key, transaction_id)
        payload.setdefault("transaction_id", transaction_id)
    payload.setdefault("transaction_type", transaction_type)
    return payload


def _transaction_tool_output(
    *,
    transaction_type: str,
    record: Any,
    source_mode: str,
    degraded_reason: str | None = None,
) -> Dict[str, Any]:
    payload = _transaction_payload(record, transaction_type)
    source = "java" if source_mode == "java_business" else "transaction_store"
    result = {
        "status": payload.get("status"),
        transaction_type: payload,
        "source": source,
        "source_mode": source_mode,
        "degraded_reason": degraded_reason,
    }
    if payload.get("approval_state") is not None:
        result["approval_state"] = payload.get("approval_state")
    return _tool_output(result)


def _run_transaction_action(
    *,
    client: Any,
    transaction_type: str,
    remote_call: Callable[[], Any],
    store_call: Callable[[], Any],
) -> tuple[Any, str, str | None]:
    is_remote_ready = client is not None and bool(getattr(client, "enabled", False))
    fallback_allowed = client is None or bool(getattr(client, "enable_fallback", False))
    if is_remote_ready:
        try:
            remote_record = remote_call()
        except Exception as exc:
            if not fallback_allowed:
                raise RuntimeError("Java business write failed") from exc
            remote_record = None
            degraded_reason = "java_business_write_failed"
        else:
            if remote_record is not None:
                return remote_record, "java_business", None
            if not fallback_allowed:
                raise RuntimeError("Java business write returned no result")
            degraded_reason = "java_business_write_unavailable"
    else:
        if not fallback_allowed:
            raise RuntimeError("Java business client is unavailable")
        degraded_reason = "java_business_not_configured"

    return store_call(), "transaction_store", degraded_reason


def _normalize_tags(values: Sequence[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        text = str(value or "").strip().lower()
        if text:
            normalized.append(text)
    return normalized


def _build_local_life_slots(payload: SearchRestaurantsToolInput) -> LocalLifeSlots:
    preferences = list(payload.preferences)
    scene_tags = _normalize_tags(payload.scene_tags)
    if payload.need_quiet or "quiet" in scene_tags:
        preferences.append("quiet")
    if payload.need_parking or "parking" in scene_tags or "parking_available" in scene_tags:
        preferences.append("parking_available")
    if payload.need_family_friendly or "family" in scene_tags or "family_dinner" in scene_tags:
        preferences.append("family_friendly")
    if payload.need_elder_friendly or "elder" in scene_tags or "elder_friendly" in scene_tags:
        preferences.append("elder_friendly")

    return LocalLifeSlots(
        city=payload.city,
        category=payload.category,
        location=LocationNorm(city=payload.city, lat=payload.lat, lng=payload.lng, radius_km=payload.radius_km),
        price=PriceNorm(per_person_min=payload.price_min, per_person_max=payload.price_max, target=payload.target_price),
        scene=payload.scene,
        companions=list(payload.companions),
        preferences=preferences,
        avoid=list(payload.avoid),
        action=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        shop_query=payload.shop_query or payload.query or payload.category,
        shop_ids=list(payload.shop_ids),
        page=payload.page,
    )


def _make_topic_text(payload: Any) -> str:
    topic = getattr(payload, "topic", None)
    if isinstance(topic, str) and topic.strip():
        return topic.strip()
    query = getattr(payload, "query", None)
    if isinstance(query, str) and query.strip():
        return query.strip()
    return "general-topic"


def _parse_open_window(value: Optional[str]) -> tuple[Optional[time], Optional[time]]:
    if not isinstance(value, str) or "-" not in value:
        return None, None
    start_text, end_text = value.split("-", 1)
    try:
        start_hour, start_minute = [int(part) for part in start_text.strip().split(":", 1)]
        end_hour, end_minute = [int(part) for part in end_text.strip().split(":", 1)]
    except Exception:
        return None, None
    try:
        return time(hour=start_hour, minute=start_minute), time(hour=end_hour, minute=end_minute)
    except Exception:
        return None, None




def _shop_payload(shop: ShopRecord) -> Dict[str, Any]:
    return _dump_model(shop)


def _voucher_payload(voucher: VoucherRecord) -> Dict[str, Any]:
    return _dump_model(voucher)


def _blog_payload(blog: BlogRecord) -> Dict[str, Any]:
    return _dump_model(blog)


def _shop_type_payload(shop_type: ShopTypeRecord) -> Dict[str, Any]:
    return _dump_model(shop_type)


def _resolve_catalog_shop(
    *,
    client: Any,
    catalog: LocalLifeCatalog,
    shop_id: Optional[int] = None,
    shop_name: Optional[str] = None,
    query: str = "",
    current: int = 1,
) -> ShopRecord | None:
    if shop_id is not None:
        try:
            resolved_id = int(shop_id)
        except Exception:
            resolved_id = None
        if resolved_id is not None:
            if client is not None and hasattr(client, "get_shop_detail"):
                try:
                    return client.get_shop_detail(resolved_id)
                except Exception:
                    if not _catalog_fallback_allowed(client):
                        raise
            shop = catalog.get_shop(resolved_id)
            if shop is not None:
                return shop

    search_name = (shop_name or query or "").strip()
    if search_name:
        if client is not None and hasattr(client, "search_shops_by_name"):
            try:
                shops = client.search_shops_by_name(name=search_name, current=int(current))
                if shops:
                    return shops[0]
            except Exception:
                if not _catalog_fallback_allowed(client):
                    raise
        shops = catalog.search_shops(query=search_name, slots=LocalLifeSlots(shop_query=search_name), limit=1)
        if shops:
            return shops[0]
    return None


def _detect_source(client: Any) -> str:
    if client is not None and bool(getattr(client, "enabled", False)):
        return "java"
    return "catalog"


def _catalog_fallback_allowed(client: Any) -> bool:
    if client is None:
        return True
    return bool(getattr(client, "enable_fallback", False))


def build_builtin_tool_registry(
    *,
    java_business_client: Any = None,
    transaction_store: InMemoryTransactionStore | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    catalog = get_default_catalog()
    local_life_client = java_business_client
    transaction_store = transaction_store or InMemoryTransactionStore()


    def _search_restaurants(payload: SearchRestaurantsToolInput) -> Dict[str, Any]:
        slots = _build_local_life_slots(payload)
        query = payload.query or payload.shop_query or payload.category or _make_topic_text(payload)
        if local_life_client is not None and hasattr(local_life_client, "recommend_shops"):
            try:
                shops = list(local_life_client.recommend_shops(query=query, slots=slots, limit=payload.limit))
            except Exception:
                if not _catalog_fallback_allowed(local_life_client):
                    raise
                shops = catalog.search_shops(query=query, slots=slots, limit=payload.limit, shop_ids=payload.shop_ids)
        elif local_life_client is not None and hasattr(local_life_client, "search_candidates"):
            try:
                shops = list(local_life_client.search_candidates(query=query, slots=slots, limit=payload.limit))
            except Exception:
                if not _catalog_fallback_allowed(local_life_client):
                    raise
                shops = catalog.search_shops(query=query, slots=slots, limit=payload.limit, shop_ids=payload.shop_ids)
        else:
            shops = catalog.search_shops(query=query, slots=slots, limit=payload.limit, shop_ids=payload.shop_ids)

        if payload.need_open_now:
            open_shops: list[ShopRecord] = []
            for shop in shops:
                status = _check_open_status(local_life_client, catalog, shop=shop, open_hours=None)
                if bool(status.get("open_now")):
                    open_shops.append(shop)
            if open_shops:
                shops = open_shops

        data = {
            "query": query,
            "slots": _dump_model(slots),
            "candidate_count": len(shops),
            "shop_ids": [int(shop.id) for shop in shops],
            "candidates": [_shop_payload(shop) for shop in shops],
            "source": _detect_source(local_life_client),
        }
        return _tool_output(data)

    def _search_shop_types(payload: ShopTypeListToolInput) -> Dict[str, Any]:
        if local_life_client is not None and hasattr(local_life_client, "list_shop_types"):
            try:
                shop_types = list(local_life_client.list_shop_types())
            except Exception:
                if not _catalog_fallback_allowed(local_life_client):
                    raise
                shop_types = catalog.list_shop_types()
        else:
            shop_types = catalog.list_shop_types()
        shop_types = shop_types[: max(0, int(payload.limit))]
        return _tool_output(
            {
                "count": len(shop_types),
                "shop_types": [_shop_type_payload(item) for item in shop_types],
                "source": _detect_source(local_life_client),
            }
        )

    def _search_shop_detail(payload: ShopDetailToolInput) -> Dict[str, Any]:
        shop = _resolve_catalog_shop(
            client=local_life_client,
            catalog=catalog,
            shop_id=payload.shop_id,
            shop_name=payload.shop_name,
            query=payload.query,
            current=payload.current,
        )
        if shop is None:
            raise RuntimeError("shop not found")
        open_status = _check_open_status(local_life_client, catalog, shop=shop, open_hours=None)
        distance_eta = _get_distance_eta(
            local_life_client,
            catalog,
            shop=shop,
            lat=payload.lat,
            lng=payload.lng,
            shop_lat=None,
            shop_lng=None,
            mode="drive",
            speed_kmh=None,
        )
        return _tool_output(
            {
                "shop": _shop_payload(shop),
                "open_status": open_status,
                "distance_eta": distance_eta,
                "source": _detect_source(local_life_client),
            }
        )

    def _search_coupons(payload: CouponListToolInput) -> Dict[str, Any]:
        shop = _resolve_catalog_shop(
            client=local_life_client,
            catalog=catalog,
            shop_id=payload.shop_id,
            shop_name=payload.shop_name,
        )
        shop_id = int(shop.id) if shop is not None else int(payload.shop_id or 0)
        if shop_id:
            if local_life_client is not None and hasattr(local_life_client, "get_coupon_list"):
                try:
                    coupons = list(local_life_client.get_coupon_list(shop_id))
                except Exception:
                    if not _catalog_fallback_allowed(local_life_client):
                        raise
                    coupons = catalog.list_vouchers(shop_id)
            else:
                coupons = catalog.list_vouchers(shop_id)
        else:
            coupons = []
        coupons = coupons[: max(0, int(payload.limit))]
        return _tool_output(
            {
                "shop_id": shop_id or None,
                "count": len(coupons),
                "coupons": [_voucher_payload(voucher) for voucher in coupons],
                "source": _detect_source(local_life_client),
            }
        )

    def _search_blogs(payload: BlogListToolInput) -> Dict[str, Any]:
        blogs: list[BlogRecord]
        scope = "hot"
        if payload.shop_id is not None or payload.shop_name:
            shop = _resolve_catalog_shop(
                client=local_life_client,
                catalog=catalog,
                shop_id=payload.shop_id,
                shop_name=payload.shop_name,
            )
            if shop is not None:
                scope = "shop"
                if local_life_client is not None and hasattr(local_life_client, "get_shop_blogs"):
                    try:
                        blogs = list(local_life_client.get_shop_blogs(int(shop.id), int(payload.limit)))
                    except Exception:
                        if not _catalog_fallback_allowed(local_life_client):
                            raise
                        blogs = catalog.list_shop_blogs(int(shop.id), limit=payload.limit)
                else:
                    blogs = catalog.list_shop_blogs(int(shop.id), limit=payload.limit)
            else:
                blogs = []
        elif payload.user_id is not None:
            scope = "user"
            if local_life_client is not None and hasattr(local_life_client, "get_blog_of_user"):
                try:
                    blogs = list(local_life_client.get_blog_of_user(int(payload.user_id), int(payload.current)))
                except Exception:
                    if not _catalog_fallback_allowed(local_life_client):
                        raise
                    blogs = catalog.list_user_blogs(int(payload.user_id), limit=payload.limit)
            else:
                blogs = catalog.list_user_blogs(int(payload.user_id), limit=payload.limit)
        else:
            if local_life_client is not None and hasattr(local_life_client, "get_blog_hot"):
                try:
                    blogs = list(local_life_client.get_blog_hot(int(payload.current)))
                except Exception:
                    if not _catalog_fallback_allowed(local_life_client):
                        raise
                    blogs = catalog.list_hot_blogs(limit=payload.limit)
            else:
                blogs = catalog.list_hot_blogs(limit=payload.limit)
        blogs = blogs[: max(0, int(payload.limit))]
        return _tool_output(
            {
                "scope": scope,
                "count": len(blogs),
                "blogs": [_blog_payload(blog) for blog in blogs],
                "source": _detect_source(local_life_client),
            }
        )

    def _check_open_status(
        client: Any,
        catalog: LocalLifeCatalog,
        *,
        shop: ShopRecord | None = None,
        shop_id: Optional[int] = None,
        shop_name: Optional[str] = None,
        open_hours: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_shop = shop or _resolve_catalog_shop(
            client=client,
            catalog=catalog,
            shop_id=shop_id,
            shop_name=shop_name,
        )
        if resolved_shop is None and not open_hours:
            return {"open_status": "unknown", "open_now": None}
        if client is not None and hasattr(client, "check_open_status"):
            try:
                return dict(client.check_open_status(resolved_shop or {"open_hours": open_hours}))
            except Exception:
                pass
        hours = open_hours or getattr(resolved_shop, "open_hours", None)
        if not isinstance(hours, str) or "-" not in hours:
            return {"open_status": "unknown", "open_now": None, "open_hours": hours}
        start, end = _parse_open_window(hours)
        if start is None or end is None:
            return {"open_status": "unknown", "open_now": None, "open_hours": hours}
        now = datetime.now().time()
        open_now = start <= now <= end if start <= end else (now >= start or now <= end)
        return {
            "open_status": "open" if open_now else "closed",
            "open_now": open_now,
            "open_hours": hours,
        }

    def _get_distance_eta(
        client: Any,
        catalog: LocalLifeCatalog,
        *,
        shop: ShopRecord | None = None,
        shop_id: Optional[int] = None,
        shop_name: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        shop_lat: Optional[float] = None,
        shop_lng: Optional[float] = None,
        mode: str = "drive",
        speed_kmh: Optional[float] = None,
    ) -> Dict[str, Any]:
        resolved_shop = shop or _resolve_catalog_shop(
            client=client,
            catalog=catalog,
            shop_id=shop_id,
            shop_name=shop_name,
        )
        if client is not None and hasattr(client, "get_distance_eta"):
            try:
                return dict(
                    client.get_distance_eta(
                        resolved_shop or {
                            "x": shop_lat,
                            "y": shop_lng,
                            "distance_km": None,
                        },
                        lat=lat,
                        lng=lng,
                    )
                )
            except Exception:
                pass

        source_x = shop_lat
        source_y = shop_lng
        if resolved_shop is not None:
            source_x = getattr(resolved_shop, "x", None)
            source_y = getattr(resolved_shop, "y", None)
        distance_km = None
        if lat is not None and lng is not None and source_x is not None and source_y is not None:
            from math import asin, cos, radians, sin, sqrt

            radius = 6371.0
            d_lat = radians(float(source_y) - float(lat))
            d_lng = radians(float(source_x) - float(lng))
            a = sin(d_lat / 2) ** 2 + cos(radians(float(lat))) * cos(radians(float(source_y))) * sin(d_lng / 2) ** 2
            distance_km = 2 * radius * asin(sqrt(max(0.0, min(1.0, a))))
        if distance_km is None:
            distance_km = getattr(resolved_shop, "distance_km", None) or 0.0
        speed = float(speed_kmh or (35.0 if mode == "drive" else 5.0))
        eta_minutes = max(5, int(round((float(distance_km) / max(speed, 1.0)) * 60.0)))
        return {
            "distance_km": round(float(distance_km), 2),
            "eta_minutes": eta_minutes,
            "mode": mode,
            "source": _detect_source(client),
        }

    def _open_status_handler(payload: OpenStatusToolInput) -> Dict[str, Any]:
        shop = _resolve_catalog_shop(
            client=local_life_client,
            catalog=catalog,
            shop_id=payload.shop_id,
            shop_name=payload.shop_name,
        )
        return _tool_output(
            {
                **_check_open_status(
                    local_life_client,
                    catalog,
                    shop=shop,
                    shop_id=payload.shop_id,
                    shop_name=payload.shop_name,
                    open_hours=payload.open_hours,
                ),
                "source": _detect_source(local_life_client),
            }
        )

    def _distance_eta_handler(payload: DistanceEtaToolInput) -> Dict[str, Any]:
        shop = _resolve_catalog_shop(
            client=local_life_client,
            catalog=catalog,
            shop_id=payload.shop_id,
            shop_name=payload.shop_name,
        )
        return _tool_output(
            _get_distance_eta(
                local_life_client,
                catalog,
                shop=shop,
                shop_id=payload.shop_id,
                shop_name=payload.shop_name,
                lat=payload.lat,
                lng=payload.lng,
                shop_lat=payload.shop_lat,
                shop_lng=payload.shop_lng,
                mode=payload.mode,
                speed_kmh=payload.speed_kmh,
            )
        )

    def _create_booking(payload: BookingToolInput) -> Dict[str, Any]:
        record, source_mode, degraded_reason = _run_transaction_action(
            client=local_life_client,
            transaction_type="booking",
            remote_call=lambda: local_life_client.create_booking(
                shop_id=int(payload.shop_id) if payload.shop_id is not None else None,
                shop_name=payload.shop_name,
                payload={
                    "booking_time": payload.booking_time,
                    "party_size": payload.party_size,
                    "contact_name": payload.contact_name,
                    "contact_phone": payload.contact_phone,
                    "note": payload.note,
                    "current": payload.current,
                },
                idempotency_key=payload.idempotency_key,
            ),
            store_call=lambda: transaction_store.create_booking(
                shop_id=int(payload.shop_id) if payload.shop_id is not None else None,
                shop_name=payload.shop_name,
                payload={
                    "booking_time": payload.booking_time,
                    "party_size": payload.party_size,
                    "contact_name": payload.contact_name,
                    "contact_phone": payload.contact_phone,
                    "note": payload.note,
                    "current": payload.current,
                },
                idempotency_key=payload.idempotency_key,
            ),
        )
        return _transaction_tool_output(
            transaction_type="booking",
            record=record,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
        )

    def _create_order(payload: OrderToolInput) -> Dict[str, Any]:
        record, source_mode, degraded_reason = _run_transaction_action(
            client=local_life_client,
            transaction_type="order",
            remote_call=lambda: local_life_client.create_order(
                shop_id=int(payload.shop_id) if payload.shop_id is not None else None,
                shop_name=payload.shop_name,
                payload={
                    "amount": payload.amount,
                    "note": payload.note,
                    "contact_name": payload.contact_name,
                    "contact_phone": payload.contact_phone,
                    "current": payload.current,
                },
                idempotency_key=payload.idempotency_key,
            ),
            store_call=lambda: transaction_store.create_order(
                shop_id=int(payload.shop_id) if payload.shop_id is not None else None,
                shop_name=payload.shop_name,
                payload={
                    "amount": payload.amount,
                    "note": payload.note,
                    "contact_name": payload.contact_name,
                    "contact_phone": payload.contact_phone,
                    "current": payload.current,
                },
                idempotency_key=payload.idempotency_key,
            ),
        )
        return _transaction_tool_output(
            transaction_type="order",
            record=record,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
        )

    def _cancel_order(payload: CancelOrderToolInput) -> Dict[str, Any]:
        record, source_mode, degraded_reason = _run_transaction_action(
            client=local_life_client,
            transaction_type="order",
            remote_call=lambda: local_life_client.cancel_order(
                payload.order_id,
                reason=payload.reason,
                idempotency_key=payload.idempotency_key,
            ),
            store_call=lambda: transaction_store.cancel_order(
                payload.order_id,
                reason=payload.reason,
                idempotency_key=payload.idempotency_key,
            ),
        )
        return _transaction_tool_output(
            transaction_type="order",
            record=record,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
        )

    def _refund_order(payload: RefundOrderToolInput) -> Dict[str, Any]:
        record, source_mode, degraded_reason = _run_transaction_action(
            client=local_life_client,
            transaction_type="order",
            remote_call=lambda: local_life_client.refund_order(
                payload.order_id,
                reason=payload.reason,
                idempotency_key=payload.idempotency_key,
            ),
            store_call=lambda: transaction_store.refund_order(
                payload.order_id,
                reason=payload.reason,
                idempotency_key=payload.idempotency_key,
            ),
        )
        return _transaction_tool_output(
            transaction_type="order",
            record=record,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
        )

    def _get_order_status(payload: OrderStatusToolInput) -> Dict[str, Any]:
        record, source_mode, degraded_reason = _run_transaction_action(
            client=local_life_client,
            transaction_type="order",
            remote_call=lambda: local_life_client.get_order_status(payload.order_id),
            store_call=lambda: transaction_store.get_order_status(payload.order_id),
        )
        return _transaction_tool_output(
            transaction_type="order",
            record=record,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
        )

    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="search_restaurants",
                description="按位置、价格、类目、场景等条件搜索餐厅候选",
                input_model=SearchRestaurantsToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
                degrade_to="catalog-search",
            ),
            handler=_search_restaurants,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="get_shop_detail",
                description="查询单个商户详情",
                input_model=ShopDetailToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_search_shop_detail,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="get_shop_type_list",
                description="查询商户分类列表",
                input_model=ShopTypeListToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_search_shop_types,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="get_coupon_list",
                description="查询商户优惠券列表",
                input_model=CouponListToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_search_coupons,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="get_blog_list",
                description="查询商户/用户/热门探店笔记",
                input_model=BlogListToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_search_blogs,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="get_distance_eta",
                description="估算距离和到达时间",
                input_model=DistanceEtaToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_distance_eta_handler,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="check_open_status",
                description="查询商户营业状态",
                input_model=OpenStatusToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_open_status_handler,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="create_booking",
                description="创建订座请求，并在可用时优先写入 Java 业务适配层",
                input_model=BookingToolInput,
                output_model=GenericToolOutput,
                idempotent=False,
                retryable=True,
                side_effect_level=SideEffectLevel.HIGH,
                risk_level="medium",
                allowed_execution_modes=("plan_execute",),
                requires_approval=True,
            ),
            handler=_create_booking,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="create_order",
                description="创建订单，并在可用时优先写入 Java 业务适配层",
                input_model=OrderToolInput,
                output_model=GenericToolOutput,
                idempotent=False,
                retryable=True,
                side_effect_level=SideEffectLevel.HIGH,
                risk_level="medium",
                allowed_execution_modes=("plan_execute",),
                requires_approval=True,
            ),
            handler=_create_order,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="cancel_order",
                description="取消订单，并在可用时优先写入 Java 业务适配层",
                input_model=CancelOrderToolInput,
                output_model=GenericToolOutput,
                idempotent=False,
                retryable=True,
                side_effect_level=SideEffectLevel.HIGH,
                risk_level="high",
                allowed_execution_modes=("plan_execute",),
                requires_approval=True,
            ),
            handler=_cancel_order,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="refund_order",
                description="退款订单，并在可用时优先写入 Java 业务适配层",
                input_model=RefundOrderToolInput,
                output_model=GenericToolOutput,
                idempotent=False,
                retryable=True,
                side_effect_level=SideEffectLevel.HIGH,
                risk_level="high",
                allowed_execution_modes=("plan_execute",),
                requires_approval=True,
            ),
            handler=_refund_order,
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="get_order_status",
                description="查询订单状态，并在可用时优先写入 Java 业务适配层",
                input_model=OrderStatusToolInput,
                output_model=GenericToolOutput,
                idempotent=True,
                retryable=True,
                side_effect_level=SideEffectLevel.NONE,
                risk_level="low",
                allowed_execution_modes=("auto", "simple", "plan_execute"),
            ),
            handler=_get_order_status,
        )
    )

    return registry
