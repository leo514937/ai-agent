from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .coupon_result import CouponResult
from .tool_result_normalizer import ToolResult


class FacetResultBundle(BaseModel):
    coupon_result: CouponResult | None = None
    open_status_result: dict[str, Any] | None = None
    distance_eta_result: dict[str, Any] | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)

    def find_tool_result(self, facet: str, shop_id: int | None = None) -> ToolResult | None:
        for result in self.tool_results:
            if str(result.facet or "").strip() != str(facet or "").strip():
                continue
            if shop_id is None:
                return result
            try:
                result_shop_id = int(result.shop_id) if result.shop_id is not None else None
            except Exception:
                result_shop_id = None
            if result_shop_id == int(shop_id):
                return result
        return None
