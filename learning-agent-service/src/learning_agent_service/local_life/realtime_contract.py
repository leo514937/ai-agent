from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RealtimeContract(BaseModel):
    facet: str
    requires_tool: bool = True
    allowed_tools: list[str]
    freshness_required: Literal["realtime", "near_realtime", "session"] = "realtime"
    fallback_allowed: bool = True
    fallback_message: str
    cannot_infer_from_rag: bool = True


_REALTIME_CONTRACTS: dict[str, RealtimeContract] = {
    "coupon": RealtimeContract(
        facet="coupon",
        allowed_tools=["get_coupon_list"],
        fallback_message="我暂时没有查到这家店的实时优惠券信息，建议以店铺页面显示为准。",
    ),
    "open_status": RealtimeContract(
        facet="open_status",
        allowed_tools=["check_open_status"],
        fallback_message="我暂时无法确认这家店当前是否营业，建议以店铺页面实时状态为准。",
    ),
    "distance_eta": RealtimeContract(
        facet="distance_eta",
        allowed_tools=["get_distance_eta"],
        fallback_message="我暂时无法确认这家店与你的实时距离信息，建议以地图页面显示为准。",
    ),
}


def get_realtime_contract(facet: str | None) -> RealtimeContract | None:
    key = str(facet or "").strip()
    if not key:
        return None
    return _REALTIME_CONTRACTS.get(key)


def fallback_message_for_facet(facet: str | None, shop_name: str | None = None) -> str | None:
    contract = get_realtime_contract(facet)
    if contract is None:
        return None
    shop_label = str(shop_name or "").strip() or "这家店"
    return contract.fallback_message.replace("这家店", shop_label, 1)
