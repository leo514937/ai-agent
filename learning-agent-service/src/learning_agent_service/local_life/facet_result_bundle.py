from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel
from .coupon_result import CouponResult


class FacetResultBundle(BaseModel):
    coupon_result: Optional[CouponResult] = None
    open_status_result: Optional[Dict[str, Any]] = None
    distance_eta_result: Optional[Dict[str, Any]] = None
