from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .tool_capabilities import TOOL_CAPABILITY_REGISTRY, ToolCapabilitySpec


class ToolGovernanceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    tool_side_effect: str = "read"
    idempotency_key_required: bool = False
    safe_to_retry: bool = True
    requires_user_confirmation: bool = False
    permission_scope: str = "local_life:read"
    sensitive_fields: list[str] = Field(default_factory=list)
    cacheable: bool = True
    cost_level: int = 1
    max_qps: int = 20
    allowed_in_preview: bool = True
    allowed_in_parallel: bool = True
    owner: str | None = None
    notes: str | None = None


def _default_permission_scope(owner: str | None) -> str:
    owner_text = str(owner or "local_life").strip() or "local_life"
    return f"{owner_text}:read"


def _governance_from_capability(spec: ToolCapabilitySpec) -> ToolGovernanceSpec:
    tool_name = str(spec.tool_name or "").strip()
    owner = str(spec.owner or "").strip() or None
    cacheable = tool_name in {"search_shops", "get_shop_detail", "get_shop_cards", "get_shop_review_summary", "check_open_status", "get_distance_eta", "calculate_distance_km"}
    allowed_in_parallel = tool_name not in {"get_shop_detail"} or tool_name in {"search_shops", "get_shop_cards", "get_shop_review_summary"}
    max_qps = 30 if tool_name == "search_shops" else 20
    return ToolGovernanceSpec(
        tool_name=tool_name,
        tool_side_effect="read",
        idempotency_key_required=False,
        safe_to_retry=bool(spec.retryable_failure_types),
        requires_user_confirmation=False,
        permission_scope=_default_permission_scope(owner),
        sensitive_fields=[],
        cacheable=cacheable,
        cost_level=max(1, int(spec.cost_weight or 1)),
        max_qps=max_qps,
        allowed_in_preview=True,
        allowed_in_parallel=allowed_in_parallel,
        owner=owner,
        notes=spec.notes,
    )


TOOL_GOVERNANCE_REGISTRY: dict[str, ToolGovernanceSpec] = {
    name: _governance_from_capability(spec)
    for name, spec in TOOL_CAPABILITY_REGISTRY.items()
}


def get_tool_governance(tool_name: str) -> ToolGovernanceSpec | None:
    return TOOL_GOVERNANCE_REGISTRY.get(str(tool_name or "").strip())


def tool_requires_confirmation(tool_name: str) -> bool:
    spec = get_tool_governance(tool_name)
    return bool(spec.requires_user_confirmation) if spec else False


def tool_allowed_in_parallel(tool_name: str) -> bool:
    spec = get_tool_governance(tool_name)
    return bool(spec.allowed_in_parallel) if spec else False
