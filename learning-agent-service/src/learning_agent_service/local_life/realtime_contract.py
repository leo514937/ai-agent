from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from learning_agent_service.local_life.boundary_prompts import get_boundary_prompt


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
        fallback_message=get_boundary_prompt("no_coupon_evidence"),
    ),
    "open_status": RealtimeContract(
        facet="open_status",
        allowed_tools=["check_open_status"],
        fallback_message=get_boundary_prompt("no_open_status"),
    ),
    "distance_eta": RealtimeContract(
        facet="distance_eta",
        allowed_tools=["get_distance_eta"],
        fallback_message=get_boundary_prompt("no_distance_info"),
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