from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

try:
    import httpx
except Exception:  # pragma: no cover - optional dependency in fallback-only environments
    httpx = None

from learning_agent_service.config import Settings, get_settings

from ..local_life.catalog import LocalLifeCatalog, get_default_catalog
from ..local_life.schemas import BlogRecord, LocalLifeSlots, ShopRecord, ShopTypeRecord, VoucherRecord


def _unwrap_result(payload: Any) -> Any:
    if isinstance(payload, dict):
        if "success" in payload:
            if payload.get("success"):
                return payload.get("data")
            return None
        if "data" in payload:
            return payload.get("data")
    return payload


def _coerce_list(payload: Any) -> list[Any]:
    data = _unwrap_result(payload)
    if data is None:
        return []
    if isinstance(data, list):
        return list(data)
    if isinstance(data, dict):
        if "records" in data and isinstance(data["records"], list):
            return list(data["records"])
        if "list" in data and isinstance(data["list"], list):
            return list(data["list"])
    return [data]


def _coerce_one(payload: Any) -> dict[str, Any]:
    data = _unwrap_result(payload)
    if isinstance(data, dict):
        return dict(data)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return dict(first)
    return {}


def _coerce_map(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_shop(payload: Any) -> ShopRecord | None:
    data = _coerce_one(payload)
    if not data:
        return None
    return ShopRecord(
        id=_coerce_int(data.get("id")) or 0,
        name=str(data.get("name") or ""),
        type_id=_coerce_int(data.get("typeId") or data.get("type_id")),
        type_name=data.get("typeName") or data.get("type_name"),
        area=data.get("area"),
        address=data.get("address"),
        x=_coerce_float(data.get("x")),
        y=_coerce_float(data.get("y")),
        avg_price=_coerce_float(data.get("avgPrice") or data.get("avg_price")),
        sold=_coerce_int(data.get("sold")),
        comments=_coerce_int(data.get("comments")),
        score=(
            (float(data.get("score")) / 10.0)
            if isinstance(data.get("score"), (int, float))
            else _coerce_float(data.get("score"))
        ),
        open_hours=data.get("openHours") or data.get("open_hours"),
        image=(data.get("image") or data.get("images") or "").split(",")[0] or None,
        distance_km=_coerce_float(data.get("distance")),
        source="java",
    )


def _coerce_voucher(payload: Any) -> VoucherRecord | None:
    data = _coerce_one(payload)
    if not data:
        return None
    return VoucherRecord(
        id=_coerce_int(data.get("id")) or 0,
        shop_id=_coerce_int(data.get("shopId") or data.get("shop_id")) or 0,
        shop_name=data.get("shopName") or data.get("shop_name"),
        title=str(data.get("title") or ""),
        sub_title=data.get("subTitle") or data.get("sub_title"),
        rules=data.get("rules"),
        pay_value=_coerce_float(data.get("payValue") or data.get("pay_value")),
        actual_value=_coerce_float(data.get("actualValue") or data.get("actual_value")),
        stock=_coerce_int(data.get("stock")),
        begin_time=data.get("beginTime") or data.get("begin_time"),
        end_time=data.get("endTime") or data.get("end_time"),
        source="java",
    )


def _coerce_blog(payload: Any) -> BlogRecord | None:
    data = _coerce_one(payload)
    if not data:
        return None
    return BlogRecord(
        id=_coerce_int(data.get("id")) or 0,
        shop_id=_coerce_int(data.get("shopId") or data.get("shop_id")),
        user_id=_coerce_int(data.get("userId") or data.get("user_id")),
        title=str(data.get("title") or ""),
        content=str(data.get("content") or ""),
        liked=_coerce_int(data.get("liked") or 0) or 0,
        comments=_coerce_int(data.get("comments") or 0) or 0,
        source="java",
    )


def _coerce_shop_type(payload: Any) -> ShopTypeRecord | None:
    data = _coerce_one(payload)
    if not data:
        return None
    return ShopTypeRecord(
        id=_coerce_int(data.get("id")) or 0,
        name=str(data.get("name") or ""),
        icon=data.get("icon"),
        sort=_coerce_int(data.get("sort")) or 0,
    )


def _coerce_transaction_payload(
    payload: Any,
    transaction_type: str,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any] | None:
    data = _unwrap_result(payload)
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, Mapping):
        data = dict(data)
        nested = data.get(transaction_type)
        if isinstance(nested, Mapping):
            data = dict(nested)
    if not isinstance(data, dict):
        return None

    transaction_id = (
        data.get("transaction_id")
        or data.get("transactionId")
        or data.get("booking_id")
        or data.get("bookingId")
        or data.get("order_id")
        or data.get("orderId")
        or data.get("id")
    )
    if transaction_id is None:
        nested_payload = data.get("payload")
        if isinstance(nested_payload, Mapping):
            transaction_id = (
                nested_payload.get("transaction_id")
                or nested_payload.get("transactionId")
                or nested_payload.get("booking_id")
                or nested_payload.get("bookingId")
                or nested_payload.get("order_id")
                or nested_payload.get("orderId")
                or nested_payload.get("id")
            )
    if transaction_id is None:
        return None

    record_key = "booking_id" if transaction_type == "booking" else "order_id"
    created_at = data.get("created_at") or data.get("createdAt")
    updated_at = data.get("updated_at") or data.get("updatedAt")
    payload_data = data.get("payload")
    if not isinstance(payload_data, Mapping):
        payload_data = {}

    record = {
        record_key: str(transaction_id),
        "transaction_id": str(transaction_id),
        "transaction_type": str(data.get("transaction_type") or data.get("transactionType") or transaction_type),
        "status": str(data.get("status") or data.get("state") or ("confirmed" if transaction_type == "booking" else "created")),
        "approval_state": str(data.get("approval_state") or data.get("approvalState") or "approved"),
        "shop_id": _coerce_int(data.get("shop_id") or data.get("shopId")),
        "shop_name": data.get("shop_name") or data.get("shopName"),
        "payload": dict(payload_data),
        "history": list(data.get("history") or []),
        "created_at": created_at,
        "updated_at": updated_at,
        "idempotency_key": data.get("idempotency_key") or data.get("idempotencyKey"),
        "source": "java",
    }
    if idempotency_key and not record.get("idempotency_key"):
        record["idempotency_key"] = idempotency_key
    for key, value in data.items():
        record.setdefault(key, value)
    return record


