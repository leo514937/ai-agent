from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CouponItem(BaseModel):
    coupon_id: str
    title: str
    status: Literal["available", "unavailable", "expired", "unknown"]
    source: Literal["realtime_tool", "rag_history", "mock", "fallback"]
    shop_id: int | None = None
    valid_until: str | None = None
    price: float | None = None
    original_price: float | None = None
    description: str | None = None


class CouponResult(BaseModel):
    shop_id: int
    realtime_available_count: int
    realtime_total_count: int
    items: list[CouponItem]
    query_success: bool
    source: Literal["realtime_tool", "fallback", "rag_history"]
    error_message: str | None = None