def _idempotency_headers(idempotency_key: str | None) -> dict[str, str]:
    if not idempotency_key:
        return {}
    return {"Idempotency-Key": idempotency_key}


def _is_production_like(settings: Settings | None) -> bool:
    if settings is None:
        return False
    checker = getattr(settings, "is_production_like", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    environment = str(getattr(settings, "environment", "") or "").strip().lower()
    app = getattr(settings, "app", None)
    if not environment and app is not None:
        environment = str(getattr(app, "environment", "") or "").strip().lower()
    return environment in {"production", "prod", "staging", "preprod", "preview"}


def _parse_hms(value: str) -> Optional[time]:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) < 2:
        return None
    try:
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except Exception:
        return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    return 2 * radius * asin(sqrt(max(0.0, min(1.0, a))))


@dataclass
class JavaBusinessClient:
    settings: Settings | None = None
    catalog: LocalLifeCatalog | None = None

    def __post_init__(self) -> None:
        self.settings = self.settings or get_settings()
        self.catalog = self.catalog or get_default_catalog()
        self.base_url = str(getattr(self.settings, "java_business_base_url", "") or "").strip().rstrip("/")
        self.internal_token = str(getattr(self.settings, "java_business_internal_token", "") or "").strip()
        self.timeout_seconds = float(getattr(self.settings, "java_business_timeout_seconds", 5.0) or 5.0)
        self.enable_fallback = bool(getattr(self.settings, "java_business_enable_fallback", True)) and not _is_production_like(self.settings)
        self._client: httpx.Client | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http_client(self) -> httpx.Client:
        if httpx is None:
            raise RuntimeError("httpx is not available")
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self.internal_token:
                headers["x-internal-token"] = self.internal_token
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds, headers=headers)
        return self._client

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Any = None,
        headers: Optional[dict[str, Any]] = None,
    ) -> Any:
        if not self.enabled:
            if self.enable_fallback:
                return None
            raise RuntimeError("Java business backend is not configured")
        try:
            request_headers = {}
            if headers:
                request_headers.update(headers)
            response = self._http_client().request(method, path, params=params, json=json_body, headers=request_headers)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            if self.enable_fallback:
                return None
            raise RuntimeError(f"Java business request failed for {path}") from exc

    def list_shop_types(self) -> list[ShopTypeRecord]:
        payload = self._request_json("GET", "/shop-type/list")
        items = [_coerce_shop_type(item) for item in _coerce_list(payload)]
        items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            return self.catalog.list_shop_types()
        return items

    def get_shop_detail(self, shop_id: int) -> ShopRecord:
        payload = self._request_json("GET", f"/internal/v1/business/shops/{int(shop_id)}/detail")
        payload_map = _coerce_map(_unwrap_result(payload))
        shop = _coerce_shop(payload_map.get("shop"))
        if shop is None:
            payload = self._request_json("GET", f"/shop/{int(shop_id)}")
            shop = _coerce_shop(payload)
        if shop is not None:
            return shop
        if self.enable_fallback:
            catalog_shop = self.catalog.get_shop(int(shop_id))
            if catalog_shop is not None:
                catalog_shop.source = "catalog"
                return catalog_shop
        raise RuntimeError(f"shop {shop_id} not found")

    def search_shops_by_type(
        self,
        *,
        type_id: int,
        current: int = 1,
        x: float | None = None,
        y: float | None = None,
    ) -> list[ShopRecord]:
        params: dict[str, Any] = {"typeId": int(type_id), "current": int(current)}
        if x is not None:
            params["x"] = float(x)
        if y is not None:
            params["y"] = float(y)
        payload = self._request_json(
            "POST",
            "/internal/v1/business/shops/search",
            json_body={
                "message": "",
                "limit": int(current) * 5 if int(current) > 0 else 5,
                "userId": None,
                "context": {
                    "typeId": int(type_id),
                    "x": float(x) if x is not None else None,
                    "y": float(y) if y is not None else None,
                },
            },
        )
        payload_map = _coerce_map(_unwrap_result(payload))
        items = [_coerce_shop(item) for item in _coerce_list(payload_map.get("shops"))]
        items = [item for item in items if item is not None]
        if not items:
            payload = self._request_json("GET", "/shop/of/type", params=params)
            items = [_coerce_shop(item) for item in _coerce_list(payload)]
            items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            return self.catalog.search_shops(limit=5, type_id=int(type_id))
        return items

    def search_shops_by_name(self, *, name: str, current: int = 1) -> list[ShopRecord]:
        payload = self._request_json(
            "POST",
            "/internal/v1/business/shops/search",
            json_body={
                "message": str(name or ""),
                "limit": int(current) * 5 if int(current) > 0 else 5,
                "context": {
                    "shopName": str(name or ""),
                    "shopQuery": str(name or ""),
                },
            },
        )
        payload_map = _coerce_map(_unwrap_result(payload))
        items = [_coerce_shop(item) for item in _coerce_list(payload_map.get("shops"))]
        items = [item for item in items if item is not None]
        if not items:
            params = {"name": name, "current": int(current)}
            payload = self._request_json("GET", "/shop/of/name", params=params)
            items = [_coerce_shop(item) for item in _coerce_list(payload)]
        items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            slots = LocalLifeSlots(shop_query=name)
            return self.catalog.search_shops(query=name, slots=slots, limit=5)
        return items

    def get_coupon_list(self, shop_id: int) -> list[VoucherRecord]:
        payload = self._request_json("GET", f"/internal/v1/business/shops/{int(shop_id)}/vouchers")
        payload_map = _coerce_map(_unwrap_result(payload))
        items = [_coerce_voucher(item) for item in _coerce_list(payload_map.get("vouchers"))]
        items = [item for item in items if item is not None]
        if not items:
            payload = self._request_json("GET", f"/voucher/list/{int(shop_id)}")
            items = [_coerce_voucher(item) for item in _coerce_list(payload)]
        items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            return self.catalog.list_vouchers(int(shop_id))
        return items

    def get_blog_hot(self, current: int = 1) -> list[BlogRecord]:
        payload = self._request_json("GET", "/blog/hot", params={"current": int(current)})
        items = [_coerce_blog(item) for item in _coerce_list(payload)]
        items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            return self.catalog.list_hot_blogs()
        return items

    def get_blog_of_user(self, user_id: int, current: int = 1) -> list[BlogRecord]:
        payload = self._request_json("GET", "/blog/of/user", params={"id": int(user_id), "current": int(current)})
        items = [_coerce_blog(item) for item in _coerce_list(payload)]
        items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            return self.catalog.list_user_blogs(int(user_id))
        return items

    def get_shop_blogs(self, shop_id: int, limit: int = 5) -> list[BlogRecord]:
        payload = self._request_json("GET", f"/internal/v1/business/shops/{int(shop_id)}/blogs", params={"limit": int(limit)})
        payload_map = _coerce_map(_unwrap_result(payload))
        items = [_coerce_blog(item) for item in _coerce_list(payload_map.get("blogs"))]
        items = [item for item in items if item is not None]
        if items:
            return items
        if self.enable_fallback:
            return self.catalog.list_shop_blogs(int(shop_id), limit=limit)
        return items

    def create_booking(
        self,
        *,
        shop_id: int | None = None,
        shop_name: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        body = {
            "shop_id": shop_id,
            "shopId": shop_id,
            "shop_name": shop_name,
            "shopName": shop_name,
            "idempotency_key": idempotency_key,
            "idempotencyKey": idempotency_key,
        }
        body.update(dict(payload or {}))
        response = self._request_json(
            "POST",
            "/booking",
            json_body=body,
            headers=_idempotency_headers(idempotency_key),
        )
        return _coerce_transaction_payload(response, "booking", idempotency_key=idempotency_key)

    def create_order(
        self,
        *,
        shop_id: int | None = None,
        shop_name: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        body = {
            "shop_id": shop_id,
            "shopId": shop_id,
            "shop_name": shop_name,
            "shopName": shop_name,
            "idempotency_key": idempotency_key,
            "idempotencyKey": idempotency_key,
        }
        body.update(dict(payload or {}))
        response = self._request_json(
            "POST",
            "/order",
            json_body=body,
            headers=_idempotency_headers(idempotency_key),
        )
        return _coerce_transaction_payload(response, "order", idempotency_key=idempotency_key)

    def cancel_order(
        self,
        order_id: str | None,
        *,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        order_id_text = str(order_id or "").strip()
        response = self._request_json(
            "POST",
            f"/order/{order_id_text}/cancel",
            json_body={
                "order_id": order_id,
                "orderId": order_id,
                "reason": reason,
                "idempotency_key": idempotency_key,
                "idempotencyKey": idempotency_key,
            },
            headers=_idempotency_headers(idempotency_key),
        )
        return _coerce_transaction_payload(response, "order", idempotency_key=idempotency_key)

    def refund_order(
        self,
        order_id: str | None,
        *,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        order_id_text = str(order_id or "").strip()
        response = self._request_json(
            "POST",
            f"/order/{order_id_text}/refund",
            json_body={
                "order_id": order_id,
                "orderId": order_id,
                "reason": reason,
                "idempotency_key": idempotency_key,
                "idempotencyKey": idempotency_key,
            },
            headers=_idempotency_headers(idempotency_key),
        )
        return _coerce_transaction_payload(response, "order", idempotency_key=idempotency_key)

    def get_order_status(self, order_id: str | None) -> dict[str, Any] | None:
        order_id_text = str(order_id or "").strip()
        response = self._request_json("GET", f"/internal/v1/business/orders/{order_id_text}/status")
        response_map = _coerce_map(_unwrap_result(response))
        if response_map.get("found") is True:
            return {
                "order_id": response_map.get("orderId") or response_map.get("order_id") or order_id_text,
                "transaction_id": response_map.get("orderId") or response_map.get("order_id") or order_id_text,
                "transaction_type": "order",
                "status": response_map.get("status"),
                "voucher_id": response_map.get("voucherId") or response_map.get("voucher_id"),
                "user_id": response_map.get("userId") or response_map.get("user_id"),
                "source": "java",
            }
        response = self._request_json("GET", f"/order/{order_id_text}")
        return _coerce_transaction_payload(response, "order")

    def search_candidates(
        self,
        *,
        query: str,
        slots: LocalLifeSlots,
        limit: int = 5,
    ) -> list[ShopRecord]:
        shop_types = self.list_shop_types()
        type_id = None
        if slots.category:
            normalized_category = slots.category.strip()
            for shop_type in shop_types:
                if normalized_category in shop_type.name or shop_type.name in normalized_category:
                    type_id = shop_type.id
                    break
        if slots.shop_query:
            by_name = self.search_shops_by_name(name=slots.shop_query, current=1)
            if by_name:
                return by_name[:limit]
        if type_id is not None:
            return self.search_shops_by_type(
                type_id=type_id,
                current=1,
                x=slots.location.lat,
                y=slots.location.lng,
            )[:limit]
        if self.enable_fallback:
            return self.catalog.search_shops(query=query, slots=slots, limit=limit)
        return []

    def check_open_status(self, shop: ShopRecord | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(shop, ShopRecord):
            open_hours = shop.open_hours
        else:
            open_hours = shop.get("open_hours") or shop.get("openHours")
        now = datetime.now().time()
        start, end = None, None
        if isinstance(open_hours, str) and "-" in open_hours:
            start_text, end_text = open_hours.split("-", 1)
            start = _parse_hms(start_text.strip())
            end = _parse_hms(end_text.strip())
        if start is None or end is None:
            return {"open_status": "unknown", "open_now": None}
        open_now = start <= now <= end if start <= end else (now >= start or now <= end)
        return {
            "open_status": "open" if open_now else "closed",
            "open_now": open_now,
            "open_hours": open_hours,
        }

    def get_distance_eta(self, shop: ShopRecord | Dict[str, Any], *, lat: float | None, lng: float | None) -> Dict[str, Any]:
        if isinstance(shop, ShopRecord):
            x, y = shop.x, shop.y
            distance_hint = shop.distance_km
        else:
            x = shop.get("x")
            y = shop.get("y")
            distance_hint = shop.get("distance_km") or shop.get("distance")
        distance_km = distance_hint
        if lat is not None and lng is not None and x is not None and y is not None:
            distance_km = _haversine_km(float(lat), float(lng), float(y), float(x))
        if distance_km is None:
            distance_km = 0.0
        eta_minutes = max(5, int(round(float(distance_km) * 4 + 8)))
        return {"distance_km": round(float(distance_km), 2), "eta_minutes": eta_minutes}

    def get_shop_detail_with_fallback(self, shop_id: int) -> ShopRecord:
        return self.get_shop_detail(shop_id)

    def recommend_shops(self, *, query: str, slots: LocalLifeSlots, limit: int = 5) -> list[ShopRecord]:
        return self.search_candidates(query=query, slots=slots, limit=limit)
